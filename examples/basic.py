"""GOAL_API_KEY=... python examples/basic.py

The status section works without a key.
"""

from __future__ import annotations

import os
import sys

from goal_api import GoalAPI, GoalAPIError, RateLimitError

api_key = os.environ.get("GOAL_API_KEY")

with GoalAPI(api_key or "unset") as goal:
    # --- public status: no API key required ---------------------------------
    status = goal.status.get()
    print(f"Platform: {status.get('status')}")
    for component in status.get("components", []):
        uptime = (component.get("uptime") or {}).get("24h")
        print(f"  {component['name']:<28} {component['status']:<14} 24h {uptime}%")

    if not api_key:
        print("\nSet GOAL_API_KEY to run the authenticated examples.")
        sys.exit(0)

    try:
        # --- live matches ---------------------------------------------------
        live = goal.fixtures.live()["data"]
        print(f"\n{len(live)} match(es) in play")
        for match in live[:5]:
            home = (match.get("homeTeam") or {}).get("name", "?")
            away = (match.get("awayTeam") or {}).get("name", "?")
            print(f"  {home} {match.get('homeScore', 0)}-{match.get('awayScore', 0)} {away}"
                  f"  ({match.get('minute', '?')}')")

        # --- pick a league and read its table -------------------------------
        leagues = goal.leagues.list(isActive=True, limit=1)["data"]
        if leagues:
            league = leagues[0]
            print(f"\nStandings: {league['name']}")
            table = goal.leagues.standings(league["id"])["data"]
            for row in (table if isinstance(table, list) else [])[:5]:
                name = (row.get("team") or {}).get("name") or row.get("teamName", "?")
                print(f"  {str(row.get('position', '?')):>2}. {name:<24} {row.get('points')} pts")

            print(f"\nTop scorers: {league['name']}")
            scorers = goal.leagues.top_scorers(league["id"], limit=5)["data"]
            for scorer in scorers if isinstance(scorers, list) else []:
                name = (scorer.get("player") or {}).get("name") or scorer.get("name", "?")
                print(f"  {name:<24} {scorer.get('goals', 0)}")

            # --- pagination across every team in the league ------------------
            teams = goal.collect(lambda **p: goal.leagues.teams(league["id"], **p))
            print(f"\n{len(teams)} teams in {league['name']}")

        print("\nQuota:", goal.rate_limit.as_dict())

    except RateLimitError as error:
        print(f"Rate limited ({error.rate_limit_type}). Retry in {error.retry_after}s.", file=sys.stderr)
        sys.exit(1)
    except GoalAPIError as error:
        print(f"{error.code or 'ERROR'}: {error.message} [{error.correlation_id}]", file=sys.stderr)
        sys.exit(1)
