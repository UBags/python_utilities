"""
Payment Errors Module

Typed exceptions for payment operations. Using typed errors (rather than
generic `Exception`) lets callers distinguish recoverable failures
(NetworkError, RateLimitedError) from terminal ones (CardDeclinedError,
FraudBlockedError) and decide whether to retry, compensate, or surface.

Production use cases:
- Drive retry vs compensation decisions in Saga orchestration
- Map gateway-specific errors to a stable internal taxonomy
- Generate appropriate HTTP status codes at the API edge
"""

from typing import Optional, Dict, Any


class PaymentError(Exception):
    """Base class for all payment-related errors."""

    # Whether retrying the same operation might succeed.
    # Saga orchestrator and @retry decorators consult this.
    retriable: bool = False

    def __init__(
        self,
        message: str,
        code: Optional[str] = None,
        gateway_response: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.gateway_response = gateway_response or {}

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for logging / API responses (gateway_response is sanitized upstream)."""
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "code": self.code,
            "retriable": self.retriable,
        }


# ---------------------------------------------------------------------------
# Retriable errors — the operation may succeed on a later attempt
# ---------------------------------------------------------------------------

class NetworkError(PaymentError):
    """Transient network failure talking to gateway. Safe to retry with idempotency key."""
    retriable = True


class GatewayTimeoutError(PaymentError):
    """Gateway did not respond in time. Charge state is UNKNOWN — must reconcile or query."""
    retriable = True


class RateLimitedError(PaymentError):
    """Gateway rate-limited us. Back off and retry."""
    retriable = True

    def __init__(self, message: str, retry_after_seconds: Optional[float] = None, **kwargs):
        super().__init__(message, **kwargs)
        self.retry_after_seconds = retry_after_seconds


# ---------------------------------------------------------------------------
# Terminal errors — retrying will not help
# ---------------------------------------------------------------------------

class CardDeclinedError(PaymentError):
    """Issuer declined the card. Show user-facing message; do not retry."""
    retriable = False


class InsufficientFundsError(CardDeclinedError):
    """Specific decline reason: not enough funds. Surface to user."""


class FraudBlockedError(PaymentError):
    """Blocked by fraud rules (velocity, blocklist, ML score). Do not retry."""
    retriable = False


class AuthenticationRequiredError(PaymentError):
    """3DS / SCA challenge required before charge can proceed."""
    retriable = False

    def __init__(self, message: str, challenge_url: Optional[str] = None, **kwargs):
        super().__init__(message, **kwargs)
        self.challenge_url = challenge_url


class InvalidRequestError(PaymentError):
    """Caller sent a malformed request (bad amount, unsupported currency, etc.)."""
    retriable = False


# ---------------------------------------------------------------------------
# Idempotency / Saga errors
# ---------------------------------------------------------------------------

class IdempotencyConflictError(PaymentError):
    """
    Same idempotency key was reused with a different payload hash.

    Per Stripe / RFC draft conventions, this is a hard 4xx — the caller
    must either use a fresh key or send the original payload.
    """
    retriable = False


class IdempotencyInFlightError(PaymentError):
    """
    A request with this idempotency key is currently being processed.
    The caller should poll, not retry-and-create.
    """
    retriable = False


class SagaCompensationError(PaymentError):
    """
    A compensating transaction failed. This is the worst case — the saga
    is now in an inconsistent state and requires human intervention.
    Always log loudly and page on-call.
    """
    retriable = False


# ---------------------------------------------------------------------------
# Webhook errors
# ---------------------------------------------------------------------------

class WebhookSignatureError(PaymentError):
    """Webhook signature verification failed. Reject the request — do NOT process."""
    retriable = False


class WebhookReplayError(PaymentError):
    """Webhook timestamp is outside the allowed replay window. Reject."""
    retriable = False
