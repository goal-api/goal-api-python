"""Inbound webhook signature verification.

Signature format is ``t=<unix>,v1=<hex>``, where the HMAC-SHA256 covers
``"<timestamp>.<raw body>"`` keyed with the endpoint secret.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from .errors import GoalAPIError

__all__ = [
    "WEBHOOK_EVENTS",
    "SIGNATURE_HEADER",
    "EVENT_HEADER",
    "DELIVERY_HEADER",
    "WebhookSignatureError",
    "verify_webhook",
]

WEBHOOK_EVENTS = (
    "match.started",
    "match.finished",
    "goal.scored",
    "score.changed",
    "match.status_changed",
)

SIGNATURE_HEADER = "X-Goal-Signature"
EVENT_HEADER = "X-Goal-Event"
DELIVERY_HEADER = "X-Goal-Delivery"


class WebhookSignatureError(GoalAPIError):
    """Missing, malformed, wrong, or too old."""


def verify_webhook(
    payload: bytes | str,
    signature_header: str | None,
    secret: str,
    *,
    tolerance: int = 300,
) -> dict[str, Any]:
    """Verifies an inbound webhook and returns the parsed event.

    ``payload`` must be the raw body. Re-serializing a parsed dict reorders keys and
    changes whitespace, which breaks the HMAC::

        @app.post("/goal-webhooks")
        async def hook(request: Request):
            event = verify_webhook(await request.body(),
                                   request.headers.get("x-goal-signature"),
                                   SECRET)

    Raises ``WebhookSignatureError`` on a bad signature, or a timestamp older than
    ``tolerance`` seconds (replay protection). ``tolerance=0`` disables that check --
    only sensible if you dedupe on ``X-Goal-Delivery`` yourself.
    """
    if not secret:
        raise WebhookSignatureError("Webhook secret is required")
    if not signature_header:
        raise WebhookSignatureError(f"Missing {SIGNATURE_HEADER} header")

    raw = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    timestamp, signature = _parse_signature_header(signature_header)

    expected = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{raw}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        raise WebhookSignatureError("Webhook signature does not match")

    if tolerance > 0:
        age = int(time.time()) - timestamp
        if abs(age) > tolerance:
            raise WebhookSignatureError(
                f"Webhook timestamp is {age}s old, outside the {tolerance}s tolerance"
            )

    try:
        event = json.loads(raw)
    except ValueError as error:
        raise WebhookSignatureError("Webhook body is not valid JSON") from error

    if not isinstance(event, dict):
        raise WebhookSignatureError("Webhook body is not a JSON object")
    return event


def _parse_signature_header(header: str) -> tuple[int, str]:
    timestamp: int | None = None
    signature: str | None = None

    for part in header.split(","):
        key, _, value = part.partition("=")
        key, value = key.strip(), value.strip()
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError:
                timestamp = None
        elif key == "v1":
            signature = value

    if timestamp is None or not signature or not _is_hex(signature):
        raise WebhookSignatureError(f"Malformed {SIGNATURE_HEADER} header: {header}")
    return timestamp, signature


def _is_hex(value: str) -> bool:
    try:
        bytes.fromhex(value)
    except ValueError:
        return False
    return True
