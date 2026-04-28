"""
Gateway Module

Abstract interface for payment gateways. Concrete implementations live
outside this package (one per gateway you integrate: Stripe, Adyen, etc.).

Why an abstraction:
  - Tests don't need network access — substitute FakePaymentGateway.
  - You can run primary + secondary gateways for redundancy.
  - You can migrate gateways without rewriting business logic.
  - Saga steps and idempotent functions depend on this protocol, not on
    a specific SDK, keeping orchestration code clean.

The interface intentionally separates authorize from capture. Many flows
benefit from a delayed capture (e.g., capture on shipment, not order),
and gateways universally support this two-step model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Optional, Protocol


class ChargeStatus(str, Enum):
    AUTHORIZED = "authorized"      # Funds reserved on the card; not yet captured.
    CAPTURED = "captured"           # Money moved.
    VOIDED = "voided"               # Authorization released without capture.
    REFUNDED = "refunded"           # Captured then refunded (full or partial).
    FAILED = "failed"


@dataclass(frozen=True)
class ChargeRequest:
    amount: Decimal
    currency: str
    card_token: str  # Tokenized — never a raw PAN.
    customer_id: Optional[str] = None
    description: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChargeResult:
    charge_id: str
    status: ChargeStatus
    amount: Decimal
    currency: str
    gateway_reference: Optional[str] = None
    avs_result: Optional[str] = None
    cvv_result: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RefundRequest:
    charge_id: str
    amount: Optional[Decimal] = None  # None = full refund.
    reason: Optional[str] = None


@dataclass(frozen=True)
class RefundResult:
    refund_id: str
    charge_id: str
    amount: Decimal
    status: str
    raw: Dict[str, Any] = field(default_factory=dict)


class PaymentGateway(Protocol):
    """
    All methods accept an optional `idempotency_key` so the @idempotent
    decorator can compose with concrete implementations cleanly. The key
    is the gateway's own idempotency key (most gateways support one);
    the @idempotent decorator's key is the application-level one. They
    serve the same purpose at different layers — gateway protects against
    your retries to it; @idempotent protects against your client's retries
    to you.
    """

    def authorize(
        self, request: ChargeRequest, *, idempotency_key: Optional[str] = None
    ) -> ChargeResult: ...

    def capture(
        self,
        charge_id: str,
        amount: Optional[Decimal] = None,
        *,
        idempotency_key: Optional[str] = None,
    ) -> ChargeResult: ...

    def void(
        self, charge_id: str, *, idempotency_key: Optional[str] = None
    ) -> ChargeResult: ...

    def refund(
        self, request: RefundRequest, *, idempotency_key: Optional[str] = None
    ) -> RefundResult: ...
