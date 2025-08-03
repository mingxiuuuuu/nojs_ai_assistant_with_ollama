import logging
import logging.handlers
import json
import sys
from datetime import datetime
from typing import Dict, Any
from pathlib import Path
from config import config
import pytz

class StructuredFormatter(logging.Formatter):
    """Custom formatter for structured logging"""

    def format(self, record: logging.LogRecord) -> str:
        # Get timezone from config
        tz = pytz.timezone(config.TIMEZONE)
        # Convert UTC time to configured timezone
        local_time = datetime.utcnow().replace(tzinfo=pytz.UTC).astimezone(tz)
        
        log_entry = {
            'timestamp': local_time.isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }

        # Add extra fields if present
        if hasattr(record, 'user_id'):
            log_entry['user_id'] = record.user_id
        if hasattr(record, 'request_id'):
            log_entry['request_id'] = record.request_id
        if hasattr(record, 'model'):
            log_entry['model'] = record.model
        if hasattr(record, 'response_time'):
            log_entry['response_time'] = record.response_time
        if hasattr(record, 'error_type'):
            log_entry['error_type'] = record.error_type

        # Add exception info if present
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False)

class RequestContextFilter(logging.Filter):
    """Filter to add request context to log records"""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, 'request_id'):
            record.request_id = 'unknown'
        if not hasattr(record, 'user_id'):
            record.user_id = 'anonymous'
        return True

def setup_logging():
    """Setup comprehensive logging configuration"""

    # Create logs directory if it doesn't exist
    log_dir = Path('logs')
    log_dir.mkdir(exist_ok=True)

    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, config.LOG_LEVEL.upper()))

    # Clear existing handlers
    root_logger.handlers.clear()

    # Console handler with colored output
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)

    if config.DEBUG:
        # Use simple format for development with timezone
        tz = pytz.timezone(config.TIMEZONE)
        console_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        # Override formatTime to use configured timezone
        def formatTime(self, record, datefmt=None):
            ct = datetime.fromtimestamp(record.created, tz=tz)
            if datefmt:
                s = ct.strftime(datefmt)
            else:
                s = ct.isoformat()
            return s
        console_formatter.formatTime = formatTime.__get__(console_formatter, logging.Formatter)
    else:
        # Use structured format for production
        console_formatter = StructuredFormatter()

    console_handler.setFormatter(console_formatter)
    console_handler.addFilter(RequestContextFilter())
    root_logger.addHandler(console_handler)

    # File handler for application logs
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / 'app.log',
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(StructuredFormatter())
    file_handler.addFilter(RequestContextFilter())
    root_logger.addHandler(file_handler)

    # Error file handler
    error_handler = logging.handlers.RotatingFileHandler(
        log_dir / 'error.log',
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(StructuredFormatter())
    error_handler.addFilter(RequestContextFilter())
    root_logger.addHandler(error_handler)

    # Performance log handler
    perf_handler = logging.handlers.RotatingFileHandler(
        log_dir / 'performance.log',
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=3
    )
    perf_handler.setLevel(logging.INFO)
    perf_handler.setFormatter(StructuredFormatter())

    # Create performance logger
    perf_logger = logging.getLogger('performance')
    perf_logger.addHandler(perf_handler)
    perf_logger.propagate = False

    # Suppress noisy third-party loggers
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('aiohttp').setLevel(logging.WARNING)
    logging.getLogger('asyncio').setLevel(logging.WARNING)

    logging.info("Logging configuration initialized")

def get_logger(name: str) -> logging.Logger:
    """Get a logger with the specified name"""
    return logging.getLogger(name)

def log_performance(operation: str, duration: float, **kwargs):
    """Log performance metrics"""
    perf_logger = logging.getLogger('performance')
    extra = {
        'operation': operation,
        'duration': duration,
        **kwargs
    }
    perf_logger.info(f"Performance: {operation} took {duration:.3f}s", extra=extra)

def log_request(method: str, path: str, status_code: int, duration: float, **kwargs):
    """Log HTTP request details"""
    logger = logging.getLogger('requests')
    extra = {
        'method': method,
        'path': path,
        'status_code': status_code,
        'duration': duration,
        **kwargs
    }
    logger.info(f"{method} {path} - {status_code} ({duration:.3f}s)", extra=extra)

def log_error(error: Exception, context: Dict[str, Any] = None):
    """Log error with context"""
    logger = logging.getLogger('errors')
    extra = {
        'error_type': type(error).__name__,
        'error_message': str(error),
        **(context or {})
    }
    logger.error(f"Error occurred: {str(error)}", exc_info=error, extra=extra)