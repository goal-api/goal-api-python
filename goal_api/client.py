"""The sync and async GOAL API clients."""

from __future__ import annotations

from typing import Any, AsyncIterator, Awaitable, Callable, Iterator, Mapping

import httpx

from ._transport import DEFAULT_BASE_URL, AsyncTransport, RateLimit, SyncTransport
from . import resources as _r

__all__ = ["GoalAPI", "AsyncGoalAPI"]

_DEFAULT_PAGE_SIZE = 100
PageFetcher = Callable[..., Any]


class _ClientBase:
    """Attaches the resource groups and holds the shared pagination logic."""

    def __init__(self, transport: Any) -> None:
        self._t = transport
        for name, cls in _r.ALL_RESOURCES.items():
            setattr(self, name, cls(transport))

    # Declared for type checkers; actually assigned in __init__ from ALL_RESOURCES.
    status: _r.Status
    countries: _r.Countries
    leagues: _r.Leagues
    teams: _r.Teams
    fixtures: _r.Fixtures
    standings: _r.Standings
    players: _r.Players
    coaches: _r.Coaches
    h2h: _r.HeadToHead
    results: _r.Results
    videos: _r.Videos
    odds: _r.Odds
    predictions: _r.Predictions

    @property
    def rate_limit(self) -> RateLimit:
        """Quota from the last response. All None until the first authenticated call."""
        return self._t.rate_limit

    @property
    def base_url(self) -> str:
        return self._t.base_url

    @staticmethod
    def _page_items(page: Mapping[str, Any] | None) -> list[Any]:
        data = (page or {}).get("data")
        return data if isinstance(data, list) else []

    @staticmethod
    def _has_more(page: Mapping[str, Any] | None, got: int, page_size: int) -> bool:
        pagination = (page or {}).get("pagination")
        if isinstance(pagination, Mapping) and "hasMore" in pagination:
            return bool(pagination["hasMore"])
        # Some endpoints omit pagination; a short page is the only other signal.
        return got >= page_size


class GoalAPI(_ClientBase):
    """Synchronous GOAL API client.

        goal = GoalAPI(api_key=os.environ["GOAL_API_KEY"])
        for match in goal.fixtures.live()["data"]:
            print(match["homeTeam"]["name"])

    Use it as a context manager to close the connection pool.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        max_retries: int = 2,
        user_agent: str | None = None,
        headers: Mapping[str, str] | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        super().__init__(
            SyncTransport(
                api_key,
                base_url=base_url,
                timeout=timeout,
                max_retries=max_retries,
                user_agent=user_agent,
                headers=headers,
                client=http_client,
            )
        )

    def request(self, path: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """For endpoints not wrapped here yet."""
        return self._t.get(path, params)

    def paginate(
        self,
        fetch_page: PageFetcher,
        *,
        page_size: int = _DEFAULT_PAGE_SIZE,
        max_items: int | None = None,
        start_offset: int = 0,
    ) -> Iterator[Any]:
        """Walks pages, yielding items.

            for team in goal.paginate(lambda **p: goal.leagues.teams(league_id, **p)):
                print(team["name"])

        100 is the limit ceiling on most endpoints; /results and /countries take 500.
        """
        offset, yielded = start_offset, 0
        while max_items is None or yielded < max_items:
            page = fetch_page(limit=page_size, offset=offset)
            items = self._page_items(page)
            if not items:
                return
            for item in items:
                yield item
                yielded += 1
                if max_items is not None and yielded >= max_items:
                    return
            if not self._has_more(page, len(items), page_size):
                return
            offset += len(items)

    def collect(self, fetch_page: PageFetcher, **kwargs: Any) -> list[Any]:
        """``paginate`` collected into a list."""
        return list(self.paginate(fetch_page, **kwargs))

    def live(self, **kwargs: Any):
        """Live match updates. Needs the ``live`` extra.

        Returns an async client even here -- WebSockets have no sync equivalent.
        """
        from .live import LiveClient

        return LiveClient(self._t, **kwargs)

    def close(self) -> None:
        self._t.close()

    def __enter__(self) -> GoalAPI:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class AsyncGoalAPI(_ClientBase):
    """Asynchronous GOAL API client. Same methods as ``GoalAPI``, awaited.

        async with AsyncGoalAPI(api_key=...) as goal:
            page = await goal.fixtures.live()
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        max_retries: int = 2,
        user_agent: str | None = None,
        headers: Mapping[str, str] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            AsyncTransport(
                api_key,
                base_url=base_url,
                timeout=timeout,
                max_retries=max_retries,
                user_agent=user_agent,
                headers=headers,
                client=http_client,
            )
        )

    async def request(self, path: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return await self._t.get(path, params)

    async def paginate(
        self,
        fetch_page: Callable[..., Awaitable[Mapping[str, Any]]],
        *,
        page_size: int = _DEFAULT_PAGE_SIZE,
        max_items: int | None = None,
        start_offset: int = 0,
    ) -> AsyncIterator[Any]:
        """As ``GoalAPI.paginate``, iterated with ``async for``."""
        offset, yielded = start_offset, 0
        while max_items is None or yielded < max_items:
            page = await fetch_page(limit=page_size, offset=offset)
            items = self._page_items(page)
            if not items:
                return
            for item in items:
                yield item
                yielded += 1
                if max_items is not None and yielded >= max_items:
                    return
            if not self._has_more(page, len(items), page_size):
                return
            offset += len(items)

    async def collect(self, fetch_page: Callable[..., Awaitable[Mapping[str, Any]]], **kwargs: Any) -> list[Any]:
        return [item async for item in self.paginate(fetch_page, **kwargs)]

    def live(self, **kwargs: Any):
        from .live import LiveClient

        return LiveClient(self._t, **kwargs)

    async def aclose(self) -> None:
        await self._t.aclose()

    async def __aenter__(self) -> AsyncGoalAPI:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()
