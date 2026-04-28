"""
Python Utilities - Production-Ready Utilities Library

A comprehensive collection of production-tested utilities for modern Python applications.
Covering decorators, async patterns, performance optimization, validation, DI, and design patterns.

Usage:
    from python_utilities.decorators import retry, rate_limit, timer
    from python_utilities.async_utils import RateLimitedFetcher, AsyncQueue
    from python_utilities.validation import validate_with_pydantic
    from python_utilities.patterns import Repository, UnitOfWork, EventBus
"""

__version__ = "1.0.0"
__author__ = "Python Utilities Contributors"

# Import key utilities for convenience
from python_utilities.decorators import (
    retry,
    rate_limit,
    timer,
    cached,
    log_execution,
    circuit_breaker,
)

from python_utilities.async_utils import (
    AsyncQueue,
    RateLimitedFetcher,
    retry_async,
)

from python_utilities.context_managers import (
    database_session,
    temporary_directory,
    atomic_write,
    managed_resource,
)

from python_utilities.performance import (
    profile_function,
    measure_memory,
    benchmark,
)

from python_utilities.validation import (
    validate_with_pydantic,
    create_settings,
)

from python_utilities.dependency_injection import (
    DIContainer,
    inject,
)

from python_utilities.patterns import (
    Repository,
    UnitOfWork,
    EventBus,
)

__all__ = [
    # Decorators
    "retry",
    "rate_limit",
    "timer",
    "cached",
    "log_execution",
    "circuit_breaker",
    # Async utilities
    "AsyncQueue",
    "RateLimitedFetcher",
    "retry_async",
    # Context managers
    "database_session",
    "temporary_directory",
    "atomic_write",
    "managed_resource",
    # Performance
    "profile_function",
    "measure_memory",
    "benchmark",
    # Validation
    "validate_with_pydantic",
    "create_settings",
    # Dependency injection
    "DIContainer",
    "inject",
    # Patterns
    "Repository",
    "UnitOfWork",
    "EventBus",
]
