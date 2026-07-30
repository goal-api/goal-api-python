"""Error types mapped from the API's error envelope. Everything subclasses GoalAPIError."""

from __future__ import annotations

from typing import Any, Mapping

__all__ = [
    "GoalAPIError",
    "ConnectionError",
    "TimeoutError",
    "ValidationError",
    "AuthenticationError",
    "PermissionError",
    "PlanUpgradeRequiredError",
    "NotFoundError",
    "ConflictError",
    "RateLimitError",
    "ServiceUnavailableError",
    "ServerError",
    "error_from_response",
]


class GoalAPIError(Exception):
    """Base for everything this SDK raises."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        category: str | None = None,
        details: Any = None,
        correlation_id: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.category = category
        self.details = details
        self.correlation_id = correlation_id
        self.headers = dict(headers) if headers else {}

    def __str__(self) -> str:
        parts = [self.message]
        if self.code:
            parts.append(f"code={self.code}")
        if self.status:
            parts.append(f"status={self.status}")
        if self.correlation_id:
            parts.append(f"correlation_id={self.correlation_id}")
        return " ".join(parts)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self!s})"


# These shadow builtins. Callers reach them as goal_api.ConnectionError etc.
class ConnectionError(GoalAPIError):  # noqa: A001
    """No HTTP response at all: DNS, TLS, socket."""


class TimeoutError(ConnectionError):  # noqa: A001
    """Exceeded the configured timeout."""


class ValidationError(GoalAPIError):
    """400, 422."""


class AuthenticationError(GoalAPIError):
    """401."""


class PermissionError(GoalAPIError):  # noqa: A001
    """403."""


class PlanUpgradeRequiredError(GoalAPIError):
    """402: endpoint not included in the current plan."""


class NotFoundError(GoalAPIError):
    """404."""


class ConflictError(GoalAPIError):
    """409."""


class RateLimitError(GoalAPIError):
    """429. ``retry_after`` is in seconds."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        self.retry_after: int | None = kwargs.pop("retry_after", None)
        self.limit: int | None = kwargs.pop("limit", None)
        self.remaining: int | None = kwargs.pop("remaining", None)
        self.reset: int | None = kwargs.pop("reset", None)
        self.rate_limit_type: str | None = kwargs.pop("rate_limit_type", None)
        super().__init__(message, **kwargs)


class ServiceUnavailableError(GoalAPIError):
    """503."""


class ServerError(GoalAPIError):
    """5xx."""


_BY_STATUS: dict[int, type[GoalAPIError]] = {
    400: ValidationError,
    401: AuthenticationError,
    402: PlanUpgradeRequiredError,
    403: PermissionError,
    404: NotFoundError,
    409: ConflictError,
    422: ValidationError,
    429: RateLimitError,
    503: ServiceUnavailableError,
}


def _int_header(headers: Mapping[str, str], name: str) -> int | None:
    raw = headers.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def error_from_response(
    status: int,
    body: Mapping[str, Any] | None,
    headers: Mapping[str, str],
) -> GoalAPIError:
    """Maps a non-2xx response to an error.

    The API has two error shapes: the gateway sends ``message``, football-service sends
    ``error``. ``body`` is None when the response was not JSON (nginx 502s are HTML).
    """
    cls = _BY_STATUS.get(status) or (ServerError if status >= 500 else GoalAPIError)
    body = body or {}
    message = body.get("message") or body.get("error") or f"HTTP {status}"

    kwargs: dict[str, Any] = {
        "status": status,
        "code": body.get("code"),
        "category": body.get("category"),
        "details": body.get("details"),
        "correlation_id": body.get("correlationId"),
        "headers": headers,
    }

    if cls is RateLimitError:
        kwargs.update(
            retry_after=_int_header(headers, "retry-after"),
            limit=_int_header(headers, "x-ratelimit-limit"),
            remaining=_int_header(headers, "x-ratelimit-remaining"),
            reset=_int_header(headers, "x-ratelimit-reset"),
            rate_limit_type=headers.get("x-ratelimit-type"),
        )

    return cls(message, **kwargs)
