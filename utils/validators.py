import re
import html
from typing import Optional, List
from pydantic import BaseModel, validator, Field
from config import config

class ChatRequest(BaseModel):
    """Validation model for chat requests"""
    message: str = Field(..., min_length=1, max_length=config.MAX_MESSAGE_LENGTH)
    model: str = Field(..., min_length=1, max_length=100)

    @validator('message')
    def validate_message(cls, v: str) -> str:
        """Validate and sanitize message content"""
        if not v or not v.strip():
            raise ValueError('Message cannot be empty')

        # Remove excessive whitespace
        v = re.sub(r'\s+', ' ', v.strip())

        # Check for suspicious patterns
        suspicious_patterns = [
            r'<script[^>]*>.*?</script>',  # Script tags
            r'javascript:',  # JavaScript URLs
            r'on\w+\s*=',  # Event handlers
            r'\beval\s*\(',  # eval() calls
        ]

        for pattern in suspicious_patterns:
            if re.search(pattern, v, re.IGNORECASE | re.DOTALL):
                raise ValueError('Message contains potentially unsafe content')

        # HTML escape for safety
        v = html.escape(v)

        return v

    @validator('model')
    def validate_model(cls, v: str) -> str:
        """Validate model name"""
        if not v or not v.strip():
            raise ValueError('Model name cannot be empty')

        # Only allow alphanumeric, hyphens, underscores, dots, and colons
        if not re.match(r'^[a-zA-Z0-9._:-]+$', v):
            raise ValueError('Invalid model name format')

        return v.strip().lower()

class ModelInfo(BaseModel):
    """Model information validation"""
    name: str
    description: Optional[str] = None
    size: Optional[str] = None
    family: Optional[str] = None

    @validator('name')
    def validate_name(cls, v: str) -> str:
        if not re.match(r'^[a-zA-Z0-9._:-]+$', v):
            raise ValueError('Invalid model name format')
        return v.lower()

def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe file operations"""
    # Remove or replace dangerous characters
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Remove leading/trailing dots and spaces
    filename = filename.strip('. ')
    # Limit length
    if len(filename) > 255:
        filename = filename[:255]
    return filename

def validate_url(url: str) -> bool:
    """Validate URL format"""
    url_pattern = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+'  # domain...
        r'(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'  # host...
        r'localhost|'  # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    return bool(url_pattern.match(url))

def validate_model_name(model_name: str) -> bool:
    """Validate Ollama model name format"""
    # Ollama model names can contain letters, numbers, hyphens, underscores, dots, and colons
    pattern = r'^[a-zA-Z0-9._:-]+$'
    return bool(re.match(pattern, model_name))

def sanitize_log_message(message: str) -> str:
    """Sanitize message for logging to prevent log injection"""
    # Remove newlines and carriage returns to prevent log injection
    message = re.sub(r'[\r\n]', ' ', message)
    # Limit length
    if len(message) > 1000:
        message = message[:1000] + '...'
    return message

def validate_port(port: int) -> bool:
    """Validate port number"""
    return 1 <= port <= 65535

def validate_timeout(timeout: int) -> bool:
    """Validate timeout value"""
    return 1 <= timeout <= 300  # 1 second to 5 minutes

def extract_model_info(model_string: str) -> dict:
    """Extract model information from model string"""
    # Handle formats like "model:tag" or "model"
    parts = model_string.split(':')
    name = parts[0]
    tag = parts[1] if len(parts) > 1 else 'latest'

    return {
        'name': name,
        'tag': tag,
        'full_name': model_string
    }

def is_safe_content(content: str) -> bool:
    """Check if content is safe for display"""
    # Check for potentially dangerous content
    dangerous_patterns = [
        r'<script[^>]*>.*?</script>',
        r'javascript:',
        r'data:text/html',
        r'vbscript:',
        r'on\w+\s*=',
    ]

    for pattern in dangerous_patterns:
        if re.search(pattern, content, re.IGNORECASE | re.DOTALL):
            return False

    return True

def truncate_text(text: str, max_length: int = 100, suffix: str = '...') -> str:
    """Truncate text to specified length"""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix

def validate_environment_config() -> List[str]:
    """Validate environment configuration and return list of issues"""
    issues = []

    if not validate_url(config.OLLAMA_URL):
        issues.append(f"Invalid OLLAMA_URL: {config.OLLAMA_URL}")

    if not validate_timeout(config.OLLAMA_TIMEOUT):
        issues.append(f"Invalid OLLAMA_TIMEOUT: {config.OLLAMA_TIMEOUT}")

    if not validate_port(config.PORT):
        issues.append(f"Invalid PORT: {config.PORT}")

    if config.MAX_MESSAGE_LENGTH <= 0:
        issues.append(f"Invalid MAX_MESSAGE_LENGTH: {config.MAX_MESSAGE_LENGTH}")

    return issues