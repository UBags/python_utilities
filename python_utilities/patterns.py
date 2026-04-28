"""
Design Patterns Module

Production-ready design patterns:
- Repository Pattern (Data Access Layer)
- Unit of Work Pattern (Transaction Management)
- Event Bus Pattern (Event-Driven Architecture)
- Service Layer Pattern
"""

import logging
from typing import (
    TypeVar, Generic, List, Optional, Dict, Any,
    Callable, Protocol, Set
)
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from contextlib import contextmanager

logger = logging.getLogger(__name__)

T = TypeVar('T')
ID = TypeVar('ID')


# ============================================================================
# REPOSITORY PATTERN
# ============================================================================

class Repository(ABC, Generic[T, ID]):
    """
    Abstract repository pattern for data access.
    
    Production use cases:
    - Clean architecture / hexagonal architecture
    - Database abstraction
    - Testability (swap implementations)
    - Domain-Driven Design
    
    Example:
        class User:
            def __init__(self, id: int, name: str, email: str):
                self.id = id
                self.name = name
                self.email = email
        
        class UserRepository(Repository[User, int]):
            def __init__(self, db):
                self.db = db
            
            def get(self, id: int) -> Optional[User]:
                row = self.db.query(f"SELECT * FROM users WHERE id={id}")
                return User(**row) if row else None
            
            def list(self, skip: int = 0, limit: int = 100) -> List[User]:
                rows = self.db.query(f"SELECT * FROM users LIMIT {limit} OFFSET {skip}")
                return [User(**row) for row in rows]
            
            def create(self, entity: User) -> User:
                self.db.execute(f"INSERT INTO users ...")
                return entity
            
            def update(self, id: int, entity: User) -> Optional[User]:
                self.db.execute(f"UPDATE users SET ...")
                return entity
            
            def delete(self, id: int) -> bool:
                self.db.execute(f"DELETE FROM users WHERE id={id}")
                return True
    """
    
    @abstractmethod
    def get(self, id: ID) -> Optional[T]:
        """Get entity by ID."""
        pass
    
    @abstractmethod
    def list(self, skip: int = 0, limit: int = 100) -> List[T]:
        """List entities with pagination."""
        pass
    
    @abstractmethod
    def create(self, entity: T) -> T:
        """Create new entity."""
        pass
    
    @abstractmethod
    def update(self, id: ID, entity: T) -> Optional[T]:
        """Update existing entity."""
        pass
    
    @abstractmethod
    def delete(self, id: ID) -> bool:
        """Delete entity."""
        pass


class InMemoryRepository(Repository[T, ID]):
    """
    In-memory repository implementation for testing.
    
    Production use cases:
    - Unit testing without database
    - Rapid prototyping
    - Development environments
    
    Example:
        users_repo = InMemoryRepository()
        users_repo.create(User(1, "Alice", "alice@example.com"))
        user = users_repo.get(1)
    """
    
    def __init__(self):
        self._storage: Dict[ID, T] = {}
        self._next_id = 1
    
    def get(self, id: ID) -> Optional[T]:
        """Get entity by ID."""
        return self._storage.get(id)
    
    def list(self, skip: int = 0, limit: int = 100) -> List[T]:
        """List entities with pagination."""
        items = list(self._storage.values())
        return items[skip:skip + limit]
    
    def create(self, entity: T) -> T:
        """Create new entity."""
        # Auto-assign ID if entity has id attribute
        if hasattr(entity, 'id') and entity.id is None:
            entity.id = self._next_id
            self._next_id += 1
        
        entity_id = getattr(entity, 'id', len(self._storage) + 1)
        self._storage[entity_id] = entity
        logger.debug(f"Created entity with ID {entity_id}")
        return entity
    
    def update(self, id: ID, entity: T) -> Optional[T]:
        """Update existing entity."""
        if id not in self._storage:
            return None
        
        self._storage[id] = entity
        logger.debug(f"Updated entity with ID {id}")
        return entity
    
    def delete(self, id: ID) -> bool:
        """Delete entity."""
        if id in self._storage:
            del self._storage[id]
            logger.debug(f"Deleted entity with ID {id}")
            return True
        return False
    
    def clear(self):
        """Clear all entities (useful for testing)."""
        self._storage.clear()
        self._next_id = 1


# ============================================================================
# UNIT OF WORK PATTERN
# ============================================================================

class UnitOfWork:
    """
    Unit of Work pattern for transaction management.
    
    Production use cases:
    - Atomic operations across multiple repositories
    - Transaction boundaries
    - Consistency across multiple tables
    - Domain-Driven Design
    
    Example:
        class AppUnitOfWork(UnitOfWork):
            def __init__(self, session):
                super().__init__()
                self.session = session
                self.users = UserRepository(session)
                self.products = ProductRepository(session)
            
            def _commit(self):
                self.session.commit()
            
            def _rollback(self):
                self.session.rollback()
        
        with AppUnitOfWork(db_session) as uow:
            user = uow.users.get(1)
            product = uow.products.get(100)
            
            user.purchase(product)
            
            uow.users.update(user.id, user)
            uow.products.update(product.id, product)
            # Automatically commits or rolls back
    """
    
    def __init__(self):
        self._new_entities: List[Any] = []
        self._dirty_entities: List[Any] = []
        self._removed_entities: List[Any] = []
        self._committed = False
    
    def register_new(self, entity: Any):
        """Register new entity to be inserted."""
        self._new_entities.append(entity)
        logger.debug(f"Registered new entity: {entity}")
    
    def register_dirty(self, entity: Any):
        """Register modified entity to be updated."""
        if entity not in self._dirty_entities:
            self._dirty_entities.append(entity)
            logger.debug(f"Registered dirty entity: {entity}")
    
    def register_removed(self, entity: Any):
        """Register entity to be deleted."""
        self._removed_entities.append(entity)
        logger.debug(f"Registered removed entity: {entity}")
    
    def commit(self):
        """Commit all changes."""
        if self._committed:
            raise RuntimeError("Unit of work already committed")
        
        try:
            # Process in order: new, dirty, removed
            for entity in self._new_entities:
                self._persist_new(entity)
            
            for entity in self._dirty_entities:
                self._persist_dirty(entity)
            
            for entity in self._removed_entities:
                self._persist_removed(entity)
            
            # Subclass implements actual commit
            self._commit()
            
            self._committed = True
            logger.info("Unit of work committed successfully")
        
        except Exception as e:
            logger.error(f"Unit of work commit failed: {e}")
            self.rollback()
            raise
    
    def rollback(self):
        """Rollback all changes."""
        self._rollback()
        self._clear()
        logger.info("Unit of work rolled back")
    
    def _clear(self):
        """Clear all tracked entities."""
        self._new_entities.clear()
        self._dirty_entities.clear()
        self._removed_entities.clear()
    
    def _persist_new(self, entity: Any):
        """Persist new entity (override in subclass)."""
        pass
    
    def _persist_dirty(self, entity: Any):
        """Persist dirty entity (override in subclass)."""
        pass
    
    def _persist_removed(self, entity: Any):
        """Persist removed entity (override in subclass)."""
        pass
    
    def _commit(self):
        """Execute commit (override in subclass)."""
        pass
    
    def _rollback(self):
        """Execute rollback (override in subclass)."""
        pass
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with auto-commit/rollback."""
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False


# ============================================================================
# EVENT BUS PATTERN
# ============================================================================

@dataclass
class Event:
    """Base event class."""
    event_type: str
    timestamp: datetime = field(default_factory=datetime.now)
    data: Dict[str, Any] = field(default_factory=dict)


class EventBus:
    """
    Event bus for event-driven architecture.
    
    Production use cases:
    - Decoupling services
    - Domain events
    - Audit logging
    - Side effects (email, notifications)
    - Saga pattern
    
    Example:
        event_bus = EventBus()
        
        # Subscribe handlers
        @event_bus.subscribe('user_registered')
        async def send_welcome_email(event: Event):
            await email_service.send(event.data['email'], "Welcome!")
        
        @event_bus.subscribe('user_registered')
        async def track_analytics(event: Event):
            await analytics.track('registration', event.data)
        
        # Publish event
        await event_bus.publish(Event(
            event_type='user_registered',
            data={'user_id': 123, 'email': 'user@example.com'}
        ))
    """
    
    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = {}
        self._middleware: List[Callable] = []
    
    def subscribe(self, event_type: str, handler: Optional[Callable] = None):
        """
        Subscribe to event type.
        
        Can be used as decorator:
            @event_bus.subscribe('user_registered')
            def handle_user_registered(event):
                pass
        
        Or directly:
            event_bus.subscribe('user_registered', handler_func)
        """
        def decorator(fn: Callable) -> Callable:
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            
            self._handlers[event_type].append(fn)
            logger.debug(f"Subscribed {fn.__name__} to {event_type}")
            return fn
        
        if handler is None:
            return decorator
        else:
            return decorator(handler)
    
    def unsubscribe(self, event_type: str, handler: Callable):
        """Unsubscribe handler from event type."""
        if event_type in self._handlers:
            self._handlers[event_type].remove(handler)
            logger.debug(f"Unsubscribed {handler.__name__} from {event_type}")
    
    async def publish(self, event: Event):
        """
        Publish event to all subscribers.
        
        Async version that awaits async handlers.
        """
        import asyncio
        
        logger.info(f"Publishing event: {event.event_type}")
        
        # Apply middleware
        for middleware in self._middleware:
            event = await middleware(event) if asyncio.iscoroutinefunction(middleware) else middleware(event)
        
        # Get handlers for this event type
        handlers = self._handlers.get(event.event_type, [])
        
        if not handlers:
            logger.warning(f"No handlers for event type: {event.event_type}")
            return
        
        # Execute handlers
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
                logger.debug(f"Handler {handler.__name__} executed for {event.event_type}")
            except Exception as e:
                logger.error(f"Handler {handler.__name__} failed: {e}")
    
    def publish_sync(self, event: Event):
        """
        Publish event synchronously (for non-async code).
        """
        logger.info(f"Publishing event (sync): {event.event_type}")
        
        # Apply middleware
        for middleware in self._middleware:
            event = middleware(event)
        
        handlers = self._handlers.get(event.event_type, [])
        
        for handler in handlers:
            try:
                handler(event)
                logger.debug(f"Handler {handler.__name__} executed for {event.event_type}")
            except Exception as e:
                logger.error(f"Handler {handler.__name__} failed: {e}")
    
    def add_middleware(self, middleware: Callable):
        """
        Add middleware to process all events.
        
        Middleware receives event and returns modified event.
        """
        self._middleware.append(middleware)
        logger.debug(f"Added middleware: {middleware.__name__}")
    
    def get_handler_count(self, event_type: str) -> int:
        """Get number of handlers for event type."""
        return len(self._handlers.get(event_type, []))


# ============================================================================
# SERVICE LAYER PATTERN
# ============================================================================

class Service(ABC):
    """
    Abstract service layer.
    
    Production use cases:
    - Business logic layer
    - Orchestration of repositories
    - Transaction boundaries
    - Use case implementation
    
    Example:
        class UserService(Service):
            def __init__(
                self,
                user_repo: UserRepository,
                email_service: EmailService,
                event_bus: EventBus,
            ):
                self.user_repo = user_repo
                self.email_service = email_service
                self.event_bus = event_bus
            
            async def register_user(self, name: str, email: str) -> User:
                # Business logic
                if await self.user_repo.email_exists(email):
                    raise ValueError("Email already registered")
                
                # Create user
                user = User(name=name, email=email)
                user = self.user_repo.create(user)
                
                # Side effects
                await self.email_service.send_welcome(email)
                await self.event_bus.publish(Event(
                    event_type='user_registered',
                    data={'user_id': user.id, 'email': email}
                ))
                
                return user
    """
    pass


# ============================================================================
# SPECIFICATION PATTERN
# ============================================================================

class Specification(ABC, Generic[T]):
    """
    Specification pattern for business rules.
    
    Production use cases:
    - Complex query building
    - Business rule validation
    - Reusable filters
    
    Example:
        class AdultUserSpec(Specification):
            def is_satisfied_by(self, user: User) -> bool:
                return user.age >= 18
        
        class ActiveUserSpec(Specification):
            def is_satisfied_by(self, user: User) -> bool:
                return user.is_active
        
        adult_and_active = AdultUserSpec() & ActiveUserSpec()
        users = [u for u in all_users if adult_and_active.is_satisfied_by(u)]
    """
    
    @abstractmethod
    def is_satisfied_by(self, entity: T) -> bool:
        """Check if entity satisfies specification."""
        pass
    
    def __and__(self, other: 'Specification[T]') -> 'Specification[T]':
        """Combine specifications with AND."""
        return AndSpecification(self, other)
    
    def __or__(self, other: 'Specification[T]') -> 'Specification[T]':
        """Combine specifications with OR."""
        return OrSpecification(self, other)
    
    def __invert__(self) -> 'Specification[T]':
        """Negate specification."""
        return NotSpecification(self)


class AndSpecification(Specification[T]):
    """AND combination of specifications."""
    
    def __init__(self, spec1: Specification[T], spec2: Specification[T]):
        self.spec1 = spec1
        self.spec2 = spec2
    
    def is_satisfied_by(self, entity: T) -> bool:
        return self.spec1.is_satisfied_by(entity) and self.spec2.is_satisfied_by(entity)


class OrSpecification(Specification[T]):
    """OR combination of specifications."""
    
    def __init__(self, spec1: Specification[T], spec2: Specification[T]):
        self.spec1 = spec1
        self.spec2 = spec2
    
    def is_satisfied_by(self, entity: T) -> bool:
        return self.spec1.is_satisfied_by(entity) or self.spec2.is_satisfied_by(entity)


class NotSpecification(Specification[T]):
    """NOT negation of specification."""
    
    def __init__(self, spec: Specification[T]):
        self.spec = spec
    
    def is_satisfied_by(self, entity: T) -> bool:
        return not self.spec.is_satisfied_by(entity)


# ============================================================================
# OBSERVER PATTERN (Alternative to Event Bus)
# ============================================================================

class Observer(ABC):
    """Observer interface."""
    
    @abstractmethod
    def update(self, subject: 'Subject', event: Any):
        """Called when subject changes."""
        pass


class Subject:
    """
    Subject in observer pattern.
    
    Production use cases:
    - Real-time updates
    - Model-View synchronization
    - Change notifications
    
    Example:
        class PriceObserver(Observer):
            def update(self, subject, event):
                print(f"Price changed to {event['new_price']}")
        
        product = Product()
        observer = PriceObserver()
        product.attach(observer)
        
        product.set_price(99.99)  # Observer notified
    """
    
    def __init__(self):
        self._observers: Set[Observer] = set()
    
    def attach(self, observer: Observer):
        """Attach an observer."""
        self._observers.add(observer)
        logger.debug(f"Attached observer: {observer}")
    
    def detach(self, observer: Observer):
        """Detach an observer."""
        self._observers.discard(observer)
        logger.debug(f"Detached observer: {observer}")
    
    def notify(self, event: Any):
        """Notify all observers."""
        for observer in self._observers:
            try:
                observer.update(self, event)
            except Exception as e:
                logger.error(f"Observer {observer} failed: {e}")
