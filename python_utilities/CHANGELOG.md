# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2024-01-01

### Added
- Initial release of python-utilities
- Decorators module with retry, rate limiting, circuit breaker, caching, and timing
- Async utilities for concurrent operations and queue management
- Context managers for resource safety and transaction management
- Performance profiling and benchmarking tools
- Pydantic-based validation utilities
- Dependency injection container with lifecycle management
- Design patterns: Repository, Unit of Work, Event Bus, Specification
- Comprehensive documentation and examples
- Production-ready code with logging and error handling

### Features

#### Decorators
- `@retry` - Retry with exponential backoff
- `@rate_limit` - Rate limiting with sliding window
- `@circuit_breaker` - Circuit breaker pattern for fault tolerance
- `@cached` - Caching with TTL support
- `@timer` - Execution time measurement
- `@log_execution` - Automatic logging
- `@require_auth` / `@require_roles` - Authentication and authorization

#### Async Utilities
- `AsyncQueue` - Producer-consumer pattern implementation
- `RateLimitedFetcher` - Concurrent requests with rate limiting
- `AsyncBatchProcessor` - Batch processing with auto-flush
- `AsyncResourcePool` - Generic resource pooling
- `retry_async` - Async retry decorator

#### Context Managers
- `database_session` - Database session management
- `temporary_directory` - Temporary directory with cleanup
- `atomic_write` - Atomic file writes
- `file_lock` - File-based locking
- `managed_resource` - Generic resource management
- `ConnectionPool` - Connection pooling

#### Performance
- `profile_function` - cProfile integration
- `measure_memory` - Memory usage tracking
- `benchmark` - Function benchmarking
- `compare_implementations` - Compare multiple implementations
- `PerformanceMonitor` - Production performance monitoring
- `CacheStats` - Cache hit/miss tracking

#### Validation
- `validate_with_pydantic` - Automatic input/output validation
- `create_settings` - Settings from environment variables
- `validate_bulk` - Bulk validation
- `generate_json_schema` - Schema generation
- Built-in validators for email, phone, password, URL, etc.

#### Dependency Injection
- `DIContainer` - Dependency injection container
- Lifecycle management (singleton, transient, scoped)
- Automatic dependency resolution
- `@inject` decorator
- `Factory` pattern implementation
- `Lazy` initialization

#### Design Patterns
- `Repository` - Abstract repository pattern
- `InMemoryRepository` - In-memory implementation for testing
- `UnitOfWork` - Transaction management
- `EventBus` - Event-driven architecture
- `Specification` - Business rule specification
- `Observer` - Observer pattern

### Documentation
- Comprehensive README with examples
- Detailed docstrings for all public APIs
- Complete example applications
- Quick-start guide

### Testing
- Unit test helpers with in-memory implementations
- Mock-friendly dependency injection
- Test utilities for async code

## [Unreleased]

### Planned
- Distributed tracing integration (OpenTelemetry)
- More async patterns (semaphores, barriers, etc.)
- Database-specific repository implementations (SQLAlchemy, MongoDB)
- Enhanced caching strategies (write-through, write-behind)
- Metrics exporters for Prometheus/Grafana
- Circuit breaker with half-open state
- Saga pattern for distributed transactions
- CQRS pattern utilities
