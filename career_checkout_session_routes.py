"""Robust Career Pro checkout-session endpoint.

This route exists to keep the preferred frontend UI stable while guaranteeing
that checkout creation always returns JSON to the browser, even if Dodo returns
an unexpected response.
"""
from __future__ import annotations

import os

import requests
from flask import Blueprint, jsonify, request

from account_routes import current_account_user

checkout_session_bp = Blueprint(
    "checkout_session",
    __name__,
    url_prefix="/api/billing",
)


def _dodo_base() -> str:
    explicit = (os.getenv("DODO_API_BASE") or "").strip().rstrip("/")
    if explicit:
        return explicit
    environment = (os.getenv("DODO_PAYMENTS_ENVIRONMENT") or "").strip().lower()
    if "test" in environment:
        return "https://test.dodopayments.com"
    return "https://live.dodopayments.com"


def _product_id(plan: str) -> str:
    name = "DODO_CAREER_YEARLY_PRODUCT_ID" if plan == "yearly" else "DODO_CAREER_MONTHLY_PRODUCT_ID"
    return (os.getenv(name) or "").strip()


def _safe_error(resp: requests.Response) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict):
            return str(
                data.get("message")
                or data.get("error")
                or data.get("detail")
                or ""
            ).strip()
    except Exception:
        pass
    return ""


@checkout_session_bp.post("/checkout-session")
def create_checkout_session():
    try:
        user = current_account_user(required=True)
        data = request.get_json(silent=True) or {}
        plan = str(data.get("plan") or "yearly").strip().lower()
        if plan not in {"monthly", "yearly"}:
            return jsonify({"success": False, "error": "Choose monthly or yearly."}), 400

        product_id = _product_id(plan)
        if not product_id:
            return jsonify({
                "success": False,
                "error": f"Career Pro {plan} checkout is not configured yet.",
            }), 503

        api_key = (os.getenv("DODO_PAYMENTS_API_KEY") or "").strip()
        if not api_key:
            return jsonify({"success": False, "error": "Dodo Payments is not configured yet."}), 503

        payload = {
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
        }

        try:
            resp = requests.post(
                f"{_dodo_base()}/checkouts",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=payload,
                timeout=25,
                allow_redirects=False,
            )
        except requests.RequestException:
            return jsonify({
                "success": False,
                "error": "The payment service is temporarily unavailable. Please try again.",
            }), 503

        if 300 <= resp.status_code < 400:
            return jsonify({
                "success": False,
                "error": "The payment service returned an unexpected redirect. Check the Dodo test/live environment configuration.",
            }), 503

        if not resp.ok:
            provider_error = _safe_error(resp)
            if resp.status_code in (401, 403):
                message = "Dodo authentication failed. Check that the API key matches the selected test/live environment."
            elif resp.status_code == 404:
                message = "Dodo could not find this Career Pro product. Check that the product ID belongs to the same test/live environment as the API key."
            elif resp.status_code in (400, 409, 422):
                message = provider_error or "Dodo rejected the checkout configuration. Check the product and return URL settings."
            elif resp.status_code == 429:
                message = "Dodo is rate-limiting checkout requests. Please try again shortly."
            else:
                message = provider_error or f"Payment service rejected the request (HTTP {resp.status_code})."
            return jsonify({"success": False, "error": message}), 503

        try:
            record = resp.json()
        except Exception:
            return jsonify({
                "success": False,
                "error": "The payment service returned an unexpected response. Check the Dodo test/live environment configuration.",
            }), 503

        checkout_url = record.get("checkout_url")
        session_id = record.get("session_id") or record.get("id")
        if not checkout_url or not session_id:
            return jsonify({
                "success": False,
                "error": "The payment service returned an incomplete checkout session.",
            }), 503

        return jsonify({
            "success": True,
            "plan": plan,
            "checkout_url": checkout_url,
            "session_id": session_id,
        })

    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 401
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503
    except Exception:
        return jsonify({
            "success": False,
            "error": "EggyPDF could not start the checkout. Please try again.",
        }), 500
