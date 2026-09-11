"""One class per endpoint group, shared by the sync and async clients.

The methods just return whatever the transport gives back, so the same definition serves
``goal.teams.list()`` and ``await goal.teams.list()``.

Rows stay dicts rather than dataclasses -- they are provider-shaped and change. Accepted
params and limit ceilings: ENDPOINTS.md
"""

from __future__ import annotations

from typing import Any, Dict, Iterable

from ._transport import csv, quote_segment as _q

# Evaluated at runtime, so typing.Dict rather than dict[...] to keep Python 3.9 working.
Response = Dict[str, Any]


class _Resource:
    __slots__ = ("_t",)

    def __init__(self, transport: Any) -> None:
        self._t = transport


class Status(_Resource):
    """Unauthenticated status and coverage. No API key needed.

    These five do not use the ``{"success", "data"}`` envelope -- they return bare
    objects, so read ``goal.status.get()["status"]``, not ``["data"]["status"]``.
    """

    def get(self) -> Response:
        """``{status, updatedAt, measurement, components[]}``"""
        return self._t.get("/public/status")

    def coverage(self) -> Response:
        """``{leagues, countries, teams, players, fixtures, ...}``"""
        return self._t.get("/public/coverage")

    def coverage_leagues(self, **params: Any) -> Response:
        """``{leagues[], total, page, limit, pages}``

        Paginates with ``page``/``limit``, not ``offset``, so ``paginate()`` will not work
        here. Also accepts ``q`` and ``country``.
        """
        return self._t.get("/public/coverage/leagues", params)

    def coverage_countries(self) -> Response:
        """``{countries[], total}``"""
        return self._t.get("/public/coverage/countries")

    def coverage_league(self, league_id: Any) -> Response:
        """A bare league object. The 404 body is ``{error, code}``."""
        return self._t.get(f"/public/coverage/leagues/{_q(league_id)}")


class Countries(_Resource):
    def list(self, **params: Any) -> Response:
        return self._t.get("/countries", params)

    def get(self, country_id: Any) -> Response:
        return self._t.get(f"/countries/{_q(country_id)}")

    def leagues(self, country_id: Any, **params: Any) -> Response:
        return self._t.get(f"/countries/{_q(country_id)}/leagues", params)


class Leagues(_Resource):
    def list(self, **params: Any) -> Response:
        return self._t.get("/leagues", params)

    def get(self, league_id: Any) -> Response:
        return self._t.get(f"/leagues/{_q(league_id)}")

    def teams(self, league_id: Any, **params: Any) -> Response:
        return self._t.get(f"/leagues/{_q(league_id)}/teams", params)

    def standings(self, league_id: Any, **params: Any) -> Response:
        return self._t.get(f"/leagues/{_q(league_id)}/standings", params)

    def fixtures(self, league_id: Any, **params: Any) -> Response:
        return self._t.get(f"/leagues/{_q(league_id)}/fixtures", params)

    def top_scorers(self, league_id: Any, **params: Any) -> Response:
        return self._t.get(f"/leagues/{_q(league_id)}/top-scorers", params)

    def results(self, league_id: Any, **params: Any) -> Response:
        return self._t.get(f"/leagues/{_q(league_id)}/results", params)


class Teams(_Resource):
    def list(self, **params: Any) -> Response:
        return self._t.get("/teams", params)

    def get(self, team_id: Any, **params: Any) -> Response:
        return self._t.get(f"/teams/{_q(team_id)}", params)

    def players(self, team_id: Any, **params: Any) -> Response:
        return self._t.get(f"/teams/{_q(team_id)}/players", params)

    def fixtures(self, team_id: Any, **params: Any) -> Response:
        return self._t.get(f"/teams/{_q(team_id)}/fixtures", params)

    def results(self, team_id: Any, **params: Any) -> Response:
        return self._t.get(f"/teams/{_q(team_id)}/results", params)

    def statistics(self, team_id: Any, **params: Any) -> Response:
        return self._t.get(f"/teams/{_q(team_id)}/statistics", params)

    def upcoming(self, team_id: Any, **params: Any) -> Response:
        return self._t.get(f"/teams/{_q(team_id)}/upcoming", params)


class Fixtures(_Resource):
    def list(self, **params: Any) -> Response:
        return self._t.get("/fixtures", params)

    def live(self, **params: Any) -> Response:
        return self._t.get("/fixtures/live", params)

    def by_date(self, date: str, **params: Any) -> Response:
        return self._t.get(f"/fixtures/date/{_q(date)}", params)

    def get(self, fixture_id: Any) -> Response:
        return self._t.get(f"/fixtures/{_q(fixture_id)}")

    def events(self, fixture_id: Any) -> Response:
        return self._t.get(f"/fixtures/{_q(fixture_id)}/events")

    def lineups(self, fixture_id: Any) -> Response:
        return self._t.get(f"/fixtures/{_q(fixture_id)}/lineups")

    def statistics(self, fixture_id: Any, **params: Any) -> Response:
        return self._t.get(f"/fixtures/{_q(fixture_id)}/statistics", params)

    def cards(self, fixture_id: Any) -> Response:
        return self._t.get(f"/fixtures/{_q(fixture_id)}/cards")

    def substitutions(self, fixture_id: Any) -> Response:
        return self._t.get(f"/fixtures/{_q(fixture_id)}/substitutions")

    # These four accept a matchApiId as well as a fixture id.
    def odds(self, fixture_id: Any) -> Response:
        return self._t.get(f"/fixtures/{_q(fixture_id)}/odds")

    def predictions(self, fixture_id: Any) -> Response:
        return self._t.get(f"/fixtures/{_q(fixture_id)}/predictions")

    def live_odds(self, fixture_id: Any) -> Response:
        return self._t.get(f"/fixtures/{_q(fixture_id)}/live-odds")

    def commentary(self, fixture_id: Any) -> Response:
        return self._t.get(f"/fixtures/{_q(fixture_id)}/commentary")


class Standings(_Resource):
    def get(self, league_id: Any, **params: Any) -> Response:
        return self._t.get(f"/standings/{_q(league_id)}", params)

    def team(self, league_id: Any, team_id: Any) -> Response:
        return self._t.get(f"/standings/{_q(league_id)}/team/{_q(team_id)}")

    def home(self, league_id: Any, **params: Any) -> Response:
        return self._t.get(f"/standings/{_q(league_id)}/home", params)

    def away(self, league_id: Any, **params: Any) -> Response:
        return self._t.get(f"/standings/{_q(league_id)}/away", params)

    def form(self, league_id: Any, **params: Any) -> Response:
        return self._t.get(f"/standings/{_q(league_id)}/form", params)

    def zones(self, league_id: Any, **params: Any) -> Response:
        return self._t.get(f"/standings/{_q(league_id)}/zones", params)


class Players(_Resource):
    def list(self, **params: Any) -> Response:
        return self._t.get("/players", params)

    def search(self, q: str, **params: Any) -> Response:
        return self._t.get("/players/search", {**params, "q": q})

    def compare(self, ids: Iterable[Any] | str) -> Response:
        """2-5 ids, as a sequence or an already-joined string."""
        return self._t.get("/players/compare", {"ids": csv(ids)})

    def top(self, stat: str, **params: Any) -> Response:
        return self._t.get(f"/players/top/{_q(stat)}", params)

    def get(self, player_id: Any) -> Response:
        return self._t.get(f"/players/{_q(player_id)}")

    def statistics(self, player_id: Any, **params: Any) -> Response:
        return self._t.get(f"/players/{_q(player_id)}/statistics", params)


class Coaches(_Resource):
    def list(self, **params: Any) -> Response:
        return self._t.get("/coaches", params)

    def search(self, q: str, **params: Any) -> Response:
        return self._t.get("/coaches/search", {**params, "q": q})

    def by_country(self, country: str, **params: Any) -> Response:
        return self._t.get(f"/coaches/country/{_q(country)}", params)

    def by_team(self, team_id: Any) -> Response:
        return self._t.get(f"/coaches/team/{_q(team_id)}")

    def get(self, coach_id: Any) -> Response:
        return self._t.get(f"/coaches/{_q(coach_id)}")


class HeadToHead(_Resource):
    def get(self, team1_id: Any, team2_id: Any) -> Response:
        return self._t.get(f"/h2h/{_q(team1_id)}/{_q(team2_id)}")

    def direct(self, team1_id: Any, team2_id: Any, **params: Any) -> Response:
        return self._t.get(f"/h2h/{_q(team1_id)}/{_q(team2_id)}/direct", params)

    def stats(self, team1_id: Any, team2_id: Any) -> Response:
        return self._t.get(f"/h2h/{_q(team1_id)}/{_q(team2_id)}/stats")


class Results(_Resource):
    def list(self, **params: Any) -> Response:
        return self._t.get("/results", params)

    def today(self) -> Response:
        return self._t.get("/results/today")

    def yesterday(self) -> Response:
        return self._t.get("/results/yesterday")

    def stats(self, **params: Any) -> Response:
        return self._t.get("/results/stats", params)

    def high_scoring(self, **params: Any) -> Response:
        return self._t.get("/results/high-scoring", params)

    def by_date(self, date: str) -> Response:
        return self._t.get(f"/results/date/{_q(date)}")

    def by_league(self, league_id: Any, **params: Any) -> Response:
        return self._t.get(f"/results/league/{_q(league_id)}", params)

    def by_team(self, team_id: Any, **params: Any) -> Response:
        return self._t.get(f"/results/team/{_q(team_id)}", params)


class Videos(_Resource):
    def list(self, **params: Any) -> Response:
        return self._t.get("/videos", params)

    def recent(self, **params: Any) -> Response:
        return self._t.get("/videos/recent", params)

    def by_match(self, match_id: Any) -> Response:
        return self._t.get(f"/videos/match/{_q(match_id)}")

    def by_league(self, league_id: Any, **params: Any) -> Response:
        return self._t.get(f"/videos/league/{_q(league_id)}", params)

    def by_date(self, date: str, **params: Any) -> Response:
        return self._t.get(f"/videos/date/{_q(date)}", params)


class News(_Resource):
    def list(self, **params: Any) -> Response:
        """Articles newest first.

        Filters: ``leagueId``, ``teamId``, ``matchId``, ``from``, ``to``, ``limit``,
        ``offset``. Parameter names go to the wire verbatim, and ``from`` is a Python
        keyword, so the date range has to be splatted::

            client.news.list(leagueId="3", **{"from": "2026-09-01", "to": "2026-09-08"})

        That is true of every date-range endpoint in this SDK, not only this one.
        """
        return self._t.get("/news", params)

    def by_match(self, match_id: Any, **params: Any) -> Response:
        return self._t.get(f"/news/match/{_q(match_id)}", params)

    def by_team(self, team_id: Any, **params: Any) -> Response:
        return self._t.get(f"/news/team/{_q(team_id)}", params)

    def by_league(self, league_id: Any, **params: Any) -> Response:
        return self._t.get(f"/news/league/{_q(league_id)}", params)

    def get(self, article_id: Any) -> Response:
        """One article, by our id or the provider's news key. 404s when absent."""
        return self._t.get(f"/news/{_q(article_id)}")


class Odds(_Resource):
    def list(self, **params: Any) -> Response:
        return self._t.get("/odds", params)


class Predictions(_Resource):
    def list(self, **params: Any) -> Response:
        return self._t.get("/predictions", params)


ALL_RESOURCES: dict[str, type[_Resource]] = {
    "status": Status,
    "countries": Countries,
    "leagues": Leagues,
    "teams": Teams,
    "fixtures": Fixtures,
    "standings": Standings,
    "players": Players,
    "coaches": Coaches,
    "h2h": HeadToHead,
    "results": Results,
    "videos": Videos,
    "news": News,
    "odds": Odds,
    "predictions": Predictions,
}
