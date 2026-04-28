"""
Idempotency Module

Implements the idempotency-key pattern that prevents duplicate charges
from network timeouts, client retries, and browser refreshes.

How it works:
  1. Client sends an Idempotency-Key header (UUID, typically).
  2. Server hashes the request payload.
  3. Server checks the store for that key:
     - Not seen     -> mark IN_FLIGHT, process, store result, return result.
     - IN_FLIGHT    -> raise IdempotencyInFlightError (client should poll).
     - COMPLETED    -> if payload hash matches, return stored result (no reprocess).
                       if hash differs, raise IdempotencyConflictError.
     - FAILED       -> if payload hash matches, return stored error.
                       if hash differs, raise IdempotencyConflictError.

Production notes:
  - Store MUST be durable across restarts (Redis with AOF, or a DB row).
  - Records have a TTL (24h is typical for payments — long enough to cover
    most retry windows but short enough to bound the store).
  - The "payload hash" must be stable across language/runtime serializers.
    We use sorted-key JSON + SHA-256.
  - This module is sync-and-async friendly; the store interface is sync,
    but @idempotent works on async functions too.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, Optional, Protocol, TypeVar

from .errors import (
    IdempotencyConflictError,
    IdempotencyInFlightError,
    PaymentError,
)

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


# ---------------------------------------------------------------------------
# State and record types
# ---------------------------------------------------------------------------

class IdempotencyState(str, Enum):
    IN_FLIGHT = "in_flight"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class IdempotencyRecord:
    """
    One row in the idempotency store.

    `payload_hash` is checked on key reuse to detect mismatched payloads
    (a sign of a buggy client or — worse — an attacker replaying keys).
    """
    key: str
    payload_hash: str
    state: IdempotencyState
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    # COMPLETED records hold the function return value.
    result: Optional[Any] = None
    # FAILED records hold a serialized error description.
    error: Optional[Dict[str, Any]] = None

    def is_expired(self, now: Optional[float] = None) -> bool:
        return (now or time.time()) >= self.expires_at


# ---------------------------------------------------------------------------
# Store interface — implementations should be durable in production
# ---------------------------------------------------------------------------

class IdempotencyStore(Protocol):
    """
    Pluggable store. Two implementations ship with this module:

    - InMemoryIdempotencyStore: for tests and single-process apps.
    - For production, implement this Protocol against Redis (SETNX + EXPIRE)
      or a DB table with a unique index on `key`.

    All operations must be atomic. The `set_if_absent` method is the critical
    primitive — it must succeed for exactly one caller when two arrive at the
    same time with the same key.
    """

    def get(self, key: str) -> Optional[IdempotencyRecord]: ...
    def set_if_absent(self, record: IdempotencyRecord) -> bool: ...
    def update(self, record: IdempotencyRecord) -> None: ...
    def delete(self, key: str) -> None: ...


class InMemoryIdempotencyStore:
    """
    Thread-safe in-memory store. NOT for production — process restart loses
    all records, defeating idempotency. Useful for tests and local dev.
    """

    def __init__(self) -> None:
        self._data: Dict[str, IdempotencyRecord] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[IdempotencyRecord]:
        with self._lock:
            record = self._data.get(key)
            if record and record.is_expired():
                # Lazy expiration on read.
                del self._data[key]
                return None
            return record

    def set_if_absent(self, record: IdempotencyRecord) -> bool:
        """Returns True if inserted, False if a non-expired record already exists."""
        with self._lock:
            existing = self._data.get(record.key)
            if existing and not existing.is_expired():
                return False
            self._data[record.key] = record
            return True

    def update(self, record: IdempotencyRecord) -> None:
        with self._lock:
            self._data[record.key] = record

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def hash_payload(payload: Any) -> str:
    """
    Deterministic SHA-256 of a JSON-serializable payload.

    `sort_keys=True` and `separators=(",",":")` make the encoding stable
    regardless of dict insertion order or pretty-printing.

    For non-JSON-serializable payloads (dataclasses, Pydantic models),
    convert to dict first.
    """
    if hasattr(payload, "model_dump"):  # Pydantic v2
        payload = payload.model_dump()
    elif hasattr(payload, "dict"):  # Pydantic v1
        payload = payload.dict()
    elif hasattr(payload, "__dataclass_fields__"):
        payload = asdict(payload)

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------

def idempotent(
    store: IdempotencyStore,
    *,
    key_arg: str = "idempotency_key",
    payload_arg: Optional[str] = None,
    ttl_seconds: float = 24 * 60 * 60,
):
    """
    Make a function idempotent.

    The wrapped function must accept an `idempotency_key` keyword argument
    (the parameter name is configurable via `key_arg`). The payload to be
    hashed is taken from `payload_arg` if specified, otherwise from all
    other kwargs combined.

    Args:
        store: Where to persist idempotency records. Use Redis or a DB
               table in production.
        key_arg: Name of the kwarg holding the idempotency key.
        payload_arg: Name of the kwarg whose value identifies the request.
                     If None, all kwargs except `key_arg` are hashed.
        ttl_seconds: How long to remember keys. 24h is standard for payments.

    Raises:
        IdempotencyInFlightError: If the same key is currently being processed.
        IdempotencyConflictError: If the same key was used with a different payload.

    Example:
        store = RedisIdempotencyStore(redis_client)

        @idempotent(store, payload_arg="charge_request")
        def create_charge(charge_request: dict, idempotency_key: str) -> dict:
            return gateway.charge(**charge_request)

        # First call: processes and stores result.
        result = create_charge(charge_request={"amount": 100, "card": "tok_x"},
                               idempotency_key="abc-123")
        # Second call with same key+payload: returns stored result, no re-charge.
        result = create_charge(charge_request={"amount": 100, "card": "tok_x"},
                               idempotency_key="abc-123")
    """

    def decorator(func: F) -> F:

        def _build_record(key: str, payload_hash: str) -> IdempotencyRecord:
            now = time.time()
            return IdempotencyRecord(
                key=key,
                payload_hash=payload_hash,
                state=IdempotencyState.IN_FLIGHT,
                created_at=now,
                expires_at=now + ttl_seconds,
            )

        def _check_existing(
            existing: IdempotencyRecord, payload_hash: str, key: str
        ) -> Any:
            # Payload mismatch is always a hard error — no exceptions for any state.
            if existing.payload_hash != payload_hash:
                logger.warning(
                    "Idempotency key %s reused with mismatched payload hash", key
                )
                raise IdempotencyConflictError(
                    f"Idempotency key '{key}' was used with a different payload",
                    code="idempotency_conflict",
                )

            if existing.state == IdempotencyState.IN_FLIGHT:
                raise IdempotencyInFlightError(
                    f"Request with idempotency key '{key}' is still processing",
                    code="idempotency_in_flight",
                )

            if existing.state == IdempotencyState.COMPLETED:
                logger.info("Idempotency hit (completed) for key %s", key)
                return existing.result

            if existing.state == IdempotencyState.FAILED:
                # Replay the original error rather than retrying — the caller
                # asked for the same operation and it failed terminally.
                logger.info("Idempotency hit (failed) for key %s", key)
                err = existing.error or {}
                raise PaymentError(
                    err.get("message", "Previous attempt with this key failed"),
                    code=err.get("code"),
                )

        def _extract_payload(args: tuple, kwargs: dict) -> Any:
            if payload_arg is not None:
                if payload_arg in kwargs:
                    return kwargs[payload_arg]
                raise InvalidIdempotencyUsage(
                    f"@idempotent expected kwarg '{payload_arg}' to be present"
                )
            # Hash everything except the key itself and any positional args.
            # We discourage positional args here — they make payload identity fragile.
            return {k: v for k, v in kwargs.items() if k != key_arg}

        if asyncio.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                key = kwargs.get(key_arg)
                if not key:
                    # If no key is supplied, we cannot enforce idempotency.
                    # This is a deliberate design choice: we don't auto-generate
                    # keys because that would silently make the call non-idempotent.
                    return await func(*args, **kwargs)

                payload = _extract_payload(args, kwargs)
                payload_hash = hash_payload(payload)

                new_record = _build_record(key, payload_hash)
                if not store.set_if_absent(new_record):
                    existing = store.get(key)
                    if existing is not None:
                        return _check_existing(existing, payload_hash, key)
                    # Race: record was deleted/expired between set_if_absent and get.
                    # Try once more — if this fails, surface the conflict honestly.
                    if not store.set_if_absent(new_record):
                        raise IdempotencyInFlightError(
                            f"Could not acquire idempotency slot for '{key}'",
                            code="idempotency_race",
                        )

                try:
                    result = await func(*args, **kwargs)
                except PaymentError as e:
                    if not e.retriable:
                        # Persist terminal failures — replaying the same key
                        # should reproduce the same error, not retry the call.
                        new_record.state = IdempotencyState.FAILED
                        new_record.error = e.to_dict()
                        store.update(new_record)
                    else:
                        # Retriable errors: clear the record so the client can retry.
                        store.delete(key)
                    raise
                except Exception:
                    # Unknown errors are treated as retriable — clear the slot.
                    store.delete(key)
                    raise

                new_record.state = IdempotencyState.COMPLETED
                new_record.result = result
                store.update(new_record)
                return result

            return async_wrapper  # type: ignore[return-value]

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            key = kwargs.get(key_arg)
            if not key:
                return func(*args, **kwargs)

            payload = _extract_payload(args, kwargs)
            payload_hash = hash_payload(payload)

            new_record = _build_record(key, payload_hash)
            if not store.set_if_absent(new_record):
                existing = store.get(key)
                if existing is not None:
                    return _check_existing(existing, payload_hash, key)
                if not store.set_if_absent(new_record):
                    raise IdempotencyInFlightError(
                        f"Could not acquire idempotency slot for '{key}'",
                        code="idempotency_race",
                    )

            try:
                result = func(*args, **kwargs)
            except PaymentError as e:
                if not e.retriable:
                    new_record.state = IdempotencyState.FAILED
                    new_record.error = e.to_dict()
                    store.update(new_record)
                else:
                    store.delete(key)
                raise
            except Exception:
                store.delete(key)
                raise

            new_record.state = IdempotencyState.COMPLETED
            new_record.result = result
            store.update(new_record)
            return result

        return sync_wrapper  # type: ignore[return-value]

    return decorator


class InvalidIdempotencyUsage(Exception):
    """The @idempotent decorator was used incorrectly at definition time."""
