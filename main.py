import asyncio
import time
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, Request, Form, HTTPException, Depends, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
import markdown

from config import config
from services.ollama_service import OllamaService
from services.database_service import DatabaseService
from utils.timezone_utils import now_local, get_local_timestamp

settings = config
from middleware.security import SecurityMiddleware, RateLimitMiddleware, RequestLoggingMiddleware
from utils.logging_config import setup_logging, get_logger, log_performance
from utils.validators import ChatRequest, validate_environment_config
from utils.rate_limiter import get_client_ip
import logging

# ─────────────────────────────
# Application Lifecycle
# ─────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    setup_logging()
    logger = get_logger(__name__)

    # Validate configuration
    config_issues = validate_environment_config()
    if config_issues:
        logger.error(f"Configuration issues found: {config_issues}")
        for issue in config_issues:
            logger.error(f"  - {issue}")

    # Initialize services
    logger.info("Initializing services...")

    # Initialize database
    try:
        await app.state.db_service.initialize()
        logger.info("Database service initialized")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise

    # Initialize Ollama service
    try:
        await app.state.ollama_service.initialize()
        logger.info("Ollama service initialized")
    except Exception as e:
        logger.warning(f"Ollama service initialization failed: {e}")

    logger.info("Application startup complete")

    yield

    # Shutdown
    logger.info("Application shutdown initiated")

    # Cleanup services
    if hasattr(app.state, 'db_service'):
        await app.state.db_service.close()
        logger.info("Database service closed")

    if hasattr(app.state, 'ollama_service'):
        await app.state.ollama_service.close()
        logger.info("Ollama service closed")

    logger.info("Application shutdown complete")

# ─────────────────────────────
# FastAPI Application Setup
# ─────────────────────────────
app = FastAPI(
    title="No-JS AI Assistant",
    description="A secure, offline-first AI assistant powered by Ollama",
    version="2.0.0",
    lifespan=lifespan
)

# Initialize services
app.state.ollama_service = OllamaService(
    base_url=config.OLLAMA_URL,
    timeout=config.OLLAMA_TIMEOUT
)
app.state.db_service = DatabaseService()

# Add middleware (order matters - last added is executed first)
app.add_middleware(SecurityMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestLoggingMiddleware)

# Templates
templates = Jinja2Templates(directory="app/templates")

# Logger
logger = get_logger(__name__)

# ─────────────────────────────
# Dependency Injection
# ─────────────────────────────
def get_ollama_service(request: Request) -> OllamaService:
    """Get Ollama service instance"""
    return request.app.state.ollama_service

def get_database_service(request: Request) -> DatabaseService:
    """Get database service instance"""
    return request.app.state.db_service

async def generate_service_status_message(ollama_service: OllamaService) -> str:
    """Generate helpful message about Ollama service status"""
    is_healthy = await ollama_service.check_health()
    if is_healthy:
        models = await ollama_service.get_models()
        if models:
            model_list = ', '.join(models[:3])
            suffix = '...' if len(models) > 3 else ''
            return f"✅ Ollama is running! Available models: {model_list}{suffix}"
        else:
            return "✅ Ollama is running! No models installed yet."
    else:
        return """❌ Ollama service is not running. To fix this:

1. Install Ollama from https://ollama.ai
2. Open terminal and run: ollama serve
3. Download a model: ollama pull mistral
4. Refresh this page
"""

# ─────────────────────────────
# Utility Functions
# ─────────────────────────────
def process_messages_for_display(messages):
    """Process messages to convert markdown to HTML for display"""
    processed_messages = []
    for message in messages:
        processed_message = message.copy()
        if message['role'] == 'assistant':
            # Debug: Log original content
            logger.debug(f"Original content: {repr(message['content'][:200])}")

            # Convert markdown to HTML for assistant messages
            html_content = markdown.markdown(
                message['content'],
                extensions=['extra', 'codehilite']
            )
            
            # Debug: Log converted HTML
            logger.debug(f"Converted HTML: {repr(html_content[:200])}")

            processed_message['content'] = html_content
        processed_messages.append(processed_message)
    return processed_messages

# ─────────────────────────────
# Background Task Functions
# ─────────────────────────────
async def generate_ai_response_background(
    session_id: int,
    message: str,
    model: str,
    ollama_service: OllamaService,
    db_service: DatabaseService,
    client_ip: str
):
    """Generate AI response in background task"""
    start_time = time.time()
    
    try:
        logger.info(f"Starting background AI response generation for session {session_id}")
        
        # Check if this is the first user message in the session
        should_generate_title = False
        try:
            current_session = await db_service.get_session(session_id)
            if current_session:
                message_count = current_session.get('message_count', 0)
                if message_count <= 1:  # User message was just saved, so count is 1
                    should_generate_title = True
        except Exception as e:
            logger.warning(f"Error checking session for title generation: {e}")

        # Generate title if needed
        if should_generate_title:
            try:
                title_start_time = time.time()
                title_prompt = f"""
Analyze this conversation starter and create a concise title (3-5 words):
"{message[:200]}"

Return only the title, nothing else.
"""
                generated_title = await ollama_service.generate_response(
                    model=model,
                    prompt=title_prompt
                )
                title_duration = time.time() - title_start_time
                
                # Log title generation performance
                log_performance(
                    operation="title_generation",
                    duration=title_duration,
                    model=model,
                    message_preview=message[:50]
                )
                
                clean_title = generated_title.strip().strip('"').strip("'").strip()
                
                if clean_title and len(clean_title.split()) >= 3:
                    await db_service.update_session_title(session_id, clean_title)
            except Exception as e:
                logger.warning(f"Title generation failed: {e}")

        # Get conversation context
        context_start_time = time.time()
        context_messages = await db_service.get_conversation_history(session_id, limit=10)
        context_duration = time.time() - context_start_time
        
        # Log context retrieval performance if it takes too long
        if context_duration > config.PERFORMANCE_LOG_THRESHOLD:
            log_performance(
                operation="db_get_conversation_history",
                duration=context_duration,
                session_id=session_id,
                message_count=len(context_messages)
            )
        
        # Generate AI response
        ai_response_start_time = time.time()
        reply = await ollama_service.generate_response(
            model=model,
            prompt=message,
            context=context_messages[:-1] if context_messages else []
        )
        ai_response_duration = time.time() - ai_response_start_time
        
        # Log AI response generation performance
        if ai_response_duration > config.PERFORMANCE_LOG_THRESHOLD:
            log_performance(
                operation="ollama_generate_response",
                duration=ai_response_duration,
                model=model,
                message_length=len(message),
                context_size=len(context_messages)
            )

        # Save the AI response
        await db_service.save_message("assistant", reply, session_id, model=model, response_time=time.time() - start_time)
        
        logger.info(
            f"Background AI response completed for session {session_id}: {reply[:100]}...",
            extra={
                'ip': client_ip,
                'model': model,
                'response_time': time.time() - start_time
            }
        )

    except Exception as e:
        logger.error(f"Error in background AI response generation: {e}", exc_info=True)
        
        # Save error message instead
        error_reply = f"⚠️ **Error generating response**: {str(e)}"
        await db_service.save_message("assistant", error_reply, session_id)

@app.post("/chat")
async def chat(
    request: Request,
    message: str = Form(""),
    model: str = Form("mistral"),
    session_id: int = Form(None),
    ollama_service: OllamaService = Depends(get_ollama_service),
    db_service: DatabaseService = Depends(get_database_service)
):
    """Handle chat message submission - TWO STEP APPROACH"""
    request_start = time.time()
    client_ip = get_client_ip(request)

    try:
        # If no session_id provided, create new session
        if session_id is None:
            session_id = await db_service.create_session("New Chat")

        # Validate that we have a message
        actual_message = message.strip()
        if not actual_message:
            return RedirectResponse(f"/chat/{session_id}", status_code=303)

        logger.info(f"User submitted message: {actual_message[:100]}...")

        # Validate input
        chat_request = ChatRequest(message=actual_message, model=model)

        # Check if selected model is available
        try:
            installed_models = await ollama_service.get_models()
            if installed_models:
                model_available = False
                for installed_model in installed_models:
                    if (chat_request.model == installed_model or
                        chat_request.model == installed_model.split(':')[0] or
                        installed_model == f"{chat_request.model}:latest"):
                        model_available = True
                        chat_request.model = installed_model
                        break

                if not model_available:
                    available_models_str = ", ".join(installed_models)
                    reply = f"🚫 **Model '{chat_request.model}' Not Available**\n\nThe selected model is not installed. Available models: {available_models_str}\n\nTo install the model, run: `ollama pull {chat_request.model}`"
                    await db_service.save_message("user", chat_request.message, session_id)
                    await db_service.save_message("assistant", reply, session_id)
                    return RedirectResponse(f"/chat/{session_id}", status_code=303)
        except Exception as e:
            logger.warning(f"Could not validate model availability: {e}")

        # STEP 1: Save user message ONLY and redirect immediately
        await db_service.save_message("user", chat_request.message, session_id)
        
        # STEP 2: Start background AI response generation
        asyncio.create_task(generate_ai_response_background(
            session_id, chat_request.message, chat_request.model, ollama_service, db_service, client_ip
        ))
        
        # Log total chat request performance
        total_duration = time.time() - request_start
        log_performance(
            operation="chat_request_total",
            duration=total_duration,
            model=chat_request.model,
            session_id=session_id
        )
        
        # Redirect immediately to show user message (with waiting state)
        return RedirectResponse(f"/chat/{session_id}?waiting=true", status_code=303)

    except ValidationError as e:
        logger.warning(f"Validation error: {e}")
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid input", "details": str(e)}
        )
    except Exception as e:
        logger.error(f"Unexpected error in chat endpoint: {e}", exc_info=True)
        return JSONResponse(
             status_code=500,
             content={"error": "Internal server error"}
         )

async def get_service_status(request: Request = None):
    """Get service status for display"""
    try:
        if request:
            ollama_service = request.app.state.ollama_service
            db_service = request.app.state.db_service
        else:
            # Fallback for when called without request context
            return {
                "ollama": False,
                "database": False
            }

        ollama_status = await ollama_service.check_health()
        db_status = db_service._initialized
        return {
            "ollama": ollama_status,
            "database": db_status
        }
    except Exception as e:
        logger.error(f"Error getting service status: {str(e)}")
        return {
            "ollama": False,
            "database": False
        }

async def get_available_models(request: Request = None):
    """Get available models from Ollama service"""
    from config import config
    
    # Get allowed models from config (in the desired order)
    allowed_models = config.AVAILABLE_MODELS
    
    try:
        if request:
            ollama_service = request.app.state.ollama_service
            installed_models = await ollama_service.get_models()
            if not installed_models:
                return config.FALLBACK_MODELS  # Use fallback from config
            
            # Get installed model base names
            installed_base_names = set()
            for model in installed_models:
                base_name = model.split(':')[0]
                installed_base_names.add(base_name)
            
            # Return models in the order specified in AVAILABLE_MODELS, but only if they're installed
            available_models = []
            for model in allowed_models:
                if model in installed_base_names:
                    available_models.append(model)
            
            # If no allowed models are installed, return fallback
            return available_models if available_models else config.FALLBACK_MODELS
        else:
            return config.FALLBACK_MODELS  # Use fallback from config
    except Exception as e:
        logger.error(f"Error getting models: {str(e)}")
        return config.FALLBACK_MODELS  # Use fallback from config

# ─────────────────────────────
# Session Management Routes
# ─────────────────────────────

@app.post("/sessions/new")
async def create_new_session(
    request: Request,
    title: str = Form("New Chat"),
    db_service: DatabaseService = Depends(get_database_service)
):
    """Create a new chat session"""
    try:
        session_id = await db_service.create_session(title)
        return RedirectResponse(url=f"/chat/{session_id}", status_code=302)
    except Exception as e:
        logger.error(f"Error creating new session: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/sessions/{session_id}/title")
async def update_session_title(
    session_id: int,
    title: str = Form(...),
    db_service: DatabaseService = Depends(get_database_service)
):
    """Update session title"""
    try:
        success = await db_service.update_session_title(session_id, title)
        if success:
            return RedirectResponse(url=f"/chat/{session_id}", status_code=302)
        else:
            return JSONResponse({"error": "Failed to update title"}, status_code=500)
    except Exception as e:
        logger.error(f"Error updating session title: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/sessions/{session_id}/delete")
async def delete_session(
    session_id: int,
    db_service: DatabaseService = Depends(get_database_service)
):
    """Delete a chat session"""
    try:
        success = await db_service.delete_session(session_id)
        if success:
            return RedirectResponse(url="/", status_code=302)
        else:
            return JSONResponse({"error": "Failed to delete session"}, status_code=500)
    except Exception as e:
        logger.error(f"Error deleting session: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/sessions")
async def get_sessions_api(
    db_service: DatabaseService = Depends(get_database_service)
):
    """Get all sessions as JSON"""
    try:
        sessions = await db_service.get_sessions()
        return JSONResponse({"sessions": sessions})
    except Exception as e:
        logger.error(f"Error getting sessions: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)

# ─────────────────────────────
# API Routes
# ─────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Main chat interface - redirect to latest session or create new one"""
    try:
        db_service = request.app.state.db_service
        # Get latest session or create new one
        sessions = await db_service.get_sessions(limit=1)
        if sessions:
            session_id = sessions[0]['id']
        else:
            session_id = await db_service.create_session("New Chat")

        # Redirect to session-specific URL
        return RedirectResponse(url=f"/chat/{session_id}", status_code=302)
    except Exception as e:
        logger.error(f"Error in root endpoint: {str(e)}")
        # Fallback to basic interface
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "messages": [],
                "models": [],
                "sessions": [],
                "current_session": None,
                "service_status": {"ollama": False, "database": False},
                "error": str(e)
            }
        )

@app.get("/chat/{session_id}", response_class=HTMLResponse)
async def chat_session(request: Request, session_id: int, waiting: bool = Query(False)):
    """Chat interface for specific session"""
    try:
        db_service = request.app.state.db_service
        
        # Get current session
        current_session = await db_service.get_session(session_id)
        if not current_session:
            # Session doesn't exist, create new one
            session_id = await db_service.create_session("New Chat")
            return RedirectResponse(url=f"/chat/{session_id}", status_code=302)

        # Get conversation history for this session
        messages = await db_service.get_conversation_history(session_id)

        # Process messages for markdown display
        processed_messages = process_messages_for_display(messages)

        # Get all sessions for sidebar
        sessions = await db_service.get_sessions()

        # Get available models
        models = await get_available_models(request)

        # Determine if we should show waiting state
        is_waiting = waiting
        auto_refresh = waiting  # Auto-refresh when waiting
        
        # If waiting=true, check if AI response has been generated
        if waiting and messages:
            last_message = messages[-1]
            # If last message is from assistant, AI response is ready
            if last_message['role'] == 'assistant':
                is_waiting = False
                auto_refresh = False
                # Redirect to remove waiting parameter
                return RedirectResponse(f"/chat/{session_id}", status_code=302)

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "messages": processed_messages,
                "models": models,
                "sessions": sessions,
                "current_session": current_session,
                "service_status": await get_service_status(request),
                "is_waiting": is_waiting,
                "auto_refresh": auto_refresh
            }
        )
    except Exception as e:
        logger.error(f"Error in chat session endpoint: {str(e)}")
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "messages": [],
                "models": [],
                "sessions": [],
                "current_session": None,
                "service_status": {"ollama": False, "database": False},
                "error": str(e),
                "is_waiting": False,
                "auto_refresh": False
            }
        )

@app.post("/chat")
async def chat(
    request: Request,
    message: str = Form(""),
    original_message: str = Form(""),
    model: str = Form("mistral"),
    session_id: int = Form(None),
    no_js: bool = Form(False),
    ollama_service: OllamaService = Depends(get_ollama_service),
    db_service: DatabaseService = Depends(get_database_service)
):
    """Handle chat message submission - SYNCHRONOUS approach"""
    start_time = time.time()
    client_ip = get_client_ip(request)

    try:
        # If no session_id provided, create new session
        if session_id is None:
            session_id = await db_service.create_session("New Chat")

        # Use original_message if available, otherwise use message
        actual_message = original_message.strip() if original_message.strip() else message.strip()

        # Validate that we have a message
        if not actual_message:
            return RedirectResponse(f"/chat/{session_id}", status_code=303)

        # Validate input and model availability
        chat_request = ChatRequest(message=actual_message, model=model)

        # Check if selected model is available
        try:
            installed_models = await ollama_service.get_models()
            if installed_models:
                model_available = False
                for installed_model in installed_models:
                    if (chat_request.model == installed_model or
                        chat_request.model == installed_model.split(':')[0] or
                        installed_model == f"{chat_request.model}:latest"):
                        model_available = True
                        chat_request.model = installed_model
                        break

                if not model_available:
                    available_models_str = ", ".join(installed_models)
                    reply = f"🚫 **Model '{chat_request.model}' Not Available**\n\nThe selected model is not installed. Available models: {available_models_str}\n\nTo install the model, run: `ollama pull {chat_request.model}`"
                    await db_service.save_message("user", chat_request.message, session_id)
                    await db_service.save_message("assistant", reply, session_id)
                    return RedirectResponse(f"/chat/{session_id}", status_code=303)
        except Exception as e:
            logger.warning(f"Could not validate model availability: {e}")

        logger.info(
            f"User submitted message: {chat_request.message[:100]}... (model: {chat_request.model})",
            extra={'ip': client_ip, 'model': chat_request.model}
        )

        # Check if this is the first user message in the session
        should_generate_title = False
        try:
            current_session = await db_service.get_session(session_id)
            if current_session:
                message_count = current_session.get('message_count', 0)
                if message_count == 0:
                    should_generate_title = True
        except Exception as e:
            logger.warning(f"Error checking session for title generation: {e}")

        # Save user message FIRST - this shows immediately
        await db_service.save_message("user", chat_request.message, session_id)
        
        # Now generate the response synchronously (this takes time, but user sees their message)
        try:
            # Generate title if needed
            if should_generate_title:
                try:
                    title_prompt = f"""
Analyze this conversation starter and create a concise title (3-7 words):
"{chat_request.message[:200]}"

Return only the title, nothing else.
"""
                    generated_title = await ollama_service.generate_response(
                        model=chat_request.model,
                        prompt=title_prompt
                    )
                    clean_title = generated_title.strip().strip('"').strip("'").strip()
                    
                    if clean_title and len(clean_title.split()) >= 3:
                        await db_service.update_session_title(session_id, clean_title)
                except Exception as e:
                    logger.warning(f"Title generation failed: {e}")

            # Get conversation context (excluding any "Thinking..." messages)
            context_messages = await db_service.get_conversation_history(session_id, limit=10)
            
            # Generate AI response
            reply = await ollama_service.generate_response(
                model=chat_request.model,
                prompt=chat_request.message,
                context=context_messages[:-1] if context_messages else []
            )

            # Save the actual AI response
            await db_service.save_message("assistant", reply, session_id, model=chat_request.model, response_time=time.time() - start_time)
            
            logger.info(
                f"Assistant reply generated: {reply[:100]}...",
                extra={
                    'ip': client_ip,
                    'model': chat_request.model,
                    'response_time': time.time() - start_time
                }
            )

        except Exception as e:
            logger.error(f"Error generating AI response: {e}", exc_info=True)
            
            # Save error message instead
            error_reply = f"⚠️ **Error generating response**: {str(e)}"
            await db_service.save_message("assistant", error_reply, session_id)
        
        # Simple redirect back to the chat - no special parameters needed
        return RedirectResponse(f"/chat/{session_id}", status_code=303)

    except ValidationError as e:
        logger.warning(f"Validation error: {e}")
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid input", "details": str(e)}
        )
    except Exception as e:
        logger.error(f"Unexpected error in chat endpoint: {e}", exc_info=True)
        return JSONResponse(
             status_code=500,
             content={"error": "Internal server error"}
         )

# ─────────────────────────────
# Health Check and Monitoring
# ─────────────────────────────
@app.get("/health")
async def health_check(
    ollama_service: OllamaService = Depends(get_ollama_service),
    db_service: DatabaseService = Depends(get_database_service)
):
    """Health check endpoint for monitoring"""
    start_time = time.time()

    health_status = {
        "status": "healthy",
        "timestamp": get_local_timestamp(),
        "version": "2.0.0",
        "services": {}
    }

    # Check database health
    try:
        db_healthy = await db_service.health_check()
        health_status["services"]["database"] = {
            "status": "healthy" if db_healthy else "unhealthy",
            "response_time": time.time() - start_time
        }
    except Exception as e:
        health_status["services"]["database"] = {
            "status": "unhealthy",
            "error": str(e),
            "response_time": time.time() - start_time
        }
        health_status["status"] = "degraded"

    # Check Ollama health
    ollama_start = time.time()
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
            "error": str(e),
            "response_time": time.time() - ollama_start
        }
        health_status["status"] = "degraded"

    # Overall health check
    if health_status["status"] == "degraded":
        return JSONResponse(status_code=503, content=health_status)

    return health_status

@app.get("/metrics")
async def metrics(
    db_service: DatabaseService = Depends(get_database_service)
):
    """Application metrics endpoint"""
    try:
        stats = await db_service.get_stats()

        metrics_data = {
            "timestamp": get_local_timestamp(),
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

        return metrics_data

    except Exception as e:
        logger.error(f"Error getting metrics: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": "Failed to retrieve metrics"}
        )

@app.get("/api/models")
async def get_models(
    ollama_service: OllamaService = Depends(get_ollama_service)
):
    """Get available models API endpoint"""
    try:
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

    except Exception as e:
        logger.error(f"Error getting models: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": "Failed to retrieve models"}
        )

# ─────────────────────────────
# Application Entry Point
# ─────────────────────────────
if __name__ == "__main__":
    import uvicorn

    # Store start time for uptime calculation
    app.state.start_time = time.time()

    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        reload=config.DEBUG,
        log_level="info" if not config.DEBUG else "debug"
    )