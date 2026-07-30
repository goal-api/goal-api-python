"""Runs against the real API. Skipped unless GOAL_API_KEY is set.

Endpoint-by-endpoint coverage lives in ../tools/sweep.py. This checks the parts
that are the SDK's job: auth, param encoding, envelope handling, pagination across real
pages, error mapping and the quota snapshot.
"""

from __future__ import annotations

import os

import pytest

from goal_api import (
    AsyncGoalAPI,
    AuthenticationError,
    GoalAPI,
    NotFoundError,
    ValidationError,
)

API_KEY = os.environ.get("GOAL_API_KEY", "")

pytestmark = pytest.mark.skipif(not API_KEY, reason="GOAL_API_KEY is not set")


@pytest.fixture(scope="module")
def goal():
    with GoalAPI(API_KEY, timeout=30.0) as client:
        yield client


def test_status_returns_the_bare_body(goal):
    status = goal.status.get()
    assert isinstance(status["status"], str)
    assert isinstance(status["components"], list)
    assert "data" not in status, "/public/* must not be wrapped in an envelope"


def test_coverage_leagues_paginates_with_page(goal):
    page = goal.status.coverage_leagues(page=1, limit=5)
    assert isinstance(page["leagues"], list)
    assert len(page["leagues"]) <= 5
    assert isinstance(page["total"], int)
    assert isinstance(page["pages"], int)


def test_leagues_list_returns_the_envelope(goal):
    page = goal.leagues.list(isActive=True, limit=3)
    assert page["success"] is True
    assert isinstance(page["data"], list)
    assert len(page["data"]) <= 3
    assert isinstance(page["pagination"]["total"], int)
    assert page["source"] in ("cache", "database")


def test_quota_snapshot_is_populated(goal):
    goal.leagues.list(limit=1)
    quota = goal.rate_limit
    assert isinstance(quota.limit, int)
    assert quota.remaining <= quota.limit
    assert quota.type in ("DAILY", "MONTHLY")


def test_fixtures_live(goal):
    page = goal.fixtures.live()
    assert page["success"] is True
    assert isinstance(page["data"], list)


def test_a_real_league_resolves_through_nested_endpoints(goal):
    leagues = goal.leagues.list(isActive=True, limit=1)["data"]
    assert leagues, "expected at least one active league"
    league_id = leagues[0]["id"]

    assert goal.leagues.teams(league_id, limit=5)["success"] is True
    assert goal.leagues.fixtures(league_id, limit=5)["success"] is True


def test_paginate_walks_real_pages(goal):
    seen = [row["id"] for row in goal.paginate(
        lambda **p: goal.countries.list(**p), page_size=20, max_items=45)]
    assert len(seen) > 20, "expected pagination to cross a page boundary"
    assert len(set(seen)) == len(seen), "pagination returned duplicates"


def test_date_range_params_are_accepted(goal):
    # `from` is a Python keyword, so it can only be passed through a dict.
    window = {"from": "2026-07-01", "to": "2026-07-07"}
    page = goal.results.list(limit=5, **window)
    assert page["success"] is True


def test_players_search(goal):
    page = goal.players.search("silva", limit=3)
    assert page["success"] is True
    assert len(page["data"]) <= 3


def test_unknown_id_raises_not_found(goal):
    with pytest.raises(NotFoundError) as excinfo:
        goal.fixtures.get("definitely-not-a-real-id")

    error = excinfo.value
    assert error.status == 404
    assert error.code == "FIXTURE_NOT_FOUND"
    # football-service puts the text in `error`, not `message`; the SDK normalises both.
    assert error.message


def test_bad_enum_raises_validation_error_with_details(goal):
    with pytest.raises(ValidationError) as excinfo:
        goal.players.top("not-a-real-stat")

    error = excinfo.value
    assert error.status == 400
    assert error.code == "VALIDATION_ERROR"
    assert isinstance(error.details, list), "expected express-validator details"


def test_bad_key_raises_authentication_error():
    with GoalAPI("gapi_not_a_real_key", max_retries=0) as bad:
        with pytest.raises(AuthenticationError):
            bad.leagues.list(limit=1)


@pytest.mark.asyncio
async def test_async_client_against_the_real_api():
    async with AsyncGoalAPI(API_KEY, timeout=30.0) as goal:
        status, page = await goal.status.get(), await goal.leagues.list(limit=2)
        assert isinstance(status["status"], str)
        assert page["success"] is True

        collected = await goal.collect(
            lambda **p: goal.countries.list(**p), page_size=20, max_items=25)
        assert len(collected) > 20
