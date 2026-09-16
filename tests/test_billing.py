"""Webhook verification and plan changes."""
import hashlib
import hmac
import json

import billing
import config
import core
import store


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_stripe_webhook_is_rejected_without_a_secret(monkeypatch):
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", "")
    ok, message = billing.handle_stripe_webhook(b'{"type":"checkout.session.completed"}', "sig")
    assert ok is False
    assert "not configured" in message


def test_forged_traakteer_signature_changes_nothing(user, monkeypatch):
    monkeypatch.setattr(config, "TRAAKTEER_SECRET", "topsecret")
    body = json.dumps({
        "event": "subscription.created",
        "plan_id": "plan_elite_monthly",
        "subscriber": {"email": user["email"]},
    }).encode()

    ok, message = billing.handle_traakteer_webhook("not-the-signature", body)

    assert ok is False
    assert message == "Invalid signature."
    assert core.get_user(user["email"])["plan"] == "starter", "plan must be untouched"


def test_valid_traakteer_signature_upgrades_the_account(user, monkeypatch):
    monkeypatch.setattr(config, "TRAAKTEER_SECRET", "topsecret")
    body = json.dumps({
        "id": "evt_1",
        "event": "subscription.created",
        "plan_id": "plan_pro_monthly",
        "subscriber": {"email": user["email"]},
    }).encode()

    ok, _ = billing.handle_traakteer_webhook(_sign("topsecret", body), body)

    assert ok is True
    upgraded = core.get_user(user["email"])
    assert upgraded["plan"] == "pro"
    assert upgraded["tokens"] == 15_000


def test_traakteer_events_are_idempotent(user, monkeypatch):
    monkeypatch.setattr(config, "TRAAKTEER_SECRET", "topsecret")
    body = json.dumps({
        "id": "evt_dup",
        "event": "subscription.created",
        "plan_id": "plan_pro_monthly",
        "subscriber": {"email": user["email"]},
    }).encode()
    signature = _sign("topsecret", body)

    billing.handle_traakteer_webhook(signature, body)
    core.spend_tokens(user["email"], 5_000)
    ok, message = billing.handle_traakteer_webhook(signature, body)

    assert ok is True
    assert "Duplicate" in message
    assert core.get_user(user["email"])["tokens"] == 10_000, "replay must not re-grant"


def test_unknown_account_is_refused(monkeypatch):
    monkeypatch.setattr(config, "TRAAKTEER_SECRET", "topsecret")
    body = json.dumps({
        "event": "subscription.created",
        "plan_id": "plan_pro_monthly",
        "subscriber": {"email": "ghost@example.com"},
    }).encode()

    ok, message = billing.handle_traakteer_webhook(_sign("topsecret", body), body)
    assert ok is False
    assert "Unknown account" in message


def test_cancellation_downgrades(user):
    core.set_plan(user["email"], "elite")
    ok, _ = billing.cancel_subscription(user["email"])

    assert ok is True
    assert core.get_user(user["email"])["plan"] == "starter"


def test_checkout_url_is_none_when_unconfigured(user):
    assert billing.checkout_url(user["email"], "starter") is None


def test_no_checkout_link_when_traakteer_cannot_be_verified(user, monkeypatch):
    """A payment we cannot verify must never be offered."""
    monkeypatch.setattr(config, "TRAAKTEER_SECRET", "")
    assert billing.traakteer_checkout_url(user["email"], "pro") is None
    assert billing.checkout_url(user["email"], "pro") is None


def test_checkout_link_appears_once_traakteer_is_configured(user, monkeypatch):
    monkeypatch.setattr(config, "TRAAKTEER_SECRET", "topsecret")
    url = billing.checkout_url(user["email"], "pro")
    assert url and "plan_pro_monthly" in url
