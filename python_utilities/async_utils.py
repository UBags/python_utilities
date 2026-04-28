"""
Async Utilities Module

Production-ready async patterns:
- Concurrent task execution
- Producer-consumer patterns with queues
- Rate-limited async operations
- Async retry mechanisms
- WebSocket and SSE utilities
"""

import asyncio
import logging
from typing import Callable, Any, Optional, List, TypeVar, Coroutine
from datetime import datetime, timedelta
from collections import deque
import functools

logger = logging.getLogger(__name__)

T = TypeVar('T')


# ============================================================================
# ASYNC RETRY - Retry with exponential backoff for async functions
# ============================================================================

def retry_async(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
):
    """
    Async retry decorator with exponential backoff.
    
    Production use cases:
    - Async HTTP requests that may timeout
    - Database operations in async frameworks
    - Async message queue operations
    
    Example:
        @retry_async(max_attempts=5, delay=1.0, backoff=2.0)
        async def fetch_data(url: str):
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    return await response.json()
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_attempts - 1:
                        logger.error(
                            f"{func.__name__} failed after {max_attempts} attempts: {e}"
                        )
                        raise
                    
                    logger.warning(
                        f"{func.__name__} attempt {attempt + 1}/{max_attempts} "
                        f"failed: {e}. Retrying in {current_delay}s..."
                    )
                    
                    await asyncio.sleep(current_delay)
                    current_delay *= backoff
            
            raise last_exception
        
        return wrapper
    return decorator


# ============================================================================
# ASYNC QUEUE - Producer-Consumer Pattern
# ============================================================================

class AsyncQueue:
    """
    Async producer-consumer queue with worker pool.
    
    Production use cases:
    - Task queues for background processing
    - Rate-limited API consumption
    - Log aggregation and streaming
    - Event processing pipelines
    
    Example:
        async def process_item(item):
            await asyncio.sleep(1)  # Simulate processing
            return f"Processed: {item}"
        
        queue = AsyncQueue(num_workers=5, process_func=process_item)
        await queue.start()
        
        # Add items
        for i in range(100):
            await queue.put(i)
        
        await queue.stop()
    """
    
    def __init__(
        self,
        num_workers: int = 5,
        process_func: Optional[Callable] = None,
        maxsize: int = 0,
        on_error: Optional[Callable] = None,
    ):
        self.num_workers = num_workers
        self.process_func = process_func
        self.on_error = on_error
        self.queue = asyncio.Queue(maxsize=maxsize)
        self.workers: List[asyncio.Task] = []
        self.results: List[Any] = []
        self._running = False
    
    async def start(self):
        """Start worker pool."""
        self._running = True
        self.workers = [
            asyncio.create_task(self._worker(i))
            for i in range(self.num_workers)
        ]
        logger.info(f"Started {self.num_workers} workers")
    
    async def _worker(self, worker_id: int):
        """Worker coroutine."""
        logger.debug(f"Worker {worker_id} started")
        
        while self._running:
            try:
                # Wait for item with timeout to allow graceful shutdown
                item = await asyncio.wait_for(
                    self.queue.get(),
                    timeout=1.0
                )
            except asyncio.TimeoutError:
                continue
            
            try:
                if self.process_func:
                    result = await self.process_func(item)
                    self.results.append(result)
                    logger.debug(f"Worker {worker_id} processed item: {item}")
            except Exception as e:
                logger.error(f"Worker {worker_id} error processing {item}: {e}")
                if self.on_error:
                    await self.on_error(item, e)
            finally:
                self.queue.task_done()
    
    async def put(self, item: Any):
        """Add item to queue."""
        await self.queue.put(item)
    
    async def join(self):
        """Wait for all items to be processed."""
        await self.queue.join()
    
    async def stop(self):
        """Stop all workers and wait for completion."""
        # Wait for queue to be empty
        await self.join()
        
        # Stop workers
        self._running = False
        
        # Wait for workers to finish
        await asyncio.gather(*self.workers, return_exceptions=True)
        
        logger.info("All workers stopped")
    
    def get_results(self) -> List[Any]:
        """Get all processed results."""
        return self.results.copy()


# ============================================================================
# RATE-LIMITED FETCHER - Concurrent requests with rate limiting
# ============================================================================

class RateLimitedFetcher:
    """
    Rate-limited async HTTP fetcher using semaphore.
    
    Production use cases:
    - Respect external API rate limits
    - Control concurrency to prevent overload
    - Batch processing with controlled throughput
    
    Example:
        fetcher = RateLimitedFetcher(max_concurrent=10, rate_limit=100)
        
        urls = [f"https://api.example.com/item/{i}" for i in range(1000)]
        results = await fetcher.fetch_all(urls)
    """
    
    def __init__(
        self,
        max_concurrent: int = 10,
        rate_limit: Optional[int] = None,
        rate_period: float = 60.0,
    ):
        """
        Args:
            max_concurrent: Maximum concurrent requests
            rate_limit: Maximum requests per rate_period (None for unlimited)
            rate_period: Time period for rate limit in seconds
        """
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.rate_limit = rate_limit
        self.rate_period = rate_period
        
        if rate_limit:
            self.request_times: deque = deque()
    
    async def _wait_for_rate_limit(self):
        """Wait if rate limit would be exceeded."""
        if not self.rate_limit:
            return
        
        now = datetime.now()
        cutoff = now - timedelta(seconds=self.rate_period)
        
        # Remove old requests
        while self.request_times and self.request_times[0] < cutoff:
            self.request_times.popleft()
        
        # Wait if at limit
        if len(self.request_times) >= self.rate_limit:
            sleep_time = (
                self.request_times[0] + timedelta(seconds=self.rate_period) - now
            ).total_seconds()
            if sleep_time > 0:
                logger.debug(f"Rate limit reached, waiting {sleep_time:.2f}s")
                await asyncio.sleep(sleep_time)
        
        self.request_times.append(now)
    
    async def fetch(self, fetch_func: Callable, *args, **kwargs) -> Any:
        """
        Fetch with rate limiting and concurrency control.
        
        Args:
            fetch_func: Async function to call (e.g., aiohttp request)
            *args, **kwargs: Arguments to pass to fetch_func
        """
        async with self.semaphore:
            await self._wait_for_rate_limit()
            return await fetch_func(*args, **kwargs)
    
    async def fetch_all(
        self,
        items: List[Any],
        fetch_func: Callable,
        *args,
        **kwargs
    ) -> List[Any]:
        """
        Fetch all items with rate limiting.
        
        Args:
            items: List of items to fetch
            fetch_func: Async function that takes an item and returns result
        """
        tasks = [
            self.fetch(fetch_func, item, *args, **kwargs)
            for item in items
        ]
        return await asyncio.gather(*tasks, return_exceptions=True)


# ============================================================================
# ASYNC TIMEOUT - Timeout handling utilities
# ============================================================================

async def with_timeout(
    coro: Coroutine,
    timeout: float,
    default: Any = None,
) -> Any:
    """
    Execute coroutine with timeout.
    
    Production use cases:
    - Prevent hanging operations
    - SLA enforcement
    - Resource cleanup
    
    Example:
        result = await with_timeout(
            slow_operation(),
            timeout=5.0,
            default="timeout_value"
        )
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning(f"Operation timed out after {timeout}s")
        return default


# ============================================================================
# ASYNC BATCH PROCESSOR - Process items in batches
# ============================================================================

class AsyncBatchProcessor:
    """
    Process items in batches asynchronously.
    
    Production use cases:
    - Batch database inserts
    - Bulk API operations
    - Log shipping
    
    Example:
        async def save_batch(items):
            await db.bulk_insert(items)
        
        processor = AsyncBatchProcessor(
            batch_size=100,
            flush_interval=5.0,
            process_func=save_batch
        )
        
        await processor.start()
        
        for item in data_stream:
            await processor.add(item)
        
        await processor.stop()
    """
    
    def __init__(
        self,
        batch_size: int = 100,
        flush_interval: float = 5.0,
        process_func: Callable = None,
    ):
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.process_func = process_func
        
        self.current_batch: List[Any] = []
        self.last_flush = datetime.now()
        self._running = False
        self._flush_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
    
    async def start(self):
        """Start the batch processor."""
        self._running = True
        self._flush_task = asyncio.create_task(self._auto_flush())
    
    async def add(self, item: Any):
        """Add item to batch."""
        async with self._lock:
            self.current_batch.append(item)
            
            if len(self.current_batch) >= self.batch_size:
                await self._flush()
    
    async def _flush(self):
        """Flush current batch."""
        if not self.current_batch:
            return
        
        batch = self.current_batch
        self.current_batch = []
        self.last_flush = datetime.now()
        
        try:
            if self.process_func:
                await self.process_func(batch)
            logger.debug(f"Flushed batch of {len(batch)} items")
        except Exception as e:
            logger.error(f"Error processing batch: {e}")
    
    async def _auto_flush(self):
        """Periodically flush based on time interval."""
        while self._running:
            await asyncio.sleep(1.0)
            
            async with self._lock:
                time_since_flush = (datetime.now() - self.last_flush).total_seconds()
                if time_since_flush >= self.flush_interval and self.current_batch:
                    await self._flush()
    
    async def stop(self):
        """Stop processor and flush remaining items."""
        self._running = False
        
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        
        # Final flush
        async with self._lock:
            await self._flush()


# ============================================================================
# ASYNC SEMAPHORE POOL - Controlled concurrency
# ============================================================================

class AsyncSemaphorePool:
    """
    Manage async operations with controlled concurrency.
    
    Production use cases:
    - Database connection pooling
    - API request throttling
    - Resource-constrained operations
    
    Example:
        pool = AsyncSemaphorePool(max_concurrent=5)
        
        async with pool:
            result = await expensive_operation()
    """
    
    def __init__(self, max_concurrent: int):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.active = 0
        self._lock = asyncio.Lock()
    
    async def __aenter__(self):
        await self.semaphore.acquire()
        async with self._lock:
            self.active += 1
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        async with self._lock:
            self.active -= 1
        self.semaphore.release()
        return False
    
    def get_active_count(self) -> int:
        """Get number of currently active operations."""
        return self.active


# ============================================================================
# STREAMING UTILITIES
# ============================================================================

async def async_generator_to_list(
    async_gen,
    max_items: Optional[int] = None,
) -> List[Any]:
    """
    Convert async generator to list.
    
    Production use cases:
    - Collect streaming results
    - Testing async generators
    
    Example:
        async def generate_items():
            for i in range(100):
                await asyncio.sleep(0.1)
                yield i
        
        items = await async_generator_to_list(generate_items(), max_items=10)
    """
    items = []
    count = 0
    
    async for item in async_gen:
        items.append(item)
        count += 1
        if max_items and count >= max_items:
            break
    
    return items


async def merge_async_generators(*async_gens):
    """
    Merge multiple async generators into one.
    
    Production use cases:
    - Combine multiple data streams
    - Aggregate real-time events
    
    Example:
        async def gen1():
            yield 1; yield 2
        
        async def gen2():
            yield 3; yield 4
        
        async for item in merge_async_generators(gen1(), gen2()):
            print(item)  # 1, 2, 3, 4 (order not guaranteed)
    """
    queue = asyncio.Queue()
    
    async def consume(gen):
        async for item in gen:
            await queue.put(('item', item))
        await queue.put(('done', None))
    
    # Start all consumers
    tasks = [asyncio.create_task(consume(gen)) for gen in async_gens]
    done_count = 0
    
    while done_count < len(async_gens):
        msg_type, item = await queue.get()
        if msg_type == 'done':
            done_count += 1
        else:
            yield item
    
    # Wait for all tasks to complete
    await asyncio.gather(*tasks)


# ============================================================================
# ASYNC CONTEXT MANAGERS
# ============================================================================

class AsyncResourcePool:
    """
    Generic async resource pool.
    
    Production use cases:
    - Database connection pools
    - HTTP client session pools
    - Redis connection pools
    
    Example:
        async def create_connection():
            return await asyncpg.connect('postgresql://...')
        
        pool = AsyncResourcePool(
            create_func=create_connection,
            pool_size=10
        )
        
        async with pool.acquire() as conn:
            await conn.execute('SELECT 1')
    """
    
    def __init__(self, create_func: Callable, pool_size: int = 10):
        self.create_func = create_func
        self.pool_size = pool_size
        self.pool: asyncio.Queue = asyncio.Queue(maxsize=pool_size)
        self._initialized = False
    
    async def initialize(self):
        """Initialize the pool with resources."""
        if self._initialized:
            return
        
        for _ in range(self.pool_size):
            resource = await self.create_func()
            await self.pool.put(resource)
        
        self._initialized = True
    
    def acquire(self):
        """Acquire a resource from the pool."""
        return self._PoolContext(self)
    
    class _PoolContext:
        def __init__(self, pool):
            self.pool = pool
            self.resource = None
        
        async def __aenter__(self):
            if not self.pool._initialized:
                await self.pool.initialize()
            
            self.resource = await self.pool.pool.get()
            return self.resource
        
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            await self.pool.pool.put(self.resource)
            return False
