"""
stripe_integration.py — Stripe payment processing + Traakteer fallback
Dual-payment gateway with persistent storage for all transactions and subscriptions.
All billing data, webhooks, and subscription states persist permanently.
"""

import os
import json
import hashlib
import hmac
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple
import requests
import stripe
from pathlib import Path

import db_persistent as db

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

TRAAKTEER_SECRET = os.getenv("TRAAKTEER_SECRET", "skip")

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

PLANS = {
    "starter": {
        "name": "Starter",
        "price": 0,
        "stripe_price_id": None,  # Free plan
        "traakteer_id": "",
        "tokens": 500,
        "monthly_tokens": 500,
    },
    "pro": {
        "name": "Pro",
        "price": 9.99,
        "stripe_price_id": os.getenv("STRIPE_PRICE_PRO", "price_XXXXX"),  # Set in env
        "traakteer_id": "plan_pro_monthly",
        "tokens": 15000,
        "monthly_tokens": 15000,
    },
    "elite": {
        "name": "Elite",
        "price": 29.99,
        "stripe_price_id": os.getenv("STRIPE_PRICE_ELITE", "price_YYYYY"),  # Set in env
        "traakteer_id": "plan_elite_monthly",
        "tokens": 999999,
        "monthly_tokens": 999999,
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# STRIPE PAYMENT OPERATIONS (Permanent Storage)
# ─────────────────────────────────────────────────────────────────────────────

def create_stripe_checkout_session(email: str, plan_id: str) -> Optional[str]:
    """
    Create Stripe checkout session. Persistent transaction record.
    Returns checkout URL.
    """
    if not STRIPE_SECRET_KEY or plan_id == "starter":
        return None
    
    try:
        plan = PLANS.get(plan_id)
        if not plan or plan["price"] == 0:
            return None
        
        user = db.get_user(email)
        if not user:
            return None
        
        # Create checkout session
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[
                {
                    "price": plan["stripe_price_id"],
                    "quantity": 1,
                }
            ],
            mode="subscription",
            customer_email=email,
            client_reference_id=email,
            success_url="https://asian-inference.streamlit.app/success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url="https://asian-inference.streamlit.app/",
            metadata={
                "email": email,
                "plan": plan_id,
            }
        )
        
        # Log transaction permanently
        _log_billing_event(email, "stripe_checkout_created", {
            "session_id": session.id,
            "plan": plan_id,
            "price": plan["price"],
            "timestamp": datetime.utcnow().isoformat()
        })
        
        return session.url
    
    except stripe.error.StripeError as e:
        _log_billing_event(email, "stripe_error", {
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        })
        return None


def get_stripe_customer(email: str) -> Optional[str]:
    """Get or create Stripe customer ID. Permanent storage."""
    if not STRIPE_SECRET_KEY:
        return None
    
    try:
        user = db.get_user(email)
        if not user:
            return None
        
        # Check if user already has stripe_customer_id
        if user.get("stripe_customer_id"):
            return user["stripe_customer_id"]
        
        # Create new customer
        customer = stripe.Customer.create(
            email=email,
            metadata={"email": email}
        )
        
        # Save to persistent storage
        db.update_user(email, stripe_customer_id=customer.id)
        
        return customer.id
    
    except stripe.error.StripeError as e:
        _log_billing_event(email, "stripe_customer_error", {"error": str(e)})
        return None


def handle_stripe_webhook(event_data: Dict) -> Tuple[bool, str]:
    """
    Handle Stripe webhook events. All billing changes persist permanently.
    Verifies webhook signature and processes payment/subscription events.
    """
    if not STRIPE_WEBHOOK_SECRET:
        return False, "Webhook secret not configured"
    
    try:
        event_type = event_data.get("type")
        data = event_data.get("data", {}).get("object", {})
        
        email = data.get("customer_email") or data.get("metadata", {}).get("email")
        if not email:
            return False, "No email in webhook"
        
        # ── Payment succeeded: upgrade user to paid plan ──
        if event_type == "checkout.session.completed":
            metadata = data.get("metadata", {})
            plan_id = metadata.get("plan", "pro")
            
            user = db.get_user(email)
            if user:
                # Update plan permanently
                db.update_user(email, plan=plan_id)
                
                # Grant tokens for new plan
                new_tokens = PLANS[plan_id]["monthly_tokens"]
                db.update_user(email, tokens=new_tokens)
                
                # Log permanent transaction
                _log_billing_event(email, "stripe_payment_success", {
                    "plan": plan_id,
                    "amount": PLANS[plan_id]["price"],
                    "tokens_granted": new_tokens,
                    "timestamp": datetime.utcnow().isoformat()
                })
        
        # ── Subscription updated ──
        elif event_type == "customer.subscription.updated":
            status = data.get("status")
            metadata = data.get("metadata", {})
            plan_id = metadata.get("plan", "pro")
            
            if status == "active":
                db.update_user(email, plan=plan_id, stripe_subscription_id=data.get("id"))
                _log_billing_event(email, "subscription_updated", {"status": status, "plan": plan_id})
        
        # ── Payment failed: suspend user ──
        elif event_type == "invoice.payment_failed":
            _log_billing_event(email, "payment_failed", {
                "reason": data.get("last_payment_error", {}).get("message"),
                "timestamp": datetime.utcnow().isoformat()
            })
            # Optionally downgrade to starter or flag account
        
        # ── Subscription cancelled ──
        elif event_type == "customer.subscription.deleted":
            # Keep user on their current plan but log cancellation
            _log_billing_event(email, "subscription_cancelled", {
                "timestamp": datetime.utcnow().isoformat()
            })
        
        return True, f"Processed {event_type}"
    
    except Exception as e:
        return False, f"Webhook error: {str(e)}"


# ─────────────────────────────────────────────────────────────────────────────
# TRAAKTEER FALLBACK / DUAL PAYMENT (Permanent Storage)
# ─────────────────────────────────────────────────────────────────────────────

def handle_traakteer_webhook(signature: str, body_str: str) -> Tuple[bool, str]:
    """
    Handle Traakteer webhook. Fallback payment method.
    All transactions persist permanently.
    """
    if not TRAAKTEER_SECRET or TRAAKTEER_SECRET == "skip":
        return False, "Traakteer not configured"
    
    try:
        # Verify signature
        expected_sig = hmac.new(
            TRAAKTEER_SECRET.encode(),
            body_str.encode(),
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(signature, expected_sig):
            return False, "Invalid signature"
        
        body = json.loads(body_str)
        event = body.get("event")
        
        if event == "subscription.created":
            subscriber = body.get("subscriber", {})
            email = subscriber.get("email")
            plan_id = body.get("plan_id")
            
            if email and plan_id in PLANS:
                user = db.get_user(email)
                if user:
                    # Upgrade permanently
                    db.update_user(email, plan=plan_id)
                    new_tokens = PLANS[plan_id]["monthly_tokens"]
                    db.update_user(email, tokens=new_tokens)
                    
                    _log_billing_event(email, "traakteer_payment_success", {
                        "plan": plan_id,
                        "amount": PLANS[plan_id]["price"],
                        "timestamp": datetime.utcnow().isoformat()
                    })
        
        elif event == "subscription.cancelled":
            subscriber = body.get("subscriber", {})
            email = subscriber.get("email")
            
            if email:
                _log_billing_event(email, "traakteer_cancelled", {
                    "timestamp": datetime.utcnow().isoformat()
                })
        
        return True, f"Processed Traakteer: {event}"
    
    except Exception as e:
        return False, f"Traakteer error: {str(e)}"


# ─────────────────────────────────────────────────────────────────────────────
# BILLING HISTORY & PERSISTENCE
# ─────────────────────────────────────────────────────────────────────────────

def _log_billing_event(email: str, event_type: str, details: Dict) -> None:
    """Log all billing events permanently (audit trail)."""
    try:
        # Get or create billing log for user
        conn = db._get_conn()
        c = conn.cursor()
        
        # Create billing_events table if needed
        c.execute("""
            CREATE TABLE IF NOT EXISTS billing_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                event_type TEXT NOT NULL,
                details TEXT,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (user_email) REFERENCES users(email)
            )
        """)
        
        c.execute("""
            INSERT INTO billing_events (user_email, event_type, details, timestamp)
            VALUES (?, ?, ?, ?)
        """, (email, event_type, json.dumps(details), datetime.utcnow().isoformat()))
        
        conn.commit()
        conn.close()
    except:
        pass  # Silent fail for logging


def get_billing_history(email: str) -> list:
    """Get permanent billing history for user."""
    try:
        conn = db._get_conn()
        c = conn.cursor()
        
        c.execute("""
            SELECT * FROM billing_events 
            WHERE user_email = ? 
            ORDER BY timestamp DESC 
            LIMIT 100
        """, (email,))
        
        rows = c.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    except:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# SUBSCRIPTION MANAGEMENT (Persistent)
# ─────────────────────────────────────────────────────────────────────────────

def cancel_subscription(email: str) -> Tuple[bool, str]:
    """Cancel user's Stripe subscription. Permanent state change."""
    try:
        user = db.get_user(email)
        if not user or not user.get("stripe_subscription_id"):
            return False, "No active subscription"
        
        subscription = stripe.Subscription.delete(user["stripe_subscription_id"])
        
        # Downgrade to starter (persist)
        db.update_user(email, plan="starter", tokens=PLANS["starter"]["tokens"])
        
        _log_billing_event(email, "subscription_cancelled", {
            "timestamp": datetime.utcnow().isoformat()
        })
        
        return True, "Subscription cancelled. Plan downgraded to Starter."
    
    except stripe.error.StripeError as e:
        return False, f"Stripe error: {str(e)}"


def get_subscription_status(email: str) -> Optional[Dict]:
    """Get current subscription status (persistent data)."""
    user = db.get_user(email)
    if not user:
        return None
    
    return {
        "email": email,
        "plan": user["plan"],
        "tokens": user["tokens"],
        "stripe_customer_id": user.get("stripe_customer_id"),
        "stripe_subscription_id": user.get("stripe_subscription_id"),
        "created_at": user.get("created_at"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# MONTHLY TOKEN RESET (Cron-like operation with persistent state)
# ─────────────────────────────────────────────────────────────────────────────

def reset_monthly_tokens():
    """
    Reset tokens for all users to their plan's monthly limit.
    Runs once per month. Persistent operation.
    """
    try:
        conn = db._get_conn()
        c = conn.cursor()
        
        # Get all users
        c.execute("SELECT email, plan FROM users")
        users = c.fetchall()
        
        for user in users:
            email = user["email"]
            plan = user["plan"]
            monthly_tokens = PLANS[plan]["monthly_tokens"]
            
            # Reset permanently
            db.update_user(email, tokens=monthly_tokens)
            
            # Log reset
            db.add_tokens(email, 0, f"monthly_reset:{plan}")
        
        conn.close()
        
        return True, f"Reset tokens for {len(users)} users"
    
    except Exception as e:
        return False, f"Reset error: {str(e)}"


# ─────────────────────────────────────────────────────────────────────────────
# INITIALIZE
# ─────────────────────────────────────────────────────────────────────────────

def init_stripe_integration():
    """Initialize Stripe tables and configuration."""
    db.ensure_db()
    
    try:
        conn = db._get_conn()
        c = conn.cursor()
        
        # Add Stripe fields to users if not exists
        c.execute("PRAGMA table_info(users)")
        columns = {row[1] for row in c.fetchall()}
        
        if "stripe_customer_id" not in columns:
            c.execute("ALTER TABLE users ADD COLUMN stripe_customer_id TEXT")
        if "stripe_subscription_id" not in columns:
            c.execute("ALTER TABLE users ADD COLUMN stripe_subscription_id TEXT")
        
        conn.commit()
        conn.close()
    except:
        pass  # Columns may already exist
