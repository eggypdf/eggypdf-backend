"""Production safety guard for Career Pro account-bound purchases.

Career Pro is account based. A verified checkout must belong to the same
Supabase user that is making the request; a checkout/session ID from another
browser or account must never unlock paid tools for a different user.
"""
from __future__ import annotations

from typing import Any

import career_routes
from account_routes import current_account_user, grant_career_pro


def strict_account_user() -> dict[str, Any]:
    """Require a valid signed-in EggyPDF account for every paid flow."""
    user = current_account_user(required=True)
    if not user or not user.get("id"):
        raise PermissionError("Sign in to continue.")
    return user


def strict_link_paid_record_to_account(
    record: dict[str, Any], request_user: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Link only an account-aware checkout owned by the current user."""
    if not record.get("paid"):
        return None

    request_user_id = (request_user or {}).get("id")
    if not request_user_id:
        raise PermissionError("Sign in to verify your Career Pro purchase.")

    metadata = record.get("metadata") or {}
    checkout_user_id = str(metadata.get("account_user_id") or "").strip()
    if not checkout_user_id:
        raise PermissionError(
            "This checkout is not linked to an EggyPDF account. Please start a new Career Pro checkout while signed in."
        )
    if checkout_user_id != request_user_id:
        raise PermissionError(
            "This Career Pro purchase belongs to a different EggyPDF account."
        )

    return grant_career_pro(
        request_user_id,
        product_id=career_routes.DODO_PRODUCT_ID,
        checkout_id=record.get("checkout_id"),
        payment_id=record.get("payment_id"),
    )


def install() -> None:
    """Apply the guard to the already-defined Career Pro route functions."""
    career_routes._account_user = strict_account_user
    career_routes._link_paid_record_to_account = strict_link_paid_record_to_account
