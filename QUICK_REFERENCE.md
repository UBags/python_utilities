# Python Utilities - Quick Reference Cheat Sheet

## 🎯 Import Quick Reference

```python
# Decorators
from python_utilities.decorators import (
    retry, rate_limit, circuit_breaker, cached, timer,
    log_execution, require_auth, require_roles
)

# Async
from python_utilities.async_utils import (
    AsyncQueue, RateLimitedFetcher, AsyncBatchProcessor,
    retry_async, with_timeout
)

# Context Managers
from python_utilities.context_managers import (
    database_session, temporary_directory, atomic_write,
    file_lock, timer, managed_resource
)

# Performance
from python_utilities.performance import (
    profile_function, measure_memory, benchmark,
    compare_implementations, PerformanceMonitor
)

# Validation
from python_utilities.validation import (
    validate_with_pydantic, create_settings, validate_bulk,
    sanitize_dict, generate_json_schema
)

# Dependency Injection
from python_utilities.dependency_injection import (
    DIContainer, Lifecycle, inject, Factory
)

# Patterns
from python_utilities.patterns import (
    Repository, InMemoryRepository, UnitOfWork,
    EventBus, Event, Specification
)
```

## 💡 Common Patterns

### API Resilience Stack
```python
@retry(max_attempts=3, delay=1.0, backoff=2.0)
@circuit_breaker(failure_threshold=5, recovery_timeout=60.0)
@rate_limit(max_calls=100, period=timedelta(minutes=1))
@cached(ttl_seconds=300)
@timer(metric_name="api_call")
async def api_call(url: str):
    return await fetch(url)
```

### Database Transaction
```python
with database_session(SessionFactory) as session:
    with AppUnitOfWork(session) as uow:
        entity = uow.repository.get(id)
        entity.update(data)
        uow.repository.update(id, entity)
        # Auto-commits on success, rolls back on error
```

### Event-Driven Flow
```python
event_bus = EventBus()

@event_bus.subscribe('event_name')
async def handler(event: Event):
    await process(event.data)

await event_bus.publish(Event(
    event_type='event_name',
    data={'key': 'value'}
))
```

### Background Processing
```python
async def worker(item):
    return await process(item)

queue = AsyncQueue(num_workers=10, process_func=worker)
await queue.start()

for item in items:
    await queue.put(item)

await queue.stop()
results = queue.get_results()
```

### Dependency Injection
```python
container = DIContainer()
container.register(IService, Service, lifecycle=Lifecycle.SINGLETON)
service = container.resolve(IService)  # Auto-injects dependencies
```

## 🔥 One-Liners

```python
# Retry on failure
@retry(max_attempts=3)
def unstable_operation(): pass

# Cache for 5 minutes
@cached(ttl_seconds=300)
def expensive_query(): pass

# Time execution
@timer()
def slow_operation(): pass

# Validate input/output
@validate_with_pydantic(input_model=Input, output_model=Output)
def endpoint(data: dict) -> dict: pass

# Profile memory
@measure_memory()
def memory_heavy(): pass

# Temporary workspace
with temporary_directory() as tmp_dir:
    work_in(tmp_dir)

# Atomic file write
with atomic_write(Path("file.txt")) as f:
    f.write("data")

# Benchmark function
result = benchmark(function, iterations=10000)
```

## 📊 Lifecycle Comparison

| Pattern | When to Use | Example |
|---------|-------------|---------|
| `SINGLETON` | One instance app-wide | Database pool, config |
| `TRANSIENT` | New instance each time | Request handlers |
| `SCOPED` | One per scope/request | DB session per request |

## 🎨 Design Pattern Quick Guide

### Repository
```python
class UserRepo(Repository[User, int]):
    def get(self, id: int) -> Optional[User]: ...
    def create(self, entity: User) -> User: ...
```

### Unit of Work
```python
with UnitOfWork(session) as uow:
    uow.repo1.update(...)
    uow.repo2.create(...)
    # Commits both or neither
```

### Event Bus
```python
@event_bus.subscribe('event')
def handler(event): ...

event_bus.publish_sync(Event('event', data={...}))
```

## ⚡ Performance Tips

```python
# Compare implementations
results = compare_implementations(
    method1, method2, method3,
    iterations=10000
)

# Track production performance
monitor = PerformanceMonitor()

@monitor.track
def operation(): pass

monitor.print_summary()  # Shows p50, p95, p99
```

## 🧪 Testing Shortcuts

```python
# In-memory repository for tests
repo = InMemoryRepository()
repo.create(User(id=1, name="Test"))
assert repo.get(1).name == "Test"

# Mock with DI
container.register(IDatabase, MockDatabase)
service = container.resolve(UserService)
# Service uses mock automatically
```

## 🚨 Common Pitfalls

❌ **Don't**: Call blocking code in async functions
```python
async def bad():
    time.sleep(1)  # Blocks event loop!
```

✅ **Do**: Use async sleep
```python
async def good():
    await asyncio.sleep(1)  # Non-blocking
```

❌ **Don't**: Create new DI container per request
```python
def handler():
    container = DIContainer()  # Too slow!
```

✅ **Do**: Reuse container
```python
container = DIContainer()  # Once at startup

def handler():
    service = container.resolve(IService)
```

## 📈 Scaling Checklist

- [ ] Use `@cached` for expensive operations
- [ ] Add `@circuit_breaker` for external services
- [ ] Use `AsyncQueue` for background tasks
- [ ] Profile with `@profile_function`
- [ ] Track metrics with `PerformanceMonitor`
- [ ] Use connection pools (via `ConnectionPool`)
- [ ] Implement event-driven architecture
- [ ] Use Repository pattern for data access
- [ ] Add proper error handling and logging

## 🔗 Quick Links

- **Full Guide**: `python_comprehensive_guide.md`
- **Package Docs**: `python_utilities/README.md`
- **Examples**: `python_utilities/examples/`
- **Summary**: `PACKAGE_SUMMARY.md`
