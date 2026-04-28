"""
Webhooks Module

Secure webhook receiver utilities. Payment gateways notify you asynchronously
about state changes (charge.succeeded, charge.refunded, dispute.created).
You MUST verify these or an attacker who knows your webhook URL can forge
events and trigger fulfillment for orders they never paid for.

This module provides three independent guarantees:
  1. Authenticity   — HMAC signature check using a shared secret.
  2. Freshness      — timestamp must be within a replay window.
  3. At-most-once   — processed event IDs are deduplicated.

The HMAC scheme used here mirrors Stripe's: signed payload is
`f"{timestamp}.{raw_body}"`. Other gateways (GitHub, Shopify, Adyen)
use slight variants — the WebhookVerifier class is parameterized so
you can adapt without rewriting.

Production notes:
  - ALWAYS verify against the raw request body, not a re-serialized JSON.
    Even one byte of difference (whitespace, key order) breaks HMAC.
    Capture the body before any parsing middleware runs.
  - The dedup store should be durable (Redis SETNX with TTL works well).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
import threading
from dataclasses import dataclass
from typing import Optional, Protocol

from .errors import WebhookReplayError, WebhookSignatureError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dedup store
# ---------------------------------------------------------------------------

class WebhookDedupStore(Protocol):
    """
    Tracks which webhook event IDs we've already processed.

    Required operation:
      - mark_seen(event_id, ttl_seconds) -> bool
        Returns True if this is the first time we've seen the ID, False if dup.
        Must be atomic. In Redis: `SET key 1 NX EX <ttl>`.
    """

    def mark_seen(self, event_id: str, ttl_seconds: int) -> bool: ...


class InMemoryDedupStore:
    """Thread-safe in-memory dedup. Not durable — for tests and dev only."""

    def __init__(self) -> None:
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def mark_seen(self, event_id: str, ttl_seconds: int) -> bool:
        now = time.time()
        with self._lock:
            # Lazy expiration: only clean keys we encounter.
            existing = self._seen.get(event_id)
            if existing is not None and existing > now:
                return False
            self._seen[event_id] = now + ttl_seconds
            return True


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WebhookVerificationResult:
    """Outcome of a successful verification (failures raise instead)."""
    timestamp: int
    raw_body: bytes


class WebhookVerifier:
    """
    Verifies signatures on incoming webhooks.

    Args:
        secret: Shared signing secret from your gateway dashboard.
                In production, load from a secrets manager — never check it in.
        replay_window_seconds: Reject signatures older than this. 5 minutes
                is a sensible default; payment gateways typically deliver
                within seconds, so a wide window only helps replay attackers.
        digest: Hash function name. Stripe uses sha256. Some gateways use sha512.

    Example:
        verifier = WebhookVerifier(secret=os.environ["STRIPE_WEBHOOK_SECRET"])

        # In your HTTP handler, with raw body captured before JSON parsing:
        try:
            verifier.verify(
                raw_body=request.body,
                signature_header=request.headers["Stripe-Signature"],
            )
        except (WebhookSignatureError, WebhookReplayError) as e:
            return Response(status=400)
        # Now safe to parse and process.
    """

    def __init__(
        self,
        secret: str,
        *,
        replay_window_seconds: int = 300,
        digest: str = "sha256",
    ) -> None:
        if not secret:
            raise ValueError("Webhook secret must not be empty")
        self._secret = secret.encode("utf-8")
        self._replay_window = replay_window_seconds
        self._digest = digest

    def verify(
        self,
        raw_body: bytes,
        signature_header: str,
        now: Optional[float] = None,
    ) -> WebhookVerificationResult:
        """
        Verify a webhook. Raises on failure, returns parsed metadata on success.

        `signature_header` format follows Stripe's convention:
            "t=1614265330,v1=abc123...,v1=def456..."

        Multiple `v1=` entries are allowed (used during secret rotation):
        the request is valid if ANY of them match.
        """
        timestamp, signatures = self._parse_header(signature_header)
        self._check_freshness(timestamp, now)

        signed_payload = f"{timestamp}.".encode("utf-8") + raw_body
        expected = hmac.new(
            self._secret, signed_payload, getattr(hashlib, self._digest)
        ).hexdigest()

        # Constant-time compare against every candidate. Doing this in a loop
        # rather than short-circuiting prevents a (very weak) timing oracle on
        # which signature matched.
        any_match = False
        for sig in signatures:
            if hmac.compare_digest(expected, sig):
                any_match = True
        if not any_match:
            raise WebhookSignatureError(
                "Webhook signature did not match any provided signature",
                code="webhook_signature_mismatch",
            )

        return WebhookVerificationResult(timestamp=timestamp, raw_body=raw_body)

    def _parse_header(self, header: str) -> tuple[int, list[str]]:
        if not header:
            raise WebhookSignatureError(
                "Missing signature header", code="webhook_signature_missing"
            )

        timestamp: Optional[int] = None
        signatures: list[str] = []
        for part in header.split(","):
            if "=" not in part:
                continue
            key, _, value = part.strip().partition("=")
            if key == "t":
                try:
                    timestamp = int(value)
                except ValueError:
                    raise WebhookSignatureError(
                        f"Malformed timestamp in signature header: {value!r}",
                        code="webhook_signature_malformed",
                    )
            elif key == "v1":
                signatures.append(value)
            # Other keys (newer schemes) are ignored — forward compatibility.

        if timestamp is None:
            raise WebhookSignatureError(
                "Signature header missing timestamp", code="webhook_signature_malformed"
            )
        if not signatures:
            raise WebhookSignatureError(
                "Signature header missing v1 signatures",
                code="webhook_signature_malformed",
            )
        return timestamp, signatures

    def _check_freshness(self, timestamp: int, now: Optional[float]) -> None:
        current = now if now is not None else time.time()
        age = current - timestamp
        if age > self._replay_window:
            raise WebhookReplayError(
                f"Webhook timestamp is {age:.0f}s old (max {self._replay_window}s)",
                code="webhook_replay",
            )
        # Negative age (timestamp in the future) is also suspect — small clock
        # skew is fine, but anything beyond the window is rejected.
        if age < -self._replay_window:
            raise WebhookReplayError(
                f"Webhook timestamp is {-age:.0f}s in the future",
                code="webhook_clock_skew",
            )


# ---------------------------------------------------------------------------
# Dedup helper
# ---------------------------------------------------------------------------

def is_first_delivery(
    event_id: str,
    store: WebhookDedupStore,
    *,
    ttl_seconds: int = 7 * 24 * 60 * 60,
) -> bool:
    """
    Check whether a webhook event ID has been processed before.

    Returns True if this is the first delivery (proceed with processing).
    Returns False if we've already seen it (acknowledge with 200, do nothing).

    Default TTL is 7 days — well past most gateways' retry windows. For
    extremely high-volume integrations, lower this and rely on the gateway
    not retrying past the TTL.
    """
    first = store.mark_seen(event_id, ttl_seconds)
    if not first:
        logger.info("Webhook event %s already processed, skipping", event_id)
    return first
