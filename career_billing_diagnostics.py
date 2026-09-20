"""Signed-in Career Pro activation diagnostics.

Returns only non-secret state needed to troubleshoot activation. No API keys,
full product ids, checkout ids, payment ids or subscription ids are exposed.
"""
from __future__ import annotations

import os
from flask import Blueprint, jsonify

import career_routes
from account_routes import current_account_user, get_career_entitlement
from career_billing import wallet
from career_reconcile_routes import _find_active_subscription_by_email

billing_diagnostics_bp = Blueprint(
    "billing_diagnostics", __name__, url_prefix="/api/billing"
)


def _product_summary(product_id: str) -> dict:
    if not product_id:
        return {"configured": False}
    try:
        p = career_routes._dodo("GET", f"/products/{product_id}")
        price = p.get("price") or p.get("price_detail") or {}
        if not isinstance(price, dict):
            price = {}
        return {
            "configured": True,
            "api_ok": True,
            "name": p.get("name"),
            "is_recurring": bool(p.get("is_recurring")),
            "price_type": price.get("type"),
            "currency": price.get("currency") or p.get("currency"),
        }
    except Exception as exc:
        return {
            "configured": True,
            "api_ok": False,
            "error": str(exc),
        }


@billing_diagnostics_bp.get("/diagnose-account")
def diagnose_account():
    try:
        user = current_account_user(required=True)
        user_id = user["id"]
        email = str(user.get("email") or "").strip().lower()

        entitlement = get_career_entitlement(user_id)
        entitlement_summary = {
            "exists": bool(entitlement),
            "status": entitlement.get("status") if entitlement else None,
            "active": bool(entitlement and entitlement.get("status") == "active"),
        }

        credit_summary = {"checked": False}
        if entitlement_summary["active"]:
            try:
                w = wallet(user_id, refresh=True)
                credit_summary = {
                    "checked": True,
                    "ok": True,
                    "balance": w.get("balance"),
                    "monthly_allowance": w.get("monthly_allowance"),
                }
            except Exception as exc:
                credit_summary = {
                    "checked": True,
                    "ok": False,
                    "error": str(exc),
                }

        monthly_id = (os.getenv("DODO_CAREER_MONTHLY_PRODUCT_ID") or "").strip()
        yearly_id = (os.getenv("DODO_CAREER_YEARLY_PRODUCT_ID") or "").strip()
        products = {
            "monthly": _product_summary(monthly_id),
            "yearly": _product_summary(yearly_id),
        }

        match = None
        match_error = None
        try:
            match = _find_active_subscription_by_email(email)
        except Exception as exc:
            match_error = str(exc)

        subscription_summary = {
            "active_match_found": bool(match),
            "plan": match[0] if match else None,
            "status": (match[2].get("status") if match else None),
            "period_interval": (match[2].get("subscription_period_interval") if match else None),
            "payment_interval": (match[2].get("payment_frequency_interval") if match else None),
            "error": match_error,
        }

        environment = "test" if "test" in (os.getenv("DODO_API_BASE") or "").lower() else "live"

        if entitlement_summary["active"]:
            diagnosis = "entitlement_active"
        elif not products["yearly"].get("api_ok", products["yearly"].get("configured") is False):
            diagnosis = "yearly_product_lookup_failed"
        elif products["yearly"].get("configured") and not products["yearly"].get("is_recurring"):
            diagnosis = "yearly_product_not_recurring"
        elif match_error:
            diagnosis = "dodo_subscription_lookup_failed"
        elif not match:
            diagnosis = "no_active_matching_subscription"
        else:
            diagnosis = "subscription_found_but_entitlement_missing"

        return jsonify({
            "success": True,
            "environment": environment,
            "diagnosis": diagnosis,
            "entitlement": entitlement_summary,
            "credits": credit_summary,
            "products": products,
            "subscription": subscription_summary,
        })
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 401
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 503
