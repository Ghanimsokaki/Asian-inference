"""
billing.py — Stripe checkout and webhook handling, with a Traakteer fallback.

Replaces ``stripe_integration.py``. Three things it fixes:

* the Stripe webhook handler documented signature verification but never did
  any — an unauthenticated POST could upgrade any account to Elite;
* ``import stripe`` at module scope crashed the app when the (unlisted)
  dependency was absent; it is optional now;
* plan and price definitions were duplicated, so a plan change had to be made
  in two files. They come from :mod:`config` now.

Streamlit cannot serve webhook routes, so ``webhook_server.py`` exposes these
handlers over HTTP as a separate process.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import config
import core
import store
from config import PLANS, plan_for

try:  # Optional: the app runs fine without card payments configured.
    import stripe  # type: ignore
except ImportError:  # pragma: no cover - depends on the deployment
    stripe = None


def stripe_available() -> bool:
    """True when the Stripe SDK is installed and a secret key is configured."""
    if stripe is None or not config.STRIPE_SECRET_KEY:
        return False
    stripe.api_key = config.STRIPE_SECRET_KEY
    return True


def traakteer_available() -> bool:
    secret = (config.TRAAKTEER_SECRET or "").strip().lower()
    return bool(secret) and secret != "skip"


def _stripe_errors() -> tuple[type[BaseException], ...]:
    """Stripe's error base class, across SDK versions."""
    if stripe is None:
        return ()
    error_module = getattr(stripe, "error", None)
    base = getattr(error_module, "StripeError", None) or getattr(stripe, "StripeError", None)
    return (base,) if base else (Exception,)


# ─────────────────────────────────────────────────────────────────────
# CHECKOUT
# ─────────────────────────────────────────────────────────────────────
def checkout_url(email: str, plan_id: str) -> str | None:
    """Return a payment URL for `plan_id`, preferring Stripe over Traakteer."""
    plan = PLANS.get(plan_id)
    if not plan or plan["price"] <= 0:
        return None
    return create_stripe_checkout_session(email, plan_id) or traakteer_checkout_url(email, plan_id)


def traakteer_checkout_url(email: str, plan_id: str) -> str | None:
    """Traakteer checkout link, or None when Traakteer is not set up.

    Gated on the webhook secret on purpose: without it we cannot verify the
    payment notification, so the customer would be charged and never upgraded.
    """
    from urllib.parse import urlencode

    plan = PLANS.get(plan_id)
    if not plan or not plan.get("traakteer_id") or not traakteer_available():
        return None
    query = urlencode({"plan": plan["traakteer_id"], "customer_email": email})
    return f"https://pay.traakteer.com/checkout?{query}"


def create_stripe_checkout_session(email: str, plan_id: str) -> str | None:
    """Create a Stripe Checkout session and return its URL, or None."""
    if not stripe_available():
        return None
    plan = PLANS.get(plan_id)
    if not plan or plan["price"] <= 0 or not plan.get("stripe_price_id"):
        return None
    if core.get_user(email) is None:
        return None

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": plan["stripe_price_id"], "quantity": 1}],
            customer_email=email,
            client_reference_id=email,
            success_url=f"{config.PUBLIC_URL}/?checkout=success",
            cancel_url=f"{config.PUBLIC_URL}/?checkout=cancelled",
            metadata={"email": email, "plan": plan_id},
            subscription_data={"metadata": {"email": email, "plan": plan_id}},
        )
    except _stripe_errors() as exc:
        store.log_billing_event(email, "stripe_error", {"error": str(exc)})
        return None

    store.log_billing_event(email, "stripe_checkout_created", {
        "session_id": getattr(session, "id", None),
        "plan": plan_id,
        "price": plan["price"],
    })
    return getattr(session, "url", None)


def get_or_create_stripe_customer(email: str) -> str | None:
    if not stripe_available():
        return None
    user = core.get_user(email)
    if user is None:
        return None
    if user.get("stripe_customer_id"):
        return user["stripe_customer_id"]
    try:
        customer = stripe.Customer.create(email=email, metadata={"email": email})
    except _stripe_errors() as exc:
        store.log_billing_event(email, "stripe_customer_error", {"error": str(exc)})
        return None
    store.update_user(email, stripe_customer_id=customer.id)
    return customer.id


# ─────────────────────────────────────────────────────────────────────
# WEBHOOKS
# ─────────────────────────────────────────────────────────────────────
def handle_stripe_webhook(payload: bytes | str, signature_header: str) -> tuple[bool, str]:
    """Verify and process a Stripe webhook.

    The signature is checked against ``STRIPE_WEBHOOK_SECRET`` before anything
    is read out of the body. An unverified request changes nothing.
    """
    if not config.STRIPE_WEBHOOK_SECRET:
        return False, "Stripe webhook secret is not configured."
    if stripe is None:
        return False, "Stripe SDK is not installed."
    if isinstance(payload, str):
        payload = payload.encode()

    try:
        event = stripe.Webhook.construct_event(
            payload, signature_header, config.STRIPE_WEBHOOK_SECRET
        )
    except Exception as exc:  # SignatureVerificationError or malformed payload
        return False, f"Rejected: {exc}"

    event = dict(event)
    event_id = event.get("id", "")
    if not store.mark_webhook_processed(event_id, "stripe"):
        return True, "Duplicate event ignored."

    return _apply_stripe_event(event)


def _apply_stripe_event(event: dict[str, Any]) -> tuple[bool, str]:
    event_type = event.get("type", "")
    data = (event.get("data") or {}).get("object") or {}
    metadata = data.get("metadata") or {}

    email = core.normalise_email(
        metadata.get("email")
        or data.get("customer_email")
        or data.get("client_reference_id")
        or ""
    )
    if not email:
        return False, "No account email on the event."
    if core.get_user(email) is None:
        return False, "Unknown account."

    if event_type in ("checkout.session.completed", "customer.subscription.created"):
        plan_id = metadata.get("plan", "pro")
        if plan_id not in PLANS:
            return False, f"Unknown plan '{plan_id}'."
        core.set_plan(email, plan_id)
        if data.get("subscription") or data.get("id"):
            store.update_user(email, stripe_subscription_id=str(
                data.get("subscription") or data.get("id")))
        store.log_billing_event(email, "stripe_payment_success", {
            "plan": plan_id, "amount": plan_for(plan_id)["price"],
        })
        return True, f"Upgraded {email} to {plan_id}."

    if event_type == "customer.subscription.updated":
        status = data.get("status")
        plan_id = metadata.get("plan", "pro")
        if status == "active" and plan_id in PLANS:
            core.set_plan(email, plan_id, grant_tokens_now=False)
            store.update_user(email, stripe_subscription_id=str(data.get("id") or ""))
        store.log_billing_event(email, "subscription_updated",
                                {"status": status, "plan": plan_id})
        return True, f"Subscription {status} for {email}."

    if event_type == "customer.subscription.deleted":
        core.set_plan(email, "starter")
        store.update_user(email, stripe_subscription_id=None)
        store.log_billing_event(email, "subscription_cancelled", {})
        return True, f"Downgraded {email} to starter."

    if event_type == "invoice.payment_failed":
        store.log_billing_event(email, "payment_failed", {
            "reason": (data.get("last_payment_error") or {}).get("message"),
        })
        return True, f"Recorded failed payment for {email}."

    return True, f"Ignored event type '{event_type}'."


def handle_traakteer_webhook(signature: str, body: bytes | str) -> tuple[bool, str]:
    """Verify and process a Traakteer webhook using HMAC-SHA256."""
    if not traakteer_available():
        return False, "Traakteer is not configured."
    if isinstance(body, str):
        body = body.encode()

    expected = hmac.new(
        config.TRAAKTEER_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest((signature or "").strip(), expected):
        return False, "Invalid signature."

    try:
        event = json.loads(body)
    except ValueError:
        return False, "Malformed JSON body."

    event_id = str(event.get("id") or event.get("event_id") or "")
    if event_id and not store.mark_webhook_processed(event_id, "traakteer"):
        return True, "Duplicate event ignored."

    name = event.get("event", "")
    email = core.normalise_email((event.get("subscriber") or {}).get("email", ""))
    if not email or core.get_user(email) is None:
        return False, "Unknown account."

    if name == "subscription.created":
        plan_id = event.get("plan_id", "")
        resolved = next(
            (pid for pid, plan in PLANS.items()
             if plan_id in (pid, plan.get("traakteer_id"))), None
        )
        if not resolved:
            return False, f"Unknown plan '{plan_id}'."
        core.set_plan(email, resolved)
        store.log_billing_event(email, "traakteer_payment_success", {
            "plan": resolved, "amount": plan_for(resolved)["price"],
        })
        return True, f"Upgraded {email} to {resolved}."

    if name == "subscription.cancelled":
        core.set_plan(email, "starter")
        store.log_billing_event(email, "traakteer_cancelled", {})
        return True, f"Downgraded {email} to starter."

    return True, f"Ignored event '{name}'."


# ─────────────────────────────────────────────────────────────────────
# SUBSCRIPTION MANAGEMENT
# ─────────────────────────────────────────────────────────────────────
def cancel_subscription(email: str) -> tuple[bool, str]:
    user = core.get_user(email)
    if user is None:
        return False, "Account not found."

    subscription_id = user.get("stripe_subscription_id")
    if subscription_id and stripe_available():
        try:
            stripe.Subscription.delete(subscription_id)
        except _stripe_errors() as exc:
            return False, f"Stripe could not cancel the subscription: {exc}"

    core.set_plan(email, "starter")
    store.update_user(email, stripe_subscription_id=None)
    store.log_billing_event(email, "subscription_cancelled", {"source": "self-service"})
    return True, "Subscription cancelled. Your plan is now Starter."


def subscription_status(email: str) -> dict | None:
    user = core.get_user(email)
    if user is None:
        return None
    return {
        "email": email,
        "plan": user["plan"],
        "plan_name": plan_for(user["plan"])["name"],
        "tokens": user["tokens"],
        "stripe_customer_id": user.get("stripe_customer_id"),
        "stripe_subscription_id": user.get("stripe_subscription_id"),
        "created": user.get("created"),
    }


def billing_history(email: str, limit: int = 50) -> list[dict]:
    return store.billing_history(email, limit)


def reset_monthly_tokens() -> tuple[bool, str]:
    count = core.reset_monthly_tokens()
    return True, f"Reset token allowances for {count} account(s)."
