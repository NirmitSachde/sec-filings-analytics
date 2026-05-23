"""Rate-limited, retrying EDGAR HTTP client.

Enforces SEC's 10 req/s policy via a token-bucket rate limiter.
Sets User-Agent on every request per SEC requirements.
"""

import asyncio
import time

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from sec_filings.config import get_settings

EDGAR_BASE = "https://www.sec.gov"
EDGAR_DATA_BASE = "https://data.sec.gov"

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_REQUESTS_PER_SECOND = 10


class _TokenBucket:
    """Simple async token-bucket rate limiter."""

    def __init__(self, rate: float, capacity: int) -> None:
        self._rate = rate
        self._capacity = capacity
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last_refill = now

            if self._tokens < 1:
                wait_time = (1 - self._tokens) / self._rate
                await asyncio.sleep(wait_time)
                self._tokens = 0
            else:
                self._tokens -= 1


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS_CODES
    return isinstance(exc, (httpx.TimeoutException, httpx.ConnectError))


class EdgarClient:
    """Async EDGAR HTTP client with rate limiting and retries."""

    def __init__(self) -> None:
        settings = get_settings()
        self._user_agent = settings.edgar_user_agent
        self._rate_limiter = _TokenBucket(
            rate=_MAX_REQUESTS_PER_SECOND,
            capacity=_MAX_REQUESTS_PER_SECOND,
        )
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                http2=True,
                timeout=httpx.Timeout(30.0, connect=10.0),
                headers={
                    "User-Agent": self._user_agent,
                    "Accept-Encoding": "gzip, deflate",
                },
                follow_redirects=True,
            )
        return self._client

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=16),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    async def get(self, url: str) -> httpx.Response:
        await self._rate_limiter.acquire()
        client = await self._get_client()
        response = await client.get(url)
        response.raise_for_status()
        return response

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=16),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    async def get_text(self, url: str) -> str:
        await self._rate_limiter.acquire()
        client = await self._get_client()
        response = await client.get(url)
        response.raise_for_status()
        return response.text

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=16),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    async def get_bytes(self, url: str) -> bytes:
        await self._rate_limiter.acquire()
        client = await self._get_client()
        response = await client.get(url)
        response.raise_for_status()
        return response.content

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "EdgarClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
