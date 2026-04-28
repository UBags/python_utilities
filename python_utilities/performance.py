"""
Performance Utilities Module

Production-ready performance optimization tools:
- Profiling and flame graphs
- Memory tracking and optimization
- Benchmarking utilities
- Cache strategies
"""

import cProfile
import pstats
import tracemalloc
import time
import timeit
import functools
import logging
from io import StringIO
from typing import Callable, Any, Optional, Dict, List
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


# ============================================================================
# PROFILING UTILITIES
# ============================================================================

def profile_function(
    func: Optional[Callable] = None,
    sort_by: str = 'cumulative',
    top_n: int = 20,
    output_file: Optional[str] = None,
):
    """
    Profile a function and print stats.
    
    Production use cases:
    - Identify performance bottlenecks
    - Optimize hot paths
    - Production profiling with py-spy integration
    
    Example:
        @profile_function(sort_by='cumulative', top_n=10)
        def expensive_operation():
            # Complex logic
            return result
        
        # Or as a context manager
        with ProfileContext() as profiler:
            expensive_operation()
            profiler.print_stats()
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            profiler = cProfile.Profile()
            profiler.enable()
            
            try:
                result = fn(*args, **kwargs)
                return result
            finally:
                profiler.disable()
                
                # Print stats
                stats = pstats.Stats(profiler)
                stats.strip_dirs()
                stats.sort_stats(sort_by)
                
                if output_file:
                    stats.dump_stats(output_file)
                    logger.info(f"Profile saved to {output_file}")
                else:
                    s = StringIO()
                    stats.stream = s
                    stats.print_stats(top_n)
                    logger.info(f"\n{s.getvalue()}")
        
        return wrapper
    
    if func is None:
        return decorator
    else:
        return decorator(func)


class ProfileContext:
    """
    Context manager for profiling code blocks.
    
    Example:
        with ProfileContext() as profiler:
            # Code to profile
            expensive_operation()
        
        profiler.print_stats(top_n=10)
    """
    
    def __init__(self):
        self.profiler = cProfile.Profile()
        self.stats = None
    
    def __enter__(self):
        self.profiler.enable()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.profiler.disable()
        self.stats = pstats.Stats(self.profiler)
        self.stats.strip_dirs()
        return False
    
    def print_stats(self, sort_by: str = 'cumulative', top_n: int = 20):
        """Print profiling stats."""
        if self.stats:
            self.stats.sort_stats(sort_by)
            self.stats.print_stats(top_n)
    
    def save_stats(self, filename: str):
        """Save stats to file for analysis."""
        if self.stats:
            self.stats.dump_stats(filename)
            logger.info(f"Profile saved to {filename}")


# ============================================================================
# MEMORY PROFILING
# ============================================================================

def measure_memory(
    func: Optional[Callable] = None,
    log_results: bool = True,
):
    """
    Measure memory usage of a function.
    
    Production use cases:
    - Identify memory leaks
    - Optimize memory-intensive operations
    - Monitor memory growth
    
    Example:
        @measure_memory(log_results=True)
        def process_large_dataset():
            data = [x ** 2 for x in range(1000000)]
            return sum(data)
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            tracemalloc.start()
            
            try:
                result = fn(*args, **kwargs)
                
                current, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                
                if log_results:
                    logger.info(
                        f"{fn.__name__} Memory Usage:\n"
                        f"  Current: {current / 1024 / 1024:.2f} MB\n"
                        f"  Peak: {peak / 1024 / 1024:.2f} MB"
                    )
                
                return result
            except Exception as e:
                tracemalloc.stop()
                raise e
        
        return wrapper
    
    if func is None:
        return decorator
    else:
        return decorator(func)


class MemoryTracker:
    """
    Track memory usage over time.
    
    Production use cases:
    - Monitor long-running processes
    - Detect memory leaks
    - Production memory monitoring
    
    Example:
        tracker = MemoryTracker()
        tracker.start()
        
        for batch in large_dataset:
            process(batch)
            tracker.snapshot('after_batch')
        
        tracker.print_summary()
    """
    
    def __init__(self):
        self.snapshots: List[tuple] = []
        self.running = False
    
    def start(self):
        """Start tracking memory."""
        tracemalloc.start()
        self.running = True
        logger.info("Memory tracking started")
    
    def snapshot(self, label: str = ""):
        """Take a memory snapshot."""
        if not self.running:
            raise RuntimeError("Memory tracking not started")
        
        current, peak = tracemalloc.get_traced_memory()
        self.snapshots.append((
            label,
            datetime.now(),
            current,
            peak
        ))
    
    def stop(self):
        """Stop tracking and get final snapshot."""
        if self.running:
            self.snapshot("final")
            tracemalloc.stop()
            self.running = False
            logger.info("Memory tracking stopped")
    
    def print_summary(self):
        """Print memory usage summary."""
        if not self.snapshots:
            logger.warning("No snapshots recorded")
            return
        
        logger.info("\nMemory Usage Summary:")
        logger.info("-" * 70)
        logger.info(f"{'Label':<20} {'Time':<20} {'Current (MB)':<15} {'Peak (MB)':<15}")
        logger.info("-" * 70)
        
        for label, timestamp, current, peak in self.snapshots:
            logger.info(
                f"{label:<20} "
                f"{timestamp.strftime('%H:%M:%S'):<20} "
                f"{current / 1024 / 1024:<15.2f} "
                f"{peak / 1024 / 1024:<15.2f}"
            )


# ============================================================================
# BENCHMARKING UTILITIES
# ============================================================================

@dataclass
class BenchmarkResult:
    """Benchmark result data."""
    name: str
    iterations: int
    total_time: float
    avg_time: float
    min_time: float
    max_time: float
    std_dev: float
    
    def __str__(self):
        return (
            f"{self.name}:\n"
            f"  Iterations: {self.iterations}\n"
            f"  Total time: {self.total_time:.6f}s\n"
            f"  Avg time: {self.avg_time * 1000:.6f}ms\n"
            f"  Min time: {self.min_time * 1000:.6f}ms\n"
            f"  Max time: {self.max_time * 1000:.6f}ms\n"
            f"  Std dev: {self.std_dev * 1000:.6f}ms"
        )


def benchmark(
    func: Callable,
    iterations: int = 1000,
    warmup: int = 10,
) -> BenchmarkResult:
    """
    Benchmark a function.
    
    Production use cases:
    - Compare implementation alternatives
    - Performance regression testing
    - Optimization validation
    
    Example:
        def method1():
            return [x**2 for x in range(1000)]
        
        def method2():
            return list(map(lambda x: x**2, range(1000)))
        
        result1 = benchmark(method1, iterations=10000)
        result2 = benchmark(method2, iterations=10000)
        
        print(result1)
        print(result2)
    """
    # Warmup
    for _ in range(warmup):
        func()
    
    # Benchmark
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        func()
        elapsed = time.perf_counter() - start
        times.append(elapsed)
    
    total_time = sum(times)
    avg_time = total_time / iterations
    min_time = min(times)
    max_time = max(times)
    
    # Calculate standard deviation
    variance = sum((t - avg_time) ** 2 for t in times) / iterations
    std_dev = variance ** 0.5
    
    return BenchmarkResult(
        name=func.__name__,
        iterations=iterations,
        total_time=total_time,
        avg_time=avg_time,
        min_time=min_time,
        max_time=max_time,
        std_dev=std_dev,
    )


def compare_implementations(
    *funcs: Callable,
    iterations: int = 1000,
) -> List[BenchmarkResult]:
    """
    Compare multiple implementations.
    
    Production use cases:
    - Algorithm selection
    - Performance optimization
    - A/B testing performance
    
    Example:
        results = compare_implementations(
            method1,
            method2,
            method3,
            iterations=10000
        )
        
        for result in sorted(results, key=lambda r: r.avg_time):
            print(result)
    """
    results = []
    
    for func in funcs:
        logger.info(f"Benchmarking {func.__name__}...")
        result = benchmark(func, iterations=iterations)
        results.append(result)
    
    # Sort by average time
    results.sort(key=lambda r: r.avg_time)
    
    # Print comparison
    logger.info("\n" + "=" * 70)
    logger.info("BENCHMARK COMPARISON")
    logger.info("=" * 70)
    
    fastest = results[0]
    for i, result in enumerate(results, 1):
        speedup = result.avg_time / fastest.avg_time
        logger.info(f"\n#{i} {result.name}")
        logger.info(f"  Avg time: {result.avg_time * 1000:.6f}ms")
        logger.info(f"  Speedup: {speedup:.2f}x {'(baseline)' if i == 1 else 'slower'}")
    
    return results


# ============================================================================
# CACHE PERFORMANCE MONITORING
# ============================================================================

class CacheStats:
    """
    Monitor cache hit/miss statistics.
    
    Production use cases:
    - Optimize cache size
    - Identify cache inefficiencies
    - Monitor cache performance
    
    Example:
        cache_stats = CacheStats()
        
        @cached_with_stats(cache_stats)
        def expensive_func(x):
            return x ** 2
    """
    
    def __init__(self):
        self.hits = 0
        self.misses = 0
        self.evictions = 0
    
    def record_hit(self):
        """Record cache hit."""
        self.hits += 1
    
    def record_miss(self):
        """Record cache miss."""
        self.misses += 1
    
    def record_eviction(self):
        """Record cache eviction."""
        self.evictions += 1
    
    @property
    def total_requests(self) -> int:
        """Total cache requests."""
        return self.hits + self.misses
    
    @property
    def hit_rate(self) -> float:
        """Cache hit rate."""
        if self.total_requests == 0:
            return 0.0
        return self.hits / self.total_requests
    
    @property
    def miss_rate(self) -> float:
        """Cache miss rate."""
        return 1.0 - self.hit_rate
    
    def reset(self):
        """Reset statistics."""
        self.hits = 0
        self.misses = 0
        self.evictions = 0
    
    def __str__(self):
        return (
            f"Cache Statistics:\n"
            f"  Hits: {self.hits}\n"
            f"  Misses: {self.misses}\n"
            f"  Evictions: {self.evictions}\n"
            f"  Hit rate: {self.hit_rate * 100:.2f}%\n"
            f"  Miss rate: {self.miss_rate * 100:.2f}%\n"
            f"  Total requests: {self.total_requests}"
        )


# ============================================================================
# PERFORMANCE MONITOR
# ============================================================================

class PerformanceMonitor:
    """
    Monitor function performance over time.
    
    Production use cases:
    - Production performance monitoring
    - SLA tracking
    - Performance regression detection
    
    Example:
        monitor = PerformanceMonitor()
        
        @monitor.track
        def api_endpoint():
            return process_request()
        
        # Later
        print(monitor.get_stats('api_endpoint'))
    """
    
    def __init__(self):
        self.metrics: Dict[str, List[float]] = {}
    
    def track(self, func: Callable) -> Callable:
        """Decorator to track function performance."""
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                elapsed = time.perf_counter() - start
                
                if func.__name__ not in self.metrics:
                    self.metrics[func.__name__] = []
                
                self.metrics[func.__name__].append(elapsed)
        
        return wrapper
    
    def get_stats(self, func_name: str) -> Dict[str, float]:
        """Get performance statistics for a function."""
        if func_name not in self.metrics:
            return {}
        
        times = self.metrics[func_name]
        
        return {
            'count': len(times),
            'total': sum(times),
            'avg': sum(times) / len(times),
            'min': min(times),
            'max': max(times),
            'p50': self._percentile(times, 0.5),
            'p95': self._percentile(times, 0.95),
            'p99': self._percentile(times, 0.99),
        }
    
    def _percentile(self, values: List[float], percentile: float) -> float:
        """Calculate percentile."""
        sorted_values = sorted(values)
        index = int(len(sorted_values) * percentile)
        return sorted_values[min(index, len(sorted_values) - 1)]
    
    def print_summary(self):
        """Print performance summary for all tracked functions."""
        logger.info("\n" + "=" * 70)
        logger.info("PERFORMANCE SUMMARY")
        logger.info("=" * 70)
        
        for func_name in self.metrics:
            stats = self.get_stats(func_name)
            logger.info(f"\n{func_name}:")
            logger.info(f"  Count: {stats['count']}")
            logger.info(f"  Avg: {stats['avg'] * 1000:.2f}ms")
            logger.info(f"  Min: {stats['min'] * 1000:.2f}ms")
            logger.info(f"  Max: {stats['max'] * 1000:.2f}ms")
            logger.info(f"  P50: {stats['p50'] * 1000:.2f}ms")
            logger.info(f"  P95: {stats['p95'] * 1000:.2f}ms")
            logger.info(f"  P99: {stats['p99'] * 1000:.2f}ms")
    
    def reset(self):
        """Reset all metrics."""
        self.metrics.clear()


# ============================================================================
# QUERY OPTIMIZER HINTS
# ============================================================================

def suggest_optimizations(func: Callable) -> Callable:
    """
    Analyze function and suggest optimizations.
    
    Production use cases:
    - Development-time optimization hints
    - Code review automation
    - Performance best practices enforcement
    
    Example:
        @suggest_optimizations
        def process_data(items):
            # Inefficient patterns detected automatically
            result = []
            for item in items:
                result.append(item ** 2)  # Hint: Use list comprehension
            return result
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Run with profiling
        profiler = cProfile.Profile()
        profiler.enable()
        result = func(*args, **kwargs)
        profiler.disable()
        
        # Analyze and suggest
        stats = pstats.Stats(profiler)
        stats.strip_dirs()
        
        # Simple heuristics
        suggestions = []
        
        # Check for common patterns
        import inspect
        source = inspect.getsource(func)
        
        if 'append' in source and 'for' in source:
            suggestions.append(
                "Consider using list comprehension instead of append in loop"
            )
        
        if suggestions:
            logger.info(f"\nOptimization suggestions for {func.__name__}:")
            for suggestion in suggestions:
                logger.info(f"  - {suggestion}")
        
        return result
    
    return wrapper
