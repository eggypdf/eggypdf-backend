"""Dodo Payments subscription webhook synchronization for Career Pro.

Dodo follows the Standard Webhooks specification. We verify the exact raw body
before changing any EggyPDF entitlement state and use webhook-id for idempotency.
"""
from __future__ import annotations

import json
import os
from typing import Any

from flask import Blueprint, jsonify, request
from standardwebhooks.webhooks import Webhook

from career_billing import _request

webhook_bp = Blueprint("career_webhooks", __name__, url_prefix="/api/webhooks")


def _products() -> dict[str, str]:
    return {
        "monthly": os.getenv("DODO_CAREER_MONTHLY_PRODUCT_ID", "").strip(),
        "yearly": os.getenv("DODO_CAREER_YEARLY_PRODUCT_ID", "").strip(),
    }


def _plan_for_product(product_id: str) -> str | None:
    for plan, configured in _products().items():
        if configured and configured == product_id:
            return plan
    return None


def _safe_supabase_error(resp, fallback: str) -> str:
    """Return non-secret PostgREST diagnostics for webhook troubleshooting."""
    detail = ""
    try:
        body = resp.json()
        if isinstance(body, dict):
            code = str(body.get("code") or "").strip()
            message = str(body.get("message") or body.get("error") or "").strip()
            hint = str(body.get("hint") or "").strip()
            parts = [x for x in [code, message, hint] if x]
            detail = " | ".join(parts)
    except Exception:
        detail = ""
    suffix = f" Supabase HTTP {resp.status_code}."
    if detail:
        suffix += f" {detail}"
    return fallback + suffix


def _already_processed(webhook_id: str) -> bool:
    r = _request(
        "GET",
        "/rest/v1/career_billing_webhooks",
        params={"select": "webhook_id", "webhook_id": f"eq.{webhook_id}", "limit": "1"},
    )
    if not r.ok:
        raise RuntimeError(_safe_supabase_error(r, "Could not check webhook idempotency."))
    return bool(r.json() or [])


def _mark_processed(webhook_id: str, event_type: str) -> None:
    r = _request(
        "POST",
        "/rest/v1/career_billing_webhooks",
        json={"webhook_id": webhook_id, "event_type": event_type},
        prefer="return=minimal",
    )
    if not r.ok and r.status_code != 409:
        raise RuntimeError(_safe_supabase_error(r, "Could not record webhook processing."))


def _upsert_entitlement(user_id: str, payload: dict[str, Any]) -> None:
    """Create or update an entitlement row for an account-aware subscription."""
    body = {"user_id": user_id, **payload}
    r = _request(
        "POST",
        "/rest/v1/career_entitlements",
        params={"on_conflict": "user_id"},
        json=body,
        prefer="resolution=merge-duplicates,return=minimal",
    )
    if not r.ok:
        raise RuntimeError(_safe_supabase_error(r, "Could not synchronize Career Pro entitlement."))


def _sync_subscription(event_type: str, sub: dict[str, Any]) -> None:
    product_id = str(sub.get("product_id") or "").strip()
    plan = _plan_for_product(product_id)
    if not plan:
        raise RuntimeError("Dodo subscription product does not match the configured Career Pro product IDs.")

    metadata = sub.get("metadata") or {}
    user_id = str(metadata.get("account_user_id") or "").strip()
    if not user_id:
        raise RuntimeError("Dodo subscription metadata is missing account_user_id.")

    dodo_status = str(sub.get("status") or "").strip().lower()
    cancel_next = bool(sub.get("cancel_at_next_billing_date"))
    next_billing = sub.get("next_billing_date")
    previous_billing = sub.get("previous_billing_date")

    if event_type in {"subscription.active", "subscription.renewed"} or dodo_status == "active":
        local_status = "active"
    elif dodo_status == "on_hold" or event_type == "subscription.on_hold":
        local_status = "on_hold"
    elif dodo_status in {"cancelled", "failed", "expired"}:
        local_status = dodo_status
    else:
        raise RuntimeError(f"Unsupported subscription state: {dodo_status or event_type}")

    _upsert_entitlement(
        user_id,
        {
            "status": local_status,
            "product_id": product_id,
            "plan": plan,
            "source": "dodo",
            "dodo_subscription_id": sub.get("subscription_id"),
            "current_period_start": previous_billing,
            "current_period_end": next_billing,
            "cancel_at_period_end": cancel_next,
            "access_ends_at": next_billing if cancel_next and local_status == "active" else None,
            "monthly_credits": 2000,
        },
    )


@webhook_bp.post("/dodo")
def dodo_webhook():
    secret = os.getenv("DODO_PAYMENTS_WEBHOOK_KEY", "").strip()
    if not secret:
        return jsonify({"error": "Webhook verification is not configured."}), 503

    raw = request.get_data(as_text=True)
    wh_headers = {
        "webhook-id": request.headers.get("webhook-id", ""),
        "webhook-signature": request.headers.get("webhook-signature", ""),
        "webhook-timestamp": request.headers.get("webhook-timestamp", ""),
    }
    try:
        Webhook(secret).verify(raw, wh_headers)
    except Exception:
        return jsonify({"error": "Invalid webhook signature."}), 401

    webhook_id = wh_headers["webhook-id"].strip()
    if not webhook_id:
        return jsonify({"error": "Missing webhook id."}), 400

    try:
        if _already_processed(webhook_id):
            return jsonify({"received": True, "duplicate": True})

        payload = json.loads(raw)
        event_type = str(payload.get("type") or "").strip()
        data = payload.get("data") or {}
        if event_type.startswith("subscription."):
            _sync_subscription(event_type, data)

        _mark_processed(webhook_id, event_type or "unknown")
        return jsonify({"received": True})
    except (ValueError, TypeError, json.JSONDecodeError):
        return jsonify({"error": "Invalid webhook payload."}), 400
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 503
