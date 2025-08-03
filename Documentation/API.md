# API Documentation

## Overview

The No-JS AI Assistant uses **form-based HTTP communication** instead of traditional REST APIs. All interactions happen through HTML forms and server-side rendering, making it compatible with JavaScript-disabled environments.

## API Architecture

### Communication Pattern
```
HTML Form → POST Request → FastAPI Handler → Template Response → HTML Page
```

Unlike typical APIs that return JSON, this application returns rendered HTML templates.

## Core Endpoints

### 1. Chat Interface

#### `GET /`
**Purpose**: Main entry point - redirects to latest session or creates new one

**Implementation** (from main.py):
```python
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    try:
        db_service = request.app.state.db_service
        sessions = await db_service.get_sessions(limit=1)
        if sessions:
            session_id = sessions[0]['id']
        else:
            session_id = await db_service.create_session("New Chat")
        return RedirectResponse(url=f"/chat/{session_id}", status_code=302)
    except Exception as e:
        # Fallback to basic interface
        return templates.TemplateResponse("index.html", {...})
```

**Response**: `302 Redirect` to `/chat/{session_id}`

#### `GET /chat/{session_id}`
**Purpose**: Display specific chat session

**Parameters**:
- `session_id` (path): Integer session identifier
- `waiting` (query, optional): Boolean to show waiting state

**Implementation** (from main.py):
```python
@app.get("/chat/{session_id}", response_class=HTMLResponse)
async def chat_session(request: Request, session_id: int, waiting: bool = Query(False)):
    # Get session and messages
    current_session = await db_service.get_session(session_id)
    messages = await db_service.get_conversation_history(session_id)
    
    # Process for display
    processed_messages = process_messages_for_display(messages)
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "messages": processed_messages,
        "current_session": current_session,
        "is_waiting": waiting,
        "auto_refresh": waiting
    })
```

**Response**: HTML page with chat interface

**Template Variables**:
- `messages`: List of conversation messages
- `models`: Available AI models
- `sessions`: All user sessions
- `current_session`: Active session data
- `is_waiting`: Boolean for waiting state
- `auto_refresh`: Boolean for meta refresh

#### `POST /chat`
**Purpose**: Submit new chat message

**Form Data**:
- `message` (required): User message text
- `model` (required): Selected AI model
- `session_id` (optional): Session ID (creates new if missing)
- `original_message` (optional): Original message content

**Validation** (from validators.py):
```python
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=config.MAX_MESSAGE_LENGTH)
    model: str = Field(..., min_length=1, max_length=100)

    @validator('message')
    def validate_message(cls, v: str) -> str:
        # XSS prevention
        v = html.escape(v)
        return v
```

**Implementation Flow** (from main.py):
```python
@app.post("/chat")
async def chat(...):
    # 1. Create session if needed
    if session_id is None:
        session_id = await db_service.create_session("New Chat")
    
    # 2. Validate input
    chat_request = ChatRequest(message=actual_message, model=model)
    
    # 3. Check model availability
    installed_models = await ollama_service.get_models()
    
    # 4. Save user message
    await db_service.save_message("user", chat_request.message, session_id)
    
    # 5. Generate AI response
    reply = await ollama_service.generate_response(
        model=chat_request.model,
        prompt=chat_request.message,
        context=context_messages[:-1]
    )
    
    # 6. Save AI response
    await db_service.save_message("assistant", reply, session_id, 
                                 model=chat_request.model, 
                                 response_time=time.time() - start_time)
    
    # 7. Redirect to updated conversation
    return RedirectResponse(f"/chat/{session_id}", status_code=303)
```

**Response**: `303 Redirect` to `/chat/{session_id}`

### 2. Session Management

#### `POST /sessions/new`
**Purpose**: Create new chat session

**Form Data**:
- `title` (optional): Session title (defaults to "New Chat")

**Implementation**:
```python
@app.post("/sessions/new")
async def create_new_session(
    request: Request,
    title: str = Form("New Chat"),
    db_service: DatabaseService = Depends(get_database_service)
):
    session_id = await db_service.create_session(title)
    return RedirectResponse(url=f"/chat/{session_id}", status_code=302)
```

**Response**: `302 Redirect` to `/chat/{new_session_id}`

#### `POST /sessions/{session_id}/title`
**Purpose**: Update session title

**Form Data**:
- `title` (required): New session title

**Implementation**:
```python
@app.post("/sessions/{session_id}/title")
async def update_session_title(
    session_id: int,
    title: str = Form(...),
    db_service: DatabaseService = Depends(get_database_service)
):
    success = await db_service.update_session_title(session_id, title)
    if success:
        return RedirectResponse(url=f"/chat/{session_id}", status_code=302)
    else:
        return JSONResponse({"error": "Failed to update title"}, status_code=500)
```

**Response**: `302 Redirect` to `/chat/{session_id}` or `500 JSON Error`

#### `POST /sessions/{session_id}/delete`
**Purpose**: Delete chat session

**Implementation**:
```python
@app.post("/sessions/{session_id}/delete")
async def delete_session(
    session_id: int,
    db_service: DatabaseService = Depends(get_database_service)
):
    success = await db_service.delete_session(session_id)
    if success:
        return RedirectResponse(url="/", status_code=302)
    else:
        return JSONResponse({"error": "Failed to delete session"}, status_code=500)
```

**Response**: `302 Redirect` to `/` or `500 JSON Error`

## JSON API Endpoints

Some endpoints provide JSON responses for programmatic access:

### 1. Session Data

#### `GET /api/sessions`
**Purpose**: Get all sessions as JSON

**Implementation**:
```python
@app.get("/api/sessions")
async def get_sessions_api(
    db_service: DatabaseService = Depends(get_database_service)
):
    sessions = await db_service.get_sessions()
    return JSONResponse({"sessions": sessions})
```

**Response**:
```json
{
  "sessions": [
    {
      "id": 1,
      "title": "Python Development Help",
      "created_at": "2025-01-15T10:30:00",
      "message_count": 12
    },
    {
      "id": 2,
      "title": "Docker Deployment",
      "created_at": "2025-01-15T11:45:00", 
      "message_count": 8
    }
  ]
}
```

### 2. Health and Monitoring

#### `GET /health`
**Purpose**: System health check

**Implementation** (from main.py):
```python
@app.get("/health")
async def health_check(
    ollama_service: OllamaService = Depends(get_ollama_service),
    db_service: DatabaseService = Depends(get_database_service)
):
    health_status = {
        "status": "healthy",
        "timestamp": time.time(),
        "version": "2.0.0",
        "services": {}
    }
    
    # Check database
    try:
        db_healthy = await db_service.health_check()
        health_status["services"]["database"] = {
            "status": "healthy" if db_healthy else "unhealthy",
            "response_time": time.time() - start_time
        }
    except Exception as e:
        health_status["services"]["database"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health_status["status"] = "degraded"
    
    # Check Ollama
    try:
        ollama_healthy = await ollama_service.check_health()
        health_status["services"]["ollama"] = {
            "status": "healthy" if ollama_healthy else "unhealthy",
            "response_time": time.time() - ollama_start
        }
        if ollama_healthy:
            models = await ollama_service.get_models()
            health_status["services"]["ollama"]["models_count"] = len(models)
    except Exception as e:
        health_status["services"]["ollama"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health_status["status"] = "degraded"
```

**Response**:
```json
{
  "status": "healthy",
  "timestamp": 1673123456.789,
  "version": "2.0.0",
  "services": {
    "database": {
      "status": "healthy",
      "response_time": 0.023
    },
    "ollama": {
      "status": "healthy",
      "response_time": 0.156,
      "models_count": 4
    }
  }
}
```

**Status Codes**:
- `200`: All services healthy
- `503`: One or more services degraded

#### `GET /metrics`
**Purpose**: Application usage metrics

**Implementation**:
```python
@app.get("/metrics")
async def metrics(
    db_service: DatabaseService = Depends(get_database_service)
):
    stats = await db_service.get_stats()
    return {
        "timestamp": time.time(),
        "database": {
            "total_messages": stats.get("total_messages", 0),
            "user_messages": stats.get("user_messages", 0),
            "assistant_messages": stats.get("assistant_messages", 0),
            "messages_today": stats.get("messages_today", 0)
        },
        "application": {
            "uptime": time.time() - getattr(app.state, 'start_time', time.time()),
            "version": "2.0.0"
        }
    }
```

**Response**:
```json
{
  "timestamp": 1673123456.789,
  "database": {
    "total_messages": 15420,
    "user_messages": 7710,
    "assistant_messages": 7710,
    "messages_today": 234
  },
  "application": {
    "uptime": 86400.5,
    "version": "2.0.0"
  }
}
```

#### `GET /api/models`
**Purpose**: Get available AI models

**Implementation**:
```python
@app.get("/api/models")
async def get_models(
    ollama_service: OllamaService = Depends(get_ollama_service)
):
    is_healthy = await ollama_service.check_health()
    if not is_healthy:
        return JSONResponse(
            status_code=503,
            content={"error": "Ollama service not available"}
        )

    installed_models = await ollama_service.get_models()
    popular_models = ollama_service.get_popular_models()

    return {
        "installed_models": installed_models,
        "popular_models": popular_models,
        "ollama_healthy": is_healthy
    }
```

**Response**:
```json
{
  "installed_models": ["mistral", "llama3.2", "phi3", "tinyllama"],
  "popular_models": ["mistral", "llama3", "codellama", "phi3"],
  "ollama_healthy": true
}
```

## Form Examples

### 1. Chat Message Form (from index.html)

```html
<form method="post" action="/chat" class="chat-form">
    <!-- Hidden session ID -->
    {% if current_session %}
    <input type="hidden" name="session_id" value="{{ current_session.id }}">
    {% endif %}
    
    <!-- Model selection -->
    <select name="model" class="model-select">
        {% for model in models %}
        <option value="{{ model }}">{{ model.title() }}</option>
        {% endfor %}
    </select>
    
    <!-- Message input -->
    <input type="text" name="message" placeholder="Type message..." required>
    
    <!-- Submit button -->
    <button type="submit">Send</button>
</form>
```

### 2. New Session Form

```html
<form action="/sessions/new" method="post">
    <button type="submit" class="new-chat-btn">+ New Chat</button>
</form>
```

### 3. Title Update Form

```html
<form action="/sessions/{{ session.id }}/title" method="post">
    <input type="text" name="title" value="{{ session.title }}" required>
    <button type="submit">Update Title</button>
</form>
```

### 4. Session Delete Form

```html
<form action="/sessions/{{ session.id }}/delete" method="post">
    <button type="submit" onclick="return confirm('Delete this chat?')">
        Delete
    </button>
</form>
```

## Message Processing Pipeline

### 1. Input Processing (from main.py)

```python
def process_messages_for_display(messages):
    """Process messages to convert markdown to HTML for display"""
    processed_messages = []
    for message in messages:
        processed_message = message.copy()
        if message['role'] == 'assistant':
            # Convert markdown to HTML for assistant messages
            html_content = markdown.markdown(
                message['content'],
                extensions=['extra', 'codehilite']
            )
            processed_message['content'] = html_content
        processed_messages.append(processed_message)
    return processed_messages
```

### 2. Context Building

```python
# Get last 10 messages for context
context_messages = await db_service.get_conversation_history(session_id, limit=10)

# Format for Ollama API (exclude current message)
formatted_context = context_messages[:-1] if context_messages else []
```

### 3. AI Response Generation

```python
# Send to Ollama with context
reply = await ollama_service.generate_response(
    model=chat_request.model,
    prompt=chat_request.message,
    context=formatted_context
)
```

## Error Handling

### Error Response Format

**Validation Errors**:
```python
except ValidationError as e:
    return JSONResponse(
        status_code=400,
        content={"error": "Invalid input", "details": str(e)}
    )
```

**Server Errors**:
```python
except Exception as e:
    logger.error(f"Unexpected error: {e}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"}
    )
```

**Template Error Handling**:
```python
# Show error in template instead of JSON
return templates.TemplateResponse(
    "index.html",
    {
        "request": request,
        "error": str(e),
        "messages": [],
        "sessions": []
    }
)
```

## Rate Limiting

All endpoints are subject to rate limiting (from config.py):

- **General requests**: 60 per minute per IP
- **AI chat requests**: 10 per minute per IP
- **Global limit**: Token bucket system

Rate limit headers:
- `X-RateLimit-Remaining`: Requests remaining
- `X-RateLimit-Reset`: Reset timestamp
- `Retry-After`: Seconds to wait (when limited)

## Static File Serving

```python
# Mount static files if directory exists
if os.path.exists("app/static"):
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
```

**Available at**: `/static/*` (CSS, images, etc.)

## Dependency Injection

The application uses FastAPI's dependency injection:

```python
def get_ollama_service(request: Request) -> OllamaService:
    return request.app.state.ollama_service

def get_database_service(request: Request) -> DatabaseService:
    return request.app.state.db_service

# Used in routes
async def chat(
    ollama_service: OllamaService = Depends(get_ollama_service),
    db_service: DatabaseService = Depends(get_database_service)
):
```

This ensures proper service lifecycle management and makes testing easier.