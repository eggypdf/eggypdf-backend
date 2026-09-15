"""Attach Career Pro account/credit guards after Flask registers blueprints."""
from __future__ import annotations

from datetime import datetime, timezone

from flask import jsonify

import account_routes
import career_routes
from account_routes import current_account_user
from career_pro_system import (
    CREDIT_COSTS,
    MONTHLY_CREDITS,
    _career_status,
    _credit_wrapper,
    _enriched_me,
    _entitlement,
    _product_id,
    _rpc,
    _upsert_entitlement,
)


def _active_career_pro(user_id: str) -> bool:
    """Use the recurring entitlement rules everywhere, including zero-credit Pro routes."""
    try:
        return bool(_career_status(user_id).get("active"))
    except Exception:
        return False


def _verify_subscription_checkout(identifier: str):
    """Verify once, bind to the signed-in account, and never re-grant credits on refresh."""
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

        # The return URL can be revisited many times. Never let a refresh mint
        # another 2,000 credits for the same checkout.
        existing = _entitlement(user["id"])
        already_linked = bool(
            existing
            and existing.get("status") == "active"
            and existing.get("dodo_checkout_id") == identifier
            and existing.get("plan") == plan
        )

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

        # If Dodo already exposes the subscription object, persist the exact
        # paid period immediately. Otherwise subscription.active/updated will
        # fill these fields through the verified webhook shortly afterwards.
        current_period_start = (existing or {}).get("current_period_start")
        current_period_end = (existing or {}).get("current_period_end")
        subscription_status = "active"
        cancel_at_period_end = False
        if subscription_id:
            try:
                subscription = career_routes._dodo("GET", f"/subscriptions/{subscription_id}")
                current_period_start = subscription.get("previous_billing_date") or current_period_start
                current_period_end = subscription.get("next_billing_date") or current_period_end
                subscription_status = str(subscription.get("status") or "active").lower()
                cancel_at_period_end = bool(subscription.get("cancel_at_next_billing_date"))
                sub_customer = subscription.get("customer") or {}
                if isinstance(sub_customer, dict) and sub_customer.get("customer_id"):
                    customer = sub_customer
            except Exception:
                pass

        _upsert_entitlement(
            user["id"],
            status="active",
            product_id=_product_id(plan),
            dodo_checkout_id=identifier,
            dodo_payment_id=payment_id,
            purchased_at=(existing or {}).get("purchased_at") or datetime.now(timezone.utc).isoformat(),
            plan=plan,
            access_source="paid",
            subscription_status=subscription_status,
            dodo_subscription_id=subscription_id or (existing or {}).get("dodo_subscription_id"),
            dodo_customer_id=(customer.get("customer_id") if isinstance(customer, dict) else None) or (existing or {}).get("dodo_customer_id"),
            current_period_start=current_period_start,
            current_period_end=current_period_end,
            cancel_at_period_end=cancel_at_period_end,
            expires_at=None,
        )
        if not already_linked:
            _rpc("career_reset_credits", {"p_user_id": user["id"], "p_allowance": MONTHLY_CREDITS})

        return jsonify({
            "success": True,
            "paid": True,
            "payment_status": status,
            "feature_id": "career_pro",
            "account_linked": True,
            "plan": plan,
            "credits": MONTHLY_CREDITS,
            "credits_granted": not already_linked,
        })
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


def install(app) -> None:
    # Keep every access path on the same recurring/promo entitlement rules.
    account_routes.user_has_career_pro = _active_career_pro
    career_routes.user_has_career_pro = _active_career_pro
    app.view_functions["account.me"] = _enriched_me
    app.view_functions["career_system.verify_subscription_checkout"] = _verify_subscription_checkout

    wrapped = {
        "career.pro_optimize": ("resume_optimizer", CREDIT_COSTS["resume_optimizer"]),
        "career.tailor": ("job_tailoring", CREDIT_COSTS["job_tailoring"]),
        "career.letter": ("cover_letter", CREDIT_COSTS["cover_letter"]),
        "career.pro_regenerate_section": ("section_regeneration", CREDIT_COSTS["section_regeneration"]),
        "career.pro_pdf_summary": ("pdf_summarizer", CREDIT_COSTS["pdf_summarizer"]),
    }
    for endpoint, (action, amount) in wrapped.items():
        original = app.view_functions.get(endpoint)
        if original and not getattr(original, "_eggy_credit_wrapped", False):
            replacement = _credit_wrapper(original, action, amount)
            replacement._eggy_credit_wrapped = True
            app.view_functions[endpoint] = replacement
