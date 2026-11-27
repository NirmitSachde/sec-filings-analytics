"""Extra tests for the EDGAR HTTP client: rate limiting, retries, client lifecycle."""

import time

import httpx
import pytest

from sec_filings.http import edgar_client
from sec_filings.http.edgar_client import EdgarClient, _is_retryable, _TokenBucket

URL = "https://www.sec.gov/files/test.json"


@pytest.fixture
def sleeps(monkeypatch):
    """Replace asyncio.sleep (used by the bucket and by tenacity) with a recorder."""
    recorded: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(edgar_client.asyncio, "sleep", fake_sleep)
    return recorded


def _client_with(handler) -> EdgarClient:
    client = EdgarClient()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


# ---------------------------------------------------------------- token bucket


async def test_bucket_sleeps_when_empty(sleeps):
    bucket = _TokenBucket(rate=10, capacity=10)
    bucket._tokens = 0.0
    bucket._last_refill = time.monotonic()
    await bucket.acquire()
    assert len(sleeps) == 1
    # About one token's worth of time at 10 tokens/s.
    assert 0.09 < sleeps[0] <= 0.1
    assert bucket._tokens == 0


async def test_bucket_refills_over_time_without_sleeping(sleeps):
    bucket = _TokenBucket(rate=10, capacity=10)
    bucket._tokens = 0.0
    bucket._last_refill = time.monotonic() - 5.0  # 50 tokens worth, capped at 10
    await bucket.acquire()
    assert sleeps == []
    assert 8.9 < bucket._tokens <= 9.0


async def test_bucket_eleventh_request_waits(sleeps):
    bucket = _TokenBucket(rate=10, capacity=10)
    for _ in range(10):
        await bucket.acquire()
    assert sleeps == []
    await bucket.acquire()
    assert len(sleeps) == 1


# ---------------------------------------------------------------- retry predicate


def _status_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", URL)
    return httpx.HTTPStatusError("x", request=req, response=httpx.Response(code, request=req))


@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
def test_retryable_status_codes(code):
    assert _is_retryable(_status_error(code))


@pytest.mark.parametrize("code", [400, 403, 404])
def test_non_retryable_status_codes(code):
    assert not _is_retryable(_status_error(code))


def test_retryable_transport_errors():
    assert _is_retryable(httpx.ReadTimeout("slow"))
    assert _is_retryable(httpx.ConnectError("down"))
    assert not _is_retryable(ValueError("other"))
    assert not _is_retryable(httpx.DecodingError("bad"))


# ---------------------------------------------------------------- client lifecycle


async def test_get_client_sets_sec_headers_and_is_reused(monkeypatch):
    seen: list[httpx.Request] = []
    created: list[dict] = []
    real_async_client = httpx.AsyncClient

    def factory(**kwargs):
        created.append(kwargs)

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, text="ok")

        return real_async_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(edgar_client.httpx, "AsyncClient", factory)
    client = EdgarClient()
    first = await client._get_client()
    second = await client._get_client()
    assert first is second
    assert len(created) == 1
    assert created[0]["http2"] is True
    assert created[0]["follow_redirects"] is True

    await first.get(URL)
    assert seen[0].headers["User-Agent"] == client._user_agent
    assert "gzip" in seen[0].headers["Accept-Encoding"]

    await client.close()
    assert client._client is None
    third = await client._get_client()
    assert third is not first
    assert len(created) == 2
    await client.close()


async def test_get_client_recreated_when_closed_externally():
    client = EdgarClient()
    first = await client._get_client()
    await first.aclose()
    second = await client._get_client()
    assert second is not first
    assert not second.is_closed
    await client.close()


async def test_close_is_noop_without_client():
    client = EdgarClient()
    await client.close()
    assert client._client is None


async def test_context_manager_closes_client():
    async with EdgarClient() as client:
        inner = await client._get_client()
    assert inner.is_closed
    assert client._client is None


# ---------------------------------------------------------------- get / get_text / get_bytes


async def test_get_returns_response(sleeps):
    client = _client_with(lambda req: httpx.Response(200, json={"a": 1}))
    resp = await client.get(URL)
    assert resp.json() == {"a": 1}
    await client.close()


async def test_get_text_and_bytes(sleeps):
    client = _client_with(lambda req: httpx.Response(200, content=b"hello \xe2\x9c\x93"))
    assert await client.get_text(URL) == "hello ✓"
    assert await client.get_bytes(URL) == b"hello \xe2\x9c\x93"
    await client.close()


@pytest.mark.parametrize("method", ["get", "get_text", "get_bytes"])
async def test_retries_transient_errors_then_succeeds(sleeps, method):
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        if calls["n"] == 2:
            raise httpx.ConnectError("reset", request=req)
        return httpx.Response(200, text="done")

    client = _client_with(handler)
    result = await getattr(client, method)(URL)
    assert calls["n"] == 3
    if method == "get":
        assert result.text == "done"
    elif method == "get_text":
        assert result == "done"
    else:
        assert result == b"done"
    # Two exponential back-off waits from tenacity (1s, 2s), no rate-limit waits.
    assert sleeps == [1, 2]
    await client.close()


@pytest.mark.parametrize("method", ["get", "get_text", "get_bytes"])
async def test_non_retryable_status_raises_immediately(sleeps, method):
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404)

    client = _client_with(handler)
    with pytest.raises(httpx.HTTPStatusError) as exc:
        await getattr(client, method)(URL)
    assert exc.value.response.status_code == 404
    assert calls["n"] == 1
    assert sleeps == []
    await client.close()


async def test_gives_up_after_five_attempts(sleeps):
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429)

    client = _client_with(handler)
    with pytest.raises(httpx.HTTPStatusError) as exc:
        await client.get(URL)
    assert exc.value.response.status_code == 429
    assert calls["n"] == 5
    assert sleeps == [1, 2, 4, 8]
    await client.close()
