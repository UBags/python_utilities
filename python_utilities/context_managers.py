"""
Context Managers Module

Production-ready context managers for resource safety:
- Database sessions and connection pooling
- File operations with atomic writes
- Temporary resources
- Lock management
- Transaction boundaries
"""

import os
import shutil
import tempfile
from pathlib import Path
from contextlib import contextmanager, asynccontextmanager
from typing import Optional, Any, Generator
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# DATABASE SESSION CONTEXT MANAGER
# ============================================================================

@contextmanager
def database_session(session_factory, commit_on_success: bool = True):
    """
    Database session context manager with automatic commit/rollback.
    
    Production use cases:
    - SQLAlchemy session management
    - Ensure proper cleanup even on exceptions
    - Transaction boundaries
    
    Example:
        from sqlalchemy.orm import sessionmaker
        
        Session = sessionmaker(bind=engine)
        
        with database_session(Session) as session:
            user = User(name="Alice")
            session.add(user)
            # Automatically commits on success, rolls back on exception
    """
    session = session_factory()
    try:
        yield session
        if commit_on_success:
            session.commit()
            logger.debug("Database transaction committed")
    except Exception as e:
        session.rollback()
        logger.error(f"Database transaction rolled back due to: {e}")
        raise
    finally:
        session.close()
        logger.debug("Database session closed")


@asynccontextmanager
async def async_database_session(session_factory, commit_on_success: bool = True):
    """
    Async database session context manager.
    
    Production use cases:
    - Async SQLAlchemy sessions
    - AsyncPG connection management
    - FastAPI with async database
    
    Example:
        from sqlalchemy.ext.asyncio import AsyncSession
        
        async with async_database_session(AsyncSession) as session:
            result = await session.execute(select(User))
            users = result.scalars().all()
    """
    session = session_factory()
    try:
        yield session
        if commit_on_success:
            await session.commit()
            logger.debug("Async database transaction committed")
    except Exception as e:
        await session.rollback()
        logger.error(f"Async database transaction rolled back due to: {e}")
        raise
    finally:
        await session.close()
        logger.debug("Async database session closed")


# ============================================================================
# TEMPORARY DIRECTORY - Auto-cleanup
# ============================================================================

@contextmanager
def temporary_directory(
    prefix: str = "tmp_",
    cleanup_on_error: bool = True,
) -> Generator[Path, None, None]:
    """
    Create temporary directory with automatic cleanup.
    
    Production use cases:
    - File processing pipelines
    - Test fixtures
    - Build artifacts
    
    Example:
        with temporary_directory(prefix="build_") as tmp_dir:
            output_file = tmp_dir / "output.txt"
            output_file.write_text("data")
            # Process files
        # Directory automatically deleted
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix=prefix))
    logger.debug(f"Created temporary directory: {tmp_dir}")
    
    try:
        yield tmp_dir
    except Exception as e:
        logger.error(f"Error in temporary directory context: {e}")
        if not cleanup_on_error:
            logger.warning(f"Preserving directory for debugging: {tmp_dir}")
            raise
        raise
    finally:
        if tmp_dir.exists() and (cleanup_on_error or True):
            shutil.rmtree(tmp_dir)
            logger.debug(f"Cleaned up temporary directory: {tmp_dir}")


# ============================================================================
# ATOMIC FILE WRITE - Write-then-rename pattern
# ============================================================================

@contextmanager
def atomic_write(
    filepath: Path,
    mode: str = 'w',
    encoding: str = 'utf-8',
    **kwargs
) -> Generator:
    """
    Atomic file write using temp file and rename.
    
    Production use cases:
    - Config file updates
    - Critical data files
    - Prevent partial writes on crash
    
    Example:
        with atomic_write(Path("config.json")) as f:
            json.dump(config_data, f)
        # File only updated if write succeeds
    """
    filepath = Path(filepath)
    tmp_path = filepath.with_suffix('.tmp')
    
    try:
        with open(tmp_path, mode, encoding=encoding, **kwargs) as f:
            yield f
        
        # Atomic rename
        tmp_path.replace(filepath)
        logger.debug(f"Atomically wrote to {filepath}")
    
    except Exception as e:
        logger.error(f"Failed to write {filepath}: {e}")
        if tmp_path.exists():
            tmp_path.unlink()
        raise


# ============================================================================
# MANAGED RESOURCE - Generic resource management
# ============================================================================

class ManagedResource:
    """
    Generic resource manager with setup and teardown.
    
    Production use cases:
    - Custom resource types
    - Cleanup guarantees
    - Resource pooling
    
    Example:
        resource_manager = ManagedResource(
            setup=lambda: redis.Redis(),
            teardown=lambda r: r.close()
        )
        
        with resource_manager as redis_client:
            redis_client.set('key', 'value')
    """
    
    def __init__(
        self,
        setup: callable,
        teardown: Optional[callable] = None,
        on_error: Optional[callable] = None,
    ):
        self.setup = setup
        self.teardown = teardown
        self.on_error = on_error
        self.resource = None
    
    def __enter__(self):
        self.resource = self.setup()
        logger.debug(f"Resource acquired: {type(self.resource).__name__}")
        return self.resource
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            logger.error(f"Exception in resource context: {exc_val}")
            if self.on_error:
                self.on_error(self.resource, exc_val)
        
        if self.teardown and self.resource:
            try:
                self.teardown(self.resource)
                logger.debug(f"Resource released: {type(self.resource).__name__}")
            except Exception as e:
                logger.error(f"Error during resource cleanup: {e}")
        
        return False  # Don't suppress exceptions


@contextmanager
def managed_resource(
    setup: callable,
    teardown: Optional[callable] = None,
):
    """
    Functional wrapper for ManagedResource.
    
    Example:
        def create_connection():
            return psycopg2.connect('postgresql://...')
        
        with managed_resource(
            setup=create_connection,
            teardown=lambda conn: conn.close()
        ) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT 1')
    """
    manager = ManagedResource(setup, teardown)
    with manager as resource:
        yield resource


# ============================================================================
# FILE LOCK - Prevent concurrent access
# ============================================================================

@contextmanager
def file_lock(
    lock_file: Path,
    timeout: float = 10.0,
    check_interval: float = 0.1,
):
    """
    Simple file-based lock.
    
    Production use cases:
    - Prevent concurrent script execution
    - Single-instance enforcement
    - Coordinating multiple processes
    
    Example:
        with file_lock(Path("/tmp/myapp.lock")):
            # Critical section - only one process at a time
            perform_exclusive_operation()
    """
    import time
    lock_file = Path(lock_file)
    elapsed = 0.0
    
    # Wait for lock
    while lock_file.exists() and elapsed < timeout:
        time.sleep(check_interval)
        elapsed += check_interval
    
    if lock_file.exists():
        raise TimeoutError(f"Could not acquire lock on {lock_file} after {timeout}s")
    
    # Create lock file
    lock_file.touch()
    logger.debug(f"Acquired lock: {lock_file}")
    
    try:
        yield lock_file
    finally:
        if lock_file.exists():
            lock_file.unlink()
            logger.debug(f"Released lock: {lock_file}")


# ============================================================================
# CHANGE DIRECTORY - Temporarily change working directory
# ============================================================================

@contextmanager
def change_directory(path: Path):
    """
    Temporarily change working directory.
    
    Production use cases:
    - Build scripts
    - Legacy code requiring specific working directory
    - File operations relative to specific path
    
    Example:
        with change_directory(Path("/tmp")):
            # Working directory is /tmp
            Path("file.txt").write_text("data")
        # Working directory restored
    """
    original_dir = Path.cwd()
    try:
        os.chdir(path)
        logger.debug(f"Changed directory to: {path}")
        yield path
    finally:
        os.chdir(original_dir)
        logger.debug(f"Restored directory to: {original_dir}")


# ============================================================================
# ENVIRONMENT VARIABLES - Temporary environment changes
# ============================================================================

@contextmanager
def environment_variables(**kwargs):
    """
    Temporarily set environment variables.
    
    Production use cases:
    - Testing with different configs
    - Subprocess execution with custom env
    - Feature flag testing
    
    Example:
        with environment_variables(DEBUG="true", API_KEY="test-key"):
            # Environment variables set
            run_application()
        # Original environment restored
    """
    original_env = {}
    
    # Save original values and set new ones
    for key, value in kwargs.items():
        original_env[key] = os.environ.get(key)
        os.environ[key] = str(value)
        logger.debug(f"Set {key}={value}")
    
    try:
        yield
    finally:
        # Restore original environment
        for key, original_value in original_env.items():
            if original_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original_value
        logger.debug("Restored original environment")


# ============================================================================
# TIMER CONTEXT - Measure execution time
# ============================================================================

@contextmanager
def timer(name: str = "Operation", log_level: int = logging.INFO):
    """
    Context manager to measure execution time.
    
    Production use cases:
    - Performance monitoring
    - Identify slow operations
    - SLA monitoring
    
    Example:
        with timer("Database query"):
            results = db.execute(complex_query)
        # Logs: "Database query completed in 1.234s"
    """
    import time
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        logger.log(log_level, f"{name} completed in {elapsed:.4f}s")


# ============================================================================
# SUPPRESS EXCEPTIONS - Silent error handling
# ============================================================================

@contextmanager
def suppress_exceptions(*exceptions, log_errors: bool = True):
    """
    Context manager to suppress specific exceptions.
    
    Production use cases:
    - Optional cleanup operations
    - Graceful degradation
    - Ignore expected errors
    
    Example:
        with suppress_exceptions(FileNotFoundError, log_errors=True):
            os.remove("optional_file.txt")
        # Continues even if file doesn't exist
    """
    try:
        yield
    except exceptions as e:
        if log_errors:
            logger.warning(f"Suppressed exception: {type(e).__name__}: {e}")


# ============================================================================
# CONNECTION POOL CONTEXT
# ============================================================================

class ConnectionPool:
    """
    Simple connection pool context manager.
    
    Production use cases:
    - Database connection pooling
    - HTTP client session pooling
    - Redis connection pooling
    
    Example:
        pool = ConnectionPool(
            create_func=lambda: psycopg2.connect('postgresql://...'),
            max_size=10
        )
        
        with pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT 1')
    """
    
    def __init__(self, create_func: callable, max_size: int = 10):
        self.create_func = create_func
        self.max_size = max_size
        self.pool: list = []
        self.in_use: set = set()
    
    @contextmanager
    def get_connection(self):
        """Get connection from pool."""
        conn = self._acquire()
        try:
            yield conn
        finally:
            self._release(conn)
    
    def _acquire(self):
        """Acquire connection from pool."""
        if self.pool:
            conn = self.pool.pop()
            logger.debug("Reused connection from pool")
        else:
            conn = self.create_func()
            logger.debug("Created new connection")
        
        self.in_use.add(id(conn))
        return conn
    
    def _release(self, conn):
        """Release connection back to pool."""
        self.in_use.remove(id(conn))
        
        if len(self.pool) < self.max_size:
            self.pool.append(conn)
            logger.debug("Returned connection to pool")
        else:
            # Pool full, close connection
            if hasattr(conn, 'close'):
                conn.close()
            logger.debug("Closed connection (pool full)")
    
    def close_all(self):
        """Close all connections in pool."""
        for conn in self.pool:
            if hasattr(conn, 'close'):
                conn.close()
        self.pool.clear()
        logger.info(f"Closed all connections in pool")


# ============================================================================
# TRANSACTION CONTEXT - Generic transaction boundary
# ============================================================================

@contextmanager
def transaction(
    begin_func: callable,
    commit_func: callable,
    rollback_func: callable,
):
    """
    Generic transaction context manager.
    
    Production use cases:
    - Custom transaction protocols
    - Multi-phase commits
    - Distributed transactions
    
    Example:
        with transaction(
            begin_func=lambda: db.begin(),
            commit_func=lambda: db.commit(),
            rollback_func=lambda: db.rollback()
        ):
            db.execute("INSERT ...")
            db.execute("UPDATE ...")
        # Auto-commits on success, rolls back on exception
    """
    begin_func()
    logger.debug("Transaction started")
    
    try:
        yield
        commit_func()
        logger.debug("Transaction committed")
    except Exception as e:
        logger.error(f"Transaction failed: {e}")
        rollback_func()
        logger.debug("Transaction rolled back")
        raise
