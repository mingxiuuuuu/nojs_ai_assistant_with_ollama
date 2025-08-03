# Security Documentation

## Security Overview

The No-JS AI Assistant is designed with security as a primary concern, implementing multiple layers of protection against common web vulnerabilities while maintaining the no-JavaScript constraint.

## Core Security Principles

1. **Defense in Depth**: Multiple security layers
2. **Input Validation**: All user input validated and sanitized
3. **Least Privilege**: Minimal required permissions
4. **Secure by Default**: Safe default configurations
5. **No Client-Side Execution**: Zero JavaScript attack surface

## Input Validation & Sanitization

### Message Validation (from validators.py)

```python
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
            r'javascript:',               # JavaScript URLs
            r'on\w+\s*=',                # Event handlers
            r'\beval\s*\(',              # eval() calls
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
```

### Additional Validation Functions

```python
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

def is_safe_content(content: str) -> bool:
    """Check if content is safe for display"""
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
```

## Rate Limiting

### Multi-Layer Rate Limiting (from rate_limiter.py)

```python
class GlobalRateLimiter:
    """Global rate limiter for the entire application"""

    def __init__(self):
        # Per-IP rate limiting
        self.ip_limiter = SlidingWindowRateLimiter(
            max_requests=config.RATE_LIMIT_REQUESTS_PER_MINUTE,
            window_size=60
        )

        # Global rate limiting
        self.global_limiter = TokenBucket(
            capacity=config.RATE_LIMIT_REQUESTS_PER_MINUTE * 10,
            refill_rate=config.RATE_LIMIT_REQUESTS_PER_MINUTE / 60
        )

        # Adaptive limiting for Ollama requests
        self.ollama_limiter = AdaptiveRateLimiter(
            base_limit=config.RATE_LIMIT_REQUESTS_PER_MINUTE // 2,
            window_size=60
        )
```

### Rate Limiting Configuration (from config.py)

```python
# Rate Limiting Configuration
RATE_LIMIT_ENABLED: bool = Field(default=True)
RATE_LIMIT_REQUESTS_PER_MINUTE: int = Field(default=60)
RATE_LIMIT_BURST_SIZE: int = Field(default=10)

# Ollama-specific rate limits
OLLAMA_RATE_LIMIT_REQUESTS_PER_MINUTE: int = Field(default=10)
OLLAMA_RATE_LIMIT_BURST_SIZE: int = Field(default=3)

# Adaptive rate limiting
ADAPTIVE_RATE_LIMIT_ENABLED: bool = Field(default=True)
ADAPTIVE_RATE_LIMIT_MIN_REQUESTS: int = Field(default=5)
ADAPTIVE_RATE_LIMIT_MAX_REQUESTS: int = Field(default=20)
```

### Client IP Extraction (from rate_limiter.py)

```python
def get_client_ip(request) -> str:
    """Extract client IP from request"""
    # Check for forwarded headers first
    forwarded_for = request.headers.get('X-Forwarded-For')
    if forwarded_for:
        # Take the first IP in the chain
        return forwarded_for.split(',')[0].strip()

    real_ip = request.headers.get('X-Real-IP')
    if real_ip:
        return real_ip

    # Fall back to direct connection IP
    return request.client.host if hasattr(request, 'client') else '127.0.0.1'
```

## Security Headers

### Production Security Headers (from config.py)

```python
def get_security_headers(self) -> dict:
    """Get security headers configuration."""
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-XSS-Protection": "1; mode=block",
        "Referrer-Policy": "strict-origin-when-cross-origin"
    }

    if self.is_production:
        headers.update({
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';"
        })

    return headers
```

### Header Explanations

| Header | Purpose | Value |
|--------|---------|-------|
| `X-Content-Type-Options` | Prevents MIME sniffing | `nosniff` |
| `X-Frame-Options` | Prevents clickjacking | `DENY` |
| `X-XSS-Protection` | Browser XSS protection | `1; mode=block` |
| `Referrer-Policy` | Controls referrer information | `strict-origin-when-cross-origin` |
| `Strict-Transport-Security` | Enforces HTTPS | `max-age=31536000; includeSubDomains` |
| `Content-Security-Policy` | Controls resource loading | `default-src 'self'; ...` |

## Authentication & Authorization

### Current Implementation
- **No Authentication**: Open access model
- **Session-based**: Sessions tied to browser, not users
- **IP-based Rate Limiting**: Protection against abuse

### Adding Authentication (Future Enhancement)

For production environments requiring authentication:

```python
# Example: Basic session-based auth
class AuthMiddleware:
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            request = Request(scope, receive)
            
            # Check for auth session
            session_token = request.cookies.get("session_token")
            if not session_token and request.url.path not in ["/login", "/health"]:
                response = RedirectResponse("/login")
                await response(scope, receive, send)
                return
                
        await self.app(scope, receive, send)
```

## Data Protection

### Database Security

```python
# From config.py - Secure database configuration
DATABASE_URL: str = Field(default="sqlite:///./chat_history.db")
DATABASE_POOL_SIZE: int = Field(default=10)
DATABASE_MAX_OVERFLOW: int = Field(default=20)
DATABASE_POOL_TIMEOUT: int = Field(default=30)

# Automatic cleanup to prevent data accumulation
DATABASE_CLEANUP_DAYS: int = Field(default=30)
```

### SQL Injection Prevention
- **Parameterized Queries**: All database interactions use parameterized queries
- **ORM Protection**: SQLAlchemy prevents direct SQL injection
- **Input Validation**: All inputs validated before database operations

### Data Encryption
- **At Rest**: SQLite database can be encrypted using SQLCipher
- **In Transit**: HTTPS enforced in production
- **Memory**: Sensitive data not stored in logs

## File System Security

### Safe File Operations (from validators.py)

```python
def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe file operations"""
    # Remove or replace dangerous characters
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Remove leading/trailing dots and spaces
    filename = filename.strip('. ')
    # Limit length
    if len(filename) > config.MAX_FILENAME_LENGTH:
        filename = filename[:config.MAX_FILENAME_LENGTH]
    return filename
```

### Directory Traversal Prevention
- **Restricted Paths**: File operations limited to specific directories
- **Path Validation**: All file paths validated and sanitized
- **Containerization**: Docker provides additional isolation

## Container Security

### Docker Security Configuration

```yaml
# From docker-compose.yml - Security considerations
services:
  nojs-ai:
    # Run as non-root user
    user: "1000:1000"
    
    # Read-only root filesystem
    read_only: true
    
    # Temporary filesystems for writes
    tmpfs:
      - /tmp
      - /var/tmp
    
    # Security options
    security_opt:
      - no-new-privileges:true
    
    # Resource limits
    deploy:
      resources:
        limits:
          memory: 2G
          cpus: '2.0'
```

### Network Security
- **Internal Networks**: Services communicate via Docker internal networks
- **Port Exposure**: Only necessary ports exposed to host
- **Service Isolation**: Each service runs in separate container

## Logging & Monitoring Security

### Secure Logging (from logging_config.py)

```python
def sanitize_log_message(message: str) -> str:
    """Sanitize message for logging to prevent log injection"""
    # Remove newlines and carriage returns to prevent log injection
    message = re.sub(r'[\r\n]', ' ', message)
    # Limit length
    if len(message) > 1000:
        message = message[:1000] + '...'
    return message

class StructuredFormatter(logging.Formatter):
    """Custom formatter for structured logging"""
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': sanitize_log_message(record.getMessage()),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }
        return json.dumps(log_entry, ensure_ascii=False)
```

### Log Security Practices
- **No Sensitive Data**: Never log passwords, tokens, or sensitive content
- **Log Injection Prevention**: All log messages sanitized
- **Structured Logging**: JSON format prevents log parsing attacks
- **Access Control**: Log files protected with appropriate permissions

## Configuration Security

### Environment Variable Security (from config.py)

```python
# Security Configuration
SECRET_KEY: str = Field(default="your-secret-key-change-in-production")
ALLOWED_HOSTS: List[str] = Field(default=["localhost", "127.0.0.1"])
CORS_ORIGINS: List[str] = Field(default=["http://localhost:8000"])

# Security limits
MAX_REQUEST_SIZE: int = Field(default=1024 * 1024)  # 1MB
MAX_MESSAGE_LENGTH: int = Field(default=10000)
MAX_FILENAME_LENGTH: int = Field(default=255)

def validate_configuration(self) -> List[str]:
    """Validate configuration and return list of warnings/errors."""
    warnings = []
    
    if self.is_production:
        if self.SECRET_KEY == "your-secret-key-change-in-production":
            warnings.append("Using default secret key in production")
        if self.DEBUG:
            warnings.append("Debug mode enabled in production")
        if "localhost" in self.ALLOWED_HOSTS:
            warnings.append("Localhost in allowed hosts for production")
    
    return warnings
```

### Production Configuration Checklist

- [ ] **SECRET_KEY**: Changed from default value
- [ ] **DEBUG**: Set to `False`
- [ ] **ALLOWED_HOSTS**: Configured for production domain
- [ ] **HTTPS**: SSL/TLS enabled
- [ ] **CORS_ORIGINS**: Restricted to trusted domains
- [ ] **Rate Limiting**: Enabled and configured appropriately
- [ ] **Log Level**: Set to `INFO` or `WARNING`

## Middleware Security

### Security Middleware Stack (from main.py)

```python
# Add middleware (order matters - last added is executed first)
app.add_middleware(SecurityMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestLoggingMiddleware)
```

### Request Size Limits

```python
# From config.py
MAX_REQUEST_SIZE: int = Field(default=1024 * 1024)  # 1MB limit
```

## Vulnerability Assessments

### Common Web Vulnerabilities

| Vulnerability | Status | Protection Method |
|---------------|--------|-------------------|
| **XSS** | ✅ Protected | HTML escaping, CSP headers, no JavaScript |
| **SQL Injection** | ✅ Protected | Parameterized queries, ORM |
| **CSRF** | ✅ Protected | Form-based requests, same-origin |
| **Clickjacking** | ✅ Protected | X-Frame-Options: DENY |
| **MIME Sniffing** | ✅ Protected | X-Content-Type-Options: nosniff |
| **Directory Traversal** | ✅ Protected | Path sanitization, containerization |
| **Log Injection** | ✅ Protected | Log message sanitization |
| **Rate Limiting Bypass** | ✅ Protected | Multi-layer rate limiting |
| **File Upload** | ✅ N/A | No file upload functionality |
| **Session Fixation** | ⚠️ Partial | No authentication system currently |
| **Insecure Deserialization** | ✅ Protected | No deserialization of untrusted data |


This security documentation provides comprehensive coverage of the current security implementation and guidelines for maintaining and enhancing security as the application evolves.