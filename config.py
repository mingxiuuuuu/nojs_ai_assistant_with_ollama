"""Configuration management for the AI Assistant application.

This module provides centralized configuration management with environment variable support,
validation, and type safety. It handles all application settings including server configuration,
Ollama integration, database settings, security parameters, and logging configuration.
"""

import os
from typing import Optional, List, Dict
from pydantic import validator, Field
from pydantic_settings import BaseSettings
from pathlib import Path


class Config(BaseSettings):
    """Application configuration with environment variable support and validation."""

    # ─────────────────────────────
    # Application Settings
    # ─────────────────────────────
    APP_NAME: str = Field(default="AI Assistant", description="Application name")
    VERSION: str = Field(default="2.0.0", description="Application version")
    DEBUG: bool = Field(default=False, description="Enable debug mode")
    ENVIRONMENT: str = Field(default="development", description="Environment (development/production)")

    # ─────────────────────────────
    # Server Configuration
    # ─────────────────────────────
    HOST: str = Field(default="127.0.0.1", description="Server host")
    PORT: int = Field(default=8000, description="Server port")
    WORKERS: int = Field(default=1, description="Number of worker processes")

    # ─────────────────────────────
    # Ollama Configuration
    # ─────────────────────────────
    OLLAMA_URL: str = Field(default="http://127.0.0.1:11434", description="Ollama service URL")
    OLLAMA_TIMEOUT: int = Field(default=120, description="Ollama request timeout in seconds")
    OLLAMA_MAX_RETRIES: int = Field(default=3, description="Maximum retry attempts for Ollama requests")
    OLLAMA_RETRY_DELAY: float = Field(default=1.0, description="Delay between retries in seconds")
    OLLAMA_CIRCUIT_BREAKER_THRESHOLD: int = Field(default=5, description="Circuit breaker failure threshold")
    OLLAMA_CIRCUIT_BREAKER_TIMEOUT: int = Field(default=60, description="Circuit breaker timeout in seconds")
    OLLAMA_MODEL_CACHE_TTL: int = Field(default=300, description="Model cache TTL in seconds")

    # Model Configuration
    DEFAULT_MODEL: str = Field(default="llama3", description="Default model to use")
    FALLBACK_MODELS: List[str] = Field(default=["llama3", "mistral"], description="Fallback models list")
    
    # Available models for UI and download (in alphabetical order)
    AVAILABLE_MODELS: List[str] = Field(default=["llama3", "mistral", "phi3", "tinyllama"], 
                                       description="Models available in UI and for download")

    # Model descriptions for UI display
    MODEL_DESCRIPTIONS: Dict[str, str] = Field(default={
        "mistral": "Fast & versatile",
        "llama3": "Meta's flagship",
        "llama3.1": "Advanced reasoning",
        "llama3.2": "Latest Meta model",
        "llama2": "Reliable & stable",
        "codellama": "Programming expert",
        "phi3": "Microsoft's efficient model",
        "gemma2": "Google's latest",
        "qwen2.5": "Alibaba's multilingual",
        "deepseek-coder": "Code specialist",
        "nomic-embed-text": "Text embeddings",
        "all-minilm": "Sentence embeddings",
        "tinyllama": "Lightweight & fast",
        "orca-mini": "Compact reasoning",
        "vicuna": "Conversational AI"
    }, description="Model descriptions for UI display")


    # ─────────────────────────────
    # Database Configuration
    # ─────────────────────────────
    DB_PATH: Optional[str] = Field(default=None, description="Override database file path")
    DATABASE_URL: str = Field(default="sqlite:///./chat_history.db", description="Database connection URL")
    DATABASE_POOL_SIZE: int = Field(default=10, description="Database connection pool size")
    DATABASE_MAX_OVERFLOW: int = Field(default=20, description="Database max overflow connections")
    DATABASE_POOL_TIMEOUT: int = Field(default=30, description="Database pool timeout in seconds")
    DATABASE_CLEANUP_DAYS: int = Field(default=30, description="Days to keep old messages")

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

    # ─────────────────────────────
    # Security Configuration
    # ─────────────────────────────
    SECRET_KEY: str = Field(default="your-secret-key-change-in-production", description="Application secret key")
    ALLOWED_HOSTS: List[str] = Field(default=["localhost", "127.0.0.1"], description="Allowed hosts")
    CORS_ORIGINS: List[str] = Field(default=["http://localhost:8000"], description="CORS allowed origins")
    CORS_METHODS: List[str] = Field(default=["GET", "POST"], description="CORS allowed methods")
    CORS_HEADERS: List[str] = Field(default=["*"], description="CORS allowed headers")

    # Security limits
    MAX_REQUEST_SIZE: int = Field(default=1024 * 1024, description="Maximum request size in bytes (1MB)")
    MAX_MESSAGE_LENGTH: int = Field(default=10000, description="Maximum message length")
    MAX_FILENAME_LENGTH: int = Field(default=255, description="Maximum filename length")

    # ─────────────────────────────
    # Rate Limiting Configuration
    # ─────────────────────────────
    RATE_LIMIT_ENABLED: bool = Field(default=True, description="Enable rate limiting")
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = Field(default=60, description="General requests per minute")
    RATE_LIMIT_BURST_SIZE: int = Field(default=10, description="Burst size for rate limiting")

    # Ollama-specific rate limits
    OLLAMA_RATE_LIMIT_REQUESTS_PER_MINUTE: int = Field(default=10, description="Ollama requests per minute")
    OLLAMA_RATE_LIMIT_BURST_SIZE: int = Field(default=3, description="Ollama burst size")

    # Adaptive rate limiting
    ADAPTIVE_RATE_LIMIT_ENABLED: bool = Field(default=True, description="Enable adaptive rate limiting")
    ADAPTIVE_RATE_LIMIT_MIN_REQUESTS: int = Field(default=5, description="Minimum requests per minute")
    ADAPTIVE_RATE_LIMIT_MAX_REQUESTS: int = Field(default=20, description="Maximum requests per minute")

    # ─────────────────────────────
    # Timezone Configuration
    # ─────────────────────────────
    TIMEZONE: str = Field(default="Asia/Singapore", description="Application timezone")

    # ─────────────────────────────
    # Logging Configuration
    # ─────────────────────────────
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")
    LOG_FORMAT: str = Field(default="structured", description="Log format (structured/simple)")
    LOG_FILE_ENABLED: bool = Field(default=True, description="Enable file logging")
    LOG_FILE_PATH: str = Field(default="logs", description="Log file directory")
    LOG_FILE_MAX_SIZE: int = Field(default=10 * 1024 * 1024, description="Max log file size in bytes (10MB)")
    LOG_FILE_BACKUP_COUNT: int = Field(default=5, description="Number of log file backups")
    LOG_ROTATION_ENABLED: bool = Field(default=True, description="Enable log rotation")

    # Performance logging
    PERFORMANCE_LOG_ENABLED: bool = Field(default=True, description="Enable performance logging")
    PERFORMANCE_LOG_THRESHOLD: float = Field(default=1.0, description="Performance log threshold in seconds")

    # ─────────────────────────────
    # Monitoring Configuration
    # ─────────────────────────────
    HEALTH_CHECK_ENABLED: bool = Field(default=True, description="Enable health check endpoint")
    METRICS_ENABLED: bool = Field(default=True, description="Enable metrics endpoint")
    MONITORING_TOKEN: Optional[str] = Field(default=None, description="Token for monitoring endpoints")

    # ─────────────────────────────
    # Feature Flags
    # ─────────────────────────────
    ENABLE_REQUEST_LOGGING: bool = Field(default=True, description="Enable request logging middleware")
    ENABLE_SECURITY_MIDDLEWARE: bool = Field(default=True, description="Enable security middleware")
    ENABLE_CORS_MIDDLEWARE: bool = Field(default=True, description="Enable CORS middleware")
    ENABLE_COMPRESSION: bool = Field(default=True, description="Enable response compression")

    # pydantic prioritise .env file over hard coded values, can include a .env file next time with secret key as well
    class Config: 
        """Pydantic configuration."""
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True

    # ─────────────────────────────
    # Validators
    # ─────────────────────────────
    @validator("PORT")
    def validate_port(cls, v):
        """Validate port number."""
        if not 1 <= v <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return v

    @validator("OLLAMA_TIMEOUT")
    def validate_ollama_timeout(cls, v):
        """Validate Ollama timeout."""
        if v <= 0:
            raise ValueError("Ollama timeout must be positive")
        return v

    @validator("OLLAMA_MAX_RETRIES")
    def validate_ollama_retries(cls, v):
        """Validate Ollama retry count."""
        if v < 0:
            raise ValueError("Ollama max retries must be non-negative")
        return v

    @validator("LOG_LEVEL")
    def validate_log_level(cls, v):
        """Validate log level."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of: {valid_levels}")
        return v.upper()

    @validator("ENVIRONMENT")
    def validate_environment(cls, v):
        """Validate environment."""
        valid_envs = ["development", "staging", "production"]
        if v.lower() not in valid_envs:
            raise ValueError(f"Environment must be one of: {valid_envs}")
        return v.lower()

    @validator("MAX_REQUEST_SIZE")
    def validate_max_request_size(cls, v):
        """Validate maximum request size."""
        if v <= 0:
            raise ValueError("Max request size must be positive")
        return v

    @validator("RATE_LIMIT_REQUESTS_PER_MINUTE")
    def validate_rate_limit(cls, v):
        """Validate rate limit."""
        if v <= 0:
            raise ValueError("Rate limit must be positive")
        return v

    # ─────────────────────────────
    # Computed Properties
    # ─────────────────────────────
    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.ENVIRONMENT == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.ENVIRONMENT == "development"

    @property
    def log_file_directory(self) -> Path:
        """Get log file directory path."""
        return Path(self.LOG_FILE_PATH)

    @property
    def database_file_path(self) -> Optional[Path]:
        """Get database file path for SQLite databases."""
        if self.DATABASE_URL.startswith("sqlite"):
            # Extract file path from SQLite URL
            file_path = self.DATABASE_URL.replace("sqlite:///", "")
            return Path(file_path)
        return None

    # ─────────────────────────────
    # Utility Methods
    # ─────────────────────────────
    def create_directories(self) -> None:
        """Create necessary directories."""
        # Create log directory
        if self.LOG_FILE_ENABLED:
            self.log_file_directory.mkdir(parents=True, exist_ok=True)

        # Create database directory for SQLite
        if self.database_file_path:
            self.database_file_path.parent.mkdir(parents=True, exist_ok=True)

    def get_cors_config(self) -> dict:
        """Get CORS configuration."""
        return {
            "allow_origins": self.CORS_ORIGINS,
            "allow_methods": self.CORS_METHODS,
            "allow_headers": self.CORS_HEADERS,
            "allow_credentials": True
        }

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

    def validate_configuration(self) -> List[str]:
        """Validate configuration and return list of warnings/errors."""
        warnings = []

        # Check production settings
        if self.is_production:
            if self.SECRET_KEY == "your-secret-key-change-in-production":
                warnings.append("Using default secret key in production")

            if self.DEBUG:
                warnings.append("Debug mode enabled in production")

            if "localhost" in self.ALLOWED_HOSTS:
                warnings.append("Localhost in allowed hosts for production")

        # Check Ollama configuration
        if not self.OLLAMA_URL.startswith(("http://", "https://")):
            warnings.append("Invalid Ollama URL format")

        # Check database configuration
        if self.DATABASE_URL.startswith("sqlite") and self.is_production:
            warnings.append("Using SQLite in production (consider PostgreSQL)")

        return warnings


# ─────────────────────────────
# Global Configuration Instance
# ─────────────────────────────
config = Config()

# Create necessary directories on import
config.create_directories()

# Validate configuration and log warnings
warnings = config.validate_configuration()
if warnings:
    import logging
    logger = logging.getLogger(__name__)
    for warning in warnings:
        logger.warning(f"Configuration warning: {warning}")