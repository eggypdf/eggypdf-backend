"""Launch hardening for EggyPDF.

This module keeps legacy routes backward-compatible while tightening the
pre-marketing production behavior without rewriting the large app.py file.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any

import requests
from flask import jsonify, request

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_EMAIL_LIMIT_PER_HOUR = 10
_EMAIL_WINDOW_SECONDS = 3600
_email_sends: dict[str, list[float]] = {}
_email_lock = threading.Lock()


def _clean_json_array(text: str, count: int) -> list[str]:
    cleaned = (text or "").replace("```json", "").replace("```", "").strip()
    parsed: Any = None
    try:
        parsed = json.loads(cleaned)
    except Exception:
        match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except Exception:
                parsed = None
    if not isinstance(parsed, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in parsed:
        value = str(item or "").strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            out.append(value)
        if len(out) == count:
            break
    return out


def _gemini_list(api_key: str, prompt: str, count: int) -> list[str]:
    """Use current production Flash models with a legacy 2.5 fallback."""
    models = ("gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-2.5-flash")
    transient = False
    rate_limited = False
    for model in models:
        try:
            response = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                params={"key": api_key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "maxOutputTokens": 2200,
                    },
                },
                timeout=30,
            )
        except requests.RequestException:
            transient = True
            continue

        if response.status_code in (401, 403):
            raise RuntimeError("AI service authentication failed.")
        if response.status_code == 429:
            rate_limited = True
            continue
        if response.status_code in (500, 502, 503, 504):
            transient = True
            continue
        if response.status_code in (400, 404):
            continue
        if not response.ok:
            continue

        try:
            data = response.json()
            parts = (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
            text = str((parts[0] if parts else {}).get("text") or "")
            values = _clean_json_array(text, count)
            if len(values) == count:
                return values
        except Exception:
            continue

    if rate_limited:
        raise RuntimeError("AI is busy right now. Please try again in a minute.")
    if transient:
        raise RuntimeError("AI is temporarily unavailable. Please try again shortly.")
    raise RuntimeError("AI could not generate suggestions right now.")


def _free_ai_suggestions():
    """Safer replacement for the legacy free Resume Builder AI endpoint."""
    api_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_API") or "").strip()
    if not api_key:
        return jsonify({"error": "AI service is not configured."}), 503

    body = request.get_json(silent=True) or {}
    job_title = str(body.get("job_title") or "").strip()[:180]
    suggest_type = str(body.get("type") or "bullets").strip().lower()
    if not job_title:
        return jsonify({"error": "Please provide a job title."}), 400

    if suggest_type == "bullets":
        count = 4
        prompt = f"""Write exactly 4 general resume bullet-point suggestions for a {job_title}.
Rules:
- Start each option with a strong action verb.
- Keep each option 10-22 words.
- Write responsibility-focused examples that a user can edit to match their real experience.
- Do NOT invent numerical metrics, revenue, percentages, team sizes, employers, certifications, years, awards, or achievements.
- Do NOT claim results or facts that were not provided by the user.
- Keep the wording ATS-friendly and natural.
Return ONLY a valid JSON array of exactly 4 strings."""
    elif suggest_type == "summary":
        count = 4
        prompt = f"""Write exactly 4 concise professional resume-summary options for a {job_title}.
Rules:
- Each option must be 2 sentences and under 55 words.
- Keep the wording professional, ATS-friendly, and adaptable.
- Do NOT invent years of experience, certifications, employers, metrics, awards, or specific achievements.
- Avoid unsupported claims such as being top-ranked or exceeding targets.
Return ONLY a valid JSON array of exactly 4 strings."""
    elif suggest_type == "skills":
        count = 8
        prompt = f"""List exactly 8 commonly requested professional skills for a {job_title}.
Return only skill names. Do not invent certifications or claim that the user has these skills.
Return ONLY a valid JSON array of exactly 8 short strings."""
    else:
        return jsonify({"error": "Invalid type. Use bullets, summary, or skills."}), 400

    try:
        return jsonify({"suggestions": _gemini_list(api_key, prompt, count)})
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 503


def _pro_generate_ai_set(section: str, job_title: str, source_context: str, previous: list[str]) -> list[str]:
    """Career Pro 4-option generator using current model fallbacks and factual prompts."""
    api_key = (os.getenv("GEMINI_API") or os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("AI service is not configured.")
    avoid = "\n".join(f"- {x}" for x in previous[-12:]) or "(none)"
    if section == "summary":
        prompt = f"""Write exactly 4 distinct professional resume summaries for this candidate.
Target role: {job_title}
Candidate context: {source_context[:6000]}
Rules:
- Each option must be 2 concise sentences and under 55 words.
- Keep the writing ATS-friendly and natural.
- Use only information supported by the candidate context.
- Never invent employers, qualifications, metrics, years, team sizes, certifications, awards, or achievements.
- Make all 4 options meaningfully different in wording and emphasis.
- Do not repeat any previous option listed below.
Previous options to avoid:\n{avoid}
Return ONLY a valid JSON array of exactly 4 strings."""
    else:
        prompt = f"""Write exactly 4 professional resume bullet-point options for this work experience.
Role: {job_title}
Context: {source_context[:6000]}
Rules:
- Each option must start with a strong action verb and be 10-22 words.
- Keep wording ATS-friendly and realistic.
- Use only facts supported by the supplied context.
- Never invent numerical metrics, revenue, employers, certifications, tools, years, team sizes, awards, or achievements.
- Make all 4 options meaningfully different.
- Do not repeat any previous option listed below.
Previous options to avoid:\n{avoid}
Return ONLY a valid JSON array of exactly 4 strings."""
    return _gemini_list(api_key, prompt, 4)


def _can_send_email(user_id: str) -> bool:
    now = time.monotonic()
    with _email_lock:
        recent = [t for t in _email_sends.get(user_id, []) if now - t < _EMAIL_WINDOW_SECONDS]
        if len(recent) >= _EMAIL_LIMIT_PER_HOUR:
            _email_sends[user_id] = recent
            return False
        recent.append(now)
        _email_sends[user_id] = recent
        return True


def _career_email_resume():
    """Career Pro email delivery to any valid recipient chosen by the user."""
    import resume_routes

    try:
        user = resume_routes._career_user()
        body = request.get_json(silent=True) or {}
        account_email = str(user.get("email") or "").strip().lower()
        recipient = str(body.get("recipient_email") or body.get("email") or account_email).strip().lower()
        pdf_base64 = str(body.get("pdf_base64") or "").strip()
        filename = str(body.get("filename") or "EggyPDF_Resume.pdf").strip()

        if len(recipient) > 254 or not _EMAIL_RE.match(recipient):
            return jsonify({"success": False, "error": "Enter a valid recipient email address."}), 400
        if not pdf_base64:
            return jsonify({"success": False, "error": "Resume PDF is required."}), 400
        if pdf_base64.startswith("data:"):
            pdf_base64 = pdf_base64.split(",", 1)[-1]
        try:
            decoded = base64.b64decode(pdf_base64, validate=True)
        except Exception:
            return jsonify({"success": False, "error": "The generated PDF could not be read."}), 400
        if len(decoded) > resume_routes._MAX_PDF_BYTES:
            return jsonify({"success": False, "error": "The generated resume is too large to email."}), 413
        if not _can_send_email(str(user.get("id") or account_email)):
            return jsonify({"success": False, "error": "Email limit reached. Please try again later."}), 429

        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        filename = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename)[:120]

        api_key = os.getenv("BREVO_API_KEY", "").strip()
        sender_email = os.getenv("BREVO_SENDER_EMAIL", "").strip()
        sender_name = os.getenv("BREVO_SENDER_NAME", "EggyPDF").strip() or "EggyPDF"
        if not api_key or not sender_email:
            raise RuntimeError("Resume email delivery is not configured yet.")

        payload: dict[str, Any] = {
            "sender": {"name": sender_name, "email": sender_email},
            "to": [{"email": recipient}],
            "subject": "Resume sent via EggyPDF Career Pro",
            "htmlContent": (
                "<html><body style='font-family:Arial,sans-serif;color:#1a1a2e'>"
                "<h2>Resume attached</h2>"
                "<p>This resume was sent using EggyPDF Career Pro.</p>"
                "<p>— EggyPDF</p></body></html>"
            ),
            "attachment": [{"content": pdf_base64, "name": filename}],
        }
        if _EMAIL_RE.match(account_email):
            payload["replyTo"] = {"email": account_email, "name": "EggyPDF Career Pro user"}

        response = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"accept": "application/json", "api-key": api_key, "content-type": "application/json"},
            json=payload,
            timeout=30,
        )
        if not response.ok:
            try:
                message = (response.json() or {}).get("message")
            except Exception:
                message = None
            raise RuntimeError(message or "Could not email your resume right now.")
        return jsonify({"success": True, "email": recipient})
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


def _legacy_email_disabled():
    return jsonify({
        "error": "This legacy resume-email endpoint is disabled. Use Career Pro resume email delivery instead."
    }), 410


def _patch_temp_file_delivery() -> None:
    """Delete temporary file outputs when Flask closes the download response."""
    import app as app_module

    if getattr(app_module, "_eggy_temp_delivery_patched", False):
        return
    real_send_file = app_module.send_file
    roots = [Path(app_module.UPLOAD_FOLDER).resolve(), Path(app_module.OUTPUT_FOLDER).resolve()]

    def patched_send_file(path_or_file, *args, **kwargs):
        response = real_send_file(path_or_file, *args, **kwargs)
        if isinstance(path_or_file, (str, os.PathLike)):
            path = Path(path_or_file).resolve()
            matched_root = None
            for root in roots:
                try:
                    path.relative_to(root)
                    matched_root = root
                    break
                except ValueError:
                    continue
            if matched_root is not None:
                parent = path.parent

                def remove_after_delivery():
                    try:
                        path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    if parent != matched_root:
                        try:
                            shutil.rmtree(parent, ignore_errors=True)
                        except Exception:
                            pass

                response.call_on_close(remove_after_delivery)
        return response

    app_module.send_file = patched_send_file
    app_module._eggy_temp_delivery_patched = True


def install(app) -> None:
    """Install production hardening after all blueprints are registered."""
    if getattr(app, "_eggy_launch_hardening_installed", False):
        return

    import resume_routes

    # Use current model fallbacks for Career Pro resume suggestions.
    resume_routes._generate_ai_set = _pro_generate_ai_set

    # Keep the public Free Resume Builder endpoint but make its prompts factual
    # and move it off retired model fallbacks.
    if "ai_suggestions" in app.view_functions:
        app.view_functions["ai_suggestions"] = _free_ai_suggestions

    # The old unauthenticated CV-mail route is no longer used by the frontend.
    # Keep the URL for compatibility, but do not leave an open mail relay.
    if "send_cv_email" in app.view_functions:
        app.view_functions["send_cv_email"] = _legacy_email_disabled

    # Career Pro users may send their finished resume to any valid recipient.
    if "resume.email_resume" in app.view_functions:
        app.view_functions["resume.email_resume"] = _career_email_resume

    _patch_temp_file_delivery()
    app._eggy_launch_hardening_installed = True
