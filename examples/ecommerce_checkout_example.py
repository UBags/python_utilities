"""
End-to-End E-Commerce Checkout Example
======================================

Demonstrates how the `payments` subpackage composes with the existing
`python_utilities` decorators to build a hardened checkout flow.

The decorator stack on `charge_customer` is the key idea — each decorator
addresses one of the 10 payment requirements:

    @idempotent(...)        # #1  Idempotency for payment operations
    @circuit_breaker(...)   # #10 Resilience (cascading failure prevention)
    @retry(...)             # #1+ Safe retries (works *because* of idempotency)
    @rate_limit(...)        # #5  Velocity limiting at the API boundary
    @timer(...)             # #8  Latency observability
    @log_execution(...)     # #8  Audit trail (PCI filter scrubs the logs)
    def charge_customer(...): ...

The Saga ties the whole checkout together so a failure in any step
(reserve inventory -> authorize -> capture -> create shipment) compensates
cleanly. Webhook handling, fraud screening, redaction, and reconciliation
are wired in as their own concerns.

To run:
    cd python_utilities && pip install -e .
    cd ..  # so both python_utilities and payments are importable
    python ecommerce_checkout_example.py
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Dict, Optional

# --- Existing utilities ---------------------------------------------------
from python_utilities.decorators import (
    retry,
    circuit_breaker,
    rate_limit,
    timer,
    log_execution,
)

# --- New payments subpackage ---------------------------------------------
from payments import (
    # Idempotency
    idempotent,
    InMemoryIdempotencyStore,
    # Saga
    Saga,
    SagaState,
    InMemorySagaLog,
    assert_saga_succeeded,
    # Webhooks
    WebhookVerifier,
    InMemoryDedupStore,
    is_first_delivery,
    # Redaction (install at startup)
    install_root_redaction_filter,
    EphemeralTokenizer,
    # Fraud
    FraudEngine,
    FraudContext,
    Decision,
    VelocityTracker,
    avs_cvv_rule,
    velocity_rule,
    country_mismatch_rule,
    high_amount_rule,
    blocklist_rule,
    # Reconciliation
    Reconciler,
    TransactionRecord,
    DiscrepancyType,
    # Errors
    NetworkError,
    CardDeclinedError,
    FraudBlockedError,
    AuthenticationRequiredError,
    PaymentError,
)

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
# Install PCI redaction at the root logger BEFORE anything logs a card.
install_root_redaction_filter()
logger = logging.getLogger("checkout")


# ---------------------------------------------------------------------------
# Module-level singletons (in production: dependency-injected)
# ---------------------------------------------------------------------------

idempotency_store = InMemoryIdempotencyStore()
saga_log = InMemorySagaLog()
webhook_dedup = InMemoryDedupStore()
velocity_tracker = VelocityTracker()
tokenizer = EphemeralTokenizer()
WEBHOOK_SECRET = "whsec_demo_secret_replace_in_prod"
webhook_verifier = WebhookVerifier(secret=WEBHOOK_SECRET, replay_window_seconds=300)


# ---------------------------------------------------------------------------
# Fake gateway — stands in for Stripe/Adyen/etc.
# ---------------------------------------------------------------------------

class FakeGateway:
    """
    Simulates a real gateway with controllable failure modes for the demo.
    A real adapter would wrap stripe.Charge.create / adyen.payment.authorize.
    """

    def __init__(self) -> None:
        self.transient_failures_remaining = 2  # Will fail first 2 calls.
        self.charges: Dict[str, dict] = {}

    def authorize(
        self,
        amount: Decimal,
        currency: str,
        card_token: str,
        customer_id: str,
        idempotency_key: str,
    ) -> dict:
        # Demonstrate transient failure -> retry recovers.
        if self.transient_failures_remaining > 0:
            self.transient_failures_remaining -= 1
            raise NetworkError("Connection reset", code="network_error")

        if card_token == "tok_declined":
            raise CardDeclinedError("Card declined", code="card_declined")

        charge_id = f"ch_{uuid.uuid4().hex[:12]}"
        record = {
            "charge_id": charge_id,
            "amount": amount,
            "currency": currency,
            "status": "authorized",
            "card_token": card_token,
            "customer_id": customer_id,
            "avs_result": "match",
            "cvv_result": "match",
        }
        self.charges[charge_id] = record
        return record

    def capture(self, charge_id: str, idempotency_key: str) -> dict:
        ch = self.charges[charge_id]
        ch["status"] = "captured"
        return ch

    def void(self, charge_id: str, idempotency_key: str) -> dict:
        ch = self.charges.get(charge_id)
        if ch is None:
            return {"status": "not_found"}
        ch["status"] = "voided"
        logger.info("Gateway: voided %s", charge_id)
        return ch


gateway = FakeGateway()


# ---------------------------------------------------------------------------
# THE DECORATOR STACK
#
# This is the headline of the example: one function, one decorator stack,
# all ten payment requirements collaborated on.
#
# Order matters. Outermost (topmost) wraps everything below it:
#   1. @idempotent      — outermost; if we already processed this key,
#                         return cached result and skip the rest entirely.
#                         Crucially, this also makes #2 (retry) safe.
#   2. @circuit_breaker — open the breaker after repeated gateway failures
#                         to stop hammering a downed dependency.
#   3. @retry           — handle transient NetworkError / GatewayTimeoutError.
#                         Safe ONLY because of @idempotent above.
#   4. @rate_limit      — protect us from runaway upstream traffic.
#   5. @timer           — record latency for SLO monitoring.
#   6. @log_execution   — audit trail; PCI filter scrubs cards from output.
#
# The actual function body is short — all the cross-cutting concerns are
# expressed declaratively in the stack.
# ---------------------------------------------------------------------------

@idempotent(idempotency_store, payload_arg="charge_request", ttl_seconds=86400)
@circuit_breaker(failure_threshold=5, recovery_timeout=30.0)
@retry(max_attempts=3, delay=0.5, backoff=2.0, exceptions=(NetworkError,))
@rate_limit(max_calls=100, period=timedelta(minutes=1))
@timer(metric_name="charge_duration")
@log_execution(log_args=True, log_result=True)
def charge_customer(charge_request: dict, idempotency_key: str) -> dict:
    """
    Authorize a charge through the gateway.

    The body stays tiny because the decorator stack does the heavy lifting.
    Note that the request payload uses a tokenized card — never a raw PAN.
    """
    return gateway.authorize(
        amount=charge_request["amount"],
        currency=charge_request["currency"],
        card_token=charge_request["card_token"],
        customer_id=charge_request["customer_id"],
        idempotency_key=idempotency_key,
    )


# ---------------------------------------------------------------------------
# Fraud engine setup
# ---------------------------------------------------------------------------

fraud_engine = FraudEngine(
    rules=[
        blocklist_rule(blocked_emails={"banned@evil.com"}),
        avs_cvv_rule(),
        velocity_rule(
            velocity_tracker,
            key_fn=lambda c: c.user_id,
            max_count=5,
            window_seconds=3600,
            rule_name="user_hourly",
        ),
        country_mismatch_rule(),
        high_amount_rule(threshold=2000.0),
    ],
    review_threshold=50,
)


def screen_for_fraud(ctx: FraudContext) -> None:
    """Run fraud rules. Raise on BLOCK, mark for review/challenge as needed."""
    velocity_tracker.record(f"user_hourly:{ctx.user_id}")
    result = fraud_engine.evaluate(ctx)

    if result.decision == Decision.BLOCK:
        raise FraudBlockedError(
            f"Blocked by rule: {result.blocked_by}",
            code="fraud_block",
        )
    if result.decision == Decision.CHALLENGE:
        # In a real app, redirect to 3DS challenge URL.
        raise AuthenticationRequiredError(
            "3DS step-up required",
            challenge_url="https://issuer.example.com/3ds/challenge/abc",
            code="sca_required",
        )
    if result.decision == Decision.REVIEW:
        logger.warning(
            "Order flagged for review: score=%d signals=%s",
            result.risk_score, [v.rule_name for v in result.verdicts],
        )
    # APPROVE: silent pass-through.


# ---------------------------------------------------------------------------
# Internal services (saga steps wrap these)
# ---------------------------------------------------------------------------

@dataclass
class CheckoutContext:
    order_id: str
    user_id: str
    email: str
    amount: Decimal
    currency: str
    card_token: str
    idempotency_key: str
    # Populated by saga steps:
    reservation_id: Optional[str] = None
    charge_id: Optional[str] = None
    shipment_id: Optional[str] = None


inventory: Dict[str, int] = {"sku_widget": 10}
reservations: Dict[str, dict] = {}
shipments: Dict[str, dict] = {}


async def reserve_inventory(ctx: dict) -> dict:
    sku = "sku_widget"
    if inventory[sku] < 1:
        raise PaymentError("Out of stock", code="oos")
    reservation_id = f"rsv_{uuid.uuid4().hex[:8]}"
    inventory[sku] -= 1
    reservations[reservation_id] = {"sku": sku, "qty": 1}
    ctx["reservation_id"] = reservation_id
    logger.info("Reserved inventory %s for order %s", reservation_id, ctx["order_id"])
    return {"reservation_id": reservation_id}


async def release_inventory(ctx: dict, result: dict) -> None:
    rid = result["reservation_id"]
    rsv = reservations.pop(rid, None)
    if rsv:
        inventory[rsv["sku"]] += rsv["qty"]
    logger.info("Released inventory %s (compensation)", rid)


async def authorize_payment(ctx: dict) -> dict:
    # screen_for_fraud raises BEFORE we touch the gateway — fraud blocks
    # are cheaper if they short-circuit early.
    screen_for_fraud(FraudContext(
        user_id=ctx["user_id"],
        email=ctx["email"],
        amount=float(ctx["amount"]),
        currency=ctx["currency"],
        card_token=ctx["card_token"],
        avs_result="match",   # In real code: from card-on-file or step-up.
        cvv_result="match",
        card_country="US",
        billing_country="US",
    ))

    result = charge_customer(
        charge_request={
            "amount": ctx["amount"],
            "currency": ctx["currency"],
            "card_token": ctx["card_token"],
            "customer_id": ctx["user_id"],
        },
        idempotency_key=ctx["idempotency_key"],
    )
    ctx["charge_id"] = result["charge_id"]
    return result


async def void_payment(ctx: dict, result: dict) -> None:
    gateway.void(
        charge_id=result["charge_id"],
        idempotency_key=f"void_{result['charge_id']}",
    )


async def capture_payment(ctx: dict) -> dict:
    # Capture has no compensation in this example — once we capture, the
    # only way back is a refund, which is a separate flow with its own saga.
    return gateway.capture(
        charge_id=ctx["charge_id"],
        idempotency_key=f"cap_{ctx['charge_id']}",
    )


async def create_shipment(ctx: dict) -> dict:
    # Simulate occasional shipment-API failure to demonstrate compensation.
    if ctx.get("simulate_shipment_failure"):
        raise PaymentError("Shipping API down", code="ship_failed")
    shipment_id = f"shp_{uuid.uuid4().hex[:8]}"
    shipments[shipment_id] = {"order_id": ctx["order_id"]}
    ctx["shipment_id"] = shipment_id
    logger.info("Created shipment %s", shipment_id)
    return {"shipment_id": shipment_id}


# ---------------------------------------------------------------------------
# Checkout entry point
# ---------------------------------------------------------------------------

async def checkout(ctx: CheckoutContext, *, simulate_shipment_failure: bool = False) -> dict:
    """
    Run the full checkout saga. Returns the saga execution record.
    """
    saga_ctx = {
        "order_id": ctx.order_id,
        "user_id": ctx.user_id,
        "email": ctx.email,
        "amount": ctx.amount,
        "currency": ctx.currency,
        "card_token": ctx.card_token,
        "idempotency_key": ctx.idempotency_key,
        "simulate_shipment_failure": simulate_shipment_failure,
    }

    saga = Saga(name="checkout", log=saga_log, saga_id=f"saga_{ctx.order_id}")
    saga.add_step("reserve_inventory", reserve_inventory, release_inventory)
    saga.add_step("authorize_payment", authorize_payment, void_payment)
    saga.add_step("capture_payment", capture_payment)  # No compensation.
    saga.add_step("create_shipment", create_shipment)  # No compensation.

    execution = await saga.execute(saga_ctx)
    return execution


# ---------------------------------------------------------------------------
# Webhook handler (separate concern)
# ---------------------------------------------------------------------------

def handle_webhook(raw_body: bytes, signature_header: str) -> dict:
    """
    Webhook entry point. Verifies signature, dedups by event ID, processes.
    Returns the response that should be sent back to the gateway.
    """
    try:
        webhook_verifier.verify(raw_body, signature_header)
    except (PaymentError, Exception) as e:
        logger.warning("Rejected webhook: %s", e)
        return {"status": 400}

    import json
    event = json.loads(raw_body)
    event_id = event["id"]

    if not is_first_delivery(event_id, webhook_dedup):
        # Already processed — acknowledge so the gateway stops retrying.
        return {"status": 200, "duplicate": True}

    # In real code: route by event["type"] and update local state.
    logger.info("Processing webhook event %s of type %s", event_id, event["type"])
    return {"status": 200}


# ---------------------------------------------------------------------------
# Demo runner
# ---------------------------------------------------------------------------

async def demo() -> None:
    print("=" * 72)
    print("E-Commerce Checkout — combining decorators with payments primitives")
    print("=" * 72)

    # Tokenize the card up front. Past this point, no raw PAN exists in memory.
    card_token = tokenizer.tokenize("4111-1111-1111-1111")
    print(f"\n[setup] Card tokenized: {card_token}")

    # ----- Scenario 1: Happy path with a transient gateway failure --------
    print("\n--- Scenario 1: Successful checkout (with transient failure recovered by @retry)")
    ctx1 = CheckoutContext(
        order_id="ord_001",
        user_id="user_42",
        email="alice@example.com",
        amount=Decimal("49.99"),
        currency="USD",
        card_token=card_token,
        idempotency_key=f"ikey_{uuid.uuid4().hex}",
    )
    exec1 = await checkout(ctx1)
    print(f"   -> Saga state: {exec1.state.value}")
    print(f"   -> Inventory remaining: {inventory['sku_widget']}")

    # ----- Scenario 2: Idempotent retry with same key returns cached result
    print("\n--- Scenario 2: Same idempotency key, same payload — no double-charge")
    # Re-run authorize directly with the same key; should return cached result.
    cached = charge_customer(
        charge_request={
            "amount": ctx1.amount,
            "currency": ctx1.currency,
            "card_token": ctx1.card_token,
            "customer_id": ctx1.user_id,
        },
        idempotency_key=ctx1.idempotency_key,
    )
    print(f"   -> Cached charge_id: {cached['charge_id']}")
    print(f"   -> Gateway transient_failures_remaining (still 0, no retry happened)")

    # ----- Scenario 3: Saga compensation when shipment fails ---------------
    print("\n--- Scenario 3: Shipment fails — compensation voids payment & releases inventory")
    ctx3 = CheckoutContext(
        order_id="ord_002",
        user_id="user_42",
        email="alice@example.com",
        amount=Decimal("29.99"),
        currency="USD",
        card_token=card_token,
        idempotency_key=f"ikey_{uuid.uuid4().hex}",
    )
    exec3 = await checkout(ctx3, simulate_shipment_failure=True)
    print(f"   -> Saga state: {exec3.state.value}")
    print(f"   -> Inventory remaining: {inventory['sku_widget']} (released back)")
    print(f"   -> Steps executed: {[s.step_name for s in exec3.step_results]}")
    print(f"   -> Steps compensated: {[s.step_name for s in exec3.step_results if s.compensated]}")

    # ----- Scenario 4: Fraud block ----------------------------------------
    print("\n--- Scenario 4: Fraud rule blocks before any gateway call")
    ctx4 = CheckoutContext(
        order_id="ord_003",
        user_id="user_99",
        email="banned@evil.com",
        amount=Decimal("50.00"),
        currency="USD",
        card_token=card_token,
        idempotency_key=f"ikey_{uuid.uuid4().hex}",
    )
    exec4 = await checkout(ctx4)
    print(f"   -> Saga state: {exec4.state.value}")
    failed_step = next((s for s in exec4.step_results if not s.succeeded), None)
    if failed_step:
        print(f"   -> Failed step: {failed_step.step_name}")
        print(f"   -> Error: {failed_step.error}")

    # ----- Scenario 5: Webhook flow ---------------------------------------
    print("\n--- Scenario 5: Webhook signature verification + dedup")
    payload = b'{"id":"evt_abc","type":"charge.captured","data":{"charge_id":"ch_xyz"}}'
    ts = int(time.time())
    sig = hmac.new(
        WEBHOOK_SECRET.encode(),
        f"{ts}.".encode() + payload,
        hashlib.sha256,
    ).hexdigest()
    header = f"t={ts},v1={sig}"

    print(f"   First delivery:  {handle_webhook(payload, header)}")
    print(f"   Replay (dup ID): {handle_webhook(payload, header)}")
    print(f"   Tampered body:   {handle_webhook(b'tampered', header)}")

    # ----- Scenario 6: Reconciliation -------------------------------------
    print("\n--- Scenario 6: End-of-day reconciliation finds drift")
    internal_ledger = [
        TransactionRecord("ch_001", Decimal("49.99"), "USD", "captured", time.time()),
        TransactionRecord("ch_002", Decimal("29.99"), "USD", "captured", time.time()),
        TransactionRecord("ch_003", Decimal("99.00"), "USD", "captured", time.time()),
    ]
    gateway_report = [
        TransactionRecord("ch_001", Decimal("49.99"), "USD", "captured", time.time()),
        TransactionRecord("ch_002", Decimal("29.99"), "USD", "refunded", time.time()),  # status drift
        TransactionRecord("ch_004", Decimal("15.00"), "USD", "captured", time.time()),  # missed webhook
    ]
    reconciler = Reconciler()
    pages: list = []
    reconciler.on(DiscrepancyType.MISSING_GATEWAY, lambda d: pages.append(d.transaction_id))
    report = reconciler.reconcile(internal_ledger, gateway_report)
    print(f"   {report.summary()}")
    print(f"   On-call paged for: {pages}")

    # ----- Scenario 7: Redaction ------------------------------------------
    print("\n--- Scenario 7: PCI filter scrubs accidental card-number leaks")
    # This logger goes through the root filter installed at startup.
    logger.info("Customer support note: card 4111-1111-1111-1111 cvv: 999 was used")

    print("\n" + "=" * 72)
    print("Demo complete.")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(demo())
