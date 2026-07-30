"""GOAL_WEBHOOK_SECRET=... python examples/webhook_server.py

A minimal receiver with no framework. The important part is that verification runs on the
raw bytes: anything that parses and re-serialises the body first changes the byte order and
breaks the HMAC.
"""

from __future__ import annotations

import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

from goal_api import WEBHOOK_EVENTS, WebhookSignatureError, verify_webhook

SECRET = os.environ.get("GOAL_WEBHOOK_SECRET", "")
PORT = int(os.environ.get("PORT", "3100"))


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler's naming)
        if self.path != "/goal-webhooks":
            self.send_response(404)
            self.end_headers()
            return

        # Read the raw bytes. Do not json.loads before verifying.
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length)

        try:
            event = verify_webhook(raw, self.headers.get("x-goal-signature"), SECRET)
        except WebhookSignatureError as error:
            print(f"rejected: {error}", file=sys.stderr)
            self.send_response(400)
            self.end_headers()
            return

        kind = self.headers.get("x-goal-event")
        print(f"{kind}  delivery={self.headers.get('x-goal-delivery')}")

        if kind == "goal.scored":
            home = (event.get("homeTeam") or {}).get("name", "?")
            away = (event.get("awayTeam") or {}).get("name", "?")
            print(f"  {home} {event.get('homeScore')}-{event.get('awayScore')} {away}")
        elif kind == "match.finished":
            print("  full time")
        else:
            print(f"  {str(event)[:120]}")

        # Ack fast. Retries are ~1m, 5m, 25m, 2h, 10h, so a slow handler earns duplicate
        # deliveries; do the real work off this request.
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_args) -> None:
        pass  # the prints above are the log


if __name__ == "__main__":
    if not SECRET:
        print("GOAL_WEBHOOK_SECRET is not set.", file=sys.stderr)
        sys.exit(2)
    print(f"listening on http://localhost:{PORT}/goal-webhooks")
    print(f"events: {', '.join(WEBHOOK_EVENTS)}")
    HTTPServer(("", PORT), Handler).serve_forever()
