"""Sync and async client tests against httpx.MockTransport. No network.

Covers request shape (URL, headers, param encoding), error mapping, retries, pagination
and webhook signing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import httpx
import pytest

from goal_api import (
    AsyncGoalAPI,
    GoalAPI,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    TimeoutError as GoalTimeoutError,
    ValidationError,
    WebhookSignatureError,
    verify_webhook,
)


def make_client(handler, **kwargs):
    """Sync client on a scripted handler. Retries off unless a test asks for them."""
    transport = httpx.MockTransport(handler)
    kwargs.setdefault("max_retries", 0)
    return GoalAPI("test-key", http_client=httpx.Client(transport=transport), **kwargs)


def make_async_client(handler, **kwargs):
    transport = httpx.MockTransport(handler)
    kwargs.setdefault("max_retries", 0)
    return AsyncGoalAPI("test-key", http_client=httpx.AsyncClient(transport=transport), **kwargs)


def ok(payload, headers=None):
    return lambda request: httpx.Response(200, json=payload, headers=headers or {})


def recorder(payload=None, headers=None):
    """Records requests and replays one response."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=payload or {"success": True, "data": []}, headers=headers or {})

    handler.seen = seen  # type: ignore[attr-defined]
    return handler


# ------------------------------------------------------------------ request shape


def test_api_key_is_required():
    with pytest.raises(ValueError, match="api_key is required"):
        GoalAPI("")


def test_sends_bearer_header_to_the_right_url():
    handler = recorder({"success": True, "data": [{"id": "x"}]})
    with make_client(handler) as goal:
        assert goal.fixtures.live()["data"] == [{"id": "x"}]

    request = handler.seen[0]
    assert str(request.url) == "https://api.goal-api.com/v1/fixtures/live"
    assert request.headers["authorization"] == "Bearer test-key"
    assert request.headers["user-agent"].startswith("goal-api-python/")


def test_drops_none_params_and_lowercases_booleans():
    handler = recorder()
    with make_client(handler) as goal:
        goal.fixtures.list(leagueId="L1", status=None, teamId=None, offset=0, live=False)

    query = handler.seen[0].url.params
    assert query["leagueId"] == "L1"
    assert query["offset"] == "0"
    assert query["live"] == "false"  # the API validates the literal strings
    assert "status" not in query
    assert "teamId" not in query


def test_encodes_path_segments():
    handler = recorder()
    with make_client(handler) as goal:
        goal.coaches.by_country("Trinidad And Tobago")

    # raw_path is what goes on the wire; .path is the decoded view.
    assert handler.seen[0].url.raw_path == b"/v1/coaches/country/Trinidad%20And%20Tobago"


def test_a_slash_in_an_id_cannot_escape_its_segment():
    handler = recorder()
    with make_client(handler) as goal:
        goal.fixtures.get("../../admin")

    assert handler.seen[0].url.raw_path == b"/v1/fixtures/..%2F..%2Fadmin"


def test_empty_path_segment_is_rejected_before_the_request():
    handler = recorder()
    with make_client(handler) as goal:
        with pytest.raises(ValueError, match="Path segment is required"):
            goal.fixtures.get("")
    assert handler.seen == []


def test_compare_joins_ids_with_commas():
    handler = recorder()
    with make_client(handler) as goal:
        goal.players.compare(["p1", "p2", "p3"])
    assert handler.seen[0].url.params["ids"] == "p1,p2,p3"


def test_compare_accepts_a_prejoined_string():
    handler = recorder()
    with make_client(handler) as goal:
        goal.players.compare("p1,p2")
    assert handler.seen[0].url.params["ids"] == "p1,p2"


def test_search_puts_q_in_the_query():
    handler = recorder()
    with make_client(handler) as goal:
        goal.players.search("haaland", limit=5)
    params = handler.seen[0].url.params
    assert params["q"] == "haaland" and params["limit"] == "5"


def test_every_resource_group_is_attached():
    with make_client(recorder()) as goal:
        for group in ("status", "countries", "leagues", "teams", "fixtures", "standings",
                      "players", "coaches", "h2h", "results", "videos", "odds", "predictions"):
            assert hasattr(goal, group), group


# ------------------------------------------------------------------ errors


def test_public_endpoints_return_the_bare_body():
    body = {"status": "operational", "components": [{"name": "API", "status": "operational"}]}
    with make_client(ok(body)) as goal:
        status = goal.status.get()

    assert status["status"] == "operational"
    assert len(status["components"]) == 1
    assert "data" not in status


def test_coverage_leagues_paginates_with_page_not_offset():
    handler = recorder({"leagues": [], "total": 0, "page": 2, "limit": 50, "pages": 1})
    with make_client(handler) as goal:
        goal.status.coverage_leagues(page=2, limit=50, country="England")

    query = handler.seen[0].url.params
    assert query["page"] == "2"
    assert query["limit"] == "50"
    assert query["country"] == "England"
    assert "offset" not in query


def test_maps_400_to_validation_error_and_keeps_envelope_fields():
    body = {
        "success": False,
        "message": "League ID is required",
        "code": "VALIDATION_ERROR",
        "category": "validation",
        "details": {"field": "id"},
        "correlationId": "abc-123",
    }
    with make_client(lambda r: httpx.Response(400, json=body)) as goal:
        with pytest.raises(ValidationError) as excinfo:
            goal.leagues.get("bad")

    error = excinfo.value
    assert error.status == 400
    assert error.code == "VALIDATION_ERROR"
    assert error.correlation_id == "abc-123"
    assert error.details == {"field": "id"}
    assert "correlation_id=abc-123" in str(error)


def test_maps_404_to_not_found():
    body = {"success": False, "message": "Fixture not found", "code": "NOT_FOUND"}
    with make_client(lambda r: httpx.Response(404, json=body)) as goal:
        with pytest.raises(NotFoundError):
            goal.fixtures.get("nope")


def test_429_carries_retry_after_and_quota_headers():
    body = {"success": False, "message": "Too many requests", "code": "RATE_LIMIT_EXCEEDED"}
    headers = {
        "retry-after": "42",
        "x-ratelimit-limit": "1000",
        "x-ratelimit-remaining": "0",
        "x-ratelimit-reset": "1800000000",
        "x-ratelimit-type": "DAILY",
    }
    with make_client(lambda r: httpx.Response(429, json=body, headers=headers)) as goal:
        with pytest.raises(RateLimitError) as excinfo:
            goal.fixtures.live()

    error = excinfo.value
    assert error.retry_after == 42
    assert error.limit == 1000
    assert error.rate_limit_type == "DAILY"


def test_html_error_body_still_produces_a_useful_message():
    handler = lambda r: httpx.Response(502, text="<html><body>502 Bad Gateway</body></html>")
    with make_client(handler) as goal:
        with pytest.raises(Exception, match="502 Bad Gateway"):
            goal.fixtures.live()


def test_records_rate_limit_snapshot_from_a_success():
    headers = {
        "x-ratelimit-limit": "10000",
        "x-ratelimit-remaining": "9997",
        "x-ratelimit-reset": "1800000000",
        "x-ratelimit-type": "MONTHLY",
    }
    with make_client(recorder(headers=headers)) as goal:
        goal.results.today()
        assert goal.rate_limit.as_dict() == {
            "limit": 10000, "remaining": 9997, "reset": 1800000000, "type": "MONTHLY",
        }


def test_public_endpoint_without_quota_headers_leaves_snapshot_untouched():
    with make_client(recorder()) as goal:
        goal.status.get()
        assert goal.rate_limit.limit is None


def test_timeout_becomes_goal_timeout_error():
    def handler(request):
        raise httpx.ReadTimeout("too slow", request=request)

    with make_client(handler) as goal:
        with pytest.raises(GoalTimeoutError):
            goal.fixtures.live()


# ------------------------------------------------------------------ retries


def test_retries_a_503_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"success": False, "message": "down", "code": "SERVICE_UNAVAILABLE"})
        return httpx.Response(200, json={"success": True, "data": [1]})

    with make_client(handler, max_retries=2) as goal:
        assert goal.fixtures.live()["data"] == [1]
    assert calls["n"] == 2


def test_does_not_retry_a_400():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(400, json={"success": False, "message": "bad", "code": "VALIDATION_ERROR"})

    with make_client(handler, max_retries=3) as goal:
        with pytest.raises(ValidationError):
            goal.fixtures.live()
    assert calls["n"] == 1


def test_raises_the_last_error_when_retries_run_out():
    def handler(request):
        return httpx.Response(503, json={"success": False, "message": "still down", "code": "SERVICE_UNAVAILABLE"})

    with make_client(handler, max_retries=1) as goal:
        with pytest.raises(ServiceUnavailableError, match="still down"):
            goal.fixtures.live()


# ------------------------------------------------------------------ pagination


def test_paginate_walks_pages_and_stops_on_has_more_false():
    pages = [
        {"success": True, "data": [{"id": 1}, {"id": 2}], "pagination": {"total": 3, "limit": 2, "offset": 0, "hasMore": True}},
        {"success": True, "data": [{"id": 3}], "pagination": {"total": 3, "limit": 2, "offset": 2, "hasMore": False}},
    ]
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=pages[min(len(seen) - 1, len(pages) - 1)])

    with make_client(handler) as goal:
        items = goal.collect(lambda **p: goal.teams.list(**p), page_size=2)

    assert [i["id"] for i in items] == [1, 2, 3]
    assert seen[1].url.params["offset"] == "2"


def test_paginate_honours_max_items_without_fetching_further_pages():
    page = {"success": True, "data": [{"id": 1}, {"id": 2}], "pagination": {"total": 99, "limit": 2, "offset": 0, "hasMore": True}}
    handler = recorder(page)
    with make_client(handler) as goal:
        items = goal.collect(lambda **p: goal.teams.list(**p), page_size=2, max_items=2)

    assert len(items) == 2
    assert len(handler.seen) == 1


def test_paginate_stops_on_a_short_page_when_pagination_is_absent():
    handler = recorder({"success": True, "data": [{"id": 1}]})
    with make_client(handler) as goal:
        items = goal.collect(lambda **p: goal.videos.list(**p), page_size=10)

    assert len(items) == 1
    assert len(handler.seen) == 1


# ------------------------------------------------------------------ async client


@pytest.mark.asyncio
async def test_async_client_mirrors_the_sync_surface():
    handler = recorder({"success": True, "data": [{"id": "x"}]})
    async with make_async_client(handler) as goal:
        page = await goal.fixtures.live()
    assert page["data"] == [{"id": "x"}]
    assert handler.seen[0].headers["authorization"] == "Bearer test-key"


@pytest.mark.asyncio
async def test_async_errors_map_the_same_way():
    body = {"success": False, "message": "nope", "code": "NOT_FOUND"}
    async with make_async_client(lambda r: httpx.Response(404, json=body)) as goal:
        with pytest.raises(NotFoundError):
            await goal.teams.get("missing")


@pytest.mark.asyncio
async def test_async_paginate_yields_across_pages():
    pages = [
        {"success": True, "data": [{"id": 1}], "pagination": {"total": 2, "limit": 1, "offset": 0, "hasMore": True}},
        {"success": True, "data": [{"id": 2}], "pagination": {"total": 2, "limit": 1, "offset": 1, "hasMore": False}},
    ]
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=pages[min(len(seen) - 1, len(pages) - 1)])

    async with make_async_client(handler) as goal:
        items = await goal.collect(lambda **p: goal.leagues.list(**p), page_size=1)

    assert [i["id"] for i in items] == [1, 2]


@pytest.mark.asyncio
async def test_async_retries_a_503():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"success": False, "message": "down"})
        return httpx.Response(200, json={"success": True, "data": []})

    async with make_async_client(handler, max_retries=2) as goal:
        await goal.fixtures.live()
    assert calls["n"] == 2


# ------------------------------------------------------------------ webhooks

SECRET = "whsec_test"


def sign(body: str, timestamp: int) -> str:
    digest = hmac.new(SECRET.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def test_verify_webhook_accepts_a_correct_signature():
    body = json.dumps({"event": "goal.scored", "matchId": "m1"})
    now = int(time.time())
    assert verify_webhook(body, sign(body, now), SECRET) == {"event": "goal.scored", "matchId": "m1"}


def test_verify_webhook_accepts_raw_bytes():
    body = json.dumps({"event": "match.started"})
    now = int(time.time())
    assert verify_webhook(body.encode(), sign(body, now), SECRET)["event"] == "match.started"


def test_verify_webhook_rejects_a_tampered_body():
    body = json.dumps({"homeScore": 1})
    signature = sign(body, int(time.time()))
    with pytest.raises(WebhookSignatureError, match="does not match"):
        verify_webhook(json.dumps({"homeScore": 9}), signature, SECRET)


def test_verify_webhook_rejects_a_replayed_timestamp():
    body = json.dumps({"event": "goal.scored"})
    old = int(time.time()) - 4000
    with pytest.raises(WebhookSignatureError, match="outside the 300s tolerance"):
        verify_webhook(body, sign(body, old), SECRET)


def test_verify_webhook_allows_disabling_the_tolerance_check():
    body = json.dumps({"event": "goal.scored"})
    old = int(time.time()) - 4000
    assert verify_webhook(body, sign(body, old), SECRET, tolerance=0)["event"] == "goal.scored"


def test_verify_webhook_rejects_malformed_and_missing_headers():
    with pytest.raises(WebhookSignatureError, match="Malformed"):
        verify_webhook("{}", "garbage", SECRET)
    with pytest.raises(WebhookSignatureError, match="Missing"):
        verify_webhook("{}", None, SECRET)


def test_verify_webhook_rejects_a_wrong_secret():
    body = json.dumps({"a": 1})
    with pytest.raises(WebhookSignatureError, match="does not match"):
        verify_webhook(body, sign(body, int(time.time())), "whsec_other")
