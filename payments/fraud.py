"""
Fraud Module

Composable fraud-rule engine. This is NOT a replacement for a full fraud
service (Sift, Signifyd, Stripe Radar) — it's the layer that decides:

  - Hard blocks before money moves   (velocity, blocklist, AVS/CVV mismatch).
  - Soft challenges that step up auth (3DS, additional verification).
  - Risk scoring for downstream review.

Rules are pure functions of a `FraudContext`. They return a `RuleVerdict`.
The engine evaluates them in order, short-circuiting on the first BLOCK.
This makes rules independently testable and easy to reason about.

Production note:
  Fraud rules tend to drift toward too-strict (blocking real customers) or
  too-lenient (letting attackers through). Always log every rule's verdict
  so you can A/B test changes against historical data, and gate every new
  rule behind a feature flag for safe rollout.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class Decision(str, Enum):
    APPROVE = "approve"
    CHALLENGE = "challenge"  # Step up to 3DS / SCA before allowing.
    BLOCK = "block"
    REVIEW = "review"        # Approve, but flag for human review post-charge.


@dataclass
class FraudContext:
    """
    All fields rules might inspect. Add freely; rules ignore what they don't need.

    `risk_signals` is a free-form bag for downstream rules — e.g. an upstream
    rule might set `risk_signals["new_device"] = True` and a later rule reads it.
    """
    user_id: Optional[str] = None
    email: Optional[str] = None
    ip_address: Optional[str] = None
    amount: float = 0.0
    currency: str = "USD"
    card_token: Optional[str] = None
    card_country: Optional[str] = None
    billing_country: Optional[str] = None
    avs_result: Optional[str] = None  # "match", "partial", "mismatch", "unavailable"
    cvv_result: Optional[str] = None  # "match", "mismatch", "unavailable"
    device_fingerprint: Optional[str] = None
    is_new_user: bool = False
    risk_signals: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RuleVerdict:
    rule_name: str
    decision: Decision
    reason: str
    risk_score_delta: int = 0  # Cumulative score for REVIEW threshold.


# A rule is a callable: (ctx) -> Optional[RuleVerdict].
# Returning None means "this rule doesn't apply / no opinion".
Rule = Callable[[FraudContext], Optional[RuleVerdict]]


@dataclass
class FraudResult:
    decision: Decision
    risk_score: int
    verdicts: List[RuleVerdict]

    @property
    def blocked_by(self) -> Optional[str]:
        for v in self.verdicts:
            if v.decision == Decision.BLOCK:
                return v.rule_name
        return None


# ---------------------------------------------------------------------------
# Velocity tracking
# ---------------------------------------------------------------------------

class VelocityTracker:
    """
    Tracks event counts in a sliding time window per key.

    Used by velocity rules: "no more than N charges per user per hour",
    "no more than N declines per IP per minute". Thread-safe.

    Production note: this is in-memory and per-process. For multi-instance
    deployments, replace with a Redis-backed implementation using sorted
    sets and ZREMRANGEBYSCORE for windowed counting.
    """

    def __init__(self) -> None:
        self._events: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def record(self, key: str, now: Optional[float] = None) -> None:
        ts = now if now is not None else time.time()
        with self._lock:
            self._events[key].append(ts)

    def count(self, key: str, window_seconds: float, now: Optional[float] = None) -> int:
        ts = now if now is not None else time.time()
        cutoff = ts - window_seconds
        with self._lock:
            events = self._events.get(key)
            if not events:
                return 0
            # Trim from the left while events are older than the cutoff.
            while events and events[0] < cutoff:
                events.popleft()
            if not events:
                # Drop empty key to bound memory.
                self._events.pop(key, None)
                return 0
            return len(events)


# ---------------------------------------------------------------------------
# Built-in rules
# ---------------------------------------------------------------------------

def avs_cvv_rule(
    *,
    block_on_avs_mismatch: bool = True,
    block_on_cvv_mismatch: bool = True,
    challenge_on_partial: bool = True,
) -> Rule:
    """
    Standard AVS/CVV check. Issuers return these for every authorization;
    a hard mismatch is one of the strongest signals of stolen card use.
    """

    def rule(ctx: FraudContext) -> Optional[RuleVerdict]:
        if ctx.cvv_result == "mismatch" and block_on_cvv_mismatch:
            return RuleVerdict(
                rule_name="avs_cvv",
                decision=Decision.BLOCK,
                reason="CVV mismatch",
                risk_score_delta=100,
            )
        if ctx.avs_result == "mismatch" and block_on_avs_mismatch:
            return RuleVerdict(
                rule_name="avs_cvv",
                decision=Decision.BLOCK,
                reason="AVS mismatch",
                risk_score_delta=80,
            )
        if ctx.avs_result == "partial" and challenge_on_partial:
            return RuleVerdict(
                rule_name="avs_cvv",
                decision=Decision.CHALLENGE,
                reason="Partial AVS match",
                risk_score_delta=20,
            )
        return None

    return rule


def velocity_rule(
    tracker: VelocityTracker,
    *,
    key_fn: Callable[[FraudContext], Optional[str]],
    max_count: int,
    window_seconds: float,
    rule_name: str = "velocity",
) -> Rule:
    """
    Generic velocity limiter. Configure per-axis (user, IP, card token).

    Example:
        # No more than 5 charges per user per hour.
        velocity_rule(tracker, key_fn=lambda c: c.user_id, max_count=5,
                      window_seconds=3600, rule_name="user_velocity")
    """

    def rule(ctx: FraudContext) -> Optional[RuleVerdict]:
        key = key_fn(ctx)
        if key is None:
            return None
        count = tracker.count(f"{rule_name}:{key}", window_seconds)
        if count >= max_count:
            return RuleVerdict(
                rule_name=rule_name,
                decision=Decision.BLOCK,
                reason=f"Exceeded {max_count} events in {window_seconds:.0f}s "
                       f"(observed {count})",
                risk_score_delta=70,
            )
        return None

    return rule


def country_mismatch_rule(*, challenge_only: bool = True) -> Rule:
    """
    Card-issuing country differs from billing country. Common with
    legitimate travel — typically a CHALLENGE, not a BLOCK.
    """

    def rule(ctx: FraudContext) -> Optional[RuleVerdict]:
        if not ctx.card_country or not ctx.billing_country:
            return None
        if ctx.card_country == ctx.billing_country:
            return None
        decision = Decision.CHALLENGE if challenge_only else Decision.BLOCK
        return RuleVerdict(
            rule_name="country_mismatch",
            decision=decision,
            reason=f"Card from {ctx.card_country}, billing in {ctx.billing_country}",
            risk_score_delta=30,
        )

    return rule


def high_amount_rule(*, threshold: float, currency: str = "USD") -> Rule:
    """Charges above the threshold get a CHALLENGE (3DS step-up)."""

    def rule(ctx: FraudContext) -> Optional[RuleVerdict]:
        if ctx.currency != currency:
            return None
        if ctx.amount < threshold:
            return None
        return RuleVerdict(
            rule_name="high_amount",
            decision=Decision.CHALLENGE,
            reason=f"Amount {ctx.amount} {currency} >= threshold {threshold}",
            risk_score_delta=15,
        )

    return rule


def blocklist_rule(
    blocked_emails: Optional[set] = None,
    blocked_ips: Optional[set] = None,
    blocked_cards: Optional[set] = None,
) -> Rule:
    """Static blocklist. In production, back this with a periodically-refreshed store."""
    blocked_emails = blocked_emails or set()
    blocked_ips = blocked_ips or set()
    blocked_cards = blocked_cards or set()

    def rule(ctx: FraudContext) -> Optional[RuleVerdict]:
        if ctx.email and ctx.email.lower() in blocked_emails:
            return RuleVerdict("blocklist", Decision.BLOCK, "Blocked email", 100)
        if ctx.ip_address and ctx.ip_address in blocked_ips:
            return RuleVerdict("blocklist", Decision.BLOCK, "Blocked IP", 100)
        if ctx.card_token and ctx.card_token in blocked_cards:
            return RuleVerdict("blocklist", Decision.BLOCK, "Blocked card", 100)
        return None

    return rule


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class FraudEngine:
    """
    Evaluate fraud rules and combine their verdicts into a final decision.

    Decision logic:
      - Any BLOCK -> BLOCK (short-circuits).
      - Else any CHALLENGE -> CHALLENGE.
      - Else if cumulative risk_score >= review_threshold -> REVIEW.
      - Else APPROVE.

    Every rule's verdict is captured on the FraudResult so you can audit
    decisions, train models, and tune thresholds against historical data.
    """

    def __init__(
        self,
        rules: Optional[List[Rule]] = None,
        *,
        review_threshold: int = 50,
    ) -> None:
        self._rules: List[Rule] = list(rules or [])
        self._review_threshold = review_threshold

    def add_rule(self, rule: Rule) -> "FraudEngine":
        self._rules.append(rule)
        return self

    def evaluate(self, ctx: FraudContext) -> FraudResult:
        verdicts: List[RuleVerdict] = []
        score = 0
        decision = Decision.APPROVE

        for rule in self._rules:
            verdict = rule(ctx)
            if verdict is None:
                continue
            verdicts.append(verdict)
            score += verdict.risk_score_delta
            logger.info(
                "Fraud rule %s: %s (%s, +%d)",
                verdict.rule_name, verdict.decision.value, verdict.reason,
                verdict.risk_score_delta,
            )
            if verdict.decision == Decision.BLOCK:
                decision = Decision.BLOCK
                break
            if verdict.decision == Decision.CHALLENGE and decision == Decision.APPROVE:
                # CHALLENGE wins over APPROVE but loses to a later BLOCK.
                decision = Decision.CHALLENGE

        if decision == Decision.APPROVE and score >= self._review_threshold:
            decision = Decision.REVIEW

        return FraudResult(decision=decision, risk_score=score, verdicts=verdicts)
