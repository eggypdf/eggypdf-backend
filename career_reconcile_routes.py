"""Recover a completed Career Pro checkout into the signed-in EggyPDF account.

This is intentionally separate from checkout creation. It verifies the Dodo
checkout, payment, subscription, Career Pro product and account ownership before
creating/updating the Supabase entitlement.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, jsonify

import career_routes
from account_routes import current_account_user, grant_career_pro
from career_billing import _request, wallet

reconcile_bp = Blueprint("career_reconcile", __name__, url_prefix="/api/billing")
SUCCESS_STATES = {"succeeded", "success", "paid"}


def _products() -> dict[str, str]:
    return {
        "monthly": (os.getenv("DODO_CAREER_MONTHLY_PRODUCT_ID") or "").strip(),
        "yearly": (os.getenv("DODO_CAREER_YEARLY_PRODUCT_ID") or "").strip(),
    }


def _plan(product_id: str) -> str | None:
    for name, configured in _products().items():
        if configured and configured == product_id:
            return name
    return None


def _metadata(obj: dict[str, Any] | None) -> dict[str, Any]:
    value = (obj or {}).get("metadata") or {}
    return value if isinstance(value, dict) else {}


def _owner_ids(*objects: dict[str, Any] | None) -> set[str]:
    ids: set[str] = set()
    for obj in objects:
        value = str(_metadata(obj).get("account_user_id") or "").strip()
        if value:
            ids.add(value)
    return ids


def _candidate_emails(*objects: dict[str, Any] | None) -> set[str]:
    emails: set[str] = set()
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        direct = obj.get("customer_email") or obj.get("email")
        if direct:
            emails.add(str(direct).strip().lower())
        customer = obj.get("customer")
        if isinstance(customer, dict) and customer.get("email"):
            emails.add(str(customer.get("email")).strip().lower())
    return {x for x in emails if x}


def _patch_entitlement(user_id: str, *, plan: str, product_id: str, checkout_id: str,
                       payment_id: str, subscription: dict[str, Any]) -> None:
    subscription_id = str(subscription.get("subscription_id") or subscription.get("id") or "").strip() or None
    sub_status = str(subscription.get("status") or "active").strip().lower()
    cancel_next = bool(subscription.get("cancel_at_next_billing_date"))
    next_billing = subscription.get("next_billing_date")
    previous_billing = subscription.get("previous_billing_date")
    created_at = subscription.get("created_at") or datetime.now(timezone.utc).isoformat()

    # First guarantee the row exists.
    grant_career_pro(
        user_id,
        product_id=product_id,
        checkout_id=checkout_id,
        payment_id=payment_id,
    )

    # Then enrich it with V1 subscription fields.
    payload = {
        "status": "active" if sub_status == "active" else sub_status,
        "plan": plan,
        "source": "dodo",
        "dodo_subscription_id": subscription_id,
        "purchased_at": created_at,
        "current_period_start": previous_billing,
        "current_period_end": next_billing,
        "cancel_at_period_end": cancel_next,
        "access_ends_at": next_billing if cancel_next and sub_status == "active" else None,
        "monthly_credits": 2000,
    }
    r = _request(
        "PATCH",
        "/rest/v1/career_entitlements",
        params={"user_id": f"eq.{user_id}"},
        json=payload,
        prefer="return=minimal",
    )
    if not r.ok:
        raise RuntimeError("Payment was verified, but EggyPDF could not finish activating Career Pro.")

    wallet(user_id, refresh=True)


@reconcile_bp.get("/reconcile/<identifier>")
def reconcile_checkout(identifier: str):
    try:
        user = current_account_user(required=True)
        if not career_routes._valid(identifier, "cks_"):
            return jsonify({"success": False, "error": "Invalid checkout identifier."}), 400

        checkout = career_routes._dodo("GET", f"/checkouts/{identifier}")
        payment_id = str(checkout.get("payment_id") or "").strip()
        checkout_status = str(checkout.get("payment_status") or checkout.get("status") or "").strip().lower()

        if not payment_id:
            return jsonify({
                "success": True,
                "paid": False,
                "active": False,
                "pending": True,
                "payment_status": checkout_status or None,
            })

        payment = career_routes._dodo("GET", f"/payments/{payment_id}")
        payment_status = str(payment.get("status") or checkout_status or "").strip().lower()
        if payment_status not in SUCCESS_STATES:
            return jsonify({
                "success": True,
                "paid": False,
                "active": False,
                "pending": payment_status in {"processing", "requires_customer_action", "requires_merchant_action", "requires_payment_method", "requires_confirmation", "requires_capture"},
                "payment_status": payment_status or None,
            })

        payment_checkout = str(payment.get("checkout_session_id") or "").strip()
        if payment_checkout and payment_checkout != identifier:
            return jsonify({"success": False, "error": "Payment did not match this checkout session."}), 403

        subscription_id = str(payment.get("subscription_id") or "").strip()
        if not subscription_id:
            return jsonify({"success": False, "error": "The completed payment did not create a Career Pro subscription."}), 409

        subscription = career_routes._dodo("GET", f"/subscriptions/{subscription_id}")
        product_id = str(subscription.get("product_id") or "").strip()
        plan = _plan(product_id)
        if not plan:
            return jsonify({"success": False, "error": "This subscription is not one of EggyPDF's configured Career Pro plans."}), 403

        # Strongest ownership check: account_user_id metadata from any Dodo object.
        owner_ids = _owner_ids(checkout, payment, subscription)
        if owner_ids and user["id"] not in owner_ids:
            return jsonify({"success": False, "error": "This Career Pro payment belongs to another EggyPDF account."}), 403

        # Fallback for Dodo objects that do not copy checkout metadata to the
        # payment/subscription: checkout was created with the signed-in email.
        if not owner_ids:
            account_email = str(user.get("email") or "").strip().lower()
            emails = _candidate_emails(checkout, payment, subscription)
            if not account_email or account_email not in emails:
                return jsonify({
                    "success": False,
                    "error": "EggyPDF could not safely link this payment to the signed-in account. Sign in with the email used at checkout.",
                }), 403

        sub_status = str(subscription.get("status") or "").strip().lower()
        if sub_status != "active":
            return jsonify({
                "success": True,
                "paid": True,
                "active": False,
                "pending": sub_status in {"pending", "on_hold"},
                "subscription_status": sub_status or None,
                "plan": plan,
            })

        _patch_entitlement(
            user["id"],
            plan=plan,
            product_id=product_id,
            checkout_id=identifier,
            payment_id=payment_id,
            subscription=subscription,
        )

        return jsonify({
            "success": True,
            "paid": True,
            "active": True,
            "plan": plan,
            "payment_status": payment_status,
            "subscription_status": sub_status,
            "subscription_id": subscription_id,
            "credits": wallet(user["id"], refresh=True),
        })

    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 401
    except RuntimeError as exc:
        message = str(exc)
        if "could not find the requested checkout resource" in message.lower():
            return jsonify({"success": False, "error": "This checkout session is no longer available.", "stale_checkout": True}), 404
        return jsonify({"success": False, "error": message}), 503
    except Exception:
        return jsonify({"success": False, "error": "EggyPDF could not verify this Career Pro payment."}), 500
