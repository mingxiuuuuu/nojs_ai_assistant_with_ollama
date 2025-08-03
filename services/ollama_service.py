import asyncio
import aiohttp
import logging
from typing import List, Dict, Optional, Any
from functools import lru_cache
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from config import config

logger = logging.getLogger(__name__)

class OllamaServiceError(Exception):
    """Custom exception for Ollama service errors"""
    pass

class OllamaService:
    """Async service for Ollama API interactions"""

    def __init__(self, base_url: str = None, timeout: int = None):
        self.base_url = base_url or config.OLLAMA_URL
        self.timeout = timeout or config.OLLAMA_TIMEOUT
        self.session: Optional[aiohttp.ClientSession] = None
        self._circuit_breaker_failures = 0
        self._circuit_breaker_threshold = 5
        self._circuit_breaker_reset_time = 60
        self._last_failure_time = 0
        self._model_cache = None
        self._cache_timestamp = None
        self._cache_duration = 300  # 5 minutes

    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.timeout),
            connector=aiohttp.TCPConnector(limit=10, limit_per_host=5)
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()
            self.session = None

    async def initialize(self):
        """Initialize the service and create session"""
        if not self.session:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                connector=aiohttp.TCPConnector(limit=10, limit_per_host=5)
            )
            logger.info(f"OllamaService initialized with URL: {self.base_url}")

    async def close(self):
        """Close the service and cleanup session"""
        if self.session:
            await self.session.close()
            self.session = None
            logger.info("OllamaService closed")

    def _is_circuit_breaker_open(self) -> bool:
        """Check if circuit breaker is open"""
        if self._circuit_breaker_failures >= self._circuit_breaker_threshold:
            if asyncio.get_event_loop().time() - self._last_failure_time < self._circuit_breaker_reset_time:
                return True
            else:
                # Reset circuit breaker
                self._circuit_breaker_failures = 0
        return False

    def _record_failure(self):
        """Record a failure for circuit breaker"""
        self._circuit_breaker_failures += 1
        self._last_failure_time = asyncio.get_event_loop().time()

    def _record_success(self):
        """Record a success for circuit breaker"""
        self._circuit_breaker_failures = 0

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError))
    )
    async def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make HTTP request with retry logic"""
        if self._is_circuit_breaker_open():
            raise OllamaServiceError("Circuit breaker is open - service temporarily unavailable")

        if not self.session:
            raise OllamaServiceError("Session not initialized - use async context manager")

        url = f"{self.base_url}{endpoint}"

        try:
            async with self.session.request(method, url, **kwargs) as response:
                if response.status == 200:
                    self._record_success()
                    return await response.json()
                elif response.status == 404:
                    raise OllamaServiceError(f"Endpoint not found: {endpoint}")
                else:
                    error_text = await response.text()
                    raise OllamaServiceError(f"HTTP {response.status}: {error_text}")

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            self._record_failure()
            logger.error(f"Request failed for {url}: {str(e)}")
            raise

    async def check_health(self) -> bool:
        """Check if Ollama service is healthy"""
        try:
            await self._make_request('GET', '/api/tags')
            return True
        except Exception as e:
            logger.warning(f"Health check failed: {str(e)}")
            return False

    async def get_models(self, use_cache: bool = True) -> List[str]:
        """Get list of available models from Ollama with caching"""
        import time

        # Check cache if enabled
        if use_cache and self._model_cache is not None and self._cache_timestamp is not None:
            if time.time() - self._cache_timestamp < self._cache_duration:
                logger.debug("Returning cached models")
                return self._model_cache

        try:
            response = await self._make_request('GET', '/api/tags')
            models = [model['name'] for model in response.get('models', [])]
            logger.info(f"Retrieved {len(models)} models from Ollama")

            # Update cache
            self._model_cache = models
            self._cache_timestamp = time.time()

            return models
        except Exception as e:
            logger.error(f"Failed to get models: {str(e)}")
            # Return cached models if available, otherwise empty list
            return self._model_cache if self._model_cache is not None else []

    async def generate_response(self, model: str, prompt: str, context: List[Dict[str, str]] = None, **kwargs) -> str:
        """Generate response from Ollama model with optional conversation context"""

        # If context is provided, use chat API for better conversation handling
        if context and len(context) > 0:
            # Build messages array with context + current prompt
            messages = context.copy()
            messages.append({"role": "user", "content": prompt})

            payload = {
                'model': model,
                'messages': messages,
                'stream': False,
                **kwargs
            }

            try:
                response = await self._make_request('POST', '/api/chat', json=payload)
                return response.get('message', {}).get('content', 'No response generated')
            except Exception as e:
                logger.warning(f"Chat API failed, falling back to generate API: {str(e)}")
                # Fall back to simple generate if chat fails

        # Use simple generate API (original behavior)
        payload = {
            'model': model,
            'prompt': prompt,
            'stream': False,
            **kwargs
        }

        try:
            response = await self._make_request('POST', '/api/generate', json=payload)
            return response.get('response', 'No response generated')

        except OllamaServiceError as e:
            if "not found" in str(e).lower():
                raise OllamaServiceError(f"Model '{model}' not found. Try: ollama pull {model}")
            raise
        except Exception as e:
            logger.error(f"Failed to generate response: {str(e)}")
            raise OllamaServiceError(f"Generation failed: {str(e)}")

    async def pull_model(self, model: str) -> bool:
        """Pull a model from Ollama registry"""
        try:
            await self._make_request('POST', '/api/pull', json={'name': model})
            logger.info(f"Successfully pulled model: {model}")
            return True
        except Exception as e:
            logger.error(f"Failed to pull model {model}: {str(e)}")
            return False

    def get_popular_models(self) -> List[str]:
        """Get list of popular Ollama models"""
        return [
            "mistral",
            "llama3",
            "llama3.1",
            "llama3.2",
            "llama2",
            "codellama",
            "phi3",
            "gemma2",
            "qwen2.5",
            "deepseek-coder",
            "nomic-embed-text",
            "all-minilm",
            "tinyllama",
            "orca-mini",
            "vicuna"
        ]

# Global service instance
ollama_service = OllamaService()