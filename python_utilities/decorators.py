"""
Production-Ready Decorators Module

Decorators for cross-cutting concerns:
- Authentication/authorization
- Logging, metrics, and tracing
- Retry logic with exponential backoff
- Rate limiting and circuit breakers
- Caching and memoization
"""

import functools
import time
import logging
from typing import Callable, Any, Optional, Dict
from datetime import datetime, timedelta
from collections import defaultdict
from threading import Lock
import hashlib
import json

logger = logging.getLogger(__name__)


# ============================================================================
# RETRY DECORATOR - For handling transient failures
# ============================================================================

def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
    on_retry: Optional[Callable] = None,
):
    """
    Retry decorator with exponential backoff.
    
    Production use cases:
    - External API calls that may fail transiently
    - Database operations during brief network issues
    - File system operations with temporary locks
    
    Args:
        max_attempts: Maximum number of retry attempts
        delay: Initial delay between retries (seconds)
        backoff: Multiplier for exponential backoff
        exceptions: Tuple of exceptions to catch and retry
        on_retry: Optional callback function called on each retry
    
    Example:
        @retry(max_attempts=5, delay=1.0, backoff=2.0)
        def fetch_from_api(url: str) -> dict:
            response = requests.get(url)
            response.raise_for_status()
            return response.json()
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
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
                    
                    if on_retry:
                        on_retry(attempt, e)
                    
                    time.sleep(current_delay)
                    current_delay *= backoff
            
            raise last_exception
        
        return wrapper
    return decorator


# ============================================================================
# RATE LIMITER - Prevent API abuse and respect external limits
# ============================================================================

class RateLimiter:
    """Thread-safe rate limiter using sliding window."""
    
    def __init__(self):
        self._calls: Dict[str, list] = defaultdict(list)
        self._lock = Lock()
    
    def is_allowed(self, key: str, max_calls: int, period: timedelta) -> bool:
        """Check if call is allowed under rate limit."""
        with self._lock:
            now = datetime.now()
            cutoff = now - period
            
            # Remove old calls outside window
            self._calls[key] = [
                call_time for call_time in self._calls[key]
                if call_time > cutoff
            ]
            
            if len(self._calls[key]) >= max_calls:
                return False
            
            self._calls[key].append(now)
            return True


_global_rate_limiter = RateLimiter()


def rate_limit(max_calls: int, period: timedelta, key_func: Optional[Callable] = None):
    """
    Rate limiting decorator.
    
    Production use cases:
    - Protect APIs from abuse
    - Respect third-party API rate limits
    - Prevent resource exhaustion
    
    Args:
        max_calls: Maximum number of calls allowed
        period: Time period for the limit
        key_func: Optional function to generate rate limit key from args
    
    Example:
        @rate_limit(max_calls=100, period=timedelta(minutes=1))
        def expensive_api_call():
            return external_api.fetch_data()
        
        # Per-user rate limiting
        @rate_limit(
            max_calls=10,
            period=timedelta(seconds=60),
            key_func=lambda user_id: f"user:{user_id}"
        )
        def user_action(user_id: int):
            pass
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Generate rate limit key
            if key_func:
                key = key_func(*args, **kwargs)
            else:
                key = func.__name__
            
            if not _global_rate_limiter.is_allowed(key, max_calls, period):
                raise Exception(
                    f"Rate limit exceeded: {max_calls} calls per {period}. "
                    f"Key: {key}"
                )
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


# ============================================================================
# TIMER - Measure and log execution time
# ============================================================================

def timer(
    log_level: int = logging.INFO,
    metric_name: Optional[str] = None,
    push_to_prometheus: bool = False,
):
    """
    Timer decorator for performance monitoring.
    
    Production use cases:
    - Monitor endpoint response times
    - Identify slow operations
    - Push metrics to Prometheus/Grafana
    
    Args:
        log_level: Logging level for timing info
        metric_name: Optional metric name for monitoring systems
        push_to_prometheus: Whether to push to Prometheus (requires prometheus_client)
    
    Example:
        @timer(metric_name="db_query_duration")
        def expensive_query():
            return db.execute(complex_query)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                elapsed = time.perf_counter() - start_time
                logger.log(
                    log_level,
                    f"{func.__name__} completed in {elapsed:.4f}s"
                )
                
                # Push to Prometheus if enabled
                if push_to_prometheus and metric_name:
                    try:
                        from prometheus_client import Histogram
                        FUNCTION_DURATION = Histogram(
                            metric_name,
                            f'Duration of {func.__name__}'
                        )
                        FUNCTION_DURATION.observe(elapsed)
                    except ImportError:
                        pass
        
        return wrapper
    return decorator


# ============================================================================
# CACHING - LRU cache with TTL support
# ============================================================================

class TTLCache:
    """Time-based cache with TTL support."""
    
    def __init__(self, ttl_seconds: float):
        self.ttl_seconds = ttl_seconds
        self.cache: Dict[str, tuple] = {}
        self._lock = Lock()
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired."""
        with self._lock:
            if key in self.cache:
                timestamp, value = self.cache[key]
                if time.time() - timestamp < self.ttl_seconds:
                    return value
                else:
                    del self.cache[key]
            return None
    
    def set(self, key: str, value: Any):
        """Set value in cache with current timestamp."""
        with self._lock:
            self.cache[key] = (time.time(), value)
    
    def clear(self):
        """Clear all cache entries."""
        with self._lock:
            self.cache.clear()


def cached(ttl_seconds: Optional[float] = None, maxsize: int = 128):
    """
    Caching decorator with optional TTL.
    
    Production use cases:
    - Cache expensive computations
    - Cache database lookups
    - Cache external API responses
    
    Args:
        ttl_seconds: Time-to-live in seconds (None for no expiration)
        maxsize: Maximum cache size (for functools.lru_cache)
    
    Example:
        @cached(ttl_seconds=300)  # 5 minute cache
        def get_user_permissions(user_id: int) -> list:
            return db.query(Permission).filter_by(user_id=user_id).all()
    """
    def decorator(func: Callable) -> Callable:
        if ttl_seconds is None:
            # Use standard LRU cache for no TTL
            return functools.lru_cache(maxsize=maxsize)(func)
        
        # Use TTL cache
        cache = TTLCache(ttl_seconds)
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Create cache key from args and kwargs
            key_data = {
                'args': args,
                'kwargs': kwargs,
            }
            cache_key = hashlib.md5(
                json.dumps(key_data, sort_keys=True, default=str).encode()
            ).hexdigest()
            
            # Check cache
            cached_value = cache.get(cache_key)
            if cached_value is not None:
                logger.debug(f"Cache hit for {func.__name__}")
                return cached_value
            
            # Compute and cache
            logger.debug(f"Cache miss for {func.__name__}")
            result = func(*args, **kwargs)
            cache.set(cache_key, result)
            return result
        
        wrapper.cache_clear = cache.clear
        return wrapper
    
    return decorator


# ============================================================================
# LOGGING DECORATOR - Automatic execution logging
# ============================================================================

def log_execution(
    log_args: bool = True,
    log_result: bool = False,
    log_level: int = logging.INFO,
):
    """
    Decorator for automatic execution logging.
    
    Production use cases:
    - Audit trails
    - Debugging production issues
    - Monitoring function usage
    
    Args:
        log_args: Whether to log function arguments
        log_result: Whether to log function result
        log_level: Logging level
    
    Example:
        @log_execution(log_args=True, log_result=True)
        def process_payment(user_id: int, amount: float):
            return payment_gateway.charge(user_id, amount)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            func_name = func.__name__
            
            if log_args:
                logger.log(
                    log_level,
                    f"Calling {func_name} with args={args}, kwargs={kwargs}"
                )
            else:
                logger.log(log_level, f"Calling {func_name}")
            
            try:
                result = func(*args, **kwargs)
                
                if log_result:
                    logger.log(
                        log_level,
                        f"{func_name} returned: {result}"
                    )
                else:
                    logger.log(log_level, f"{func_name} completed successfully")
                
                return result
            except Exception as e:
                logger.error(f"{func_name} raised {type(e).__name__}: {e}")
                raise
        
        return wrapper
    return decorator


# ============================================================================
# CIRCUIT BREAKER - Prevent cascading failures
# ============================================================================

class CircuitBreakerState:
    """Circuit breaker state machine."""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"      # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreaker:
    """Circuit breaker pattern implementation."""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: type = Exception,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = CircuitBreakerState.CLOSED
        self._lock = Lock()
    
    def call(self, func: Callable, *args, **kwargs):
        """Execute function with circuit breaker protection."""
        with self._lock:
            if self.state == CircuitBreakerState.OPEN:
                if time.time() - self.last_failure_time > self.recovery_timeout:
                    logger.info(f"Circuit breaker entering HALF_OPEN state")
                    self.state = CircuitBreakerState.HALF_OPEN
                else:
                    raise Exception(
                        f"Circuit breaker is OPEN. "
                        f"Service unavailable for {self.recovery_timeout}s"
                    )
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise e
    
    def _on_success(self):
        """Handle successful call."""
        with self._lock:
            self.failure_count = 0
            if self.state == CircuitBreakerState.HALF_OPEN:
                logger.info("Circuit breaker closing after successful test")
                self.state = CircuitBreakerState.CLOSED
    
    def _on_failure(self):
        """Handle failed call."""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold:
                logger.warning(
                    f"Circuit breaker opening after {self.failure_count} failures"
                )
                self.state = CircuitBreakerState.OPEN


def circuit_breaker(
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
    expected_exception: type = Exception,
):
    """
    Circuit breaker decorator to prevent cascading failures.
    
    Production use cases:
    - Protect against failing external services
    - Prevent resource exhaustion
    - Fast-fail when downstream is down
    
    Args:
        failure_threshold: Number of failures before opening circuit
        recovery_timeout: Seconds before attempting recovery
        expected_exception: Exception type that triggers circuit breaker
    
    Example:
        @circuit_breaker(failure_threshold=3, recovery_timeout=30.0)
        def call_external_api():
            return requests.get('https://external-api.com/data')
    """
    breaker = CircuitBreaker(failure_threshold, recovery_timeout, expected_exception)
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return breaker.call(func, *args, **kwargs)
        
        return wrapper
    return decorator


# ============================================================================
# AUTHENTICATION/AUTHORIZATION DECORATORS
# ============================================================================

def require_auth(get_user_func: Callable):
    """
    Authentication decorator.
    
    Production use cases:
    - Protect API endpoints
    - Verify JWT tokens
    - Session validation
    
    Example:
        def get_current_user(token: str):
            # Verify token and return user
            return User.from_token(token)
        
        @require_auth(get_current_user)
        def protected_endpoint(user, data):
            return f"Hello {user.name}"
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Get token from kwargs or context
            token = kwargs.get('token') or kwargs.get('authorization')
            
            if not token:
                raise PermissionError("Authentication required")
            
            user = get_user_func(token)
            if not user:
                raise PermissionError("Invalid credentials")
            
            # Inject user into function
            return func(user=user, *args, **kwargs)
        
        return wrapper
    return decorator


def require_roles(*required_roles):
    """
    Authorization decorator for role-based access control.
    
    Production use cases:
    - Role-based API access
    - Admin-only operations
    - Feature flags by user role
    
    Example:
        @require_roles('admin', 'superuser')
        def delete_user(user, user_id: int):
            User.delete(user_id)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            user = kwargs.get('user')
            if not user:
                raise PermissionError("User context required")
            
            user_roles = getattr(user, 'roles', [])
            if not any(role in required_roles for role in user_roles):
                raise PermissionError(
                    f"Required roles: {required_roles}. User has: {user_roles}"
                )
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator
