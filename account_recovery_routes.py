"""EggyPDF account recovery helpers backed by Supabase Auth."""
from __future__ import annotations

import os
import requests
from flask import Blueprint, jsonify, request

from account_routes import _cfg, _auth_headers

account_recovery_bp = Blueprint("account_recovery", __name__, url_prefix="/api/account")


def _email(data) -> str:
    return str((data or {}).get("email") or "").strip().lower()


def _redirect_url() -> str:
    return (os.getenv("ACCOUNT_AUTH_REDIRECT_URL") or "https://eggypdf.com/").strip()


@account_recovery_bp.post("/resend-confirmation")
def resend_confirmation():
    data = request.get_json(silent=True) or {}
    email = _email(data)
    if not email or "@" not in email:
        return jsonify({"success": False, "error": "Enter a valid email address."}), 400
    try:
        url, _, _ = _cfg()
        r = requests.post(
            f"{url}/auth/v1/resend",
            headers=_auth_headers(),
            json={
                "type": "signup",
                "email": email,
                "options": {"email_redirect_to": _redirect_url()},
            },
            timeout=20,
        )
        if r.status_code == 429:
            return jsonify({"success": False, "error": "Email limit reached. Please wait before requesting another verification email."}), 429
        if not r.ok:
            try:
                body = r.json()
                msg = body.get("msg") or body.get("message") or body.get("error_description") or body.get("error")
            except Exception:
                msg = None
            return jsonify({"success": False, "error": str(msg or "Could not resend the verification email.")}), 400
        return jsonify({
            "success": True,
            "message": "If this email has a pending EggyPDF signup, Supabase will send a new verification email.",
        })
    except requests.RequestException:
        return jsonify({"success": False, "error": "Account email service is temporarily unavailable."}), 503


@account_recovery_bp.post("/password-reset")
def password_reset():
    data = request.get_json(silent=True) or {}
    email = _email(data)
    if not email or "@" not in email:
        return jsonify({"success": False, "error": "Enter a valid email address."}), 400
    try:
        url, _, _ = _cfg()
        r = requests.post(
            f"{url}/auth/v1/recover",
            headers=_auth_headers(),
            json={"email": email, "redirect_to": _redirect_url()},
            timeout=20,
        )
        if r.status_code == 429:
            return jsonify({"success": False, "error": "Email limit reached. Please wait before requesting another password-reset email."}), 429
        if not r.ok:
            try:
                body = r.json()
                msg = body.get("msg") or body.get("message") or body.get("error_description") or body.get("error")
            except Exception:
                msg = None
            return jsonify({"success": False, "error": str(msg or "Could not send the password-reset email.")}), 400
        return jsonify({
            "success": True,
            "message": "If an EggyPDF account exists for this email, a password-reset email will be sent.",
        })
    except requests.RequestException:
        return jsonify({"success": False, "error": "Account email service is temporarily unavailable."}), 503
