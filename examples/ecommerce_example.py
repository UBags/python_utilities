"""
Comprehensive Example: E-Commerce Platform

This example demonstrates how to use python_utilities to build a production-ready
e-commerce platform with proper separation of concerns, dependency injection,
event-driven architecture, and all best practices.
"""

import asyncio
import logging
from typing import Optional, List
from dataclasses import dataclass
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import utilities
from python_utilities.decorators import (
    retry, rate_limit, timer, cached, circuit_breaker
)
from python_utilities.async_utils import AsyncQueue, RateLimitedFetcher
from python_utilities.context_managers import database_session, timer as timer_ctx
from python_utilities.performance import benchmark, PerformanceMonitor
from python_utilities.validation import validate_with_pydantic
from python_utilities.dependency_injection import DIContainer, Lifecycle
from python_utilities.patterns import (
    Repository, InMemoryRepository, UnitOfWork, EventBus, Event
)

# ============================================================================
# DOMAIN MODELS
# ============================================================================

@dataclass
class User:
    """User domain model."""
    id: Optional[int] = None
    name: str = ""
    email: str = ""
    balance: float = 0.0
    created_at: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


@dataclass
class Product:
    """Product domain model."""
    id: Optional[int] = None
    name: str = ""
    price: float = 0.0
    stock: int = 0


@dataclass
class Order:
    """Order domain model."""
    id: Optional[int] = None
    user_id: int = 0
    product_id: int = 0
    quantity: int = 0
    total: float = 0.0
    status: str = "pending"
    created_at: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


# ============================================================================
# REPOSITORIES
# ============================================================================

class UserRepository(InMemoryRepository[User, int]):
    """User repository with additional methods."""
    
    def find_by_email(self, email: str) -> Optional[User]:
        """Find user by email."""
        for user in self._storage.values():
            if user.email == email:
                return user
        return None


class ProductRepository(InMemoryRepository[Product, int]):
    """Product repository with stock management."""
    
    def reserve_stock(self, product_id: int, quantity: int) -> bool:
        """Reserve stock for a product."""
        product = self.get(product_id)
        if product and product.stock >= quantity:
            product.stock -= quantity
            self.update(product_id, product)
            return True
        return False


class OrderRepository(InMemoryRepository[Order, int]):
    """Order repository."""
    pass


# ============================================================================
# UNIT OF WORK
# ============================================================================

class ECommerceUnitOfWork(UnitOfWork):
    """Unit of work for e-commerce operations."""
    
    def __init__(self):
        super().__init__()
        self.users = UserRepository()
        self.products = ProductRepository()
        self.orders = OrderRepository()
    
    def _commit(self):
        """Commit changes (in real app, this would commit DB transaction)."""
        logger.info("Transaction committed")
    
    def _rollback(self):
        """Rollback changes."""
        logger.warning("Transaction rolled back")


# ============================================================================
# SERVICES
# ============================================================================

class PaymentGateway:
    """External payment gateway (simulated)."""
    
    @circuit_breaker(failure_threshold=3, recovery_timeout=30.0)
    @retry(max_attempts=3, delay=1.0)
    def charge(self, amount: float, user_id: int) -> str:
        """Charge user (simulated)."""
        logger.info(f"Charging ${amount:.2f} to user {user_id}")
        return f"txn_{user_id}_{datetime.now().timestamp()}"


class EmailService:
    """Email service for notifications."""
    
    @rate_limit(max_calls=10, period=timedelta(seconds=60))
    async def send(self, to: str, subject: str, body: str):
        """Send email (simulated)."""
        logger.info(f"Sending email to {to}: {subject}")
        await asyncio.sleep(0.1)  # Simulate network delay


class OrderService:
    """Order service with business logic."""
    
    def __init__(
        self,
        uow: ECommerceUnitOfWork,
        payment_gateway: PaymentGateway,
        event_bus: EventBus,
    ):
        self.uow = uow
        self.payment_gateway = payment_gateway
        self.event_bus = event_bus
    
    @timer(metric_name="create_order_duration")
    async def create_order(
        self,
        user_id: int,
        product_id: int,
        quantity: int
    ) -> Order:
        """
        Create order with full transaction.
        
        This demonstrates:
        - Unit of Work for transaction management
        - Multiple repository operations
        - External service calls
        - Event publishing
        """
        with self.uow as uow:
            # Get user and product
            user = uow.users.get(user_id)
            if not user:
                raise ValueError(f"User {user_id} not found")
            
            product = uow.products.get(product_id)
            if not product:
                raise ValueError(f"Product {product_id} not found")
            
            # Check stock
            if product.stock < quantity:
                raise ValueError(f"Insufficient stock for product {product_id}")
            
            # Calculate total
            total = product.price * quantity
            
            # Check user balance
            if user.balance < total:
                raise ValueError(f"Insufficient balance for user {user_id}")
            
            # Reserve stock
            product.stock -= quantity
            uow.products.update(product_id, product)
            
            # Charge user
            user.balance -= total
            uow.users.update(user_id, user)
            
            # Create order
            order = Order(
                user_id=user_id,
                product_id=product_id,
                quantity=quantity,
                total=total,
                status="completed"
            )
            order = uow.orders.create(order)
            
            # Process payment
            try:
                transaction_id = self.payment_gateway.charge(total, user_id)
                logger.info(f"Payment successful: {transaction_id}")
            except Exception as e:
                logger.error(f"Payment failed: {e}")
                raise
            
            # Transaction committed automatically on successful exit
        
        # Publish event (after transaction commits)
        await self.event_bus.publish(Event(
            event_type='order_created',
            data={
                'order_id': order.id,
                'user_id': user_id,
                'product_id': product_id,
                'total': total
            }
        ))
        
        return order


class InventoryService:
    """Inventory management service."""
    
    def __init__(self, uow: ECommerceUnitOfWork):
        self.uow = uow
    
    @cached(ttl_seconds=60)
    def get_low_stock_products(self, threshold: int = 10) -> List[Product]:
        """Get products with low stock (cached for 60 seconds)."""
        products = self.uow.products.list()
        return [p for p in products if p.stock < threshold]


# ============================================================================
# EVENT HANDLERS
# ============================================================================

async def setup_event_handlers(event_bus: EventBus, email_service: EmailService):
    """Setup event handlers for the application."""
    
    @event_bus.subscribe('order_created')
    async def send_order_confirmation(event: Event):
        """Send order confirmation email."""
        logger.info(f"Sending order confirmation for order {event.data['order_id']}")
        await email_service.send(
            to="user@example.com",
            subject="Order Confirmation",
            body=f"Your order {event.data['order_id']} has been confirmed!"
        )
    
    @event_bus.subscribe('order_created')
    async def update_analytics(event: Event):
        """Update analytics."""
        logger.info(f"Recording analytics for order {event.data['order_id']}")
    
    @event_bus.subscribe('order_created')
    async def trigger_fulfillment(event: Event):
        """Trigger order fulfillment."""
        logger.info(f"Starting fulfillment for order {event.data['order_id']}")


# ============================================================================
# DEPENDENCY INJECTION SETUP
# ============================================================================

def setup_container() -> DIContainer:
    """Setup dependency injection container."""
    container = DIContainer()
    
    # Register repositories (singletons)
    container.register_singleton(
        ECommerceUnitOfWork,
        lambda: ECommerceUnitOfWork()
    )
    
    # Register services
    container.register_singleton(
        PaymentGateway,
        lambda: PaymentGateway()
    )
    
    container.register_singleton(
        EmailService,
        lambda: EmailService()
    )
    
    container.register_singleton(
        EventBus,
        lambda: EventBus()
    )
    
    # Register business services
    container.register(
        OrderService,
        lambda: OrderService(
            uow=container.resolve(ECommerceUnitOfWork),
            payment_gateway=container.resolve(PaymentGateway),
            event_bus=container.resolve(EventBus)
        )
    )
    
    container.register(
        InventoryService,
        lambda: InventoryService(
            uow=container.resolve(ECommerceUnitOfWork)
        )
    )
    
    return container


# ============================================================================
# MAIN APPLICATION
# ============================================================================

async def seed_data(uow: ECommerceUnitOfWork):
    """Seed initial data."""
    # Create users
    user1 = User(id=1, name="Alice", email="alice@example.com", balance=1000.0)
    user2 = User(id=2, name="Bob", email="bob@example.com", balance=500.0)
    uow.users.create(user1)
    uow.users.create(user2)
    
    # Create products
    product1 = Product(id=1, name="Laptop", price=999.99, stock=10)
    product2 = Product(id=2, name="Mouse", price=29.99, stock=100)
    product3 = Product(id=3, name="Keyboard", price=79.99, stock=50)
    uow.products.create(product1)
    uow.products.create(product2)
    uow.products.create(product3)
    
    logger.info("Data seeded successfully")


async def main():
    """Main application entry point."""
    logger.info("=" * 70)
    logger.info("E-Commerce Platform Demo")
    logger.info("Demonstrating python_utilities in production scenario")
    logger.info("=" * 70)
    
    # Setup dependency injection
    container = setup_container()
    
    # Get services
    uow = container.resolve(ECommerceUnitOfWork)
    order_service = container.resolve(OrderService)
    inventory_service = container.resolve(InventoryService)
    event_bus = container.resolve(EventBus)
    email_service = container.resolve(EmailService)
    
    # Setup event handlers
    await setup_event_handlers(event_bus, email_service)
    
    # Seed data
    await seed_data(uow)
    
    # Demonstrate order creation
    logger.info("\n" + "=" * 70)
    logger.info("Creating Orders")
    logger.info("=" * 70)
    
    try:
        # Create order 1
        with timer_ctx("Order 1 Creation"):
            order1 = await order_service.create_order(
                user_id=1,
                product_id=1,
                quantity=1
            )
            logger.info(f"✓ Order created: {order1}")
        
        # Create order 2
        with timer_ctx("Order 2 Creation"):
            order2 = await order_service.create_order(
                user_id=2,
                product_id=2,
                quantity=5
            )
            logger.info(f"✓ Order created: {order2}")
        
        # Try to create order with insufficient stock
        try:
            order3 = await order_service.create_order(
                user_id=1,
                product_id=1,
                quantity=100  # More than available
            )
        except ValueError as e:
            logger.warning(f"✗ Order failed (expected): {e}")
    
    except Exception as e:
        logger.error(f"Error creating orders: {e}")
    
    # Check inventory
    logger.info("\n" + "=" * 70)
    logger.info("Inventory Status")
    logger.info("=" * 70)
    
    all_products = uow.products.list()
    for product in all_products:
        logger.info(f"Product: {product.name:15} | Stock: {product.stock:3} | Price: ${product.price:.2f}")
    
    # Check low stock
    low_stock = inventory_service.get_low_stock_products(threshold=20)
    if low_stock:
        logger.info(f"\n⚠️  Low stock alert: {len(low_stock)} products below threshold")
        for product in low_stock:
            logger.info(f"  - {product.name}: {product.stock} units remaining")
    
    # Check user balances
    logger.info("\n" + "=" * 70)
    logger.info("User Balances")
    logger.info("=" * 70)
    
    all_users = uow.users.list()
    for user in all_users:
        logger.info(f"User: {user.name:15} | Balance: ${user.balance:.2f}")
    
    logger.info("\n" + "=" * 70)
    logger.info("Demo completed successfully!")
    logger.info("=" * 70)


if __name__ == "__main__":
    # Run the application
    asyncio.run(main())
