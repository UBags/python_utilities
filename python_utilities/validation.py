"""
Validation Module

Production-ready validation utilities using Pydantic:
- Request/response validation
- Configuration management
- Data contracts between services
- Automatic schema generation
"""

from typing import Type, TypeVar, Optional, Dict, Any, List
from pydantic import BaseModel, Field, validator, root_validator
from pydantic import ValidationError as PydanticValidationError
import logging
import json

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)


# ============================================================================
# VALIDATION DECORATOR
# ============================================================================

def validate_with_pydantic(
    input_model: Optional[Type[BaseModel]] = None,
    output_model: Optional[Type[BaseModel]] = None,
):
    """
    Validate function inputs and outputs with Pydantic models.
    
    Production use cases:
    - API request/response validation
    - Data pipeline validation
    - Microservice communication contracts
    
    Example:
        class UserInput(BaseModel):
            name: str
            email: EmailStr
            age: int = Field(ge=0, le=150)
        
        class UserOutput(BaseModel):
            id: int
            name: str
            email: str
        
        @validate_with_pydantic(
            input_model=UserInput,
            output_model=UserOutput
        )
        def create_user(data: dict) -> dict:
            # data is already validated
            user_id = save_to_db(data)
            return {**data, 'id': user_id}
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            # Validate input
            if input_model:
                if args:
                    # Assume first arg is the data
                    try:
                        validated_input = input_model(**args[0])
                        args = (validated_input.dict(),) + args[1:]
                    except PydanticValidationError as e:
                        logger.error(f"Input validation failed: {e}")
                        raise ValueError(f"Invalid input: {e}")
            
            # Call function
            result = func(*args, **kwargs)
            
            # Validate output
            if output_model and result is not None:
                try:
                    validated_output = output_model(**result)
                    return validated_output.dict()
                except PydanticValidationError as e:
                    logger.error(f"Output validation failed: {e}")
                    raise ValueError(f"Invalid output: {e}")
            
            return result
        
        return wrapper
    return decorator


# ============================================================================
# SETTINGS MANAGEMENT
# ============================================================================

def create_settings(
    model_class: Type[T],
    env_file: Optional[str] = '.env',
    **defaults
) -> T:
    """
    Create validated settings from environment variables.
    
    Production use cases:
    - Application configuration
    - Environment-specific settings
    - Feature flags and secrets management
    
    Example:
        from pydantic import BaseSettings
        
        class AppSettings(BaseSettings):
            app_name: str = "MyApp"
            debug: bool = False
            database_url: str
            redis_url: Optional[str] = None
            api_key: str
            
            class Config:
                env_file = ".env"
        
        settings = create_settings(AppSettings)
        print(settings.database_url)
    """
    try:
        settings = model_class(**defaults)
        logger.info(f"Settings loaded successfully for {model_class.__name__}")
        return settings
    except PydanticValidationError as e:
        logger.error(f"Settings validation failed: {e}")
        raise


# ============================================================================
# COMMON VALIDATION MODELS
# ============================================================================

class EmailValidation(BaseModel):
    """Email validation model."""
    email: str
    
    @validator('email')
    def validate_email(cls, v):
        """Validate email format."""
        import re
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(pattern, v):
            raise ValueError('Invalid email format')
        return v.lower()


class PhoneValidation(BaseModel):
    """Phone number validation model."""
    phone: str
    
    @validator('phone')
    def validate_phone(cls, v):
        """Validate phone number format."""
        import re
        # Remove common separators
        cleaned = re.sub(r'[\s\-\(\)]', '', v)
        # Check if valid phone number
        if not re.match(r'^\+?[1-9]\d{1,14}$', cleaned):
            raise ValueError('Invalid phone number format')
        return cleaned


class PasswordValidation(BaseModel):
    """Password validation model."""
    password: str
    
    @validator('password')
    def validate_password(cls, v):
        """Validate password strength."""
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain uppercase letter')
        if not any(c.islower() for c in v):
            raise ValueError('Password must contain lowercase letter')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain digit')
        return v


class PaginationParams(BaseModel):
    """Pagination parameters validation."""
    page: int = Field(1, ge=1, description="Page number")
    page_size: int = Field(20, ge=1, le=100, description="Items per page")
    
    @property
    def offset(self) -> int:
        """Calculate offset for database queries."""
        return (self.page - 1) * self.page_size
    
    @property
    def limit(self) -> int:
        """Get limit for database queries."""
        return self.page_size


# ============================================================================
# DATA VALIDATION HELPERS
# ============================================================================

def validate_json(json_str: str, model: Type[BaseModel]) -> BaseModel:
    """
    Validate JSON string against Pydantic model.
    
    Production use cases:
    - API request validation
    - Configuration file validation
    - Message queue payload validation
    
    Example:
        class UserData(BaseModel):
            name: str
            age: int
        
        json_data = '{"name": "Alice", "age": 30}'
        user = validate_json(json_data, UserData)
    """
    try:
        data = json.loads(json_str)
        return model(**data)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON: {e}")
        raise ValueError(f"Invalid JSON: {e}")
    except PydanticValidationError as e:
        logger.error(f"Validation failed: {e}")
        raise ValueError(f"Validation failed: {e}")


def validate_dict(data: dict, model: Type[BaseModel]) -> BaseModel:
    """
    Validate dictionary against Pydantic model.
    
    Example:
        user = validate_dict(
            {'name': 'Alice', 'age': 30},
            UserData
        )
    """
    try:
        return model(**data)
    except PydanticValidationError as e:
        logger.error(f"Validation failed: {e}")
        raise ValueError(f"Validation failed: {e}")


def get_validation_errors(data: dict, model: Type[BaseModel]) -> Optional[Dict]:
    """
    Get validation errors without raising exception.
    
    Production use cases:
    - User-friendly error messages
    - Form validation
    - Bulk validation reporting
    
    Example:
        errors = get_validation_errors(invalid_data, UserData)
        if errors:
            return {"errors": errors}
    """
    try:
        model(**data)
        return None
    except PydanticValidationError as e:
        return e.errors()


# ============================================================================
# BULK VALIDATION
# ============================================================================

def validate_bulk(
    items: List[dict],
    model: Type[BaseModel],
    skip_invalid: bool = False,
) -> tuple[List[BaseModel], List[Dict]]:
    """
    Validate multiple items.
    
    Production use cases:
    - Bulk data import
    - Batch processing
    - Data migration validation
    
    Example:
        valid, invalid = validate_bulk(
            [{'name': 'Alice', 'age': 30}, {'name': 'Bob'}],
            UserData,
            skip_invalid=True
        )
    """
    valid_items = []
    invalid_items = []
    
    for i, item in enumerate(items):
        try:
            validated = model(**item)
            valid_items.append(validated)
        except PydanticValidationError as e:
            error_info = {
                'index': i,
                'data': item,
                'errors': e.errors()
            }
            invalid_items.append(error_info)
            
            if not skip_invalid:
                logger.error(f"Validation failed for item {i}: {e}")
                raise ValueError(f"Validation failed for item {i}")
    
    logger.info(
        f"Validated {len(valid_items)} items, "
        f"{len(invalid_items)} invalid"
    )
    
    return valid_items, invalid_items


# ============================================================================
# SCHEMA GENERATION
# ============================================================================

def generate_json_schema(model: Type[BaseModel]) -> Dict[str, Any]:
    """
    Generate JSON schema from Pydantic model.
    
    Production use cases:
    - API documentation
    - Contract specification
    - Code generation
    
    Example:
        schema = generate_json_schema(UserData)
        print(json.dumps(schema, indent=2))
    """
    return model.schema()


def generate_openapi_schema(
    models: Dict[str, Type[BaseModel]]
) -> Dict[str, Any]:
    """
    Generate OpenAPI schema for multiple models.
    
    Production use cases:
    - API documentation
    - Client SDK generation
    - Contract testing
    
    Example:
        schema = generate_openapi_schema({
            'User': UserModel,
            'Product': ProductModel
        })
    """
    schemas = {}
    for name, model in models.items():
        schemas[name] = model.schema()
    
    return {
        'components': {
            'schemas': schemas
        }
    }


# ============================================================================
# SANITIZATION HELPERS
# ============================================================================

class SanitizedString(BaseModel):
    """String with automatic sanitization."""
    value: str
    
    @validator('value')
    def sanitize(cls, v):
        """Remove dangerous characters."""
        import html
        # HTML escape
        v = html.escape(v)
        # Remove null bytes
        v = v.replace('\x00', '')
        return v.strip()


def sanitize_dict(data: dict) -> dict:
    """
    Recursively sanitize dictionary values.
    
    Production use cases:
    - XSS prevention
    - SQL injection prevention
    - Input sanitization
    
    Example:
        clean_data = sanitize_dict({
            'name': '<script>alert("xss")</script>',
            'description': 'Safe text'
        })
    """
    import html
    
    def sanitize_value(value):
        if isinstance(value, str):
            return html.escape(value.replace('\x00', '').strip())
        elif isinstance(value, dict):
            return sanitize_dict(value)
        elif isinstance(value, list):
            return [sanitize_value(item) for item in value]
        return value
    
    return {k: sanitize_value(v) for k, v in data.items()}


# ============================================================================
# CUSTOM VALIDATORS
# ============================================================================

class URLValidation(BaseModel):
    """URL validation model."""
    url: str
    
    @validator('url')
    def validate_url(cls, v):
        """Validate URL format."""
        import re
        pattern = r'^https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&\/=]*)$'
        if not re.match(pattern, v):
            raise ValueError('Invalid URL format')
        return v


class DateRangeValidation(BaseModel):
    """Date range validation."""
    start_date: str
    end_date: str
    
    @root_validator
    def validate_date_range(cls, values):
        """Ensure start_date is before end_date."""
        from datetime import datetime
        
        start = datetime.fromisoformat(values.get('start_date'))
        end = datetime.fromisoformat(values.get('end_date'))
        
        if start >= end:
            raise ValueError('start_date must be before end_date')
        
        return values


class CreditCardValidation(BaseModel):
    """Credit card validation using Luhn algorithm."""
    card_number: str
    
    @validator('card_number')
    def validate_card_number(cls, v):
        """Validate credit card number using Luhn algorithm."""
        # Remove spaces and dashes
        v = v.replace(' ', '').replace('-', '')
        
        if not v.isdigit():
            raise ValueError('Card number must contain only digits')
        
        if len(v) < 13 or len(v) > 19:
            raise ValueError('Invalid card number length')
        
        # Luhn algorithm
        def luhn_checksum(card_num):
            def digits_of(n):
                return [int(d) for d in str(n)]
            
            digits = digits_of(card_num)
            odd_digits = digits[-1::-2]
            even_digits = digits[-2::-2]
            checksum = sum(odd_digits)
            for d in even_digits:
                checksum += sum(digits_of(d * 2))
            return checksum % 10
        
        if luhn_checksum(v) != 0:
            raise ValueError('Invalid card number')
        
        return v
