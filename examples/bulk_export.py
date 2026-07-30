"""GOAL_API_KEY=... python examples/bulk_export.py > countries.csv

Walks every page of a collection and streams it out as CSV. Shows paginate() doing the page
walking, and that limit ceilings differ per endpoint.
"""

from __future__ import annotations

import csv
import os
import sys

from goal_api import GoalAPI


def main() -> int:
    api_key = os.environ.get("GOAL_API_KEY", "")
    if not api_key:
        print("GOAL_API_KEY is not set.", file=sys.stderr)
        return 2

    writer = csv.writer(sys.stdout)
    writer.writerow(["id", "name", "code", "isActive"])

    rows = 0
    with GoalAPI(api_key) as goal:
        # /countries accepts limit up to 500; most endpoints cap at 100.
        for country in goal.paginate(lambda **p: goal.countries.list(**p), page_size=500):
            writer.writerow([country.get("id"), country.get("name"),
                             country.get("code"), country.get("isActive")])
            rows += 1

        print(f"\n{rows} countries exported", file=sys.stderr)
        print(f"quota: {goal.rate_limit.remaining}/{goal.rate_limit.limit} left", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        # Piping into `head` closes stdout early; a clean exit, not a crash.
        sys.exit(0)
