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


def _products() -> dict[str, str]:
    return {
        "monthly": os.getenv("DODO_CAREER_MONTHLY_PRODUCT_ID", "").strip(),
        "yearly": os.getenv("DODO_CAREER_YEARLY_PRODUCT_ID", "").strip(),
    }


def _user():
    return current_account_user(required=True)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save_subscription_fields(user_id: str, *, plan: str, product_id: str, checkout_id: str | None, payment_id: str | None) -> None:
    # grant_career_pro keeps compatibility with the existing entitlement table.
    grant_career_pro(
        user_id,
        product_id=product_id,
        checkout_id=checkout_id,
        payment_id=payment_id,
    )
    payload = {
        "plan": plan,
        "source": "dodo",
        "monthly_credits": MONTHLY_CREDITS,
        "cancel_at_period_end": False,
        "purchased_at": _iso_now(),
        "current_period_start": _iso_now(),
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
    # Creating/refeshing the wallet is delegated to the database RPC so annual
    # subscriptions also receive a fresh 2,000-credit cycle every month.
    wallet(user_id, refresh=True)


def _checkout_record(identifier: str) -> dict:
    # Dodo checkout session IDs are server-created and verified directly with
    # Dodo. We intentionally do not trust query-string return parameters.
    if not career_routes._valid(identifier, "cks_"):
        raise ValueError("Invalid checkout identifier.")
    checkout = career_routes._dodo("GET", f"/checkouts/{identifier}")
    return checkout


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
        entitlement = get_career_entitlement(user["id"])
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
    try:
        user = _user()
        checkout = _checkout_record(identifier)
        status = checkout.get("payment_status") or checkout.get("status")
        metadata = checkout.get("metadata") or {}
        plan = (metadata.get("plan") or "").strip().lower()
        owner = (metadata.get("account_user_id") or "").strip()
        if owner != user["id"]:
            raise PermissionError("This Career Pro purchase belongs to a different EggyPDF account.")
        if plan not in ("monthly", "yearly"):
            raise ValueError("This checkout is not a Career Pro monthly/yearly purchase.")
        if status != "succeeded":
            return jsonify({"success": True, "paid": False, "payment_status": status, "plan": plan})

        products = _products()
        expected_product = products.get(plan)
        if not expected_product:
            raise RuntimeError("Career Pro product configuration is missing.")
        payment_id = (checkout.get("payment_id") or "").strip() or None
        _save_subscription_fields(
            user["id"],
            plan=plan,
            product_id=expected_product,
            checkout_id=identifier,
            payment_id=payment_id,
        )
        return jsonify(
            {
                "success": True,
                "paid": True,
                "payment_status": status,
                "plan": plan,
                "credits": wallet(user["id"], refresh=True),
            }
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503
