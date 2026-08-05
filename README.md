# goal-api

Python SDK for the [GOAL API](https://goal-api.com): football fixtures, live scores,
standings, player stats, odds and live WebSocket updates.

Sync and async clients from the same surface. Python 3.9+.

```bash
pip install goal-api           # REST
pip install "goal-api[live]"   # + WebSocket live updates
```

## Quick start

```python
import os
from goal_api import GoalAPI

goal = GoalAPI(os.environ["GOAL_API_KEY"])

for match in goal.fixtures.live()["data"]:
    print(match["homeTeam"]["name"], match["homeScore"], "-", match["awayScore"], match["awayTeam"]["name"])
```

Get a key at [goal-api.com/signup](https://goal-api.com/signup).

Use it as a context manager so the connection pool closes cleanly:

```python
with GoalAPI(api_key) as goal:
    table = goal.leagues.standings(league_id)["data"]
```

## Async

Same method names, awaited:

```python
import asyncio
from goal_api import AsyncGoalAPI

async def main():
    async with AsyncGoalAPI(api_key) as goal:
        live, results = await asyncio.gather(
            goal.fixtures.live(),
            goal.results.today(),
        )
        print(len(live["data"]), "in play,", len(results["data"]), "finished today")

asyncio.run(main())
```

## Client options

```python
goal = GoalAPI(
    api_key,
    base_url="https://api.goal-api.com/v1",   # default
    timeout=30.0,                             # per attempt, seconds
    max_retries=2,                            # 429 + 5xx + network errors
    headers={"X-My-App": "scoreboard"},
)
```

Retries use exponential backoff with full jitter and always honour a server-sent
`Retry-After`.

## Endpoints

Grouped by resource. Query params are keyword arguments, passed through with the API's own
`camelCase` names. Full reference in [`ENDPOINTS.md`](ENDPOINTS.md).

```python
goal.status.get()                                    # no API key needed
goal.countries.list(search="spa")
goal.leagues.list(isActive=True, limit=100)
goal.leagues.standings(league_id)
goal.leagues.top_scorers(league_id, limit=10)
goal.teams.get(team_id, includePlayers=True)
goal.teams.statistics(team_id, season="2025-2026")
goal.fixtures.list(**{"from": "2026-08-01", "to": "2026-08-07", "status": "SCHEDULED"})
goal.fixtures.by_date("2026-08-15", leagueId=league_id)
goal.fixtures.lineups(fixture_id)
goal.fixtures.statistics(fixture_id, half="1half")
goal.standings.form(league_id)
goal.players.search("haaland", limit=5)
goal.players.compare([player_a, player_b])
goal.players.top("goals", limit=20)
goal.coaches.by_team(team_id)
goal.h2h.stats(team_a, team_b)
goal.results.today()
goal.videos.recent(leagueId=league_id, limit=10)
goal.odds.list(bookmaker="bet365")
goal.predictions.list(matchId=match_id)
```

`from` is a Python keyword, so date ranges need `**{...}` or a prepared dict:

```python
window = {"from": "2026-08-01", "to": "2026-08-31"}
goal.leagues.fixtures(league_id, **window)
```

Every method returns the raw envelope, so `pagination` and `source` stay reachable:

```python
page = goal.teams.list(leagueId=league_id, limit=50)
page["data"]                     # list of teams
page["pagination"]["hasMore"]    # bool
page["source"]                   # "cache" | "database"
```

### One exception: `goal.status.*`

The five `/public/*` endpoints don't use the `{"success", "data"}` envelope. They return
bare objects, so read them directly with no `["data"]`:

```python
status = goal.status.get()
status["status"]        # "operational"
status["components"]    # [{"name", "status", "uptime"}]
```

They also paginate with `page`/`limit` instead of `limit`/`offset`, so `paginate()` does
not apply to `coverage_leagues`.

## Pagination

`paginate` walks pages and yields items:

```python
for team in goal.paginate(lambda **p: goal.leagues.teams(league_id, **p)):
    print(team["name"])

# Or collect, with a cap. /results accepts limit up to 500:
recent = goal.collect(
    lambda **p: goal.results.list(leagueId=league_id, **p),
    page_size=500,
    max_items=500,
)
```

Async is the same call, iterated with `async for`:

```python
async for team in goal.paginate(lambda **p: goal.leagues.teams(league_id, **p)):
    ...
```

Default `page_size` is 100, the limit ceiling on most endpoints. `/results` and
`/countries` take 500.

## Errors

Everything raised is a `GoalAPIError`. Branch only where you'd actually behave
differently:

```python
from goal_api import GoalAPIError, NotFoundError, RateLimitError, ValidationError

try:
    fixture = goal.fixtures.get(fixture_id)
except NotFoundError:
    fixture = None
except RateLimitError as error:
    print(f"Quota exhausted ({error.rate_limit_type}), retry in {error.retry_after}s")
    raise
except ValidationError as error:
    print(error.details)        # which field the server rejected
    raise
except GoalAPIError as error:
    print(error.code, error.correlation_id)
    raise
```

### Two error shapes

The API answers with one of two bodies, and the SDK normalises both:

| | Gateway (auth, routing, rate limits) | Football service (most endpoints) |
|---|---|---|
| text | `message` | `error` |
| `code` | yes | yes |
| `category` | yes | no |
| `correlationId` | yes | **no** |
| `details` | object | array, on validation errors |

So `error.message` and `error.code` are always populated, and `error.correlation_id` is
only set on gateway errors. Quote it in a support ticket when you have it.

### Rate limits

```python
goal.fixtures.live()
goal.rate_limit.remaining   # int | None
goal.rate_limit.reset       # unix seconds
goal.rate_limit.type        # "DAILY" | "MONTHLY"
```

## Live WebSocket updates

> The socket is at `wss://api.goal-api.com/ws`, **not** `/v1/ws`. Only nginx's
> `location ^~ /ws` carries the `Upgrade` headers; `/v1/ws` is proxied as ordinary HTTP and
> answers 200 instead of upgrading. The SDK derives the right URL for you.
>
> Two services authenticate: the gateway authorises the upgrade from the header or
> `?wsToken=`, then websocket-service needs an `{"type": "auth", ...}` frame as the very
> first message. The SDK sends it, and treats `auth_success` as the point the connection is
> usable.
>
> **`subscribe` is capped per plan and the cap can be 0.** `auth_success` reports
> `maxSubscriptions`; if it is 0 the socket works but no `match_update` will ever arrive.
> See the known server issue in [`ENDPOINTS.md`](ENDPOINTS.md).

Needs the `live` extra. WebSockets are async, so this is async even on the sync client.

```python
import asyncio
from goal_api import GoalAPI

async def watch(fixture_id):
    goal = GoalAPI(api_key)
    live = goal.live()
    async with live:
        live.subscribe(fixture_id)
        async for message in live:
            if message["type"] == "match_update":
                print(message["data"])

asyncio.run(watch("fixture-id"))
```

Or register handlers and run in the background:

```python
live.on("match_update", lambda m: print(m["data"]))
live.on("error", lambda m: print("error:", m))
await live.connect()
live.subscribe(fixture_id)
await live.run_forever()
```

- Python clients authenticate the handshake with the `Authorization` header, so no token
  round trip.
- Reconnects with backoff and replays your subscriptions. `await live.close()` opts out.
- `subscribe()` before `connect()` is fine; it's replayed on open.
- Server caps client messages at 60/minute and concurrent subscriptions by plan.
- A slow consumer drops the oldest queued message rather than stalling the socket.

Message types: `match_update`, `auth_success`, `status`, `pong`, `server_shutdown`,
`error`. Use `on("*", ...)` for everything.

### Handing a token to a browser

Your frontend must never see your API key. Mint a single-use token server-side instead:

```python
from goal_api.live import mint_connect_token

token = mint_connect_token(goal)["data"]["token"]
# browser: new WebSocket(`wss://api.goal-api.com/v1/ws?wsToken=${token}`)
```

## Webhooks

Verify against the **raw** body. A parsed-and-reserialized dict has different bytes and
will never match.

```python
from fastapi import FastAPI, Request, Response
from goal_api import verify_webhook, WebhookSignatureError

app = FastAPI()

@app.post("/goal-webhooks")
async def hook(request: Request):
    try:
        event = verify_webhook(
            await request.body(),
            request.headers.get("x-goal-signature"),
            os.environ["GOAL_WEBHOOK_SECRET"],
        )
    except WebhookSignatureError:
        return Response(status_code=400)

    if request.headers.get("x-goal-event") == "goal.scored":
        ...
    return Response(status_code=200)   # ack fast; retries are ~1m, 5m, 25m, 2h, 10h
```

Timestamps outside 300s are rejected as replays. Override with `tolerance=`.

## Escape hatch

For an endpoint this SDK doesn't wrap yet:

```python
data = goal.request("/some/new/endpoint", {"limit": 10})
```

## Constants

```python
from goal_api import MATCH_STATUSES, PLAYER_TYPES, PLAYER_STATS, HALVES
```

## Examples

| File | Shows |
|---|---|
| [`examples/basic.py`](examples/basic.py) | Status, live fixtures, standings, pagination |
| [`examples/live_scores.py`](examples/live_scores.py) | The live socket: connect, subscribe, print every frame |
| [`examples/webhook_server.py`](examples/webhook_server.py) | Verifying a webhook against the raw request bytes |
| [`examples/bulk_export.py`](examples/bulk_export.py) | Walking every page of a collection to CSV |

```bash
GOAL_API_KEY=...          python examples/live_scores.py
GOAL_WEBHOOK_SECRET=...   python examples/webhook_server.py
GOAL_API_KEY=...          python examples/bulk_export.py > countries.csv
```

## Testing

```bash
pip install -e ".[dev]"
pytest -q                       # unit tests, no network
GOAL_API_KEY=... pytest -q      # also runs the live tests against the real API
```

The live tests skip themselves without a key. Endpoint-by-endpoint coverage of the API
lives in `tools/sweep.py` in the SDK workspace.

## Other languages

Four more first-party clients over the same API, with the same resource groups, the same
retry and pagination behaviour and the same error types. All five release in lockstep, so
a version number means the same surface everywhere.

| Language | Package | Install |
|---|---|---|
| [JavaScript / TypeScript](https://github.com/goal-api/goal-api-js) | [`@goalapi/sdk`](https://www.npmjs.com/package/@goalapi/sdk) | `npm install @goalapi/sdk` |
| [Go](https://github.com/goal-api/goal-api-go) | [`goal-api-go`](https://pkg.go.dev/github.com/goal-api/goal-api-go) | `go get github.com/goal-api/goal-api-go` |
| [Dart / Flutter](https://github.com/goal-api/goal-api-dart) | [`goal_api`](https://pub.dev/packages/goal_api) | `dart pub add goal_api` |
| [PHP](https://github.com/goal-api/goal-api-php) | [`goal-api/sdk`](https://packagist.org/packages/goal-api/sdk) | `composer require goal-api/sdk` |

Each one is its own repository and carries the same [`ENDPOINTS.md`](ENDPOINTS.md), the
API contract derived from the running service.

## Licence

MIT. See [LICENSE](LICENSE).

Runtime dependencies and their licences are in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). The short version: `httpx` (BSD-3-Clause),
plus `websockets` (BSD-3-Clause) only if you install the `live` extra. One transitive
dependency, `certifi`, is MPL-2.0 rather than permissive, which is called out there in case
your licence policy cares.

Security issues: [SECURITY.md](SECURITY.md).
