"""GOAL_API_KEY=... python examples/live_scores.py

Connects to the live socket, subscribes to whatever is in play, and prints every frame the
server sends. Exits non-zero if nothing arrives, so it works as a smoke test.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections import Counter

from goal_api import GoalAPI, GoalAPIError

API_KEY = os.environ.get("GOAL_API_KEY", "")
LISTEN_SECONDS = int(os.environ.get("LISTEN_SECONDS", "30"))


async def main() -> int:
    if not API_KEY:
        print("GOAL_API_KEY is not set.", file=sys.stderr)
        return 2

    goal = GoalAPI(API_KEY)
    live = goal.fixtures.live()["data"]
    print(f"{len(live)} match(es) in play")
    for match in live[:5]:
        home = (match.get("homeTeam") or {}).get("name", "?")
        away = (match.get("awayTeam") or {}).get("name", "?")
        print(f"  {match['id']}  {home} v {away}")

    seen: Counter[str] = Counter()
    feed = goal.live()

    feed.on("*", lambda m: seen.update([m.get("type", "?")]))

    def on_auth(message):
        data = message.get("data") or {}
        print(f"\nauthenticated: plan={data.get('plan')} maxSubscriptions={data.get('maxSubscriptions')}")
        if data.get("maxSubscriptions") == 0:
            print("  this plan allows 0 concurrent subscriptions, so no match_update can arrive")

    def on_subscribe(message):
        if message.get("success"):
            print(f"  subscribed: {message.get('data')}")
        else:
            error = message.get("error") or {}
            print(f"  subscribe rejected: {error.get('code')} {error.get('message')}")

    def on_update(message):
        data = message.get("data") or {}
        home = (data.get("homeTeam") or {}).get("name", "?")
        away = (data.get("awayTeam") or {}).get("name", "?")
        print(f"  UPDATE  {home} {data.get('homeScore')}-{data.get('awayScore')} {away}  {data.get('minute')}'")

    feed.on("auth_success", on_auth)
    feed.on("subscribe_response", on_subscribe)
    feed.on("match_update", on_update)
    feed.on("pong", lambda _m: print("  pong"))

    try:
        await feed.connect()
    except GoalAPIError as error:
        print(f"\nconnect failed: {error}", file=sys.stderr)
        goal.close()
        return 1

    for match in live[:5]:
        feed.subscribe(match["id"])
    feed.list_subscriptions()
    feed.ping()

    print(f"\nlistening for {LISTEN_SECONDS}s ...")
    await asyncio.sleep(LISTEN_SECONDS)
    await feed.close()
    goal.close()

    print(f"\nreceived: {dict(seen)}")
    if not seen.get("auth_success"):
        print("nothing was received from the socket", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
