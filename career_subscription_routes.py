"""User-facing Career Pro subscription management.

EggyPDF deliberately implements cancellation as 'stop the next renewal'. The
already-paid Career Pro period remains active until Dodo's next billing date.
"""
from __future__ import annotations

from flask import Blueprint, jsonify

import career_routes
from account_routes import current_account_user
from career_billing import _request

subscription_bp = Blueprint("career_subscription", __name__, url_prefix="/api/billing/subscription")


def _entitlement(user_id: str) -> dict | None:
    r = _request(
        "GET",
        "/rest/v1/career_entitlements",
        params={
            "select": "status,source,plan,dodo_subscription_id,current_period_end,cancel_at_period_end,access_ends_at",
            "user_id": f"eq.{user_id}",
            "limit": "1",
        },
    )
    if not r.ok:
        raise RuntimeError("Could not read your Career Pro subscription.")
    rows = r.json() or []
    return rows[0] if rows else None


def _patch_local(user_id: str, *, period_end: str | None) -> None:
    r = _request(
        "PATCH",
        "/rest/v1/career_entitlements",
        params={"user_id": f"eq.{user_id}"},
        json={"status": "active", "cancel_at_period_end": True, "access_ends_at": period_end},
        prefer="return=minimal",
    )
    if not r.ok:
        raise RuntimeError("Cancellation was scheduled but EggyPDF could not save the updated subscription state.")


@subscription_bp.post("/cancel-renewal")
def cancel_renewal():
    try:
        user = current_account_user(required=True)
        row = _entitlement(user["id"])
        if not row or row.get("status") != "active":
            return jsonify({"success": False, "error": "No active Career Pro subscription was found."}), 404
        if row.get("source") != "dodo":
            return jsonify({"success": False, "error": "Creator promotional access does not have an automatic renewal to cancel."}), 400
        subscription_id = (row.get("dodo_subscription_id") or "").strip()
        if not career_routes._valid(subscription_id, "sub_"):
            return jsonify({"success": False, "error": "This subscription is missing its Dodo Payments subscription ID."}), 409
        if row.get("cancel_at_period_end"):
            return jsonify(
                {
                    "success": True,
                    "already_scheduled": True,
                    "access_ends_at": row.get("access_ends_at") or row.get("current_period_end"),
                    "message": "Future renewal is already stopped.",
                }
            )

        subscription = career_routes._dodo(
            "PATCH",
            f"/subscriptions/{subscription_id}",
            json={"cancel_at_next_billing_date": True},
        )
        if (subscription.get("subscription_id") or "").strip() != subscription_id:
            raise RuntimeError("Dodo Payments returned an unexpected subscription record.")
        period_end = subscription.get("next_billing_date") or row.get("current_period_end")
        _patch_local(user["id"], period_end=period_end)
        return jsonify(
            {
                "success": True,
                "cancel_at_period_end": True,
                "access_ends_at": period_end,
                "message": "Future renewal is stopped. Career Pro stays active until the end of your current paid billing period.",
            }
        )
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 401
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503
