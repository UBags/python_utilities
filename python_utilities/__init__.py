"""
python_utilities — production-ready utilities for modern Python applications.

A toolbox of decorators, async patterns, context managers, profiling helpers,
validation utilities, a dependency-injection container, and architectural
design patterns (Repository, Unit of Work, Event Bus, Specification, Observer).

For payment-specific primitives (idempotency, sagas, webhook verification,
PCI redaction, fraud rules, reconciliation), see the sibling `payments`
package.

Two import styles are supported:

    # Submodule import (recommended — explicit, doesn't pollute namespace).
    from python_utilities.decorators import retry, cached
    from python_utilities.patterns import Repository, EventBus

    # Top-level import (convenient for interactive use).
    from python_utilities import retry, EventBus, DIContainer
"""

# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------
from python_utilities.decorators import (
    retry,
    rate_limit,
    RateLimiter,
    timer,
    cached,
    TTLCache,
    log_execution,
    circuit_breaker,
    CircuitBreaker,
    CircuitBreakerState,
    require_auth,
    require_roles,
)

# ---------------------------------------------------------------------------
# Async utilities
# ---------------------------------------------------------------------------
from python_utilities.async_utils import (
    retry_async,
    AsyncQueue,
    RateLimitedFetcher,
    with_timeout,
    AsyncBatchProcessor,
    AsyncSemaphorePool,
    AsyncResourcePool,
    async_generator_to_list,
    merge_async_generators,
)

# ---------------------------------------------------------------------------
# Context managers
#
# Note: both `decorators` and `context_managers` define a `timer`. The
# decorator version wins at the package level (imported above); the
# context-manager version is exported under the explicit name `timer_ctx`
# to avoid the collision. Users wanting the context-manager form can also
# do `from python_utilities.context_managers import timer`.
# ---------------------------------------------------------------------------
from python_utilities.context_managers import (
    database_session,
    async_database_session,
    temporary_directory,
    atomic_write,
    managed_resource,
    ManagedResource,
    file_lock,
    change_directory,
    environment_variables,
    suppress_exceptions,
    ConnectionPool,
    transaction,
)
from python_utilities.context_managers import timer as timer_ctx

# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------
from python_utilities.performance import (
    profile_function,
    ProfileContext,
    measure_memory,
    MemoryTracker,
    benchmark,
    BenchmarkResult,
    compare_implementations,
    CacheStats,
    PerformanceMonitor,
    suggest_optimizations,
)

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
from python_utilities.validation import (
    validate_with_pydantic,
    create_settings,
    validate_json,
    validate_dict,
    validate_bulk,
    get_validation_errors,
    generate_json_schema,
    generate_openapi_schema,
    sanitize_dict,
    SanitizedString,
    EmailValidation,
    PhoneValidation,
    PasswordValidation,
    URLValidation,
    DateRangeValidation,
    CreditCardValidation,
    PaginationParams,
)

# ---------------------------------------------------------------------------
# Dependency injection
# ---------------------------------------------------------------------------
from python_utilities.dependency_injection import (
    DIContainer,
    Lifecycle,
    inject,
    Factory,
    ServiceLocator,
    Lazy,
    Provider,
)

# ---------------------------------------------------------------------------
# Architectural patterns
# ---------------------------------------------------------------------------
from python_utilities.patterns import (
    Repository,
    InMemoryRepository,
    UnitOfWork,
    Event,
    EventBus,
    Service,
    Specification,
    AndSpecification,
    OrSpecification,
    NotSpecification,
    Observer,
    Subject,
)

__version__ = "1.0.0"

__all__ = [
    # decorators
    "retry", "rate_limit", "RateLimiter", "timer", "cached", "TTLCache",
    "log_execution", "circuit_breaker", "CircuitBreaker", "CircuitBreakerState",
    "require_auth", "require_roles",
    # async
    "retry_async", "AsyncQueue", "RateLimitedFetcher", "with_timeout",
    "AsyncBatchProcessor", "AsyncSemaphorePool", "AsyncResourcePool",
    "async_generator_to_list", "merge_async_generators",
    # context managers
    "database_session", "async_database_session", "temporary_directory",
    "atomic_write", "managed_resource", "ManagedResource", "file_lock",
    "change_directory", "environment_variables", "suppress_exceptions",
    "ConnectionPool", "transaction", "timer_ctx",
    # performance
    "profile_function", "ProfileContext", "measure_memory", "MemoryTracker",
    "benchmark", "BenchmarkResult", "compare_implementations",
    "CacheStats", "PerformanceMonitor", "suggest_optimizations",
    # validation
    "validate_with_pydantic", "create_settings", "validate_json",
    "validate_dict", "validate_bulk", "get_validation_errors",
    "generate_json_schema", "generate_openapi_schema", "sanitize_dict",
    "SanitizedString", "EmailValidation", "PhoneValidation",
    "PasswordValidation", "URLValidation", "DateRangeValidation",
    "CreditCardValidation", "PaginationParams",
    # DI
    "DIContainer", "Lifecycle", "inject", "Factory", "ServiceLocator",
    "Lazy", "Provider",
    # patterns
    "Repository", "InMemoryRepository", "UnitOfWork", "Event", "EventBus",
    "Service", "Specification", "AndSpecification", "OrSpecification",
    "NotSpecification", "Observer", "Subject",
    # version
    "__version__",
]