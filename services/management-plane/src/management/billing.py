"""Stripe billing integration — basic framework for future payment processing.

MVP: Only sets up Stripe Customer objects and defines pricing models.
Actual payment collection is deferred to M7.
"""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")

# Whether Stripe is configured
STRIPE_ENABLED = bool(STRIPE_SECRET_KEY)

_stripe = None


def _get_stripe():
    """Lazy-load Stripe SDK."""
    global _stripe
    if _stripe is None:
        try:
            import stripe
            stripe.api_key = STRIPE_SECRET_KEY
            _stripe = stripe
            logger.info("Stripe SDK initialized")
        except ImportError:
            logger.warning("stripe package not installed, billing features disabled")
            return None
    return _stripe


# ── Pricing models (for future use) ──

PLANS = {
    "free_beta": {
        "name": "Free Beta",
        "price_monthly": 0,
        "description": "Beta access — free during preview period",
        "features": ["Up to 3 companies", "All team templates", "Community support"],
    },
    "starter": {
        "name": "Starter",
        "price_monthly": 29,
        "description": "For individual developers",
        "features": ["1 company", "Standard template", "Email support"],
        "stripe_price_id": None,  # Set after creating Stripe Price
    },
    "pro": {
        "name": "Pro",
        "price_monthly": 99,
        "description": "For small teams",
        "features": ["5 companies", "All templates", "Priority support"],
        "stripe_price_id": None,
    },
}


async def create_stripe_customer(email: str, name: str | None = None) -> str | None:
    """Create a Stripe Customer for a new user. Returns customer ID or None."""
    stripe = _get_stripe()
    if not stripe or not STRIPE_ENABLED:
        logger.debug("Stripe not configured, skipping customer creation")
        return None

    try:
        customer = stripe.Customer.create(
            email=email,
            name=name or "",
            metadata={"source": "agent-hub-cloud"},
        )
        logger.info("Created Stripe customer %s for %s", customer.id, email)
        return customer.id
    except Exception as e:
        logger.error("Failed to create Stripe customer: %s", e)
        return None


async def get_stripe_customer(customer_id: str) -> dict | None:
    """Get Stripe Customer details."""
    stripe = _get_stripe()
    if not stripe or not STRIPE_ENABLED or not customer_id:
        return None

    try:
        customer = stripe.Customer.retrieve(customer_id)
        return {
            "id": customer.id,
            "email": customer.email,
            "name": customer.name,
            "created": customer.created,
        }
    except Exception as e:
        logger.error("Failed to retrieve Stripe customer: %s", e)
        return None


def get_plan_info(plan_id: str = "free_beta") -> dict:
    """Get pricing plan details."""
    return PLANS.get(plan_id, PLANS["free_beta"])


def list_plans() -> dict[str, dict]:
    """List all available plans."""
    return {k: {**v, "id": k} for k, v in PLANS.items()}
