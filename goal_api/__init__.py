"""Python SDK for the GOAL API. https://goal-api.com

    from goal_api import GoalAPI

    goal = GoalAPI(api_key="...")
    for match in goal.fixtures.live()["data"]:
        print(match["homeTeam"]["name"], match["homeScore"])
"""

from ._transport import DEFAULT_BASE_URL, VERSION
from .client import AsyncGoalAPI, GoalAPI
from .errors import (
    AuthenticationError,
    ConflictError,
    ConnectionError,
    GoalAPIError,
    NotFoundError,
    PermissionError,
    PlanUpgradeRequiredError,
    RateLimitError,
    ServerError,
    ServiceUnavailableError,
    TimeoutError,
    ValidationError,
)
from .webhooks import (
    DELIVERY_HEADER,
    EVENT_HEADER,
    SIGNATURE_HEADER,
    WEBHOOK_EVENTS,
    WebhookSignatureError,
    verify_webhook,
)

__version__ = VERSION

#: Values accepted by the ``status`` query param.
MATCH_STATUSES = (
    "SCHEDULED",
    "LIVE",
    "FINISHED",
    "HALF_TIME",
    "AFTER_ET",
    "AFTER_PEN",
    "POSTPONED",
    "CANCELLED",
    "AWARDED",
    "ABANDONED",
    "SUSPENDED",
)

#: Values accepted by the ``type`` query param on player endpoints.
PLAYER_TYPES = ("Goalkeepers", "Defenders", "Midfielders", "Forwards")

#: Values accepted as the ``stat`` path segment of ``/players/top/{stat}``.
PLAYER_STATS = (
    "goals",
    "assists",
    "yellowCards",
    "redCards",
    "rating",
    "matchPlayed",
    "minutes",
    "saves",
    "tackles",
    "shotsTotal",
    "keyPasses",
    "passes",
    "interceptions",
    "duelsWon",
    "dribbleSucc",
)

#: Values accepted by the ``half`` query param on fixture statistics.
HALVES = ("full", "1half", "2half")

__all__ = [
    "GoalAPI",
    "AsyncGoalAPI",
    "DEFAULT_BASE_URL",
    "VERSION",
    "__version__",
    "MATCH_STATUSES",
    "PLAYER_TYPES",
    "PLAYER_STATS",
    "HALVES",
    # errors
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
    # webhooks
    "verify_webhook",
    "WebhookSignatureError",
    "WEBHOOK_EVENTS",
    "SIGNATURE_HEADER",
    "EVENT_HEADER",
    "DELIVERY_HEADER",
]
