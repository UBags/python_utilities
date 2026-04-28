"""
Validation Module

Production-ready validation utilities using Pydantic v2:
- Request/response validation
- Configuration management
- Data contracts between services
- Automatic schema generation

This module targets Pydantic v2 (>=2.0). The v1 API (`@validator`,
`@root_validator`, `.dict()`, `.schema()`) is no longer supported.
"""

from typing import Type, TypeVar, Optional, Dict, Any, List, Tuple
from pydantic import BaseModel, Field, field_validator, model_validator
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
            email: str
            age: int = Field(ge=0, le=150)

        class UserOutput(BaseModel):
            id: int
            name: str
            email: str

        @validate_with_pydantic(
            input_model=UserInput,
            output_model=UserOutput,
        )
        def create_user(data: dict) -> dict:
            # data is already validated
            user_id = save_to_db(data)
            return {**data, 'id': user_id}
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            # Validate input
            if input_model and args:
                try:
                    validated_input = input_model(**args[0])
                    # model_dump() is the v2 successor to .dict().
                    args = (validated_input.model_dump(),) + args[1:]
                except PydanticValidationError as e:
                    logger.error(f"Input validation failed: {e}")
                    raise ValueError(f"Invalid input: {e}")

            # Call function
            result = func(*args, **kwargs)

            # Validate output
            if output_model and result is not None:
                try:
                    validated_output = output_model(**result)
                    return validated_output.model_dump()
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
    **defaults,
) -> T:
    """
    Create validated settings from environment variables.

    Production use cases:
    - Application configuration
    - Environment-specific settings
    - Feature flags and secrets management

    NOTE: In Pydantic v2, `BaseSettings` was extracted into a separate
    package, `pydantic-settings`. Install it with `pip install
    pydantic-settings` and import from there:

        from pydantic_settings import BaseSettings, SettingsConfigDict

        class AppSettings(BaseSettings):
            model_config = SettingsConfigDict(env_file=".env")

            app_name: str = "MyApp"
            database_url: str
            api_key: str

        settings = create_settings(AppSettings)

    For plain `BaseModel` subclasses (no env-var loading), this function
    just instantiates the class with the supplied defaults.
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

    @field_validator('email')
    @classmethod
    def validate_email(cls, v: str) -> str:
        """Validate email format."""
        import re
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(pattern, v):
            raise ValueError('Invalid email format')
        return v.lower()


class PhoneValidation(BaseModel):
    """Phone number validation model (E.164-ish)."""
    phone: str

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v: str) -> str:
        """Validate phone number format."""
        import re
        cleaned = re.sub(r'[\s\-\(\)]', '', v)
        if not re.match(r'^\+?[1-9]\d{1,14}$', cleaned):
            raise ValueError('Invalid phone number format')
        return cleaned


class PasswordValidation(BaseModel):
    """Password validation model."""
    password: str

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
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
        user = validate_dict({'name': 'Alice', 'age': 30}, UserData)
    """
    try:
        return model(**data)
    except PydanticValidationError as e:
        logger.error(f"Validation failed: {e}")
        raise ValueError(f"Validation failed: {e}")


def get_validation_errors(
    data: dict, model: Type[BaseModel]
) -> Optional[List[Dict[str, Any]]]:
    """
    Get validation errors without raising exception.

    Returns the list of error dicts produced by Pydantic, or None on success.
    The shape of each error dict in v2 is documented at
    https://docs.pydantic.dev/latest/errors/validation_errors/

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
) -> Tuple[List[BaseModel], List[Dict[str, Any]]]:
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
            skip_invalid=True,
        )
    """
    valid_items: List[BaseModel] = []
    invalid_items: List[Dict[str, Any]] = []

    for i, item in enumerate(items):
        try:
            validated = model(**item)
            valid_items.append(validated)
        except PydanticValidationError as e:
            error_info = {
                'index': i,
                'data': item,
                'errors': e.errors(),
            }
            invalid_items.append(error_info)

            if not skip_invalid:
                logger.error(f"Validation failed for item {i}: {e}")
                raise ValueError(f"Validation failed for item {i}")

    logger.info(
        f"Validated {len(valid_items)} items, {len(invalid_items)} invalid"
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
    # model_json_schema() is the v2 successor to .schema().
    return model.model_json_schema()


def generate_openapi_schema(
    models: Dict[str, Type[BaseModel]],
) -> Dict[str, Any]:
    """
    Generate OpenAPI schema fragment for multiple models.

    Production use cases:
    - API documentation
    - Client SDK generation
    - Contract testing

    Example:
        schema = generate_openapi_schema({
            'User': UserModel,
            'Product': ProductModel,
        })
    """
    schemas = {name: model.model_json_schema() for name, model in models.items()}
    return {'components': {'schemas': schemas}}


# ============================================================================
# SANITIZATION HELPERS
# ============================================================================

class SanitizedString(BaseModel):
    """String with automatic sanitization."""
    value: str

    @field_validator('value')
    @classmethod
    def sanitize(cls, v: str) -> str:
        """Remove dangerous characters."""
        import html
        v = html.escape(v)
        v = v.replace('\x00', '')
        return v.strip()


def sanitize_dict(data: dict) -> dict:
    """
    Recursively sanitize dictionary values.

    Production use cases:
    - XSS prevention
    - SQL injection prevention (combined with parameterized queries)
    - Input sanitization

    Example:
        clean = sanitize_dict({
            'name': '<script>alert("xss")</script>',
            'description': 'Safe text',
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

    @field_validator('url')
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate URL format."""
        import re
        pattern = (
            r'^https?://(?:www\.)?'
            r'[-a-zA-Z0-9@:%._\+~#=]{1,256}'
            r'\.[a-zA-Z0-9()]{1,6}\b'
            r'(?:[-a-zA-Z0-9()@:%_\+.~#?&\/=]*)$'
        )
        if not re.match(pattern, v):
            raise ValueError('Invalid URL format')
        return v


class DateRangeValidation(BaseModel):
    """Date range validation."""
    start_date: str
    end_date: str

    # mode='after' runs the validator on a fully-constructed model instance,
    # which is the v2 idiom that replaces the v1 @root_validator (which
    # operated on a raw `values` dict). Returning `self` is required.
    @model_validator(mode='after')
    def validate_date_range(self) -> 'DateRangeValidation':
        """Ensure start_date is before end_date."""
        from datetime import datetime
        start = datetime.fromisoformat(self.start_date)
        end = datetime.fromisoformat(self.end_date)
        if start >= end:
            raise ValueError('start_date must be before end_date')
        return self


class CreditCardValidation(BaseModel):
    """
    Credit card number format check using Luhn algorithm.

    NOTE: Luhn passes only confirm that a number is well-formed — it does
    NOT confirm the card is real, active, or authorized to charge. Real
    payment systems should never see raw PANs in the first place; use a
    tokenization gateway and operate on tokens. This class exists for
    edge cases like legacy data validation.
    """
    card_number: str

    @field_validator('card_number')
    @classmethod
    def validate_card_number(cls, v: str) -> str:
        """Validate credit card number using Luhn algorithm."""
        v = v.replace(' ', '').replace('-', '')

        if not v.isdigit():
            raise ValueError('Card number must contain only digits')
        if len(v) < 13 or len(v) > 19:
            raise ValueError('Invalid card number length')

        # Luhn algorithm
        def luhn_checksum(card_num: str) -> int:
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