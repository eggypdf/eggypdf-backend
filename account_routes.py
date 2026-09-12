"""EggyPDF account + Career Pro entitlement API backed by Supabase.

All Supabase credentials stay server-side on Render. The browser only talks to
EggyPDF's backend and stores the returned user session locally.
"""
from __future__ import annotations

import os
from typing import Any

import requests
from flask import Blueprint, jsonify, request

account_bp = Blueprint("account", __name__, url_prefix="/api/account")


def _cfg() -> tuple[str, str, str]:
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    anon = os.getenv("SUPABASE_ANON_KEY", "").strip()
    service = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not anon:
        raise RuntimeError("Account service is not configured yet.")
    return url, anon, service


def _auth_headers(token: str | None = None) -> dict[str, str]:
    _, anon, _ = _cfg()
    h = {"apikey": anon, "Content-Type": "application/json", "Accept": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _service_headers(prefer: str | None = None) -> dict[str, str]:
    _, _, service = _cfg()
    if not service:
        raise RuntimeError("Account database service key is not configured yet.")
    h = {
        "apikey": service,
        "Authorization": f"Bearer {service}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h


def _api_error(resp: requests.Response, fallback: str) -> RuntimeError:
    try:
        body = resp.json()
        msg = body.get("msg") or body.get("message") or body.get("error_description") or body.get("error")
    except Exception:
        msg = None
    return RuntimeError(str(msg or fallback))


def _bearer_token() -> str:
    raw = (request.headers.get("Authorization") or "").strip()
    if raw.lower().startswith("bearer "):
        return raw[7:].strip()
    return ""


def current_account_user(required: bool = False) -> dict[str, Any] | None:
    """Return the authenticated Supabase user for the current Flask request."""
    token = _bearer_token()
    if not token:
        if required:
            raise PermissionError("Sign in to continue.")
        return None
    url, _, _ = _cfg()
    try:
        r = requests.get(f"{url}/auth/v1/user", headers=_auth_headers(token), timeout=15)
    except requests.RequestException as exc:
        raise RuntimeError("Account service is temporarily unavailable.") from exc
    if r.status_code in (401, 403):
        if required:
            raise PermissionError("Your sign-in session has expired. Please sign in again.")
        return None
    if not r.ok:
        raise _api_error(r, "Could not verify your account.")
    return r.json()


def get_career_entitlement(user_id: str) -> dict[str, Any] | None:
    url, _, _ = _cfg()
    params = {
        "select": "user_id,status,product_id,dodo_checkout_id,dodo_payment_id,purchased_at,updated_at",
        "user_id": f"eq.{user_id}",
        "limit": "1",
    }
    try:
        r = requests.get(
            f"{url}/rest/v1/career_entitlements",
            headers=_service_headers(),
            params=params,
            timeout=15,
        )
    except requests.RequestException as exc:
        raise RuntimeError("Account database is temporarily unavailable.") from exc
    if not r.ok:
        raise _api_error(r, "Could not read Career Pro access.")
    rows = r.json() or []
    return rows[0] if rows else None


def user_has_career_pro(user_id: str) -> bool:
    row = get_career_entitlement(user_id)
    return bool(row and row.get("status") == "active")


def grant_career_pro(
    user_id: str,
    *,
    product_id: str,
    checkout_id: str | None = None,
    payment_id: str | None = None,
) -> dict[str, Any]:
    """Server-only entitlement upsert. Never call this directly from the browser."""
    url, _, _ = _cfg()
    payload = {
        "user_id": user_id,
        "status": "active",
        "product_id": product_id,
        "dodo_checkout_id": checkout_id or None,
        "dodo_payment_id": payment_id or None,
    }
    try:
        r = requests.post(
            f"{url}/rest/v1/career_entitlements?on_conflict=user_id",
            headers=_service_headers("resolution=merge-duplicates,return=representation"),
            json=payload,
            timeout=15,
        )
    except requests.RequestException as exc:
        raise RuntimeError("Account database is temporarily unavailable.") from exc
    if not r.ok:
        raise _api_error(r, "Could not save Career Pro access.")
    rows = r.json() or []
    return rows[0] if rows else payload


def _safe_session(payload: dict[str, Any]) -> dict[str, Any]:
    """Return only fields needed by the frontend."""
    user = payload.get("user") or {}
    return {
        "access_token": payload.get("access_token"),
        "refresh_token": payload.get("refresh_token"),
        "expires_in": payload.get("expires_in"),
        "expires_at": payload.get("expires_at"),
        "token_type": payload.get("token_type"),
        "user": {
            "id": user.get("id"),
            "email": user.get("email"),
            "email_confirmed_at": user.get("email_confirmed_at"),
        },
    }


@account_bp.get("/health")
def health():
    try:
        _, _, service = _cfg()
        return jsonify({
            "status": "ok",
            "auth_configured": True,
            "database_configured": bool(service),
        })
    except RuntimeError:
        return jsonify({"status": "setup_required", "auth_configured": False, "database_configured": False})


@account_bp.post("/signup")
def signup():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not email or "@" not in email:
        return jsonify({"success": False, "error": "Enter a valid email address."}), 400
    if len(password) < 8:
        return jsonify({"success": False, "error": "Password must be at least 8 characters."}), 400
    try:
        url, _, _ = _cfg()
        r = requests.post(
            f"{url}/auth/v1/signup",
            headers=_auth_headers(),
            json={"email": email, "password": password},
            timeout=20,
        )
        if not r.ok:
            raise _api_error(r, "Could not create your account.")
        payload = r.json()
        session = _safe_session(payload)
        needs_confirmation = not bool(session.get("access_token"))
        return jsonify({"success": True, "session": session, "needs_email_confirmation": needs_confirmation})
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@account_bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not email or not password:
        return jsonify({"success": False, "error": "Email and password are required."}), 400
    try:
        url, _, _ = _cfg()
        r = requests.post(
            f"{url}/auth/v1/token?grant_type=password",
            headers=_auth_headers(),
            json={"email": email, "password": password},
            timeout=20,
        )
        if r.status_code in (400, 401):
            return jsonify({"success": False, "error": "Incorrect email or password, or email confirmation is still required."}), 401
        if not r.ok:
            raise _api_error(r, "Could not sign in.")
        return jsonify({"success": True, "session": _safe_session(r.json())})
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@account_bp.post("/refresh")
def refresh():
    data = request.get_json(silent=True) or {}
    refresh_token = (data.get("refresh_token") or "").strip()
    if not refresh_token:
        return jsonify({"success": False, "error": "Refresh token is required."}), 400
    try:
        url, _, _ = _cfg()
        r = requests.post(
            f"{url}/auth/v1/token?grant_type=refresh_token",
            headers=_auth_headers(),
            json={"refresh_token": refresh_token},
            timeout=20,
        )
        if not r.ok:
            return jsonify({"success": False, "error": "Your session has expired. Please sign in again."}), 401
        return jsonify({"success": True, "session": _safe_session(r.json())})
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@account_bp.get("/me")
def me():
    try:
        user = current_account_user(required=True)
        entitlement = get_career_entitlement(user["id"])
        return jsonify({
            "success": True,
            "user": {"id": user.get("id"), "email": user.get("email")},
            "career_pro": {
                "active": bool(entitlement and entitlement.get("status") == "active"),
                "entitlement": entitlement,
            },
        })
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 401
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@account_bp.post("/logout")
def logout():
    token = _bearer_token()
    if not token:
        return jsonify({"success": True})
    try:
        url, _, _ = _cfg()
        requests.post(f"{url}/auth/v1/logout", headers=_auth_headers(token), timeout=15)
    except Exception:
        pass
    return jsonify({"success": True})
