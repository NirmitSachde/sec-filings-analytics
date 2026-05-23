"""Tests for the EDGAR HTTP client."""

import asyncio

import pytest

from sec_filings.http.edgar_client import EdgarClient, _TokenBucket


@pytest.mark.asyncio
async def test_token_bucket_acquire():
    bucket = _TokenBucket(rate=10, capacity=10)
    # Should not block for initial capacity
    for _ in range(10):
        await bucket.acquire()


@pytest.mark.asyncio
async def test_edgar_client_creates():
    client = EdgarClient()
    assert client._user_agent is not None
    assert "SECFilingsAnalytics" in client._user_agent or "Test" in client._user_agent
    await client.close()


@pytest.mark.asyncio
async def test_edgar_client_context_manager():
    async with EdgarClient() as client:
        assert client is not None
