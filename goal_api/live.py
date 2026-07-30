"""Live match updates over WebSocket. Needs the ``live`` extra::

    pip install "goal-api[live]"

The connection authenticates twice, because two services are involved:

1. The gateway authorises the HTTP upgrade with ``Authorization: Bearer <key>``.
2. websocket-service then requires ``{"type": "auth", "apiKey": ...}`` as the very first
   frame, and closes with 4001 if anything else arrives first.

``connect()`` returns once ``auth_success`` has been received, so a returned client is
actually usable. ``mint_connect_token`` is for handing a token to a browser instead.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any, AsyncIterator, Awaitable, Callable

from .errors import GoalAPIError

logger = logging.getLogger("goal_api.live")

Handler = Callable[[dict[str, Any]], Any]

#: Server -> client message types. The replies to client requests are named
#: ``<request>_response``, e.g. ``subscribe`` is answered with ``subscribe_response``.
SERVER_MESSAGES = frozenset(
    {
        "auth_success",
        "match_update",
        "pong",
        "status",
        "subscribe_response",
        "unsubscribe_response",
        "get_subscriptions_response",
        "server_shutdown",
        "error",
    }
)


class LiveClient:
    """Subscribe to live match updates. Reconnects with backoff and re-sends subscriptions.

    Either iterate::

        live = goal.live()
        async with live:
            live.subscribe(fixture_id)
            async for message in live:
                if message["type"] == "match_update":
                    print(message["data"])

    or register handlers and run in the background::

        live.on("match_update", lambda m: print(m["data"]))
        await live.connect()
        live.subscribe(fixture_id)
        await live.run_forever()
    """

    def __init__(
        self,
        transport: Any,
        *,
        url: str | None = None,
        auto_reconnect: bool = True,
        max_reconnect_attempts: int | None = None,
        ping_interval: float = 30.0,
        queue_size: int = 1000,
        auth_timeout: float = 10.0,
    ) -> None:
        self._t = transport
        self._url = url or derive_ws_url(transport.base_url)
        self._auto_reconnect = auto_reconnect
        self._max_attempts = max_reconnect_attempts
        self._ping_interval = ping_interval

        self._ws: Any = None
        self._handlers: dict[str, list[Handler]] = {}
        self._subscriptions: set[str] = set()
        self._queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=queue_size)
        self._tasks: set[asyncio.Task[Any]] = set()
        self._closed = False
        self._attempt = 0
        self._auth_timeout = auth_timeout
        self._authenticated = False

    # -------------------------------------------------------------- handlers

    def on(self, event: str, handler: Handler) -> Callable[[], None]:
        """Handler for one message type, or ``"*"`` for all. Returns a remove function."""
        self._handlers.setdefault(event, []).append(handler)

        def remove() -> None:
            try:
                self._handlers[event].remove(handler)
            except (KeyError, ValueError):
                pass

        return remove

    # -------------------------------------------------------------- lifecycle

    async def connect(self) -> LiveClient:
        try:
            from websockets.asyncio.client import connect as ws_connect
        except ImportError as error:  # pragma: no cover - depends on install extras
            raise GoalAPIError(
                'WebSocket support needs the "live" extra: pip install "goal-api[live]"'
            ) from error

        self._closed = False
        self._authenticated = False
        try:
            self._ws = await ws_connect(
                self._url,
                additional_headers={"Authorization": f"Bearer {self._t.api_key}"},
                ping_interval=self._ping_interval or None,
                max_queue=None,
            )
        except Exception as error:  # noqa: BLE001
            raise GoalAPIError(f"Could not open WebSocket to {self._url}: {error}") from error

        # Must be the first frame on the wire, or the server closes with 4001.
        await self._ws.send(json.dumps({"type": "auth", "apiKey": self._t.api_key}))

        try:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=self._auth_timeout)
        except asyncio.TimeoutError as error:
            await self._ws.close()
            raise GoalAPIError("Timed out waiting for auth_success") from error

        first = json.loads(raw)
        if first.get("type") != "auth_success":
            await self._ws.close()
            detail = (first.get("error") or {}).get("message") or first.get("message") or first
            raise GoalAPIError(f"WebSocket authentication failed: {detail}")

        self._authenticated = True
        self._attempt = 0
        self._dispatch(first)
        await self._enqueue(first)

        for match_id in tuple(self._subscriptions):
            await self._send({"type": "subscribe", "resource": "match", "matchId": match_id})

        self._spawn(self._reader())
        return self

    async def close(self) -> None:
        self._closed = True
        self._authenticated = False
        for task in tuple(self._tasks):
            task.cancel()
        self._tasks.clear()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001 - already closing
                pass
            self._ws = None
        await self._queue.put(None)

    async def __aenter__(self) -> LiveClient:
        return await self.connect()

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    @property
    def connected(self) -> bool:
        """True once authenticated, not merely once the socket is open."""
        return self._ws is not None and not self._closed and self._authenticated

    # -------------------------------------------------------------- messaging

    def subscribe(self, match_id: str) -> None:
        """Fine to call before ``connect()``; it is sent on open."""
        self._subscriptions.add(match_id)
        self._fire_and_forget({"type": "subscribe", "resource": "match", "matchId": match_id})

    def unsubscribe(self, match_id: str) -> None:
        self._subscriptions.discard(match_id)
        self._fire_and_forget({"type": "unsubscribe", "resource": "match", "matchId": match_id})

    def list_subscriptions(self) -> None:
        """Reply arrives as a ``get_subscriptions`` message."""
        self._fire_and_forget({"type": "get_subscriptions"})

    def request_status(self) -> None:
        self._fire_and_forget({"type": "status"})

    def ping(self) -> None:
        self._fire_and_forget({"type": "ping"})

    @property
    def subscriptions(self) -> frozenset[str]:
        return frozenset(self._subscriptions)

    async def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            message = await self._queue.get()
            if message is None:
                return
            yield message

    async def run_forever(self) -> None:
        """Drains messages into the registered handlers until ``close()``."""
        async for _ in self.__aiter__():
            pass

    # -------------------------------------------------------------- internals

    def _spawn(self, coro: Awaitable[Any]) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _fire_and_forget(self, message: dict[str, Any]) -> None:
        # subscribe/unsubscribe are held in _subscriptions and replayed on open.
        if not self.connected:
            if message["type"] not in ("subscribe", "unsubscribe"):
                logger.warning("Dropping %s: socket is not open", message["type"])
            return
        self._spawn(self._send(message))

    async def _send(self, message: dict[str, Any]) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps(message))
        except Exception as error:  # noqa: BLE001
            logger.warning("Failed to send %s: %s", message.get("type"), error)

    async def _reader(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                try:
                    message = json.loads(raw)
                except (TypeError, ValueError):
                    logger.warning("Discarding malformed WebSocket frame")
                    continue
                if not isinstance(message, dict):
                    continue
                self._dispatch(message)
                await self._enqueue(message)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001
            logger.info("WebSocket read loop ended: %s", error)

        if self._auto_reconnect and not self._closed:
            self._spawn(self._reconnect())
        else:
            await self._queue.put(None)

    def _dispatch(self, message: dict[str, Any]) -> None:
        for event in (message.get("type", ""), "*"):
            for handler in tuple(self._handlers.get(event, ())):
                try:
                    result = handler(message)
                    if asyncio.iscoroutine(result):
                        self._spawn(result)
                except Exception:  # noqa: BLE001
                    # One bad handler shouldn't stop the others.
                    logger.exception("Live message handler raised")

    async def _enqueue(self, message: dict[str, Any]) -> None:
        try:
            self._queue.put_nowait(message)
        except asyncio.QueueFull:
            # Drop the oldest rather than block the read loop, which would stall pongs
            # and get us disconnected.
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self._queue.put_nowait(message)

    async def _reconnect(self) -> None:
        if self._max_attempts is not None and self._attempt >= self._max_attempts:
            logger.error("Giving up after %d reconnect attempts", self._attempt)
            await self._queue.put(None)
            return
        delay = min(2**self._attempt, 30) * (0.5 + random.random() / 2)
        self._attempt += 1
        await asyncio.sleep(delay)
        if self._closed:
            return
        try:
            await self.connect()
        except Exception as error:  # noqa: BLE001
            logger.warning("Reconnect attempt %d failed: %s", self._attempt, error)
            self._spawn(self._reconnect())


def mint_connect_token(client: Any) -> Any:
    """A short-lived, single-use WebSocket token for a browser.

    Server-side code does not need this. Use it so a frontend can connect without seeing
    your API key::

        token = mint_connect_token(goal)["data"]["token"]            # sync
        token = (await mint_connect_token(goal))["data"]["token"]    # async
    """
    return client._t.post("/ws/token", {})


def derive_ws_url(base_url: str) -> str:
    """The live socket is served at ``/ws`` on the host root, not under ``/v1``.

    nginx routes it with ``location ^~ /ws``, the only location carrying the Upgrade
    headers. ``/v1/ws`` falls into the REST location instead and silently answers 200
    rather than upgrading, which is a confusing failure because the URL looks right.
    """
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(base_url)
    scheme = "wss" if parts.scheme == "https" else "ws"
    return urlunsplit((scheme, parts.netloc, "/ws", "", ""))
