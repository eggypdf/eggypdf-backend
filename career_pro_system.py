"""EggyPDF Career Pro recurring plans, AI credits and creator-code access.

This module is installed from wsgi.py before blueprints are registered. It keeps
all entitlement/credit mutations server-side and wraps paid AI routes so failed
AI requests automatically return reserved credits.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import datetime, timezone
from functools import wraps
from typing import Any

import requests
from flask import Blueprint, current_app, jsonify, request

import account_routes
import career_routes
from account_routes import current_account_user

career_system_bp = Blueprint("career_system", __name__, url_prefix="/api/career")

MONTHLY_CREDITS = 2000
CREDIT_COSTS = {
    "resume_optimizer": 100,
    "job_tailoring": 100,
    "cover_letter": 50,
    "section_regeneration": 20,
    "pdf_summarizer": 25,
}


def _product_id(plan: str) -> str:
    key = "DODO_CAREER_ANNUAL_PRODUCT_ID" if plan == "annual" else "DODO_CAREER_MONTHLY_PRODUCT_ID"
    return os.getenv(key, "").strip()


def _db_url() -> str:
    return account_routes._cfg()[0]


def _db_headers(prefer: str | None = None) -> dict[str, str]:
    return account_routes._service_headers(prefer)


def _db_error(resp: requests.Response, fallback: str) -> RuntimeError:
    return account_routes._api_error(resp, fallback)


def _rpc(name: str, payload: dict[str, Any]) -> Any:
    try:
        r = requests.post(
            f"{_db_url()}/rest/v1/rpc/{name}",
            headers=_db_headers(),
            json=payload,
            timeout=15,
        )
    except requests.RequestException as exc:
        raise RuntimeError("Career Pro database is temporarily unavailable.") from exc
    if not r.ok:
        try:
            body = r.json()
            message = str(body.get("message") or body.get("details") or "")
        except Exception:
            message = ""
        if "INSUFFICIENT_CREDITS" in message:
            raise PermissionError("You do not have enough Career Pro AI credits for this action.")
        if "CAREER_PRO_INACTIVE" in message:
            raise PermissionError("Career Pro is not active on this account.")
        raise _db_error(r, "Career Pro database request failed.")
    if not r.content:
        return None
    return r.json()


def _entitlement(user_id: str) -> dict[str, Any] | None:
    params = {
        "select": "*",
        "user_id": f"eq.{user_id}",
        "limit": "1",
    }
    r = requests.get(
        f"{_db_url()}/rest/v1/career_entitlements",
        headers=_db_headers(),
        params=params,
        timeout=15,
    )
    if not r.ok:
        raise _db_error(r, "Could not read Career Pro access.")
    rows = r.json() or []
    return rows[0] if rows else None


def _entitlement_by_subscription(subscription_id: str) -> dict[str, Any] | None:
    if not subscription_id:
        return None
    params = {"select": "*", "dodo_subscription_id": f"eq.{subscription_id}", "limit": "1"}
    r = requests.get(
        f"{_db_url()}/rest/v1/career_entitlements",
        headers=_db_headers(),
        params=params,
        timeout=15,
    )
    if not r.ok:
        raise _db_error(r, "Could not find subscription owner.")
    rows = r.json() or []
    return rows[0] if rows else None


def _upsert_entitlement(user_id: str, **fields: Any) -> dict[str, Any]:
    payload = {"user_id": user_id, **fields}
    r = requests.post(
        f"{_db_url()}/rest/v1/career_entitlements?on_conflict=user_id",
        headers=_db_headers("resolution=merge-duplicates,return=representation"),
        json=payload,
        timeout=15,
    )
    if not r.ok:
        raise _db_error(r, "Could not save Career Pro subscription.")
    rows = r.json() or []
    return rows[0] if rows else payload


def _wallet(user_id: str, ensure: bool = True) -> dict[str, Any] | None:
    if ensure:
        row = _rpc("career_ensure_credit_wallet", {"p_user_id": user_id})
        if isinstance(row, list):
            return row[0] if row else None
        if isinstance(row, dict):
            return row
    params = {"select": "*", "user_id": f"eq.{user_id}", "limit": "1"}
    r = requests.get(
        f"{_db_url()}/rest/v1/career_credit_wallets",
        headers=_db_headers(), params=params, timeout=15
    )
    if not r.ok:
        raise _db_error(r, "Could not read Career Pro credits.")
    rows = r.json() or []
    return rows[0] if rows else None


def _parse_dt(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_active(ent: dict[str, Any] | None) -> bool:
    if not ent or ent.get("status") != "active":
        return False
    now = datetime.now(timezone.utc)
    expiry = _parse_dt(ent.get("expires_at"))
    if expiry and expiry <= now:
        return False
    sub_status = ent.get("subscription_status")
    if sub_status in {"on_hold", "paused", "failed", "expired"}:
        return False
    if sub_status == "cancelled":
        end = _parse_dt(ent.get("current_period_end")) or expiry
        if end and end <= now:
            return False
    return True


def _public_entitlement(ent: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ent:
        return None
    keys = (
        "status", "plan", "access_source", "subscription_status",
        "current_period_start", "current_period_end", "cancel_at_period_end",
        "expires_at", "purchased_at", "updated_at",
    )
    return {k: ent.get(k) for k in keys}


def _credit_payload(wallet: dict[str, Any] | None) -> dict[str, Any] | None:
    if not wallet:
        return None
    return {
        "remaining": int(wallet.get("balance") or 0),
        "total": int(wallet.get("monthly_allowance") or MONTHLY_CREDITS),
        "period_start": wallet.get("period_start"),
        "resets_at": wallet.get("period_end"),
        "costs": CREDIT_COSTS,
    }


def _career_status(user_id: str) -> dict[str, Any]:
    ent = _entitlement(user_id)
    active = _is_active(ent)
    wallet = None
    if active:
        try:
            wallet = _wallet(user_id, ensure=True)
        except PermissionError:
            active = False
    return {
        "active": active,
        "entitlement": _public_entitlement(ent),
        "credits": _credit_payload(wallet) if active else None,
    }


def _enriched_me():
    try:
        user = current_account_user(required=True)
        return jsonify({
            "success": True,
            "user": {"id": user.get("id"), "email": user.get("email")},
            "career_pro": _career_status(user["id"]),
        })
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 401
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


def _consume(user_id: str, amount: int, action: str, request_id: str) -> dict[str, Any] | None:
    row = _rpc("career_consume_credits", {
        "p_user_id": user_id,
        "p_amount": amount,
        "p_action": action,
        "p_request_id": request_id,
    })
    if isinstance(row, list):
        return row[0] if row else None
    return row if isinstance(row, dict) else None


def _refund(user_id: str, amount: int, action: str, request_id: str) -> None:
    _rpc("career_refund_credits", {
        "p_user_id": user_id,
        "p_amount": amount,
        "p_action": action,
        "p_request_id": request_id,
    })


def _credit_wrapper(original, action: str, amount: int):
    @wraps(original)
    def wrapped(*args, **kwargs):
        try:
            user = current_account_user(required=True)
            usage_id = request.headers.get("X-Eggy-Request-Id") or f"use:{uuid.uuid4().hex}"
            wallet = _consume(user["id"], amount, action, usage_id)
        except PermissionError as exc:
            return jsonify({
                "success": False,
                "error": str(exc),
                "credits_required": amount,
                "action": action,
            }), 402 if "credits" in str(exc).lower() else 403
        except RuntimeError as exc:
            return jsonify({"success": False, "error": str(exc)}), 503

        try:
            response = current_app.make_response(original(*args, **kwargs))
        except Exception:
            try:
                _refund(user["id"], amount, f"{action}_refund", f"refund:{usage_id}")
            except Exception:
                pass
            raise

        if response.status_code >= 400:
            try:
                _refund(user["id"], amount, f"{action}_refund", f"refund:{usage_id}")
            except Exception:
                pass
        elif wallet:
            response.headers["X-Eggy-Credits-Remaining"] = str(wallet.get("balance", ""))
        return response
    return wrapped


def _verify_standard_webhook(raw_body: bytes) -> str:
    secret = (os.getenv("DODO_PAYMENTS_WEBHOOK_SECRET") or os.getenv("DODO_PAYMENTS_WEBHOOK_KEY") or "").strip()
    if not secret:
        raise RuntimeError("Dodo webhook signing secret is not configured.")
    webhook_id = (request.headers.get("webhook-id") or "").strip()
    timestamp = (request.headers.get("webhook-timestamp") or "").strip()
    signature_header = (request.headers.get("webhook-signature") or "").strip()
    if not webhook_id or not timestamp or not signature_header:
        raise PermissionError("Missing webhook signature headers.")
    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise PermissionError("Invalid webhook timestamp.") from exc
    if abs(int(time.time()) - ts) > 300:
        raise PermissionError("Webhook timestamp is outside the allowed replay window.")

    encoded = secret[6:] if secret.startswith("whsec_") else secret
    try:
        key = base64.b64decode(encoded)
    except Exception as exc:
        raise RuntimeError("Dodo webhook signing secret is invalid.") from exc
    signed = webhook_id.encode() + b"." + timestamp.encode() + b"." + raw_body
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    supplied = []
    for piece in signature_header.replace(",", " ").split():
        value = piece.split(",", 1)[-1]
        if value.startswith("v1,"):
            value = value[3:]
        elif value.startswith("v1="):
            value = value[3:]
        supplied.append(value)
    if not any(hmac.compare_digest(expected, value) for value in supplied):
        raise PermissionError("Invalid webhook signature.")
    return webhook_id


def _record_webhook(webhook_id: str, event_type: str, processed: bool, error: str | None = None) -> None:
    payload = {
        "webhook_id": webhook_id,
        "event_type": event_type,
        "processed": processed,
        "last_error": error,
        "processed_at": datetime.now(timezone.utc).isoformat() if processed else None,
    }
    r = requests.post(
        f"{_db_url()}/rest/v1/career_webhook_events?on_conflict=webhook_id",
        headers=_db_headers("resolution=merge-duplicates"),
        json=payload,
        timeout=15,
    )
    if not r.ok:
        raise _db_error(r, "Could not record webhook event.")


def _webhook_seen(webhook_id: str) -> bool:
    params = {"select": "processed", "webhook_id": f"eq.{webhook_id}", "limit": "1"}
    r = requests.get(
        f"{_db_url()}/rest/v1/career_webhook_events",
        headers=_db_headers(), params=params, timeout=15
    )
    if not r.ok:
        raise _db_error(r, "Could not check webhook idempotency.")
    rows = r.json() or []
    return bool(rows and rows[0].get("processed"))


def _sync_subscription(event_type: str, data: dict[str, Any]) -> None:
    metadata = data.get("metadata") or {}
    subscription_id = str(data.get("subscription_id") or "").strip()
    existing = _entitlement_by_subscription(subscription_id) if subscription_id else None
    user_id = str(metadata.get("account_user_id") or (existing or {}).get("user_id") or "").strip()
    if not user_id:
        return

    product_id = str(data.get("product_id") or "").strip()
    plan = str(metadata.get("plan") or (existing or {}).get("plan") or "").strip()
    if plan not in {"monthly", "annual"}:
        if product_id and product_id == _product_id("annual"):
            plan = "annual"
        elif product_id and product_id == _product_id("monthly"):
            plan = "monthly"
        else:
            plan = "monthly"

    raw_status = str(data.get("status") or event_type.split(".", 1)[-1]).lower()
    current_start = data.get("previous_billing_date") or data.get("created_at")
    current_end = data.get("next_billing_date") or data.get("expires_at")
    cancel_next = bool(data.get("cancel_at_next_billing_date"))
    customer = data.get("customer") or {}

    active_statuses = {"active", "renewed", "updated", "plan_changed", "cancelled"}
    entitlement_status = "active" if raw_status in active_statuses or event_type == "subscription.cancelled" else "inactive"
    if raw_status in {"on_hold", "paused", "failed", "expired"}:
        entitlement_status = "inactive"

    _upsert_entitlement(
        user_id,
        status=entitlement_status,
        product_id=product_id or (existing or {}).get("product_id"),
        plan=plan,
        access_source="paid",
        subscription_status="cancelled" if event_type == "subscription.cancelled" else raw_status,
        dodo_subscription_id=subscription_id or (existing or {}).get("dodo_subscription_id"),
        dodo_customer_id=customer.get("customer_id") or (existing or {}).get("dodo_customer_id"),
        current_period_start=current_start,
        current_period_end=current_end,
        cancel_at_period_end=cancel_next or event_type == "subscription.cancelled",
        expires_at=current_end if event_type in {"subscription.cancelled", "subscription.expired"} else None,
    )

    if event_type == "subscription.renewed":
        _rpc("career_reset_credits", {"p_user_id": user_id, "p_allowance": MONTHLY_CREDITS})
    elif event_type == "subscription.active":
        try:
            _wallet(user_id, ensure=True)
        except Exception:
            pass


@career_system_bp.get("/plans")
def plans():
    return jsonify({
        "success": True,
        "currency": "USD",
        "credits_per_month": MONTHLY_CREDITS,
        "default_plan": "annual",
        "plans": {
            "annual": {
                "price_per_month": 4.00,
                "billed": 48.00,
                "billing_period": "year",
                "savings_vs_monthly": 35.88,
                "savings_percent": 43,
                "configured": bool(_product_id("annual")),
            },
            "monthly": {
                "price_per_month": 6.99,
                "billed": 6.99,
                "billing_period": "month",
                "configured": bool(_product_id("monthly")),
            },
        },
        "credit_costs": CREDIT_COSTS,
    })


@career_system_bp.get("/pro/status")
def pro_status():
    try:
        user = current_account_user(required=True)
        return jsonify({"success": True, "career_pro": _career_status(user["id"])})
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 401
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@career_system_bp.post("/redeem-creator-code")
def redeem_creator_code():
    try:
        user = current_account_user(required=True)
        if not user.get("email_confirmed_at"):
            raise PermissionError("Confirm your email before redeeming a Creator Code.")
        data = request.get_json(silent=True) or {}
        code = str(data.get("code") or "").strip().upper()
        result = _rpc("career_redeem_creator_code", {"p_user_id": user["id"], "p_code": code})
        if not isinstance(result, dict):
            raise RuntimeError("Creator Code redemption returned an invalid response.")
        status = 200 if result.get("success") else 400
        return jsonify(result), status
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@career_system_bp.post("/subscription-checkout")
def subscription_checkout():
    try:
        user = current_account_user(required=True)
        current = _career_status(user["id"])
        if current.get("active"):
            return jsonify({"success": False, "error": "Career Pro is already active on this account."}), 409
        data = request.get_json(silent=True) or {}
        plan = str(data.get("plan") or "annual").strip().lower()
        if plan not in {"monthly", "annual"}:
            return jsonify({"success": False, "error": "Choose Monthly or Yearly billing."}), 400
        product_id = _product_id(plan)
        if not product_id:
            raise RuntimeError(f"Career Pro {plan} subscription product is not configured yet.")
        metadata = {
            "product": "career_pro",
            "source": "eggypdf",
            "plan": plan,
            "account_user_id": user["id"],
        }
        checkout_record = career_routes._dodo(
            "POST", "/checkouts",
            json={
                "product_cart": [{"product_id": product_id, "quantity": 1}],
                "return_url": career_routes.CAREER_PRO_RETURN_URL,
                "metadata": metadata,
            },
        )
        checkout_url = checkout_record.get("checkout_url")
        session_id = checkout_record.get("session_id")
        if not checkout_url or not session_id:
            raise RuntimeError("Payment service returned an incomplete checkout session.")
        return jsonify({
            "success": True,
            "checkout_url": checkout_url,
            "session_id": session_id,
            "plan": plan,
            "account_linked_checkout": True,
        })
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 401
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@career_system_bp.get("/subscription-checkout/<identifier>")
def verify_subscription_checkout(identifier: str):
    try:
        user = current_account_user(required=True)
        if not career_routes._valid(identifier, "cks_"):
            return jsonify({"success": False, "error": "Invalid checkout identifier."}), 400
        checkout = career_routes._dodo("GET", f"/checkouts/{identifier}")
        status = checkout.get("payment_status") or checkout.get("status")
        metadata = checkout.get("metadata") or {}
        if metadata.get("product") != "career_pro" or metadata.get("account_user_id") != user["id"]:
            raise PermissionError("This Career Pro checkout belongs to a different account.")
        plan = str(metadata.get("plan") or "").lower()
        if plan not in {"monthly", "annual"}:
            raise PermissionError("This checkout is not a valid Career Pro subscription checkout.")
        if status != "succeeded":
            return jsonify({"success": True, "paid": False, "payment_status": status, "plan": plan})

        payment_id = str(checkout.get("payment_id") or "").strip() or None
        subscription_id = str(checkout.get("subscription_id") or "").strip() or None
        customer = checkout.get("customer") or {}
        if payment_id and career_routes._valid(payment_id, "pay_"):
            try:
                payment = career_routes._dodo("GET", f"/payments/{payment_id}")
                subscription_id = subscription_id or str(payment.get("subscription_id") or "").strip() or None
                customer = payment.get("customer") or customer
            except Exception:
                pass
        _upsert_entitlement(
            user["id"],
            status="active",
            product_id=_product_id(plan),
            dodo_checkout_id=identifier,
            dodo_payment_id=payment_id,
            purchased_at=datetime.now(timezone.utc).isoformat(),
            plan=plan,
            access_source="paid",
            subscription_status="active",
            dodo_subscription_id=subscription_id,
            dodo_customer_id=customer.get("customer_id") if isinstance(customer, dict) else None,
            cancel_at_period_end=False,
            expires_at=None,
        )
        _rpc("career_reset_credits", {"p_user_id": user["id"], "p_allowance": MONTHLY_CREDITS})
        return jsonify({
            "success": True,
            "paid": True,
            "payment_status": status,
            "feature_id": "career_pro",
            "account_linked": True,
            "plan": plan,
            "credits": MONTHLY_CREDITS,
        })
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@career_system_bp.post("/webhooks/dodo")
def dodo_webhook():
    raw = request.get_data(cache=True, as_text=False)
    try:
        webhook_id = _verify_standard_webhook(raw)
        if _webhook_seen(webhook_id):
            return jsonify({"received": True, "duplicate": True})
        event = json.loads(raw.decode("utf-8"))
        event_type = str(event.get("type") or event.get("event_type") or "").strip()
        data = event.get("data") or {}
        _record_webhook(webhook_id, event_type, False)
        if event_type.startswith("subscription."):
            _sync_subscription(event_type, data)
        _record_webhook(webhook_id, event_type, True)
        return jsonify({"received": True})
    except PermissionError as exc:
        return jsonify({"received": False, "error": str(exc)}), 401
    except (ValueError, json.JSONDecodeError) as exc:
        return jsonify({"received": False, "error": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"received": False, "error": str(exc)}), 503
    except Exception as exc:
        try:
            if 'webhook_id' in locals():
                _record_webhook(webhook_id, locals().get("event_type", "unknown"), False, str(exc)[:500])
        except Exception:
            pass
        return jsonify({"received": False, "error": "Webhook processing failed."}), 500


def install() -> None:
    """Install enriched account state and AI-credit enforcement before register_blueprint."""
    account_routes.account_bp.view_functions["account.me"] = _enriched_me

    wrapped = {
        "career.pro_optimize": ("resume_optimizer", CREDIT_COSTS["resume_optimizer"]),
        "career.tailor": ("job_tailoring", CREDIT_COSTS["job_tailoring"]),
        "career.letter": ("cover_letter", CREDIT_COSTS["cover_letter"]),
        "career.pro_regenerate_section": ("section_regeneration", CREDIT_COSTS["section_regeneration"]),
        "career.pro_pdf_summary": ("pdf_summarizer", CREDIT_COSTS["pdf_summarizer"]),
    }
    for endpoint, (action, amount) in wrapped.items():
        original = career_routes.career_bp.view_functions.get(endpoint)
        if original and not getattr(original, "_eggy_credit_wrapped", False):
            replacement = _credit_wrapper(original, action, amount)
            replacement._eggy_credit_wrapped = True
            career_routes.career_bp.view_functions[endpoint] = replacement
