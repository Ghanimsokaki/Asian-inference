"""
webhook_server.py — a tiny HTTP endpoint for payment webhooks.

Streamlit serves one app; it cannot expose extra routes, so the billing
webhooks documented in the README had nowhere to arrive. Run this alongside
the app and point Stripe/Traakteer at it:

    python webhook_server.py --port 8787

    POST /stripe     header: Stripe-Signature
    POST /traakteer  header: X-Traakteer-Signature
    GET  /health

Both handlers verify signatures before touching an account, so an
unauthenticated request can never change a plan.
"""
from __future__ import annotations

import argparse
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import billing
import core

MAX_BODY_BYTES = 1_000_000

log = logging.getLogger("webhooks")


class WebhookHandler(BaseHTTPRequestHandler):
    server_version = "AsianInferenceWebhooks/1.0"

    def _respond(self, status: int, message: str) -> None:
        body = json.dumps({"ok": 200 <= status < 300, "message": message}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        if self.path.rstrip("/") in ("/health", ""):
            self._respond(200, "ok")
        else:
            self._respond(404, "Not found")

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        route = self.path.split("?", 1)[0].rstrip("/")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._respond(400, "Invalid Content-Length")
            return
        if length <= 0 or length > MAX_BODY_BYTES:
            self._respond(413, "Request body missing or too large")
            return

        body = self.rfile.read(length)

        if route == "/stripe":
            ok, message = billing.handle_stripe_webhook(
                body, self.headers.get("Stripe-Signature", "")
            )
        elif route == "/traakteer":
            ok, message = billing.handle_traakteer_webhook(
                self.headers.get("X-Traakteer-Signature", ""), body
            )
        else:
            self._respond(404, "Not found")
            return

        log.info("%s -> %s (%s)", route, ok, message)
        # A rejected signature is a 401 so the provider retries visibly rather
        # than recording a silent success.
        self._respond(200 if ok else 401, message)

    def log_message(self, fmt: str, *args) -> None:
        log.debug(fmt, *args)


def main() -> None:
    parser = argparse.ArgumentParser(description="Payment webhook endpoint")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    core.bootstrap()

    log.info("Stripe configured: %s · Traakteer configured: %s",
             billing.stripe_available(), billing.traakteer_available())
    server = ThreadingHTTPServer((args.host, args.port), WebhookHandler)
    log.info("Listening on http://%s:%s", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
