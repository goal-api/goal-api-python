"""Auth, query encoding, retries, rate-limit tracking.

Two transports with the same method names. ``SyncTransport.get()`` returns a dict,
``AsyncTransport.get()`` returns an awaitable. The resource classes just return whatever
they get back, which is why one set of definitions serves both clients.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from typing import Any, Iterable, Mapping
from urllib.parse import quote

import httpx

from .errors import (
    ConnectionError as GoalConnectionError,
    RateLimitError,
    TimeoutError as GoalTimeoutError,
    error_from_response,
)

DEFAULT_BASE_URL = "https://api.goal-api.com/v1"
VERSION = "1.0.0"

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class RateLimit:
    """Snapshot of the last seen ``X-RateLimit-*`` headers."""

    __slots__ = ("limit", "remaining", "reset", "type")

    def __init__(self) -> None:
        self.limit: int | None = None
        self.remaining: int | None = None
        self.reset: int | None = None
        self.type: str | None = None

    def _update(self, headers: Mapping[str, str]) -> None:
        def num(name: str) -> int | None:
            raw = headers.get(name)
            if raw is None or raw == "":
                return None
            try:
                return int(raw)
            except ValueError:
                return None

        limit = num("x-ratelimit-limit")
        # /public/* sends RateLimit-* (draft standard) instead, so leave the snapshot alone.
        if limit is None and headers.get("x-ratelimit-type") is None:
            return
        self.limit = limit
        self.remaining = num("x-ratelimit-remaining")
        self.reset = num("x-ratelimit-reset")
        self.type = headers.get("x-ratelimit-type")

    def as_dict(self) -> dict[str, Any]:
        return {"limit": self.limit, "remaining": self.remaining, "reset": self.reset, "type": self.type}

    def __repr__(self) -> str:
        return f"RateLimit({self.as_dict()})"


def encode_params(params: Mapping[str, Any] | None) -> dict[str, str]:
    """Drops None/empty and joins sequences with commas.

    Callers pass whole option dicts with keys unset, and ``?season=None`` is a 400.
    Booleans go out as "true"/"false", which is what the validators check for.
    """
    out: dict[str, str] = {}
    for key, value in (params or {}).items():
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            out[key] = "true" if value else "false"
        elif isinstance(value, (list, tuple, set, frozenset)):
            joined = ",".join(str(v) for v in value)
            if joined:
                out[key] = joined
        else:
            out[key] = str(value)
    return out


def _parse_body(response: httpx.Response) -> dict[str, Any] | None:
    if not response.content:
        return None
    try:
        parsed = response.json()
    except (json.JSONDecodeError, ValueError):
        # nginx returns HTML for 502s. Keep an excerpt so the message is still useful.
        return {"message": response.text[:200].strip()}
    return parsed if isinstance(parsed, dict) else {"data": parsed}


def _backoff_seconds(attempt: int, error: Exception) -> float:
    """Exponential backoff with jitter. A server-sent Retry-After takes priority."""
    if isinstance(error, RateLimitError) and error.retry_after is not None:
        return min(float(error.retry_after), 60.0)
    return random.uniform(0, min(0.5 * 2**attempt, 8.0))


def _should_retry(error: Exception) -> bool:
    if isinstance(error, (GoalTimeoutError, GoalConnectionError)):
        return True
    status = getattr(error, "status", None)
    return status in _RETRYABLE_STATUS


class _BaseTransport:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        max_retries: int = 2,
        user_agent: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required. Create one at https://goal-api.com/dashboard")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.rate_limit = RateLimit()
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": user_agent or f"goal-api-python/{VERSION}",
            **(dict(headers) if headers else {}),
        }

    def _handle(self, response: httpx.Response) -> dict[str, Any]:
        self.rate_limit._update(response.headers)
        body = _parse_body(response)
        if response.status_code >= 400:
            raise error_from_response(response.status_code, body, response.headers)
        return body or {}

    @staticmethod
    def _wrap_httpx_error(error: Exception, url: str, timeout: float) -> Exception:
        if isinstance(error, httpx.TimeoutException):
            return GoalTimeoutError(f"Request to {url} timed out after {timeout}s")
        if isinstance(error, httpx.HTTPError):
            return GoalConnectionError(f"Could not reach {url}: {error}")
        return error


class SyncTransport(_BaseTransport):
    def __init__(self, api_key: str, *, client: httpx.Client | None = None, **kwargs: Any) -> None:
        super().__init__(api_key, **kwargs)
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=self.timeout)

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        query = encode_params(params)
        last: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.get(url, params=query, headers=self._headers)
                return self._handle(response)
            except Exception as error:  # noqa: BLE001 (re-raised below after mapping)
                last = self._wrap_httpx_error(error, url, self.timeout)
                if attempt == self.max_retries or not _should_retry(last):
                    raise last from (error if last is not error else None)
                time.sleep(_backoff_seconds(attempt, last))

        assert last is not None  # unreachable; the loop always raises or returns
        raise last

    def post(self, path: str, body: Any = None) -> dict[str, Any]:
        # Not retried: /ws/token is single-use, so a retry would burn the token the first
        # attempt may already have minted.
        url = f"{self.base_url}{path}"
        try:
            response = self._client.post(url, json=body or {}, headers=self._headers)
        except Exception as error:  # noqa: BLE001
            raise self._wrap_httpx_error(error, url, self.timeout) from error
        return self._handle(response)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


class AsyncTransport(_BaseTransport):
    def __init__(self, api_key: str, *, client: httpx.AsyncClient | None = None, **kwargs: Any) -> None:
        super().__init__(api_key, **kwargs)
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=self.timeout)

    async def get(self, path: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        query = encode_params(params)
        last: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = await self._client.get(url, params=query, headers=self._headers)
                return self._handle(response)
            except Exception as error:  # noqa: BLE001
                last = self._wrap_httpx_error(error, url, self.timeout)
                if attempt == self.max_retries or not _should_retry(last):
                    raise last from (error if last is not error else None)
                await asyncio.sleep(_backoff_seconds(attempt, last))

        assert last is not None
        raise last

    async def post(self, path: str, body: Any = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            response = await self._client.post(url, json=body or {}, headers=self._headers)
        except Exception as error:  # noqa: BLE001
            raise self._wrap_httpx_error(error, url, self.timeout) from error
        return self._handle(response)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def quote_segment(segment: Any) -> str:
    """Ids, dates and country names come from callers, so they can't be interpolated raw."""
    if segment is None or segment == "":
        raise ValueError("Path segment is required")
    return quote(str(segment), safe="")


def csv(value: Any) -> str:
    """A sequence or an already-joined string, out as comma-separated."""
    if isinstance(value, str):
        return value
    if isinstance(value, Iterable):
        return ",".join(str(v) for v in value)
    return str(value)
