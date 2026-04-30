"""Integration test fixtures for aioboto3 + moto compatibility.

aiobotocore >= 2.x sends PUT/POST requests with an async body
(AioAwsChunkedWrapper) and expects responses whose .content property
returns a coroutine (AioAWSResponse).  moto 5.x uses botocore's sync
BotocoreStubber which:

  1. Receives request.body as a coroutine and passes it straight to sync
     moto handlers that call .readline() / .read() synchronously → crash.
  2. Returns a plain AWSResponse whose .content is a bytes @property, but
     aiobotocore's endpoint does `await http_response.content` → TypeError.

The patch in `mock_aws_compat` fixes both at the BotocoreStubber.__call__
level so individual test fixtures don't need to know about it.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
from unittest.mock import patch

import aiobotocore.awsrequest as _aio_req
import moto.core.botocore_stubber as _bs
import pytest

# ---------------------------------------------------------------------------
# Async-compatible raw response wrapper
# ---------------------------------------------------------------------------


class _AsyncReadable:
    """Async content reader matching the aiohttp StreamReader interface."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    async def read(self, n: int = -1) -> bytes:
        if n == -1 or n is None:  # type: ignore[comparison-overlap]
            result = self._data[self._pos :]
            self._pos = len(self._data)
        else:
            result = self._data[self._pos : self._pos + n]
            self._pos += n
        return result


class _AioMockRawResponse:
    """Drop-in for moto's MockRawResponse that works with aiobotocore.

    aiobotocore's AioAWSResponse._content_prop does:
        self._content = await self.raw.read() or b''
    and StreamingBody.read does:
        chunk = await self.__wrapped__.content.read(n)

    We satisfy both.
    """

    def __init__(self, data: bytes | str) -> None:
        if isinstance(data, str):
            data = data.encode()
        self._data = data
        self.content = _AsyncReadable(data)
        self._read_pos = 0

    async def read(self) -> bytes:
        result = self._data[self._read_pos :]
        self._read_pos = len(self._data)
        return result

    def stream(self, **_: object):  # sync generator for compatibility
        yield self._data

    def at_eof(self) -> bool:
        return self._read_pos >= len(self._data)

    async def __aenter__(self) -> _AioMockRawResponse:
        return self

    async def __aexit__(self, *_: object) -> None:
        pass


# ---------------------------------------------------------------------------
# Drain async request body synchronously in a background thread
# ---------------------------------------------------------------------------


def _drain_async_body(body: object) -> bytes:
    """Run an async body.read() in a fresh thread + event loop."""
    result: list[bytes] = []
    exc_holder: list[BaseException] = []

    def _run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            if inspect.iscoroutine(body):
                result.append(loop.run_until_complete(body))  # type: ignore[arg-type]
            else:
                result.append(loop.run_until_complete(body.read()))  # type: ignore[union-attr]
        except BaseException as exc:
            exc_holder.append(exc)
        finally:
            loop.close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join()
    if exc_holder:
        raise exc_holder[0]
    return result[0]


# ---------------------------------------------------------------------------
# Patched BotocoreStubber.__call__
# ---------------------------------------------------------------------------

_original_call = _bs.BotocoreStubber.__call__


def _patched_stubber_call(
    self: _bs.BotocoreStubber,
    event_name: str,
    request: object,
    **kwargs: object,
) -> object:
    if not self.enabled:
        return None

    # --- Fix 1: drain async request body before moto's sync handlers see it ---
    body = getattr(request, "body", None)
    if body is not None and (
        inspect.iscoroutine(body)
        or (hasattr(body, "read") and inspect.iscoroutinefunction(body.read))
    ):
        request.body = _drain_async_body(body)  # type: ignore[union-attr]

    response = self.process_request(request)  # type: ignore[arg-type]
    if response is None:
        return None

    status, headers, resp_body = response

    # --- Fix 2: return AioAWSResponse so aiobotocore can `await .content` ---
    if isinstance(resp_body, str):
        resp_body = resp_body.encode()
    return _aio_req.AioAWSResponse(
        request.url,  # type: ignore[union-attr]
        status,
        headers,
        _AioMockRawResponse(resp_body),
    )


# ---------------------------------------------------------------------------
# Autouse fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_aws_compat():
    """Apply aioboto3 + moto compatibility patches for every integration test."""
    with patch.object(_bs.BotocoreStubber, "__call__", _patched_stubber_call):
        yield
