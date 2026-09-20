"""Recover completed Career Pro subscriptions into the signed-in EggyPDF account.

Two recovery paths are supported:
1) checkout reconciliation using a saved checkout-session id;
2) account reconciliation using the signed-in email -> Dodo customer -> active
   Career Pro subscription.

Both paths verify the configured Career Pro product before creating/updating the
Supabase entitlement and 2,000-credit wallet.
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


def _items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        rows = payload.get("items") or payload.get("data") or []
        return [x for x in rows if isinstance(x, dict)] if isinstance(rows, list) else []
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    return []


def _patch_entitlement(
    user_id: str,
    *,
    plan: str,
    product_id: str,
    subscription: dict[str, Any],
    checkout_id: str | None = None,
    payment_id: str | None = None,
) -> None:
    subscription_id = str(
        subscription.get("subscription_id") or subscription.get("id") or ""
    ).strip() or None
    sub_status = str(subscription.get("status") or "active").strip().lower()
    cancel_next = bool(subscription.get("cancel_at_next_billing_date"))
    next_billing = subscription.get("next_billing_date")
    previous_billing = subscription.get("previous_billing_date")
    created_at = subscription.get("created_at") or datetime.now(timezone.utc).isoformat()

    # First guarantee the entitlement row exists.
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
        raise RuntimeError(
            "Payment was verified, but EggyPDF could not finish activating Career Pro."
        )

    wallet(user_id, refresh=True)


def _latest_successful_payment(subscription_id: str) -> tuple[str | None, str | None]:
    if not subscription_id:
        return None, None
    try:
        record = career_routes._dodo(
            "GET",
            "/payments",
            params={
                "subscription_id": subscription_id,
                "status": "succeeded",
                "page_size": 100,
                "page_number": 0,
            },
        )
    except RuntimeError:
        return None, None
    rows = _items(record)
    if not rows:
        return None, None
    rows.sort(key=lambda x: str(x.get("created_at") or x.get("updated_at") or ""), reverse=True)
    payment = rows[0]
    return (
        str(payment.get("payment_id") or payment.get("id") or "").strip() or None,
        str(payment.get("checkout_session_id") or "").strip() or None,
    )


def _find_active_subscription_by_email(email: str) -> tuple[str, str, dict[str, Any]] | None:
    email = str(email or "").strip().lower()
    if not email:
        return None

    customer_record = career_routes._dodo(
        "GET",
        "/customers",
        params={"email": email, "page_size": 100, "page_number": 0},
    )
    customers = [
        c for c in _items(customer_record)
        if str(c.get("email") or "").strip().lower() == email
    ]
    if not customers:
        return None

    matches: list[tuple[str, str, dict[str, Any]]] = []
    products = _products()
    for customer in customers:
        customer_id = str(customer.get("customer_id") or customer.get("id") or "").strip()
        if not customer_id:
            continue
        for plan, product_id in products.items():
            if not product_id:
                continue
            subs_record = career_routes._dodo(
                "GET",
                "/subscriptions",
                params={
                    "customer_id": customer_id,
                    "product_id": product_id,
                    "status": "active",
                    "page_size": 100,
                    "page_number": 0,
                },
            )
            for sub in _items(subs_record):
                if str(sub.get("product_id") or "").strip() != product_id:
                    continue
                if str(sub.get("status") or "").strip().lower() != "active":
                    continue
                sub_email = str((sub.get("customer") or {}).get("email") or "").strip().lower()
                if sub_email and sub_email != email:
                    continue
                matches.append((plan, product_id, sub))

    if not matches:
        return None
    matches.sort(
        key=lambda item: str(item[2].get("created_at") or item[2].get("previous_billing_date") or ""),
        reverse=True,
    )
    return matches[0]


@reconcile_bp.get("/reconcile-account")
def reconcile_account():
    """Recover an active Dodo Career Pro subscription by signed-in email."""
    try:
        user = current_account_user(required=True)
        email = str(user.get("email") or "").strip().lower()
        if not email:
            return jsonify({"success": False, "error": "Your EggyPDF account has no email address."}), 400

        match = _find_active_subscription_by_email(email)
        if not match:
            return jsonify({
                "success": True,
                "active": False,
                "found_subscription": False,
            })

        plan, product_id, subscription = match
        subscription_id = str(
            subscription.get("subscription_id") or subscription.get("id") or ""
        ).strip()
        payment_id, checkout_id = _latest_successful_payment(subscription_id)

        _patch_entitlement(
            user["id"],
            plan=plan,
            product_id=product_id,
            subscription=subscription,
            checkout_id=checkout_id,
            payment_id=payment_id,
        )

        return jsonify({
            "success": True,
            "active": True,
            "found_subscription": True,
            "plan": plan,
            "subscription_id": subscription_id or None,
            "credits": wallet(user["id"], refresh=True),
        })
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 401
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503
    except Exception:
        return jsonify({"success": False, "error": "EggyPDF could not restore this Career Pro subscription."}), 500


@reconcile_bp.get("/reconcile/<identifier>")
def reconcile_checkout(identifier: str):
    try:
        user = current_account_user(required=True)
        if not career_routes._valid(identifier, "cks_"):
            return jsonify({"success": False, "error": "Invalid checkout identifier."}), 400

        checkout = career_routes._dodo("GET", f"/checkouts/{identifier}")
        payment_id = str(checkout.get("payment_id") or "").strip()
        checkout_status = str(
            checkout.get("payment_status") or checkout.get("status") or ""
        ).strip().lower()

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
                "pending": payment_status in {
                    "processing",
                    "requires_customer_action",
                    "requires_merchant_action",
                    "requires_payment_method",
                    "requires_confirmation",
                    "requires_capture",
                },
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

        owner_ids = _owner_ids(checkout, payment, subscription)
        if owner_ids and user["id"] not in owner_ids:
            return jsonify({"success": False, "error": "This Career Pro payment belongs to another EggyPDF account."}), 403

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
