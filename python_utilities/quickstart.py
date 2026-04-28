"""
Quick Start Examples

Simple examples demonstrating common use cases for python_utilities.
"""

import asyncio
import logging
from datetime import timedelta

logging.basicConfig(level=logging.INFO)

# ============================================================================
# Example 1: Decorators for Resilient API Calls
# ============================================================================

print("=" * 70)
print("Example 1: Resilient API Calls")
print("=" * 70)

from python_utilities.decorators import retry, rate_limit, circuit_breaker, timer

@retry(max_attempts=3, delay=0.5, backoff=2.0)
@circuit_breaker(failure_threshold=5, recovery_timeout=10.0)
@timer()
def fetch_user_data(user_id: int):
    """Fetch user data with retry and circuit breaker."""
    print(f"Fetching data for user {user_id}")
    # Simulated API call
    return {"id": user_id, "name": f"User {user_id}"}

# Call the function
for i in range(3):
    user = fetch_user_data(i)
    print(f"  Got user: {user}")

# ============================================================================
# Example 2: Async Queue for Background Processing
# ============================================================================

print("\n" + "=" * 70)
print("Example 2: Background Task Processing")
print("=" * 70)

from python_utilities.async_utils import AsyncQueue

async def process_task(task):
    """Process a background task."""
    await asyncio.sleep(0.1)  # Simulate work
    return f"Processed: {task}"

async def background_processing_demo():
    # Create queue with 3 workers
    queue = AsyncQueue(num_workers=3, process_func=process_task)
    await queue.start()
    
    # Add tasks
    print("Adding 10 tasks to queue...")
    for i in range(10):
        await queue.put(f"Task-{i}")
    
    # Wait for completion
    await queue.stop()
    
    # Get results
    results = queue.get_results()
    print(f"Completed {len(results)} tasks")
    for result in results[:3]:  # Show first 3
        print(f"  {result}")

asyncio.run(background_processing_demo())

# ============================================================================
# Example 3: Context Managers for Resource Safety
# ============================================================================

print("\n" + "=" * 70)
print("Example 3: Safe Resource Management")
print("=" * 70)

from python_utilities.context_managers import temporary_directory, timer as timer_ctx
from pathlib import Path

with timer_ctx("File Processing"):
    with temporary_directory(prefix="demo_") as tmp_dir:
        # Create temp file
        temp_file = tmp_dir / "data.txt"
        temp_file.write_text("Hello, World!")
        
        print(f"Created temp file: {temp_file}")
        print(f"  Content: {temp_file.read_text()}")
        print(f"  Exists: {temp_file.exists()}")
    
    # tmp_dir is automatically deleted here
    print(f"After context: temp directory cleaned up")

# ============================================================================
# Example 4: Dependency Injection
# ============================================================================

print("\n" + "=" * 70)
print("Example 4: Dependency Injection")
print("=" * 70)

from python_utilities.dependency_injection import DIContainer, Lifecycle

# Define services
class Database:
    def query(self, sql: str):
        return f"Result of: {sql}"

class Cache:
    def get(self, key: str):
        return f"Cached value for: {key}"

class UserService:
    def __init__(self, database: Database, cache: Cache):
        self.db = database
        self.cache = cache
    
    def get_user(self, user_id: int):
        # Try cache first
        cached = self.cache.get(f"user:{user_id}")
        if cached:
            return cached
        
        # Fall back to database
        return self.db.query(f"SELECT * FROM users WHERE id={user_id}")

# Setup container
container = DIContainer()
container.register(Database, Database, lifecycle=Lifecycle.SINGLETON)
container.register(Cache, Cache, lifecycle=Lifecycle.SINGLETON)
container.register(UserService, UserService)

# Resolve with automatic dependency injection
user_service = container.resolve(UserService)
result = user_service.get_user(123)
print(f"User service result: {result}")

# ============================================================================
# Example 5: Event-Driven Architecture
# ============================================================================

print("\n" + "=" * 70)
print("Example 5: Event-Driven Architecture")
print("=" * 70)

from python_utilities.patterns import EventBus, Event

# Create event bus
event_bus = EventBus()

# Subscribe handlers
@event_bus.subscribe('user_created')
def log_user_creation(event: Event):
    print(f"  [Logger] User created: {event.data['user_id']}")

@event_bus.subscribe('user_created')
def send_welcome_email(event: Event):
    print(f"  [Email] Sending welcome to: {event.data['email']}")

@event_bus.subscribe('user_created')
def update_analytics(event: Event):
    print(f"  [Analytics] Recording new user signup")

# Publish event
print("Publishing user_created event...")
event_bus.publish_sync(Event(
    event_type='user_created',
    data={'user_id': 456, 'email': 'newuser@example.com'}
))

# ============================================================================
# Example 6: Repository Pattern
# ============================================================================

print("\n" + "=" * 70)
print("Example 6: Repository Pattern")
print("=" * 70)

from python_utilities.patterns import InMemoryRepository
from dataclasses import dataclass

@dataclass
class Product:
    id: int
    name: str
    price: float

# Create repository
products_repo = InMemoryRepository()

# Add products
products_repo.create(Product(id=1, name="Laptop", price=999.99))
products_repo.create(Product(id=2, name="Mouse", price=29.99))
products_repo.create(Product(id=3, name="Keyboard", price=79.99))

# Query products
print("All products:")
for product in products_repo.list():
    print(f"  {product.name}: ${product.price:.2f}")

# Get specific product
product = products_repo.get(1)
print(f"\nProduct #1: {product.name}")

# ============================================================================
# Example 7: Performance Monitoring
# ============================================================================

print("\n" + "=" * 70)
print("Example 7: Performance Monitoring")
print("=" * 70)

from python_utilities.performance import PerformanceMonitor

monitor = PerformanceMonitor()

@monitor.track
def slow_operation():
    """Simulate slow operation."""
    import time
    time.sleep(0.1)
    return "done"

@monitor.track
def fast_operation():
    """Simulate fast operation."""
    return sum(range(1000))

# Run operations
for _ in range(5):
    slow_operation()
    fast_operation()

# Print statistics
print("\nPerformance Statistics:")
monitor.print_summary()

print("\n" + "=" * 70)
print("All examples completed!")
print("=" * 70)
