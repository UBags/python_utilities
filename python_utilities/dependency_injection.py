"""
Dependency Injection Module

Production-ready dependency injection patterns:
- DI Container for service registration and resolution
- Automatic dependency resolution
- Lifecycle management (singleton, transient, scoped)
- FastAPI-style dependency injection
"""

import functools
import inspect
import logging
from typing import (
    Type, TypeVar, Callable, Dict, Any, Optional,
    get_type_hints, Protocol
)
from enum import Enum

logger = logging.getLogger(__name__)

T = TypeVar('T')


# ============================================================================
# LIFECYCLE ENUMS
# ============================================================================

class Lifecycle(Enum):
    """Service lifecycle types."""
    SINGLETON = "singleton"  # One instance for entire application
    TRANSIENT = "transient"  # New instance every time
    SCOPED = "scoped"        # One instance per scope (e.g., per request)


# ============================================================================
# DEPENDENCY INJECTION CONTAINER
# ============================================================================

class DIContainer:
    """
    Dependency injection container with automatic resolution.
    
    Production use cases:
    - Service registration and resolution
    - Automatic dependency injection
    - Testability (swap implementations)
    - Lifecycle management
    
    Example:
        # Define interfaces and implementations
        class IDatabase(Protocol):
            def query(self, sql: str): ...
        
        class PostgresDB:
            def __init__(self, connection_string: str):
                self.conn_str = connection_string
            def query(self, sql: str):
                return f"Executing: {sql}"
        
        class UserService:
            def __init__(self, database: IDatabase):
                self.db = database
            def get_user(self, user_id: int):
                return self.db.query(f"SELECT * FROM users WHERE id={user_id}")
        
        # Register services
        container = DIContainer()
        container.register(
            IDatabase,
            lambda: PostgresDB("postgresql://localhost/mydb"),
            lifecycle=Lifecycle.SINGLETON
        )
        container.register(UserService, UserService)
        
        # Resolve with automatic dependency injection
        user_service = container.resolve(UserService)
        user_service.get_user(123)
    """
    
    def __init__(self):
        self._services: Dict[Type, tuple] = {}
        self._singletons: Dict[Type, Any] = {}
        self._scoped_instances: Dict[str, Dict[Type, Any]] = {}
        self._current_scope: Optional[str] = None
    
    def register(
        self,
        interface: Type[T],
        implementation: Callable[..., T],
        lifecycle: Lifecycle = Lifecycle.TRANSIENT,
    ):
        """
        Register a service.
        
        Args:
            interface: The interface/type to register
            implementation: Factory function or class
            lifecycle: Service lifecycle (SINGLETON, TRANSIENT, SCOPED)
        """
        self._services[interface] = (implementation, lifecycle)
        logger.debug(
            f"Registered {interface.__name__} -> "
            f"{implementation.__name__ if hasattr(implementation, '__name__') else 'factory'} "
            f"[{lifecycle.value}]"
        )
    
    def register_singleton(self, interface: Type[T], implementation: Callable[..., T]):
        """Register a singleton service."""
        self.register(interface, implementation, Lifecycle.SINGLETON)
    
    def register_transient(self, interface: Type[T], implementation: Callable[..., T]):
        """Register a transient service."""
        self.register(interface, implementation, Lifecycle.TRANSIENT)
    
    def register_scoped(self, interface: Type[T], implementation: Callable[..., T]):
        """Register a scoped service."""
        self.register(interface, implementation, Lifecycle.SCOPED)
    
    def resolve(self, interface: Type[T]) -> T:
        """
        Resolve a service with automatic dependency injection.
        
        Args:
            interface: The interface/type to resolve
        
        Returns:
            Instance of the requested type
        """
        if interface not in self._services:
            raise ValueError(
                f"Service {interface.__name__} not registered. "
                f"Available services: {list(self._services.keys())}"
            )
        
        implementation, lifecycle = self._services[interface]
        
        # Handle lifecycle
        if lifecycle == Lifecycle.SINGLETON:
            if interface in self._singletons:
                logger.debug(f"Returning singleton instance of {interface.__name__}")
                return self._singletons[interface]
            
            instance = self._create_instance(implementation)
            self._singletons[interface] = instance
            return instance
        
        elif lifecycle == Lifecycle.SCOPED:
            if self._current_scope is None:
                raise RuntimeError(
                    "Cannot resolve scoped service outside of a scope. "
                    "Use container.scope() context manager."
                )
            
            if self._current_scope not in self._scoped_instances:
                self._scoped_instances[self._current_scope] = {}
            
            scope_cache = self._scoped_instances[self._current_scope]
            
            if interface in scope_cache:
                logger.debug(f"Returning scoped instance of {interface.__name__}")
                return scope_cache[interface]
            
            instance = self._create_instance(implementation)
            scope_cache[interface] = instance
            return instance
        
        else:  # TRANSIENT
            logger.debug(f"Creating transient instance of {interface.__name__}")
            return self._create_instance(implementation)
    
    def _create_instance(self, implementation: Callable) -> Any:
        """Create instance with automatic dependency resolution."""
        # Get type hints for constructor
        try:
            type_hints = get_type_hints(implementation.__init__)
        except AttributeError:
            # Factory function
            type_hints = get_type_hints(implementation)
        
        # Remove 'return' hint
        type_hints.pop('return', None)
        
        # Resolve dependencies
        kwargs = {}
        for param_name, param_type in type_hints.items():
            if param_name == 'self':
                continue
            
            # Recursively resolve dependency
            kwargs[param_name] = self.resolve(param_type)
        
        # Create instance
        return implementation(**kwargs)
    
    def scope(self, scope_id: Optional[str] = None):
        """
        Create a scope for scoped services.
        
        Example:
            with container.scope("request-123"):
                service = container.resolve(ScopedService)
                # Same instance within this scope
        """
        return self._ScopeContext(self, scope_id)
    
    class _ScopeContext:
        def __init__(self, container: 'DIContainer', scope_id: Optional[str]):
            self.container = container
            self.scope_id = scope_id or str(id(self))
        
        def __enter__(self):
            self.container._current_scope = self.scope_id
            logger.debug(f"Entering scope: {self.scope_id}")
            return self
        
        def __exit__(self, exc_type, exc_val, exc_tb):
            # Clean up scoped instances
            if self.scope_id in self.container._scoped_instances:
                del self.container._scoped_instances[self.scope_id]
            
            self.container._current_scope = None
            logger.debug(f"Exiting scope: {self.scope_id}")
            return False
    
    def clear_singletons(self):
        """Clear all singleton instances."""
        self._singletons.clear()
        logger.info("Cleared all singleton instances")


# ============================================================================
# INJECT DECORATOR
# ============================================================================

def inject(container: DIContainer):
    """
    Decorator for automatic dependency injection.
    
    Production use cases:
    - Clean separation of concerns
    - Testability
    - Reduced boilerplate
    
    Example:
        container = DIContainer()
        container.register(IDatabase, PostgresDB)
        
        @inject(container)
        def process_user(user_id: int, database: IDatabase):
            return database.query(f"SELECT * FROM users WHERE id={user_id}")
        
        # database parameter automatically injected
        result = process_user(123)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Get function signature
            sig = inspect.signature(func)
            type_hints = get_type_hints(func)
            
            # Inject dependencies
            for param_name, param in sig.parameters.items():
                if param_name in kwargs:
                    continue  # Already provided
                
                if param_name in type_hints:
                    param_type = type_hints[param_name]
                    try:
                        kwargs[param_name] = container.resolve(param_type)
                    except ValueError:
                        # Not a registered service, skip
                        pass
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


# ============================================================================
# FACTORY PATTERN
# ============================================================================

class Factory:
    """
    Generic factory for creating instances.
    
    Production use cases:
    - Object creation with complex logic
    - Strategy pattern implementation
    - Plugin systems
    
    Example:
        class EmailSender:
            pass
        
        class SmtpEmailSender(EmailSender):
            pass
        
        class SendGridEmailSender(EmailSender):
            pass
        
        factory = Factory()
        factory.register('smtp', SmtpEmailSender)
        factory.register('sendgrid', SendGridEmailSender)
        
        sender = factory.create('smtp')
    """
    
    def __init__(self):
        self._creators: Dict[str, Callable] = {}
    
    def register(self, key: str, creator: Callable):
        """Register a creator function."""
        self._creators[key] = creator
        logger.debug(f"Registered factory: {key}")
    
    def create(self, key: str, *args, **kwargs) -> Any:
        """Create instance using registered creator."""
        if key not in self._creators:
            raise ValueError(
                f"Unknown factory key: {key}. "
                f"Available: {list(self._creators.keys())}"
            )
        
        creator = self._creators[key]
        return creator(*args, **kwargs)
    
    def get_available_keys(self) -> list:
        """Get list of registered keys."""
        return list(self._creators.keys())


# ============================================================================
# SERVICE LOCATOR PATTERN (Anti-pattern, but sometimes needed)
# ============================================================================

class ServiceLocator:
    """
    Service locator pattern (use sparingly).
    
    Note: This is generally considered an anti-pattern.
    Prefer constructor injection via DIContainer.
    
    Production use cases:
    - Legacy code integration
    - Framework constraints
    - Global service access (logging, config)
    
    Example:
        ServiceLocator.register('logger', logging.getLogger())
        ServiceLocator.register('config', load_config())
        
        # Anywhere in code
        logger = ServiceLocator.get('logger')
        config = ServiceLocator.get('config')
    """
    
    _services: Dict[str, Any] = {}
    
    @classmethod
    def register(cls, name: str, service: Any):
        """Register a service."""
        cls._services[name] = service
        logger.debug(f"Registered service in locator: {name}")
    
    @classmethod
    def get(cls, name: str) -> Any:
        """Get a service."""
        if name not in cls._services:
            raise ValueError(
                f"Service '{name}' not found. "
                f"Available: {list(cls._services.keys())}"
            )
        return cls._services[name]
    
    @classmethod
    def has(cls, name: str) -> bool:
        """Check if service exists."""
        return name in cls._services
    
    @classmethod
    def clear(cls):
        """Clear all services."""
        cls._services.clear()


# ============================================================================
# LAZY INITIALIZATION
# ============================================================================

class Lazy:
    """
    Lazy initialization wrapper.
    
    Production use cases:
    - Expensive resource initialization
    - Circular dependency resolution
    - On-demand loading
    
    Example:
        class ExpensiveResource:
            def __init__(self):
                print("Expensive initialization")
                time.sleep(1)
        
        lazy_resource = Lazy(ExpensiveResource)
        # Not initialized yet
        
        resource = lazy_resource.value  # Now initialized
        resource2 = lazy_resource.value  # Same instance
    """
    
    def __init__(self, factory: Callable[[], T]):
        self._factory = factory
        self._value: Optional[T] = None
        self._initialized = False
    
    @property
    def value(self) -> T:
        """Get the lazy value, initializing if needed."""
        if not self._initialized:
            logger.debug(f"Lazy initializing {self._factory}")
            self._value = self._factory()
            self._initialized = True
        return self._value
    
    @property
    def is_initialized(self) -> bool:
        """Check if value has been initialized."""
        return self._initialized
    
    def reset(self):
        """Reset the lazy value."""
        self._value = None
        self._initialized = False


# ============================================================================
# PROVIDER PATTERN
# ============================================================================

class Provider:
    """
    Provider pattern for deferred resolution.
    
    Production use cases:
    - Breaking circular dependencies
    - Optional dependencies
    - Runtime service selection
    
    Example:
        class ServiceA:
            def __init__(self, service_b_provider: Provider):
                self.service_b = service_b_provider
            
            def do_work(self):
                b = self.service_b.get()
                return b.process()
        
        provider = Provider(lambda: container.resolve(ServiceB))
        service_a = ServiceA(provider)
    """
    
    def __init__(self, factory: Callable[[], T]):
        self._factory = factory
    
    def get(self) -> T:
        """Get instance from provider."""
        return self._factory()
