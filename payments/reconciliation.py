"""
Reconciliation Module

Daily reconciliation: compare your internal ledger against the gateway's
authoritative report, surface every discrepancy, and route them to handlers.

Why this matters:
  Even with idempotency, sagas, and webhooks, things drift. A webhook that
  was acked but never persisted, a refund issued through the gateway dashboard,
  a settlement-currency rounding difference — they all create gaps between
  what your DB believes and what the gateway recorded. Reconciliation is the
  only way to find these before they show up in a finance audit or a customer
  complaint.

Discrepancy taxonomy:
  - MISSING_INTERNAL : gateway has it, we don't (most common: missed webhook).
  - MISSING_GATEWAY  : we think it succeeded, gateway has no record.
                       Almost always a bug — investigate immediately.
  - AMOUNT_MISMATCH  : both sides have it but amounts differ.
  - STATUS_MISMATCH  : both sides have it but status differs (e.g., we say
                       captured, gateway says authorized).

Production note:
  Run this against the previous day's data, not today's — settlement and
  webhook delivery have lag. T-1 is the standard.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Callable, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class DiscrepancyType(str, Enum):
    MISSING_INTERNAL = "missing_internal"
    MISSING_GATEWAY = "missing_gateway"
    AMOUNT_MISMATCH = "amount_mismatch"
    STATUS_MISMATCH = "status_mismatch"


@dataclass(frozen=True)
class TransactionRecord:
    """
    Common shape for both internal ledger rows and gateway report rows.

    Decimal (not float) for amount: cents are exact in Decimal and floats
    accumulate rounding error that compounds across thousands of transactions.
    """
    transaction_id: str
    amount: Decimal
    currency: str
    status: str
    occurred_at: float  # epoch seconds — both sides should be in UTC.


@dataclass
class Discrepancy:
    type: DiscrepancyType
    transaction_id: str
    internal: Optional[TransactionRecord] = None
    gateway: Optional[TransactionRecord] = None
    detail: str = ""


@dataclass
class ReconciliationReport:
    matched: int = 0
    discrepancies: List[Discrepancy] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.matched + len(self.discrepancies)

    def by_type(self) -> Dict[DiscrepancyType, int]:
        counts: Dict[DiscrepancyType, int] = {}
        for d in self.discrepancies:
            counts[d.type] = counts.get(d.type, 0) + 1
        return counts

    def summary(self) -> str:
        if not self.discrepancies:
            return f"All {self.matched} transactions match."
        parts = [f"{c} {t.value}" for t, c in self.by_type().items()]
        return (
            f"{self.matched}/{self.total} matched, "
            f"{len(self.discrepancies)} discrepancies: {', '.join(parts)}"
        )


# ---------------------------------------------------------------------------
# Reconciler
# ---------------------------------------------------------------------------

# Handler signature: a function that receives a discrepancy and decides
# what to do (alert, auto-correct, ticket). Returning normally = handled.
DiscrepancyHandler = Callable[[Discrepancy], None]


class Reconciler:
    """
    Compare two streams of transactions and report discrepancies.

    Example:
        reconciler = Reconciler()

        # Optionally register handlers per discrepancy type.
        reconciler.on(DiscrepancyType.MISSING_INTERNAL, replay_webhook)
        reconciler.on(DiscrepancyType.MISSING_GATEWAY, page_oncall)

        report = reconciler.reconcile(
            internal=ledger.list_transactions(date),
            gateway=stripe_client.list_balance_transactions(date),
        )
        logger.info(report.summary())

    Both inputs can be any iterable of TransactionRecord. The reconciler
    streams them into dicts internally — for very large datasets (millions
    of rows/day), consider a chunked streaming variant.
    """

    def __init__(
        self,
        *,
        amount_tolerance: Decimal = Decimal("0.00"),
    ) -> None:
        # Tolerance > 0 is occasionally needed for FX conversion or fee rounding.
        # Default 0 means exact match required, which is right for same-currency.
        self._amount_tolerance = amount_tolerance
        self._handlers: Dict[DiscrepancyType, List[DiscrepancyHandler]] = {}

    def on(self, type_: DiscrepancyType, handler: DiscrepancyHandler) -> "Reconciler":
        """Register a handler. Multiple handlers per type are allowed; they all run."""
        self._handlers.setdefault(type_, []).append(handler)
        return self

    def reconcile(
        self,
        internal: Iterable[TransactionRecord],
        gateway: Iterable[TransactionRecord],
    ) -> ReconciliationReport:
        report = ReconciliationReport()

        internal_by_id: Dict[str, TransactionRecord] = {
            r.transaction_id: r for r in internal
        }
        gateway_by_id: Dict[str, TransactionRecord] = {
            r.transaction_id: r for r in gateway
        }

        all_ids = set(internal_by_id) | set(gateway_by_id)

        for tx_id in all_ids:
            internal_rec = internal_by_id.get(tx_id)
            gateway_rec = gateway_by_id.get(tx_id)

            if internal_rec is None:
                self._emit(report, Discrepancy(
                    type=DiscrepancyType.MISSING_INTERNAL,
                    transaction_id=tx_id,
                    gateway=gateway_rec,
                    detail="Gateway reports this transaction; no internal record",
                ))
                continue

            if gateway_rec is None:
                self._emit(report, Discrepancy(
                    type=DiscrepancyType.MISSING_GATEWAY,
                    transaction_id=tx_id,
                    internal=internal_rec,
                    detail="Internal ledger has this transaction; gateway does not",
                ))
                continue

            # Both sides have it — check fields.
            mismatches = self._compare(internal_rec, gateway_rec)
            if not mismatches:
                report.matched += 1
                continue

            for mismatch_type, detail in mismatches:
                self._emit(report, Discrepancy(
                    type=mismatch_type,
                    transaction_id=tx_id,
                    internal=internal_rec,
                    gateway=gateway_rec,
                    detail=detail,
                ))

        return report

    def _compare(
        self,
        internal: TransactionRecord,
        gateway: TransactionRecord,
    ) -> List[tuple[DiscrepancyType, str]]:
        out: List[tuple[DiscrepancyType, str]] = []

        if internal.currency != gateway.currency:
            out.append((
                DiscrepancyType.AMOUNT_MISMATCH,
                f"Currency mismatch: internal={internal.currency}, gateway={gateway.currency}",
            ))
        else:
            diff = abs(internal.amount - gateway.amount)
            if diff > self._amount_tolerance:
                out.append((
                    DiscrepancyType.AMOUNT_MISMATCH,
                    f"Amount differs by {diff} {internal.currency} "
                    f"(internal={internal.amount}, gateway={gateway.amount})",
                ))

        if internal.status != gateway.status:
            out.append((
                DiscrepancyType.STATUS_MISMATCH,
                f"Status: internal={internal.status}, gateway={gateway.status}",
            ))

        return out

    def _emit(self, report: ReconciliationReport, discrepancy: Discrepancy) -> None:
        report.discrepancies.append(discrepancy)
        logger.warning(
            "Reconciliation discrepancy: %s tx=%s detail=%s",
            discrepancy.type.value, discrepancy.transaction_id, discrepancy.detail,
        )
        for handler in self._handlers.get(discrepancy.type, []):
            try:
                handler(discrepancy)
            except Exception:
                # Handler failure must never stop reconciliation — we have other
                # discrepancies to report. Log and continue.
                logger.exception(
                    "Reconciliation handler for %s raised on tx=%s",
                    discrepancy.type.value, discrepancy.transaction_id,
                )
