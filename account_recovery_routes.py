"""EggyPDF account recovery helpers backed by Supabase Auth."""
from __future__ import annotations

import os
import requests
from flask import Blueprint, jsonify, request

from account_routes import _cfg, _auth_headers

account_recovery_bp = Blueprint("account_recovery", __name__, url_prefix="/api/account")


def _email(data) -> str:
    return str((data or {}).get("email") or "").strip().lower()


def _confirmation_redirect_url() -> str:
    return (
        os.getenv("ACCOUNT_EMAIL_CONFIRM_REDIRECT_URL")
        or os.getenv("ACCOUNT_AUTH_REDIRECT_URL")
        or "https://eggypdf.com/"
    ).strip()


def _password_redirect_url() -> str:
    return (
        os.getenv("ACCOUNT_PASSWORD_RESET_REDIRECT_URL")
        or "https://eggypdf.com/reset-password.html"
    ).strip()


def _error_message(resp: requests.Response, fallback: str) -> str:
    try:
        body = resp.json()
        return str(
            body.get("msg")
            or body.get("message")
            or body.get("error_description")
            or body.get("error")
            or fallback
        )
    except Exception:
        return fallback


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
                "options": {"email_redirect_to": _confirmation_redirect_url()},
            },
            timeout=20,
        )
        if r.status_code == 429:
            return jsonify({"success": False, "error": "Email limit reached. Please wait before requesting another verification email."}), 429
        if not r.ok:
            return jsonify({"success": False, "error": _error_message(r, "Could not resend the verification email.")}), 400
        return jsonify({
            "success": True,
            "message": "If this email has a pending EggyPDF signup, a new verification email will be sent.",
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
            params={"redirect_to": _password_redirect_url()},
            headers=_auth_headers(),
            json={"email": email},
            timeout=20,
        )
        if r.status_code == 429:
            return jsonify({"success": False, "error": "Email limit reached. Please wait before requesting another password-reset email."}), 429
        if not r.ok:
            return jsonify({"success": False, "error": _error_message(r, "Could not send the password-reset email.")}), 400
        return jsonify({
            "success": True,
            "message": "If an EggyPDF account exists for this email, a password-reset email will be sent.",
        })
    except requests.RequestException:
        return jsonify({"success": False, "error": "Account email service is temporarily unavailable."}), 503


@account_recovery_bp.post("/password-reset/exchange")
def password_reset_exchange():
    """Exchange an EggyPDF-branded recovery TokenHash for a recovery session."""
    data = request.get_json(silent=True) or {}
    token_hash = str(data.get("token_hash") or "").strip()
    token_type = str(data.get("type") or "recovery").strip().lower()

    if not token_hash:
        return jsonify({"success": False, "error": "This password-reset link is invalid or has expired. Request a new reset email."}), 400
    if token_type != "recovery":
        return jsonify({"success": False, "error": "Invalid password-reset link type."}), 400

    try:
        url, _, _ = _cfg()
        r = requests.post(
            f"{url}/auth/v1/verify",
            headers=_auth_headers(),
            json={"token_hash": token_hash, "type": "recovery"},
            timeout=20,
        )
        if r.status_code in (400, 401, 403, 422):
            return jsonify({"success": False, "error": "This password-reset link is invalid or has expired. Request a new reset email."}), 401
        if not r.ok:
            return jsonify({"success": False, "error": _error_message(r, "Could not verify the password-reset link.")}), 400

        payload = r.json() or {}
        access_token = str(payload.get("access_token") or "").strip()
        if not access_token:
            return jsonify({"success": False, "error": "The password-reset link could not be verified. Request a new reset email."}), 401

        return jsonify({
            "success": True,
            "access_token": access_token,
            "expires_in": payload.get("expires_in"),
        })
    except requests.RequestException:
        return jsonify({"success": False, "error": "Account service is temporarily unavailable."}), 503


@account_recovery_bp.post("/password-update")
def password_update():
    data = request.get_json(silent=True) or {}
    recovery_token = str(data.get("access_token") or "").strip()
    password = str(data.get("password") or "")
    if not recovery_token:
        return jsonify({"success": False, "error": "This password-reset link is invalid or has expired. Request a new reset email."}), 401
    if len(password) < 8:
        return jsonify({"success": False, "error": "Password must be at least 8 characters."}), 400
    try:
        url, _, _ = _cfg()
        r = requests.put(
            f"{url}/auth/v1/user",
            headers=_auth_headers(recovery_token),
            json={"password": password},
            timeout=20,
        )
        if r.status_code in (401, 403):
            return jsonify({"success": False, "error": "This password-reset link is invalid or has expired. Request a new reset email."}), 401
        if not r.ok:
            return jsonify({"success": False, "error": _error_message(r, "Could not update your password.")}), 400
        return jsonify({
            "success": True,
            "message": "Your EggyPDF password has been updated. You can now sign in with the new password.",
        })
    except requests.RequestException:
        return jsonify({"success": False, "error": "Account service is temporarily unavailable."}), 503
