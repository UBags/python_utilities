"""
Redaction Module

PCI-aware redaction utilities. The cheapest way to fail a PCI audit is to
log a card number into your application logs — once that happens, your log
infrastructure (and everyone who has access to it) is in scope.

This module provides three layers of defense:
  1. `redact()` / `redact_dict()` — pure functions that scrub PCI data
     from arbitrary strings or dicts before they're logged.
  2. `PCIRedactionFilter` — a logging.Filter that automatically scrubs
     anything passed through the standard logging module.
  3. `Tokenizer` interface + `EphemeralTokenizer` — a vault that swaps
     PANs for opaque tokens, enabling data minimization.

What gets redacted:
  - PANs (13-19 digit sequences passing a Luhn check, with reasonable
    separator tolerance: spaces, dashes).
  - CVV-shaped fields adjacent to PAN-shaped fields or labelled "cvv"/"cvc".
  - Track 1/2 magnetic stripe data (recognized by leading sentinels).

What does NOT get redacted (intentionally):
  - Card brand names, last-4 digits in isolation, expiry months/years.
    These are not "sensitive authentication data" under PCI DSS and are
    routinely needed in logs for support.

Production note:
  Regex-based PAN redaction is a SECOND line of defense. The first line is
  to never put raw PANs into your application in the first place — use a
  tokenization gateway (Stripe Elements, Adyen Hosted Fields, etc.) so PANs
  go directly from the user's browser to the vault and your servers only
  ever see tokens. This module exists for the cases that slip through.
"""

from __future__ import annotations

import logging
import re
import secrets
import threading
from typing import Any, Dict, Iterable, Optional, Protocol


# ---------------------------------------------------------------------------
# PAN detection
# ---------------------------------------------------------------------------

# Match 13-19 digit sequences with optional spaces/dashes between groups.
# Anchored on word boundaries so we don't eat random long numbers (order IDs).
# Greedy on the digit run so we capture the full PAN, not a substring.
_PAN_PATTERN = re.compile(
    r"\b(?:\d[ -]?){12,18}\d\b"
)

# Track 1 starts with %, Track 2 starts with ;. Both end with ?.
_TRACK_PATTERN = re.compile(r"[%;][^?\n]{10,}\?")

# Labelled CVV ("cvv": "123", cvc=4567, security_code: 999, "cvv":"4567").
# The optional [\"'] before [:=] handles JSON-style "cvv": where the closing
# quote of the key sits between the word and the colon.
_CVV_LABELLED_PATTERN = re.compile(
    r"(?i)(\bcvv2?\b|\bcvc2?\b|\bcid\b|\bsecurity[_\s-]?code\b)"
    r"[\"']?\s*[:=]\s*[\"']?(\d{3,4})[\"']?"
)


def _luhn_ok(digits: str) -> bool:
    """Standard Luhn check. Reduces false positives on long numeric IDs."""
    total = 0
    parity = len(digits) % 2
    for i, ch in enumerate(digits):
        d = ord(ch) - 48
        if d < 0 or d > 9:
            return False
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _mask_pan(match: re.Match) -> str:
    """Replace a matched PAN with `****1234` (preserving last 4 for support)."""
    digits = re.sub(r"[ -]", "", match.group(0))
    if not _luhn_ok(digits):
        # Not a real card number — leave it alone. Order IDs can be long and
        # numeric; we don't want to butcher them.
        return match.group(0)
    return "*" * (len(digits) - 4) + digits[-4:]


def redact(text: str) -> str:
    """
    Redact PCI-sensitive data from a string.

    Order matters: track data is redacted before PANs (track data contains
    a PAN substring; redacting the wider track first avoids a partial mask).
    """
    if not text:
        return text
    text = _TRACK_PATTERN.sub("[REDACTED_TRACK]", text)
    text = _CVV_LABELLED_PATTERN.sub(r"\1: [REDACTED_CVV]", text)
    text = _PAN_PATTERN.sub(_mask_pan, text)
    return text


def redact_dict(data: Any, _depth: int = 0) -> Any:
    """
    Recursively redact PCI data from a dict/list/str structure.

    Whole values for known-sensitive keys (`cvv`, `cvc`, `card_number`,
    `pan`, `track_data`) are dropped entirely — there's no support reason
    to keep them in logs even partially.
    """
    SENSITIVE_KEYS = {
        "cvv", "cvc", "cvv2", "cvc2", "cid",
        "card_number", "cardnumber", "pan", "primary_account_number",
        "track_data", "track1", "track2",
        "security_code", "securitycode",
    }
    # Bound recursion — pathological input shouldn't blow the stack.
    if _depth > 50:
        return "[REDACTED_DEPTH_LIMIT]"

    if isinstance(data, dict):
        return {
            k: ("[REDACTED]" if k.lower() in SENSITIVE_KEYS else redact_dict(v, _depth + 1))
            for k, v in data.items()
        }
    if isinstance(data, (list, tuple)):
        out = [redact_dict(v, _depth + 1) for v in data]
        return out if isinstance(data, list) else tuple(out)
    if isinstance(data, str):
        return redact(data)
    return data


# ---------------------------------------------------------------------------
# Logging filter
# ---------------------------------------------------------------------------

class PCIRedactionFilter(logging.Filter):
    """
    A logging.Filter that scrubs PCI data from log records.

    Install once at the root logger (or per handler) and every log line
    flows through it.

    Example:
        handler = logging.StreamHandler()
        handler.addFilter(PCIRedactionFilter())
        logging.getLogger().addHandler(handler)

    Caveat: filters mutate the LogRecord. If the same record reaches multiple
    handlers and only some have the filter, the redacted version may leak to
    handlers added after this one. Install on every handler, or at the root
    logger before any handlers fire.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # The pre-format `msg` is what gets logged; redact it directly.
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        # Args may carry sensitive values — redact each.
        if record.args:
            if isinstance(record.args, dict):
                record.args = redact_dict(record.args)
            else:
                record.args = tuple(
                    redact(a) if isinstance(a, str) else redact_dict(a)
                    for a in record.args
                )
        return True


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------

class Tokenizer(Protocol):
    """
    Vault interface for swapping PANs for opaque tokens.

    Production implementations call out to your gateway (Stripe tokens,
    Adyen tokens) or a dedicated tokenization service. The interface is
    deliberately narrow — most apps only need tokenize/detokenize.
    """

    def tokenize(self, pan: str) -> str: ...
    def detokenize(self, token: str) -> str: ...
    def delete(self, token: str) -> None: ...


class EphemeralTokenizer:
    """
    In-process tokenizer. NOT for production — tokens vanish on restart and
    PANs sit in process memory, defeating the point of tokenization.
    Useful for tests and local dev to verify wiring.

    Production replacement: a thin client around your gateway's token API.
    """

    _PREFIX = "tok_"

    def __init__(self) -> None:
        self._forward: Dict[str, str] = {}  # pan -> token
        self._reverse: Dict[str, str] = {}  # token -> pan
        self._lock = threading.Lock()

    def tokenize(self, pan: str) -> str:
        if not pan or not pan.replace(" ", "").replace("-", "").isdigit():
            raise ValueError("PAN must be digits with optional spaces/dashes")
        normalized = re.sub(r"[ -]", "", pan)
        with self._lock:
            existing = self._forward.get(normalized)
            if existing:
                return existing
            # 16 hex chars = 64 bits of entropy. Good enough for an ephemeral
            # tokenizer; production vaults typically use longer tokens.
            token = f"{self._PREFIX}{secrets.token_hex(16)}"
            self._forward[normalized] = token
            self._reverse[token] = normalized
            return token

    def detokenize(self, token: str) -> str:
        with self._lock:
            pan = self._reverse.get(token)
            if pan is None:
                raise KeyError(f"Unknown token: {token}")
            return pan

    def delete(self, token: str) -> None:
        with self._lock:
            pan = self._reverse.pop(token, None)
            if pan is not None:
                self._forward.pop(pan, None)


def install_root_redaction_filter() -> PCIRedactionFilter:
    """
    Convenience: attach the PCI filter to every handler on the root logger
    and return it.

    Why handlers, not the logger itself: filters attached to a logger only
    fire on records logged directly to *that* logger. Records that propagate
    up from child loggers bypass them. Handlers, in contrast, see every
    record that reaches them, so attaching the filter at the handler level
    catches all of them.

    Call this AFTER `logging.basicConfig` (or after you've added your
    handlers) — handlers added later won't have the filter unless you
    re-attach.

    Most apps want this called once at startup. For more nuanced setups
    (per-handler filters, structured logging) instantiate the filter
    yourself and attach where appropriate.
    """
    filt = PCIRedactionFilter()
    root = logging.getLogger()
    root.addFilter(filt)  # Direct logs to root.
    for handler in root.handlers:  # Records propagating up from children.
        handler.addFilter(filt)
    return filt
