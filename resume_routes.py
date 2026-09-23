"""Career Pro resume persistence and email delivery endpoints."""
from __future__ import annotations

import base64
import os
import re
from typing import Any

import requests
from flask import Blueprint, jsonify, request

from account_routes import (
    _api_error,
    _cfg,
    _service_headers,
    current_account_user,
    user_has_career_pro,
)

resume_bp = Blueprint("resume", __name__, url_prefix="/api/resume")

_ALLOWED_TEMPLATES = {
    "minimal", "classic", "modern",
    "ats-standard", "ats-professional", "ats-executive", "ats-tech",
}
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_MAX_STATE_BYTES = 3_500_000
_MAX_PDF_BYTES = 8_000_000


def _career_user() -> dict[str, Any]:
    user = current_account_user(required=True)
    if not user_has_career_pro(user["id"]):
        raise PermissionError("Career Pro is required for this feature.")
    return user


def _json_size(value: Any) -> int:
    import json
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


@resume_bp.get("/saved")
def get_saved_resume():
    try:
        user = _career_user()
        url, _, _ = _cfg()
        r = requests.get(
            f"{url}/rest/v1/career_saved_resumes",
            headers=_service_headers(),
            params={"select": "template_id,resume_state,updated_at", "user_id": f"eq.{user['id']}", "limit": "1"},
            timeout=15,
        )
        if not r.ok:
            raise _api_error(r, "Could not load your saved resume.")
        rows = r.json() or []
        return jsonify({"success": True, "resume": rows[0] if rows else None})
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@resume_bp.put("/saved")
def save_resume():
    try:
        user = _career_user()
        body = request.get_json(silent=True) or {}
        template_id = str(body.get("template_id") or "minimal").strip()
        state = body.get("resume_state")
        if template_id not in _ALLOWED_TEMPLATES:
            return jsonify({"success": False, "error": "Unknown resume template."}), 400
        if not isinstance(state, dict):
            return jsonify({"success": False, "error": "Resume state is required."}), 400
        if _json_size(state) > _MAX_STATE_BYTES:
            return jsonify({"success": False, "error": "This resume is too large to save. Try using a smaller profile photo."}), 413

        url, _, _ = _cfg()
        payload = {"user_id": user["id"], "template_id": template_id, "resume_state": state}
        r = requests.post(
            f"{url}/rest/v1/career_saved_resumes?on_conflict=user_id",
            headers=_service_headers("resolution=merge-duplicates,return=representation"),
            json=payload,
            timeout=20,
        )
        if not r.ok:
            raise _api_error(r, "Could not save your resume.")
        rows = r.json() or []
        saved = rows[0] if rows else payload
        return jsonify({"success": True, "updated_at": saved.get("updated_at")})
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@resume_bp.delete("/saved")
def delete_saved_resume():
    try:
        user = _career_user()
        url, _, _ = _cfg()
        r = requests.delete(
            f"{url}/rest/v1/career_saved_resumes",
            headers=_service_headers("return=minimal"),
            params={"user_id": f"eq.{user['id']}"},
            timeout=15,
        )
        if not r.ok:
            raise _api_error(r, "Could not clear your saved resume.")
        return jsonify({"success": True})
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@resume_bp.post("/email")
def email_resume():
    try:
        user = _career_user()
        body = request.get_json(silent=True) or {}
        # Email delivery is intentionally limited to the signed-in account email.
        # This keeps the feature personal and prevents the endpoint becoming a mail relay.
        recipient = str(user.get("email") or "").strip().lower()
        pdf_base64 = str(body.get("pdf_base64") or "").strip()
        filename = str(body.get("filename") or "EggyPDF_Resume.pdf").strip()

        if not _EMAIL_RE.match(recipient):
            return jsonify({"success": False, "error": "Your account needs a valid email address."}), 400
        if not pdf_base64:
            return jsonify({"success": False, "error": "Resume PDF is required."}), 400
        if pdf_base64.startswith("data:"):
            pdf_base64 = pdf_base64.split(",", 1)[-1]
        try:
            decoded = base64.b64decode(pdf_base64, validate=True)
        except Exception:
            return jsonify({"success": False, "error": "The generated PDF could not be read."}), 400
        if len(decoded) > _MAX_PDF_BYTES:
            return jsonify({"success": False, "error": "The generated resume is too large to email."}), 413
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        filename = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename)[:120]

        api_key = os.getenv("BREVO_API_KEY", "").strip()
        sender_email = os.getenv("BREVO_SENDER_EMAIL", "").strip()
        sender_name = os.getenv("BREVO_SENDER_NAME", "EggyPDF").strip() or "EggyPDF"
        if not api_key or not sender_email:
            raise RuntimeError("Resume email delivery is not configured yet.")

        payload = {
            "sender": {"name": sender_name, "email": sender_email},
            "to": [{"email": recipient}],
            "subject": "Your EggyPDF resume is ready",
            "htmlContent": "<html><body style='font-family:Arial,sans-serif;color:#1a1a2e'><h2>Your resume is attached.</h2><p>You can return to EggyPDF anytime while your Career Pro access is active to edit any section, switch templates, and create an updated version.</p><p>— EggyPDF</p></body></html>",
            "attachment": [{"content": pdf_base64, "name": filename}],
        }
        r = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"accept": "application/json", "api-key": api_key, "content-type": "application/json"},
            json=payload,
            timeout=30,
        )
        if not r.ok:
            try:
                message = (r.json() or {}).get("message")
            except Exception:
                message = None
            raise RuntimeError(message or "Could not email your resume right now.")
        return jsonify({"success": True, "email": recipient})
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503
