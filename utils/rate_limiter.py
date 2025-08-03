import time
import asyncio
from typing import Dict, Optional
from collections import defaultdict, deque
from dataclasses import dataclass
from config import config
import logging

logger = logging.getLogger(__name__)

@dataclass
class RateLimitInfo:
    """Information about rate limit status"""
    allowed: bool
    remaining: int
    reset_time: float
    retry_after: Optional[float] = None

class TokenBucket:
    """Token bucket algorithm for rate limiting"""

    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.tokens = capacity
        self.refill_rate = refill_rate  # tokens per second
        self.last_refill = time.time()
        self._lock = asyncio.Lock()

    async def consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens from the bucket"""
        async with self._lock:
            now = time.time()
            # Add tokens based on time elapsed
            time_passed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + time_passed * self.refill_rate)
            self.last_refill = now

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    def get_wait_time(self, tokens: int = 1) -> float:
        """Get time to wait before tokens are available"""
        if self.tokens >= tokens:
            return 0.0
        needed_tokens = tokens - self.tokens
        return needed_tokens / self.refill_rate

class SlidingWindowRateLimiter:
    """Sliding window rate limiter"""

    def __init__(self, max_requests: int, window_size: int):
        self.max_requests = max_requests
        self.window_size = window_size  # in seconds
        self.requests: Dict[str, deque] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def is_allowed(self, identifier: str) -> RateLimitInfo:
        """Check if request is allowed for the identifier"""
        async with self._lock:
            now = time.time()
            window_start = now - self.window_size

            # Clean old requests
            user_requests = self.requests[identifier]
            while user_requests and user_requests[0] < window_start:
                user_requests.popleft()

            # Check if under limit
            if len(user_requests) < self.max_requests:
                user_requests.append(now)
                remaining = self.max_requests - len(user_requests)
                return RateLimitInfo(
                    allowed=True,
                    remaining=remaining,
                    reset_time=now + self.window_size
                )
            else:
                # Calculate retry after time
                oldest_request = user_requests[0]
                retry_after = oldest_request + self.window_size - now
                return RateLimitInfo(
                    allowed=False,
                    remaining=0,
                    reset_time=oldest_request + self.window_size,
                    retry_after=max(0, retry_after)
                )

class AdaptiveRateLimiter:
    """Adaptive rate limiter that adjusts based on system load"""

    def __init__(self, base_limit: int, window_size: int):
        self.base_limit = base_limit
        self.window_size = window_size
        self.current_limit = base_limit
        self.error_count = 0
        self.success_count = 0
        self.last_adjustment = time.time()
        self.limiter = SlidingWindowRateLimiter(self.current_limit, window_size)
        self._lock = asyncio.Lock()

    async def is_allowed(self, identifier: str) -> RateLimitInfo:
        """Check if request is allowed with adaptive limiting"""
        await self._adjust_limit()
        return await self.limiter.is_allowed(identifier)

    async def record_success(self):
        """Record a successful request"""
        async with self._lock:
            self.success_count += 1

    async def record_error(self):
        """Record a failed request"""
        async with self._lock:
            self.error_count += 1

    async def _adjust_limit(self):
        """Adjust rate limit based on error rate"""
        async with self._lock:
            now = time.time()
            if now - self.last_adjustment < 60:  # Adjust every minute
                return

            total_requests = self.success_count + self.error_count
            if total_requests == 0:
                return

            error_rate = self.error_count / total_requests

            if error_rate > 0.1:  # More than 10% errors
                # Reduce limit
                new_limit = max(1, int(self.current_limit * 0.8))
                logger.warning(f"High error rate ({error_rate:.2%}), reducing limit to {new_limit}")
            elif error_rate < 0.02:  # Less than 2% errors
                # Increase limit
                new_limit = min(self.base_limit * 2, int(self.current_limit * 1.2))
                logger.info(f"Low error rate ({error_rate:.2%}), increasing limit to {new_limit}")
            else:
                new_limit = self.current_limit

            if new_limit != self.current_limit:
                self.current_limit = new_limit
                self.limiter = SlidingWindowRateLimiter(self.current_limit, self.window_size)

            # Reset counters
            self.success_count = 0
            self.error_count = 0
            self.last_adjustment = now

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

    async def check_ip_limit(self, ip: str) -> RateLimitInfo:
        """Check rate limit for specific IP"""
        return await self.ip_limiter.is_allowed(ip)

    async def check_global_limit(self) -> bool:
        """Check global rate limit"""
        return await self.global_limiter.consume()

    async def check_ollama_limit(self, identifier: str) -> RateLimitInfo:
        """Check rate limit for Ollama requests"""
        return await self.ollama_limiter.is_allowed(identifier)

    async def record_ollama_success(self):
        """Record successful Ollama request"""
        await self.ollama_limiter.record_success()

    async def record_ollama_error(self):
        """Record failed Ollama request"""
        await self.ollama_limiter.record_error()

# Global instance
rate_limiter = GlobalRateLimiter()

async def check_rate_limit(ip: str, endpoint: str = 'general') -> RateLimitInfo:
    """Check rate limit for a request"""
    # Check global limit first
    if not await rate_limiter.check_global_limit():
        return RateLimitInfo(
            allowed=False,
            remaining=0,
            reset_time=time.time() + 60,
            retry_after=60
        )

    # Check IP-specific limit
    ip_result = await rate_limiter.check_ip_limit(ip)
    if not ip_result.allowed:
        return ip_result

    # Check endpoint-specific limits
    if endpoint == 'ollama':
        ollama_result = await rate_limiter.check_ollama_limit(ip)
        if not ollama_result.allowed:
            return ollama_result

    return ip_result

async def record_request_result(success: bool, endpoint: str = 'general'):
    """Record the result of a request for adaptive limiting"""
    if endpoint == 'ollama':
        if success:
            await rate_limiter.record_ollama_success()
        else:
            await rate_limiter.record_ollama_error()

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