import time
import uuid
from typing import Callable
from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from utils.rate_limiter import check_rate_limit, get_client_ip, record_request_result
from utils.logging_config import log_request, log_error
from config import config
import logging

logger = logging.getLogger(__name__)

class SecurityMiddleware(BaseHTTPMiddleware):
    """Security middleware for request validation and protection"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Add request ID for tracing
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        # Add security headers
        start_time = time.time()

        try:
            # Validate request
            await self._validate_request(request)

            # Process request
            response = await call_next(request)

            # Add security headers to response
            self._add_security_headers(response)

            # Log successful request
            duration = time.time() - start_time
            log_request(
                method=request.method,
                path=str(request.url.path),
                status_code=response.status_code,
                duration=duration,
                request_id=request_id,
                user_agent=request.headers.get('user-agent', 'unknown'),
                ip=get_client_ip(request)
            )

            return response

        except HTTPException as e:
            # Log HTTP exceptions
            duration = time.time() - start_time
            log_request(
                method=request.method,
                path=str(request.url.path),
                status_code=e.status_code,
                duration=duration,
                request_id=request_id,
                error=str(e.detail)
            )
            raise

        except Exception as e:
            # Log unexpected errors
            duration = time.time() - start_time
            log_error(e, {
                'request_id': request_id,
                'method': request.method,
                'path': str(request.url.path),
                'duration': duration
            })

            return JSONResponse(
                status_code=500,
                content={"error": "Internal server error", "request_id": request_id}
            )

    async def _validate_request(self, request: Request):
        """Validate incoming request"""
        # Check content length
        content_length = request.headers.get('content-length')
        if content_length and int(content_length) > config.MAX_REQUEST_SIZE:
            raise HTTPException(status_code=413, detail="Request too large")

        # Check for suspicious headers
        suspicious_headers = ['x-forwarded-host', 'x-forwarded-server']
        for header in suspicious_headers:
            if header in request.headers:
                logger.warning(f"Suspicious header detected: {header}")

        # Validate User-Agent
        user_agent = request.headers.get('user-agent', '')
        if len(user_agent) > 500:
            raise HTTPException(status_code=400, detail="Invalid User-Agent")

        # Check for common attack patterns in URL
        path = str(request.url.path).lower()
        attack_patterns = [
            '../', '..\\', '/etc/', '/proc/', '/sys/',
            'script>', '<iframe', 'javascript:', 'vbscript:'
        ]

        for pattern in attack_patterns:
            if pattern in path:
                logger.warning(f"Potential attack pattern detected: {pattern}")
                raise HTTPException(status_code=400, detail="Invalid request")

    def _add_security_headers(self, response: Response):
        """Add security headers to response"""
        security_headers = {
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY',
            'X-XSS-Protection': '1; mode=block',
            'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
            'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:;",
            'Referrer-Policy': 'strict-origin-when-cross-origin',
            'Permissions-Policy': 'geolocation=(), microphone=(), camera=()'
        }

        for header, value in security_headers.items():
            response.headers[header] = value

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip rate limiting for health checks and static files
        if request.url.path in ['/health', '/metrics'] or request.url.path.startswith('/static'):
            return await call_next(request)

        # Get client IP
        client_ip = get_client_ip(request)

        # Determine endpoint type for specific rate limiting
        endpoint_type = 'general'
        if request.url.path == '/chat':
            endpoint_type = 'ollama'

        # Check rate limit
        rate_limit_info = await check_rate_limit(client_ip, endpoint_type)

        if not rate_limit_info.allowed:
            # Add rate limit headers
            headers = {
                'X-RateLimit-Limit': str(config.RATE_LIMIT_REQUESTS_PER_MINUTE),
                'X-RateLimit-Remaining': str(rate_limit_info.remaining),
                'X-RateLimit-Reset': str(int(rate_limit_info.reset_time)),
            }

            if rate_limit_info.retry_after:
                headers['Retry-After'] = str(int(rate_limit_info.retry_after))

            logger.warning(f"Rate limit exceeded for IP: {client_ip}")

            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "retry_after": rate_limit_info.retry_after
                },
                headers=headers
            )

        # Process request
        start_time = time.time()
        try:
            response = await call_next(request)

            # Record successful request
            await record_request_result(True, endpoint_type)

            # Add rate limit headers to successful responses
            response.headers['X-RateLimit-Limit'] = str(config.RATE_LIMIT_REQUESTS_PER_MINUTE)
            response.headers['X-RateLimit-Remaining'] = str(rate_limit_info.remaining)
            response.headers['X-RateLimit-Reset'] = str(int(rate_limit_info.reset_time))

            return response

        except Exception as e:
            # Record failed request
            await record_request_result(False, endpoint_type)
            raise

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Request logging middleware with performance tracking"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()

        # Add request context
        request_id = getattr(request.state, 'request_id', str(uuid.uuid4()))
        client_ip = get_client_ip(request)

        # Log request start
        logger.info(
            f"Request started: {request.method} {request.url.path}",
            extra={
                'request_id': request_id,
                'method': request.method,
                'path': str(request.url.path),
                'ip': client_ip,
                'user_agent': request.headers.get('user-agent', 'unknown')
            }
        )

        try:
            response = await call_next(request)
            duration = time.time() - start_time

            # Log request completion
            logger.info(
                f"Request completed: {request.method} {request.url.path} - {response.status_code} ({duration:.3f}s)",
                extra={
                    'request_id': request_id,
                    'method': request.method,
                    'path': str(request.url.path),
                    'status_code': response.status_code,
                    'duration': duration,
                    'ip': client_ip
                }
            )

            # Add request ID to response headers
            response.headers['X-Request-ID'] = request_id

            return response

        except Exception as e:
            duration = time.time() - start_time

            # Log request error
            logger.error(
                f"Request failed: {request.method} {request.url.path} - {str(e)} ({duration:.3f}s)",
                extra={
                    'request_id': request_id,
                    'method': request.method,
                    'path': str(request.url.path),
                    'duration': duration,
                    'ip': client_ip,
                    'error': str(e)
                },
                exc_info=e
            )

            raise

class CORSMiddleware(BaseHTTPMiddleware):
    """CORS middleware for cross-origin requests"""

    def __init__(self, app, allow_origins=None, allow_methods=None, allow_headers=None):
        super().__init__(app)
        self.allow_origins = allow_origins or ['*']
        self.allow_methods = allow_methods or ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS']
        self.allow_headers = allow_headers or ['*']

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Handle preflight requests
        if request.method == 'OPTIONS':
            response = Response()
            self._add_cors_headers(response, request)
            return response

        # Process request
        response = await call_next(request)
        self._add_cors_headers(response, request)
        return response

    def _add_cors_headers(self, response: Response, request: Request):
        """Add CORS headers to response"""
        origin = request.headers.get('origin')

        if '*' in self.allow_origins or (origin and origin in self.allow_origins):
            response.headers['Access-Control-Allow-Origin'] = origin or '*'

        response.headers['Access-Control-Allow-Methods'] = ', '.join(self.allow_methods)
        response.headers['Access-Control-Allow-Headers'] = ', '.join(self.allow_headers)
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Max-Age'] = '86400'  # 24 hours