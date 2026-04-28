"""
payments — production-worthy payment primitives.

What's in here:
  errors          : Typed exception hierarchy with `retriable` flag.
  idempotency     : @idempotent decorator + pluggable store.
  saga            : Saga orchestrator with compensation and durable log hook.
  webhooks        : HMAC verifier, replay protection, dedup helper.
  redaction       : PCI-aware log filter and tokenizer interface.
  fraud           : Composable rule engine (velocity, AVS/CVV, blocklist).
  reconciliation  : Compare internal ledger against gateway report.
  gateway         : Abstract PaymentGateway protocol.

What's intentionally NOT in here:
  - A concrete gateway client. Use Stripe/Adyen/Braintree SDKs and adapt
    them to the `PaymentGateway` Protocol in `gateway.py`. Keeping the SDK
    out of this package avoids dragging in network, retry, and credential
    concerns that belong in your gateway adapter.
  - PCI-scope-relevant code paths that touch raw PANs. This package
    operates on tokens. The only place a PAN ever appears is in the
    `EphemeralTokenizer` (test/dev only) and the redaction patterns
    (which assume a PAN already escaped into a log line and need cleanup).
"""

from .errors import (
    PaymentError,
    NetworkError,
    GatewayTimeoutError,
    RateLimitedError,
    CardDeclinedError,
    InsufficientFundsError,
    FraudBlockedError,
    AuthenticationRequiredError,
    InvalidRequestError,
    IdempotencyConflictError,
    IdempotencyInFlightError,
    SagaCompensationError,
    WebhookSignatureError,
    WebhookReplayError,
)

from .idempotency import (
    idempotent,
    IdempotencyStore,
    InMemoryIdempotencyStore,
    IdempotencyRecord,
    IdempotencyState,
    hash_payload,
)

from .saga import (
    Saga,
    SagaState,
    SagaExecution,
    SagaStepResult,
    SagaLog,
    InMemorySagaLog,
    assert_saga_succeeded,
)

from .webhooks import (
    WebhookVerifier,
    WebhookVerificationResult,
    WebhookDedupStore,
    InMemoryDedupStore,
    is_first_delivery,
)

from .redaction import (
    redact,
    redact_dict,
    PCIRedactionFilter,
    Tokenizer,
    EphemeralTokenizer,
    install_root_redaction_filter,
)

from .fraud import (
    FraudEngine,
    FraudContext,
    FraudResult,
    Decision,
    Rule,
    RuleVerdict,
    VelocityTracker,
    avs_cvv_rule,
    velocity_rule,
    country_mismatch_rule,
    high_amount_rule,
    blocklist_rule,
)

from .reconciliation import (
    Reconciler,
    ReconciliationReport,
    Discrepancy,
    DiscrepancyType,
    TransactionRecord,
)

from .gateway import (
    PaymentGateway,
    ChargeRequest,
    ChargeResult,
    ChargeStatus,
    RefundRequest,
    RefundResult,
)

__version__ = "0.1.0"

__all__ = [
    # errors
    "PaymentError", "NetworkError", "GatewayTimeoutError", "RateLimitedError",
    "CardDeclinedError", "InsufficientFundsError", "FraudBlockedError",
    "AuthenticationRequiredError", "InvalidRequestError",
    "IdempotencyConflictError", "IdempotencyInFlightError",
    "SagaCompensationError", "WebhookSignatureError", "WebhookReplayError",
    # idempotency
    "idempotent", "IdempotencyStore", "InMemoryIdempotencyStore",
    "IdempotencyRecord", "IdempotencyState", "hash_payload",
    # saga
    "Saga", "SagaState", "SagaExecution", "SagaStepResult",
    "SagaLog", "InMemorySagaLog", "assert_saga_succeeded",
    # webhooks
    "WebhookVerifier", "WebhookVerificationResult",
    "WebhookDedupStore", "InMemoryDedupStore", "is_first_delivery",
    # redaction
    "redact", "redact_dict", "PCIRedactionFilter",
    "Tokenizer", "EphemeralTokenizer", "install_root_redaction_filter",
    # fraud
    "FraudEngine", "FraudContext", "FraudResult", "Decision",
    "Rule", "RuleVerdict", "VelocityTracker",
    "avs_cvv_rule", "velocity_rule", "country_mismatch_rule",
    "high_amount_rule", "blocklist_rule",
    # reconciliation
    "Reconciler", "ReconciliationReport", "Discrepancy",
    "DiscrepancyType", "TransactionRecord",
    # gateway
    "PaymentGateway", "ChargeRequest", "ChargeResult", "ChargeStatus",
    "RefundRequest", "RefundResult",
]