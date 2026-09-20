"""Career Pro V1 billing API.

Monthly/yearly checkout selection, account credit status and creator-code
redemption live here so the existing PDF and ATS routes stay independent.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

import career_routes
from account_routes import current_account_user, get_career_entitlement, grant_career_pro
from career_billing import _request, recent_events, redeem_creator_code, wallet

billing_bp = Blueprint("billing", __name__, url_prefix="/api/billing")
MONTHLY_CREDITS = 2000
SUCCESS_STATES = {"succeeded", "success", "paid"}


def _products() -> dict[str, str]:
    return {
        "monthly": os.getenv("DODO_CAREER_MONTHLY_PRODUCT_ID", "").strip(),
        "yearly": os.getenv("DODO_CAREER_YEARLY_PRODUCT_ID", "").strip(),
    }


def _user():
    return current_account_user(required=True)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plan_for_product(product_id: str) -> str | None:
    for plan, configured_id in _products().items():
        if configured_id and configured_id == product_id:
            return plan
    return None


def _entitlement_full(user_id: str) -> dict | None:
    r = _request(
        "GET",
        "/rest/v1/career_entitlements",
        params={
            "select": "user_id,status,product_id,plan,source,dodo_checkout_id,dodo_payment_id,dodo_subscription_id,purchased_at,current_period_start,current_period_end,cancel_at_period_end,access_ends_at,monthly_credits,updated_at",
            "user_id": f"eq.{user_id}",
            "limit": "1",
        },
    )
    if not r.ok:
        raise RuntimeError("Could not read Career Pro subscription status.")
    rows = r.json() or []
    return rows[0] if rows else None


def _save_subscription_fields(
    user_id: str,
    *,
    plan: str,
    product_id: str,
    checkout_id: str | None,
    payment_id: str | None,
    subscription: dict,
) -> None:
    grant_career_pro(
        user_id,
        product_id=product_id,
        checkout_id=checkout_id,
        payment_id=payment_id,
    )
    subscription_id = (subscription.get("subscription_id") or "").strip() or None
    current_start = subscription.get("previous_billing_date") or _iso_now()
    current_end = subscription.get("next_billing_date")
    status = (subscription.get("status") or "active").strip().lower()
    if status not in {"active", "on_hold", "cancelled", "expired", "failed"}:
        status = "active"
    access_active = status == "active" or bool(subscription.get("cancel_at_next_billing_date"))
    entitlement_status = "active" if access_active else ("on_hold" if status == "on_hold" else status)
    access_ends = current_end if subscription.get("cancel_at_next_billing_date") else None

    payload = {
        "status": entitlement_status,
        "plan": plan,
        "source": "dodo",
        "dodo_subscription_id": subscription_id,
        "monthly_credits": MONTHLY_CREDITS,
        "cancel_at_period_end": bool(subscription.get("cancel_at_next_billing_date")),
        "purchased_at": subscription.get("created_at") or _iso_now(),
        "current_period_start": current_start,
        "current_period_end": current_end,
        "access_ends_at": access_ends,
    }
    r = _request(
        "PATCH",
        "/rest/v1/career_entitlements",
        params={"user_id": f"eq.{user_id}"},
        json=payload,
        prefer="return=minimal",
    )
    if not r.ok:
        raise RuntimeError("Career Pro payment was verified, but the subscription record could not be completed.")
    if entitlement_status == "active":
        wallet(user_id, refresh=True)


def _checkout_record(identifier: str) -> dict:
    if not career_routes._valid(identifier, "cks_"):
        raise ValueError("Invalid checkout identifier.")
    return career_routes._dodo("GET", f"/checkouts/{identifier}")


def _payment_record(payment_id: str) -> dict:
    if not career_routes._valid(payment_id, "pay_"):
        raise ValueError("Invalid payment identifier returned by Dodo Payments.")
    return career_routes._dodo("GET", f"/payments/{payment_id}")


def _subscription_record(subscription_id: str) -> dict:
    if not career_routes._valid(subscription_id, "sub_"):
        raise ValueError("Invalid subscription identifier returned by Dodo Payments.")
    return career_routes._dodo("GET", f"/subscriptions/{subscription_id}")


@billing_bp.get("/plans")
def plans():
    configured = _products()
    return jsonify(
        {
            "success": True,
            "default_plan": "yearly",
            "monthly": {
                "price_usd": 6.99,
                "billing_label": "$6.99 USD billed monthly",
                "credits": MONTHLY_CREDITS,
                "configured": bool(configured["monthly"]),
            },
            "yearly": {
                "price_usd": 48,
                "billing_label": "$48 USD billed annually",
                "effective_monthly_usd": 4,
                "savings_usd": 35.88,
                "savings_percent": 43,
                "credits": MONTHLY_CREDITS,
                "configured": bool(configured["yearly"]),
            },
        }
    )


@billing_bp.get("/me")
def me():
    try:
        user = _user()
        entitlement = _entitlement_full(user["id"])
        active = bool(entitlement and entitlement.get("status") == "active")
        credit_wallet = wallet(user["id"], refresh=True) if active else None
        return jsonify(
            {
                "success": True,
                "user": {"id": user.get("id"), "email": user.get("email")},
                "career_pro": {"active": active, "entitlement": entitlement},
                "credits": credit_wallet,
            }
        )
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 401
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@billing_bp.get("/credits/history")
def credit_history():
    try:
        user = _user()
        return jsonify({"success": True, "events": recent_events(user["id"], 30)})
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 401
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@billing_bp.post("/creator-code/redeem")
def redeem_code():
    try:
        user = _user()
        data = request.get_json(silent=True) or {}
        result = redeem_creator_code(user["id"], data.get("code") or "")
        status = 200 if result.get("success") else 400
        if result.get("success"):
            result["wallet"] = wallet(user["id"], refresh=True)
        return jsonify(result), status
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 401
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@billing_bp.post("/checkout")
def checkout():
    try:
        user = _user()
        data = request.get_json(silent=True) or {}
        plan = (data.get("plan") or "yearly").strip().lower()
        products = _products()
        if plan not in products:
            return jsonify({"success": False, "error": "Choose monthly or yearly."}), 400
        product_id = products[plan]
        if not product_id:
            return jsonify({"success": False, "error": f"Career Pro {plan} checkout is not configured yet."}), 503

        record = career_routes._dodo(
            "POST",
            "/checkouts",
            json={
                "product_cart": [{"product_id": product_id, "quantity": 1}],
                "customer": {"email": user.get("email")},
                "return_url": os.getenv(
                    "CAREER_PRO_RETURN_URL",
                    "https://eggypdf.com/ats-checker.html?career_pro=return",
                ),
                "metadata": {
                    "product": "career_pro",
                    "plan": plan,
                    "account_user_id": user["id"],
                    "source": "eggypdf",
                },
            },
        )
        url = record.get("checkout_url")
        session_id = record.get("session_id")
        if not url or not session_id:
            raise RuntimeError("Payment service returned an incomplete checkout session.")
        return jsonify({"success": True, "plan": plan, "checkout_url": url, "session_id": session_id})
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 401
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@billing_bp.get("/checkout/<identifier>")
def verify_checkout(identifier: str):
    """Server-side verification of a recurring Career Pro checkout."""
    try:
        user = _user()
        checkout = _checkout_record(identifier)
        checkout_status = (checkout.get("payment_status") or checkout.get("status") or "").strip().lower()
        payment_id = (checkout.get("payment_id") or "").strip()
        if checkout_status not in SUCCESS_STATES or not payment_id:
            return jsonify({"success": True, "paid": False, "active": False, "payment_status": checkout_status or None})

        payment = _payment_record(payment_id)
        payment_status = (payment.get("status") or "").strip().lower()
        if payment_status not in SUCCESS_STATES:
            return jsonify({"success": True, "paid": False, "active": False, "payment_status": payment_status or None})
        if (payment.get("checkout_session_id") or "").strip() != identifier:
            raise PermissionError("Payment verification did not match this checkout session.")

        subscription_id = (payment.get("subscription_id") or "").strip()
        if not subscription_id:
            raise ValueError("This payment did not create a Career Pro subscription.")
        subscription = _subscription_record(subscription_id)
        product_id = (subscription.get("product_id") or "").strip()
        plan = _plan_for_product(product_id)
        if not plan:
            raise PermissionError("The verified subscription is not an EggyPDF Career Pro plan.")

        payment_meta = payment.get("metadata") or {}
        subscription_meta = subscription.get("metadata") or {}
        owner = str(
            payment_meta.get("account_user_id")
            or subscription_meta.get("account_user_id")
            or ""
        ).strip()
        if owner != user["id"]:
            raise PermissionError("This Career Pro subscription belongs to a different EggyPDF account.")

        sub_status = (subscription.get("status") or "").strip().lower()
        if sub_status not in {"active", "on_hold"}:
            return jsonify({"success": True, "paid": True, "active": False, "subscription_status": sub_status, "plan": plan})

        _save_subscription_fields(
            user["id"],
            plan=plan,
            product_id=product_id,
            checkout_id=identifier,
            payment_id=payment_id,
            subscription=subscription,
        )
        entitlement = _entitlement_full(user["id"])
        active = bool(entitlement and entitlement.get("status") == "active")
        return jsonify(
            {
                "success": True,
                "paid": True,
                "active": active,
                "payment_status": payment_status or "succeeded",
                "subscription_status": sub_status,
                "plan": plan,
                "subscription_id": subscription_id,
                "credits": wallet(user["id"], refresh=True) if active else None,
            }
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except RuntimeError as exc:
        message = str(exc)
        if "could not find the requested checkout resource" in message.lower():
            return jsonify({"success": False, "error": "This checkout session is no longer available.", "stale_checkout": True}), 404
        return jsonify({"success": False, "error": message}), 503
