"""
Saga Module

Saga orchestrator for cross-service transactions. When you can't wrap
"reserve inventory + authorize payment + create shipment" in a single ACID
transaction (because they live in different services or DBs), you instead
break it into a sequence of local transactions, each with a compensating
action that undoes it.

This module implements the **orchestrated** flavor (a central coordinator
runs the steps), not choreographed (each service publishes events and
others react). Orchestration is easier to reason about for payments and
gives you a clean place to log saga state.

Failure model:
  - If a step fails, previously-completed steps are compensated in reverse order.
  - Compensations themselves can fail. We retry compensations a configurable
    number of times. If they still fail, we mark the saga FAILED_COMPENSATION
    and raise SagaCompensationError — this is a page-on-call situation.
  - The saga log records every transition so a recovery process can resume
    after a crash.

This module does NOT make individual steps idempotent — you compose with
@idempotent on the underlying functions for that. Doing so means a saga
that crashes mid-step can resume safely.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol

from .errors import PaymentError, SagaCompensationError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class SagaState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"
    # Compensation itself failed — manual intervention required.
    FAILED_COMPENSATION = "failed_compensation"


# A step is an async function: ctx -> Any (the action's result).
# A compensation is async: (ctx, step_result) -> None.
# Using async throughout removes the sync/async fork that would otherwise
# duplicate orchestration logic.
StepFn = Callable[[Dict[str, Any]], Awaitable[Any]]
CompensateFn = Callable[[Dict[str, Any], Any], Awaitable[None]]


@dataclass
class SagaStep:
    name: str
    action: StepFn
    compensate: Optional[CompensateFn] = None
    # Per-step compensation retry budget. Compensations are best-effort but
    # we try harder than normal calls because the alternative is inconsistency.
    compensation_retries: int = 3


@dataclass
class SagaStepResult:
    step_name: str
    succeeded: bool
    result: Any = None
    error: Optional[str] = None
    compensated: bool = False
    compensation_error: Optional[str] = None
    started_at: float = 0.0
    finished_at: float = 0.0


@dataclass
class SagaExecution:
    """Full record of one saga run. Persist this for audit + recovery."""
    saga_id: str
    name: str
    state: SagaState
    context: Dict[str, Any] = field(default_factory=dict)
    step_results: List[SagaStepResult] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    final_error: Optional[str] = None


# ---------------------------------------------------------------------------
# Saga log (durability hook)
# ---------------------------------------------------------------------------

class SagaLog(Protocol):
    """
    Where saga state is persisted. In production this is a database table.

    Recording every transition (start, each step result, compensation events,
    final state) lets a recovery worker resume in-flight sagas after a crash.
    """

    async def record(self, execution: SagaExecution) -> None: ...


class InMemorySagaLog:
    """For tests and local dev. NOT durable."""

    def __init__(self) -> None:
        self.history: List[SagaExecution] = []

    async def record(self, execution: SagaExecution) -> None:
        # Snapshot by reconstructing — the caller holds a live reference and
        # will keep mutating it, so we deep-copy via dict round-trip.
        import copy
        self.history.append(copy.deepcopy(execution))


# ---------------------------------------------------------------------------
# Saga orchestrator
# ---------------------------------------------------------------------------

class Saga:
    """
    Build a saga by adding steps, then run it.

    Example:
        saga = Saga(name="checkout", log=db_saga_log)

        saga.add_step(
            name="reserve_inventory",
            action=inventory_service.reserve,
            compensate=inventory_service.release,
        )
        saga.add_step(
            name="authorize_payment",
            action=payments_service.authorize,
            compensate=payments_service.void,
        )
        saga.add_step(
            name="create_shipment",
            action=shipping_service.create,
            # No compensation needed for the final step that gates user-visible state.
        )

        execution = await saga.execute({"order_id": "ord_123", "amount": 5000})
        if execution.state != SagaState.COMPLETED:
            handle_failure(execution)

    Step contract:
      - Each `action(ctx)` may write back to ctx to pass data downstream.
      - The action's return value is passed to its `compensate(ctx, result)`
        if compensation runs (e.g., the result might contain a reservation_id
        the compensation needs to release).
    """

    def __init__(
        self,
        name: str,
        log: Optional[SagaLog] = None,
        saga_id: Optional[str] = None,
    ) -> None:
        self.name = name
        self.saga_id = saga_id or f"saga_{uuid.uuid4().hex}"
        self.log = log
        self._steps: List[SagaStep] = []

    def add_step(
        self,
        name: str,
        action: StepFn,
        compensate: Optional[CompensateFn] = None,
        compensation_retries: int = 3,
    ) -> "Saga":
        """Append a step. Returns self to support fluent chaining."""
        self._steps.append(
            SagaStep(
                name=name,
                action=action,
                compensate=compensate,
                compensation_retries=compensation_retries,
            )
        )
        return self

    async def execute(self, context: Optional[Dict[str, Any]] = None) -> SagaExecution:
        execution = SagaExecution(
            saga_id=self.saga_id,
            name=self.name,
            state=SagaState.RUNNING,
            context=context or {},
        )
        await self._record(execution)

        completed_steps: List[tuple[SagaStep, Any]] = []

        for step in self._steps:
            step_result = SagaStepResult(
                step_name=step.name,
                succeeded=False,
                started_at=time.time(),
            )
            logger.info("Saga %s: starting step '%s'", self.saga_id, step.name)
            try:
                result = await step.action(execution.context)
                step_result.succeeded = True
                step_result.result = result
                step_result.finished_at = time.time()
                execution.step_results.append(step_result)
                completed_steps.append((step, result))
                await self._record(execution)
            except Exception as e:
                step_result.error = f"{type(e).__name__}: {e}"
                step_result.finished_at = time.time()
                execution.step_results.append(step_result)
                logger.error(
                    "Saga %s: step '%s' failed: %s — beginning compensation",
                    self.saga_id, step.name, e,
                )
                execution.state = SagaState.COMPENSATING
                execution.final_error = step_result.error
                await self._record(execution)

                await self._compensate(execution, completed_steps)
                # _compensate sets the final state (COMPENSATED or FAILED_COMPENSATION).
                execution.finished_at = time.time()
                await self._record(execution)
                return execution

        execution.state = SagaState.COMPLETED
        execution.finished_at = time.time()
        await self._record(execution)
        logger.info("Saga %s: completed successfully", self.saga_id)
        return execution

    async def _compensate(
        self,
        execution: SagaExecution,
        completed_steps: List[tuple[SagaStep, Any]],
    ) -> None:
        """Run compensations in reverse order. Tracks per-step success on the execution record."""
        all_compensations_succeeded = True

        for step, action_result in reversed(completed_steps):
            if step.compensate is None:
                logger.info(
                    "Saga %s: step '%s' has no compensation, skipping",
                    self.saga_id, step.name,
                )
                continue

            # Find the matching step result so we can annotate it.
            step_result = next(
                (sr for sr in execution.step_results if sr.step_name == step.name),
                None,
            )

            comp_succeeded = False
            last_error: Optional[Exception] = None
            for attempt in range(1, step.compensation_retries + 1):
                try:
                    await step.compensate(execution.context, action_result)
                    comp_succeeded = True
                    break
                except Exception as e:
                    last_error = e
                    logger.warning(
                        "Saga %s: compensation for '%s' failed (attempt %d/%d): %s",
                        self.saga_id, step.name, attempt, step.compensation_retries, e,
                    )
                    # Linear backoff between compensation attempts. Compensations
                    # are usually small idempotent operations; aggressive retry
                    # is the right default here.
                    await asyncio.sleep(min(2.0 * attempt, 10.0))

            if step_result is not None:
                step_result.compensated = comp_succeeded
                if not comp_succeeded and last_error is not None:
                    step_result.compensation_error = (
                        f"{type(last_error).__name__}: {last_error}"
                    )

            if not comp_succeeded:
                all_compensations_succeeded = False
                logger.critical(
                    "Saga %s: compensation for '%s' EXHAUSTED retries — manual intervention required",
                    self.saga_id, step.name,
                )

        if all_compensations_succeeded:
            execution.state = SagaState.COMPENSATED
        else:
            execution.state = SagaState.FAILED_COMPENSATION
            # Don't raise from here — the caller checks execution.state. Raising
            # would make the API inconsistent with the success path. The caller
            # decides whether to treat FAILED_COMPENSATION as exceptional.

    async def _record(self, execution: SagaExecution) -> None:
        if self.log is not None:
            try:
                await self.log.record(execution)
            except Exception as e:
                # Logging failures must not break the saga itself, but they're
                # serious — we lose recoverability.
                logger.error("Saga %s: failed to record state: %s", self.saga_id, e)


# ---------------------------------------------------------------------------
# Convenience helper for the common "raise on non-success" pattern
# ---------------------------------------------------------------------------

def assert_saga_succeeded(execution: SagaExecution) -> None:
    """
    Raise if the saga didn't complete cleanly.

    Most callers want to surface saga failure as an exception; this helper
    avoids forcing every caller to write the same `if state != COMPLETED` check.
    """
    if execution.state == SagaState.COMPLETED:
        return
    if execution.state == SagaState.FAILED_COMPENSATION:
        raise SagaCompensationError(
            f"Saga '{execution.name}' ({execution.saga_id}) failed compensation: "
            f"{execution.final_error}",
            code="saga_failed_compensation",
        )
    raise PaymentError(
        f"Saga '{execution.name}' ({execution.saga_id}) ended in state "
        f"{execution.state.value}: {execution.final_error}",
        code=f"saga_{execution.state.value}",
    )
