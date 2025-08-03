# Architecture Documentation

## System Overview

The No-JS AI Assistant follows a traditional server-side rendered architecture, specifically designed to work without JavaScript in the browser.

```
┌─────────────────────────────────────────────────────────────────┐
│                           Browser                               │
│  ┌─────────────────┐    ┌─────────────────┐    ┌──────────────┐ │
│  │   HTML Forms    │    │   CSS Styling   │    │Auto-refresh  │ │
│  │                 │    │                 │    │Meta Tags     │ │
│  └─────────────────┘    └─────────────────┘    └──────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                                    │
                              HTTP POST/GET
                                    │
┌─────────────────────────────────────────────────────────────────┐
│                        FastAPI Backend                         │
│  ┌─────────────────┐    ┌─────────────────┐    ┌──────────────┐ │
│  │  Route Handlers │    │   Middleware    │    │ Jinja2       │ │
│  │  - /chat        │    │  - Security     │    │ Templates    │ │
│  │  - /sessions/*  │    │  - Rate Limit   │    │              │ │
│  │  - /health      │    │  - Logging      │    │              │ │
│  └─────────────────┘    └─────────────────┘    └──────────────┘ │
│                                    │                            │
│  ┌─────────────────┐    ┌─────────────────┐                    │
│  │  Validation     │    │  Background     │                    │
│  │  (Pydantic)     │    │  Tasks          │                    │
│  └─────────────────┘    └─────────────────┘                    │
└─────────────────────────────────────────────────────────────────┘
                          │                    │
                    HTTP Requests         Database Ops
                          │                    │
┌─────────────────────────────────┐    ┌──────────────────────┐
│         Ollama Service          │    │    SQLite Database   │
│  ┌─────────────────────────────┐│    │ ┌──────────────────┐ │
│  │     HTTP API Server         ││    │ │  chat_sessions   │ │
│  │  - /api/generate            ││    │ │  chat_messages   │ │
│  │  - /api/version             ││    │ │                  │ │
│  │  - /api/tags                ││    │ └──────────────────┘ │
│  └─────────────────────────────┘│    └──────────────────────┘
│  ┌─────────────────────────────┐│
│  │      Model Engine           ││
│  │  - mistral                  ││
│  │  - llama3.2                 ││
│  │  - phi3                     ││
│  │  - tinyllama                ││
│  └─────────────────────────────┘│
└─────────────────────────────────┘
```

## Component Architecture

### 1. Frontend Layer (No JavaScript)

#### HTML Forms Communication
```python
# From index.html - Message submission
<form method="post" action="/chat" class="chat-form">
    <input type="hidden" name="session_id" value="{{ current_session.id }}">
    <select name="model" class="model-select">
        {% for model in models %}
        <option value="{{ model }}">{{ model.title() }}</option>
        {% endfor %}
    </select>
    <input type="text" name="message" placeholder="Type message..." required>
    <button type="submit">Send</button>
</form>
```

#### Auto-Refresh Mechanism
```html
<!-- From index.html - Waiting state management -->
{% if auto_refresh %}
<meta http-equiv="refresh" content="2">
{% endif %}
```

#### Session Management Forms
```html
<!-- New session -->
<form action="/sessions/new" method="post">
    <button type="submit">+ New Chat</button>
</form>

<!-- Update title -->
<form action="/sessions/{{ session.id }}/title" method="post">
    <input type="text" name="title" value="{{ session.title }}">
    <button type="submit">Update</button>
</form>
```

### 2. Backend Layer (FastAPI)

#### Application Structure (from main.py)
```python
# Core FastAPI application
app = FastAPI(
    title="No-JS AI Assistant",
    description="A secure, offline-first AI assistant powered by Ollama",
    version="2.0.0",
    lifespan=lifespan
)

# Service initialization
app.state.ollama_service = OllamaService(
    base_url=config.OLLAMA_URL,
    timeout=config.OLLAMA_TIMEOUT
)
app.state.db_service = DatabaseService()
```

#### Middleware Stack (from main.py)
```python
# Order matters - last added is executed first
app.add_middleware(SecurityMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestLoggingMiddleware)
```

#### Route Architecture
```python
# Chat routes
@app.post("/chat")                    # Message submission
@app.get("/chat/{session_id}")        # Session view

# Session management routes  
@app.post("/sessions/new")            # Create session
@app.post("/sessions/{session_id}/title")  # Update title
@app.post("/sessions/{session_id}/delete") # Delete session

# API routes
@app.get("/health")                   # Health check
@app.get("/metrics")                  # Usage metrics
@app.get("/api/models")               # Available models
```

### 3. Service Layer

#### Database Service (DatabaseService)
```python
# From main.py - Database operations referenced
await db_service.create_session(title)
await db_service.save_message("user", message, session_id)
await db_service.get_conversation_history(session_id, limit=10)
await db_service.get_sessions()
await db_service.update_session_title(session_id, title)
```

#### Ollama Service (OllamaService)
```python
# From main.py - Ollama integration
await ollama_service.generate_response(
    model=model,
    prompt=message,
    context=context_messages
)
await ollama_service.check_health()
await ollama_service.get_models()
```

## Data Flow Architecture

### 1. Message Submission Flow

```
User Types Message
        ↓
HTML Form Submission (POST /chat)
        ↓
FastAPI Route Handler
        ↓
Input Validation (Pydantic)
        ↓
Save User Message to Database
        ↓
Redirect to /chat/{session_id}?waiting=true
        ↓
Background Task: Generate AI Response
        ↓
Save AI Response to Database
        ↓
Auto-refresh Detects Response Ready
        ↓
Page Loads with Complete Conversation
```

### 2. No-JS State Management

#### Two-Phase Response System (from main.py)
```python
# Phase 1: Immediate user feedback
await db_service.save_message("user", chat_request.message, session_id)
return RedirectResponse(f"/chat/{session_id}?waiting=true", status_code=303)

# Phase 2: Background AI generation
asyncio.create_task(generate_ai_response_background(
    session_id, message, model, ollama_service, db_service, client_ip
))
```

#### Waiting State Detection (from main.py)
```python
# Check if AI response is ready
if waiting and messages:
    last_message = messages[-1]
    if last_message['role'] == 'assistant':
        is_waiting = False
        auto_refresh = False
        return RedirectResponse(f"/chat/{session_id}", status_code=302)
```

### 3. Context Management Flow

```
User Sends Message
        ↓
Retrieve Last 10 Messages from Database
        ↓
Format as Context Array
        ↓
Send to Ollama with Context
        ↓
Receive AI Response
        ↓
Save Response with Metadata
        ↓
Update UI with New Message
```

## Configuration Architecture

### 1. Configuration Hierarchy (from config.py)

```python
# Environment-based configuration
class Config(BaseSettings):
    # Application layer
    APP_NAME: str = Field(default="AI Assistant")
    VERSION: str = Field(default="2.0.0")
    ENVIRONMENT: str = Field(default="development")
    
    # Service layer
    OLLAMA_URL: str = Field(default="http://127.0.0.1:11434")
    DATABASE_URL: str = Field(default="sqlite:///./chat_history.db")
    
    # Security layer
    RATE_LIMIT_ENABLED: bool = Field(default=True)
    MAX_MESSAGE_LENGTH: int = Field(default=10000)
    
    class Config:
        env_file = ".env"
        case_sensitive = True
```

### 2. Dynamic Configuration Override (from config.py)
```python
@validator('DATABASE_URL', pre=True)
def set_database_url(cls, v, values):
    """Override DATABASE_URL if DB_PATH environment variable is set"""
    db_path = os.getenv('DB_PATH')
    if db_path:
        return f"sqlite:///{db_path}"
    return v

@validator('OLLAMA_URL', pre=True)
def set_ollama_url(cls, v):
    """Override OLLAMA_URL from environment variable"""
    return os.getenv('OLLAMA_URL', v)
```

## Security Architecture

### 1. Input Validation Layer (from validators.py)
```python
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=config.MAX_MESSAGE_LENGTH)
    model: str = Field(..., min_length=1, max_length=100)

    @validator('message')
    def validate_message(cls, v: str) -> str:
        # XSS prevention
        suspicious_patterns = [
            r'<script[^>]*>.*?</script>',
            r'javascript:',
            r'on\w+\s*=',
            r'\beval\s*\(',
        ]
        # HTML escape for safety
        v = html.escape(v)
        return v
```

### 2. Rate Limiting Architecture (from rate_limiter.py)
```python
class GlobalRateLimiter:
    def __init__(self):
        # Multi-layer rate limiting
        self.ip_limiter = SlidingWindowRateLimiter(
            max_requests=config.RATE_LIMIT_REQUESTS_PER_MINUTE,
            window_size=60
        )
        self.global_limiter = TokenBucket(
            capacity=config.RATE_LIMIT_REQUESTS_PER_MINUTE * 10,
            refill_rate=config.RATE_LIMIT_REQUESTS_PER_MINUTE / 60
        )
        self.ollama_limiter = AdaptiveRateLimiter(
            base_limit=config.RATE_LIMIT_REQUESTS_PER_MINUTE // 2,
            window_size=60
        )
```

### 3. Security Headers (from config.py)
```python
def get_security_headers(self) -> dict:
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-XSS-Protection": "1; mode=block",
        "Referrer-Policy": "strict-origin-when-cross-origin"
    }
    if self.is_production:
        headers.update({
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline';"
        })
    return headers
```

## Performance Architecture

### 1. Database Optimization
```python
# From config.py - Connection pooling
DATABASE_POOL_SIZE: int = Field(default=10)
DATABASE_MAX_OVERFLOW: int = Field(default=20)
DATABASE_POOL_TIMEOUT: int = Field(default=30)
DATABASE_CLEANUP_DAYS: int = Field(default=30)
```

### 2. Context Window Management
```python
# From main.py - Limited context retrieval
context_messages = await db_service.get_conversation_history(session_id, limit=10)
```

### 3. Caching Strategy (from config.py)
```python
OLLAMA_MODEL_CACHE_TTL: int = Field(default=300, description="Model cache TTL in seconds")
```

## Monitoring Architecture

### 1. Health Check System (from main.py)
```python
@app.get("/health")
async def health_check():
    health_status = {
        "status": "healthy",
        "timestamp": time.time(),
        "version": "2.0.0",
        "services": {
            "database": {"status": "healthy", "response_time": 0.023},
            "ollama": {"status": "healthy", "response_time": 0.156}
        }
    }
```

### 2. Logging Architecture (from logging_config.py)
```python
# Structured logging with multiple handlers
{
    "app.log": "General application logs",
    "error.log": "Error-specific logs", 
    "performance.log": "Performance metrics"
}

# Log rotation
RotatingFileHandler(
    maxBytes=10 * 1024 * 1024,  # 10MB
    backupCount=5
)
```

### 3. Metrics Collection (from main.py)
```python
@app.get("/metrics")
async def metrics():
    return {
        "database": {
            "total_messages": stats.get("total_messages", 0),
            "user_messages": stats.get("user_messages", 0),
            "assistant_messages": stats.get("assistant_messages", 0)
        },
        "application": {
            "uptime": time.time() - app.state.start_time,
            "version": "2.0.0"
        }
    }
```

## Deployment Architecture

### 1. Container Architecture (from docker-compose.yml)
```yaml
services:
  ollama:
    image: ollama/ollama:latest
    ports: ["11434:11434"]
    volumes: ["ollama_data:/root/.ollama"]
    
  nojs-ai:
    build: .
    ports: ["8000:8000"]
    depends_on: [ollama]
    volumes:
      - ./chat_data:/app/data
      - ./logs:/app/logs
```

### 2. Service Dependencies
```
nojs-ai depends_on ollama
     ↓
FastAPI waits for Ollama health check
     ↓  
Models downloaded via startup.sh
     ↓
Application ready for requests
```

### 3. Volume Management
```
ollama_data: Model storage (~2-8GB per model)
chat_data: SQLite database and user data
logs: Application logs (app.log, error.log, performance.log)
```

This architecture is specifically designed for environments where JavaScript is disabled, using server-side rendering and form-based interactions to provide a complete AI chat experience.