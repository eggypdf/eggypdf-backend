"""Career Pro resume persistence, capped AI writing, and email delivery endpoints."""
from __future__ import annotations

import base64
import json
import os
import re
import uuid
from datetime import datetime, timezone
from hashlib import sha256
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
_MAX_RESUMES = 10
_MAX_PRO_AI_SETS = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _career_user() -> dict[str, Any]:
    user = current_account_user(required=True)
    if not user_has_career_pro(user["id"]):
        raise PermissionError("Career Pro is required for this feature.")
    return user


def _json_size(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _empty_vault() -> dict[str, Any]:
    return {"vault_version": 2, "active_resume_id": None, "resumes": []}


def _normalize_vault(raw: Any, template_id: str = "minimal") -> dict[str, Any]:
    """Read both the new multi-resume vault and the previous single-resume shape."""
    if isinstance(raw, dict) and raw.get("vault_version") == 2 and isinstance(raw.get("resumes"), list):
        raw.setdefault("active_resume_id", None)
        return raw
    if isinstance(raw, dict) and raw:
        rid = str(uuid.uuid4())
        stamp = _now()
        return {
            "vault_version": 2,
            "active_resume_id": rid,
            "resumes": [{
                "id": rid,
                "title": "My Resume",
                "template_id": template_id if template_id in _ALLOWED_TEMPLATES else "minimal",
                "resume_state": raw,
                "ai_cache": {},
                "created_at": stamp,
                "updated_at": stamp,
            }],
        }
    return _empty_vault()


def _load_row(user_id: str) -> dict[str, Any] | None:
    url, _, _ = _cfg()
    r = requests.get(
        f"{url}/rest/v1/career_saved_resumes",
        headers=_service_headers(),
        params={
            "select": "template_id,resume_state,updated_at",
            "user_id": f"eq.{user_id}",
            "limit": "1",
        },
        timeout=15,
    )
    if not r.ok:
        raise _api_error(r, "Could not load your saved resumes.")
    rows = r.json() or []
    return rows[0] if rows else None


def _load_vault(user_id: str) -> dict[str, Any]:
    row = _load_row(user_id)
    if not row:
        return _empty_vault()
    return _normalize_vault(row.get("resume_state"), row.get("template_id") or "minimal")


def _active_template(vault: dict[str, Any]) -> str:
    active = vault.get("active_resume_id")
    for doc in vault.get("resumes") or []:
        if doc.get("id") == active:
            tpl = str(doc.get("template_id") or "minimal")
            return tpl if tpl in _ALLOWED_TEMPLATES else "minimal"
    return "minimal"


def _save_vault(user_id: str, vault: dict[str, Any]) -> dict[str, Any]:
    if _json_size(vault) > _MAX_STATE_BYTES:
        raise ValueError("Your saved resume workspace is too large. Remove a large profile photo or an old resume and try again.")
    url, _, _ = _cfg()
    payload = {
        "user_id": user_id,
        "template_id": _active_template(vault),
        "resume_state": vault,
    }
    r = requests.post(
        f"{url}/rest/v1/career_saved_resumes?on_conflict=user_id",
        headers=_service_headers("resolution=merge-duplicates,return=representation"),
        json=payload,
        timeout=20,
    )
    if not r.ok:
        raise _api_error(r, "Could not save your resume workspace.")
    rows = r.json() or []
    return rows[0] if rows else payload


def _find_doc(vault: dict[str, Any], resume_id: str) -> dict[str, Any] | None:
    return next((d for d in (vault.get("resumes") or []) if d.get("id") == resume_id), None)


def _public_doc(doc: dict[str, Any], include_state: bool = False) -> dict[str, Any]:
    out = {
        "id": doc.get("id"),
        "title": doc.get("title") or "Untitled Resume",
        "template_id": doc.get("template_id") or "minimal",
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }
    if include_state:
        out["resume_state"] = doc.get("resume_state") or {}
    return out


@resume_bp.get("/saved/list")
def list_saved_resumes():
    try:
        user = _career_user()
        vault = _load_vault(user["id"])
        docs = sorted(vault.get("resumes") or [], key=lambda d: d.get("updated_at") or "", reverse=True)
        return jsonify({
            "success": True,
            "active_resume_id": vault.get("active_resume_id"),
            "resumes": [_public_doc(d) for d in docs],
            "limit": _MAX_RESUMES,
        })
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@resume_bp.post("/saved")
def create_saved_resume():
    try:
        user = _career_user()
        body = request.get_json(silent=True) or {}
        vault = _load_vault(user["id"])
        if len(vault.get("resumes") or []) >= _MAX_RESUMES:
            return jsonify({"success": False, "error": f"Career Pro currently supports up to {_MAX_RESUMES} saved resumes."}), 409
        title = str(body.get("title") or "My Resume").strip()[:80] or "My Resume"
        template_id = str(body.get("template_id") or "minimal").strip()
        if template_id not in _ALLOWED_TEMPLATES:
            template_id = "minimal"
        state = body.get("resume_state") if isinstance(body.get("resume_state"), dict) else {}
        stamp = _now()
        doc = {
            "id": str(uuid.uuid4()),
            "title": title,
            "template_id": template_id,
            "resume_state": state,
            "ai_cache": {},
            "created_at": stamp,
            "updated_at": stamp,
        }
        vault.setdefault("resumes", []).append(doc)
        vault["active_resume_id"] = doc["id"]
        _save_vault(user["id"], vault)
        return jsonify({"success": True, "resume": _public_doc(doc, include_state=True)}), 201
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 413
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@resume_bp.get("/saved/<resume_id>")
def get_saved_resume_by_id(resume_id: str):
    try:
        user = _career_user()
        vault = _load_vault(user["id"])
        doc = _find_doc(vault, resume_id)
        if not doc:
            return jsonify({"success": False, "error": "Saved resume not found."}), 404
        vault["active_resume_id"] = resume_id
        _save_vault(user["id"], vault)
        return jsonify({"success": True, "resume": _public_doc(doc, include_state=True)})
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except (RuntimeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@resume_bp.put("/saved/<resume_id>")
def update_saved_resume(resume_id: str):
    try:
        user = _career_user()
        body = request.get_json(silent=True) or {}
        vault = _load_vault(user["id"])
        doc = _find_doc(vault, resume_id)
        if not doc:
            return jsonify({"success": False, "error": "Saved resume not found."}), 404
        if "title" in body:
            doc["title"] = str(body.get("title") or "Untitled Resume").strip()[:80] or "Untitled Resume"
        if "template_id" in body:
            template_id = str(body.get("template_id") or "minimal").strip()
            if template_id not in _ALLOWED_TEMPLATES:
                return jsonify({"success": False, "error": "Unknown resume template."}), 400
            doc["template_id"] = template_id
        if "resume_state" in body:
            state = body.get("resume_state")
            if not isinstance(state, dict):
                return jsonify({"success": False, "error": "Resume state must be an object."}), 400
            doc["resume_state"] = state
        doc["updated_at"] = _now()
        vault["active_resume_id"] = resume_id
        saved = _save_vault(user["id"], vault)
        return jsonify({"success": True, "resume": _public_doc(doc), "updated_at": saved.get("updated_at")})
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 413
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@resume_bp.delete("/saved/<resume_id>")
def delete_saved_resume_by_id(resume_id: str):
    try:
        user = _career_user()
        vault = _load_vault(user["id"])
        before = len(vault.get("resumes") or [])
        vault["resumes"] = [d for d in (vault.get("resumes") or []) if d.get("id") != resume_id]
        if len(vault["resumes"]) == before:
            return jsonify({"success": False, "error": "Saved resume not found."}), 404
        if vault.get("active_resume_id") == resume_id:
            vault["active_resume_id"] = vault["resumes"][0]["id"] if vault["resumes"] else None
        _save_vault(user["id"], vault)
        return jsonify({"success": True})
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except (RuntimeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


# Backward-compatible single-resume endpoints used by earlier Career Pro builds.
@resume_bp.get("/saved")
def get_saved_resume():
    try:
        user = _career_user()
        vault = _load_vault(user["id"])
        rid = vault.get("active_resume_id")
        doc = _find_doc(vault, rid) if rid else None
        if not doc and vault.get("resumes"):
            doc = vault["resumes"][0]
        return jsonify({"success": True, "resume": _public_doc(doc, include_state=True) if doc else None})
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@resume_bp.put("/saved")
def save_resume():
    try:
        user = _career_user()
        body = request.get_json(silent=True) or {}
        state = body.get("resume_state")
        if not isinstance(state, dict):
            return jsonify({"success": False, "error": "Resume state is required."}), 400
        template_id = str(body.get("template_id") or "minimal").strip()
        if template_id not in _ALLOWED_TEMPLATES:
            return jsonify({"success": False, "error": "Unknown resume template."}), 400
        vault = _load_vault(user["id"])
        rid = vault.get("active_resume_id")
        doc = _find_doc(vault, rid) if rid else None
        if not doc:
            stamp = _now()
            doc = {
                "id": str(uuid.uuid4()), "title": "My Resume", "template_id": template_id,
                "resume_state": state, "ai_cache": {}, "created_at": stamp, "updated_at": stamp,
            }
            vault.setdefault("resumes", []).append(doc)
            vault["active_resume_id"] = doc["id"]
        else:
            doc["template_id"] = template_id
            doc["resume_state"] = state
            doc["updated_at"] = _now()
        saved = _save_vault(user["id"], vault)
        return jsonify({"success": True, "resume_id": doc["id"], "updated_at": saved.get("updated_at")})
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 413
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
            raise _api_error(r, "Could not clear your saved resumes.")
        return jsonify({"success": True})
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


def _extract_json_array(text: str) -> list[str]:
    cleaned = text.replace("```json", "").replace("```", "").strip()
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
        if len(value) > 8 and key not in seen:
            seen.add(key)
            out.append(value)
        if len(out) == 4:
            break
    return out


def _generate_ai_set(section: str, job_title: str, source_context: str, previous: list[str]) -> list[str]:
    api_key = (os.getenv("GEMINI_API") or os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("AI service is not configured.")
    avoid = "\n".join(f"- {x}" for x in previous[-12:])
    if section == "summary":
        prompt = f"""Write exactly 4 distinct professional resume summaries for this candidate.
Target role: {job_title}
Candidate context: {source_context[:6000]}
Rules:
- Each option must be 2 concise sentences and under 55 words.
- Keep the writing ATS-friendly and natural.
- Use only information supported by the candidate context; never invent employers, qualifications, metrics, or achievements.
- Make all 4 options meaningfully different in wording and emphasis.
- Do not repeat any previous option listed below.
Previous options to avoid:\n{avoid or '(none)'}
Return ONLY a valid JSON array of exactly 4 strings."""
    else:
        prompt = f"""Write exactly 4 professional resume bullet-point options for this work experience.
Role: {job_title}
Context: {source_context[:6000]}
Rules:
- Each option must start with a strong action verb and be 10-22 words.
- Keep wording ATS-friendly and realistic.
- Do not invent numerical metrics, employers, certifications, tools, or achievements not present in the context.
- Make all 4 options meaningfully different.
- Do not repeat any previous option listed below.
Previous options to avoid:\n{avoid or '(none)'}
Return ONLY a valid JSON array of exactly 4 strings."""
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.8, "maxOutputTokens": 1800},
    }
    errors: list[str] = []
    for model in ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"):
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                params={"key": api_key}, json=payload, timeout=25,
            )
            if r.status_code == 429:
                raise RuntimeError("AI usage is temporarily busy. Please try again shortly.")
            if not r.ok:
                errors.append(f"{model}:{r.status_code}")
                continue
            data = r.json()
            parts = (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
            text = str((parts[0] if parts else {}).get("text") or "")
            options = _extract_json_array(text)
            if len(options) == 4:
                return options
            errors.append(f"{model}:invalid-output")
        except RuntimeError:
            raise
        except Exception as exc:
            errors.append(f"{model}:{type(exc).__name__}")
    raise RuntimeError("AI could not generate four resume options right now.")


@resume_bp.post("/ai-suggestions")
def pro_ai_suggestions():
    """Career Pro: 3 generated sets x 4 options, then loop cached sets forever."""
    try:
        user = _career_user()
        body = request.get_json(silent=True) or {}
        resume_id = str(body.get("resume_id") or "").strip()
        section = str(body.get("section") or "").strip().lower()
        section_key = str(body.get("section_key") or section).strip()[:160]
        job_title = str(body.get("job_title") or "").strip()[:180]
        source_context = str(body.get("source_context") or "").strip()
        if section not in {"summary", "bullets"}:
            return jsonify({"success": False, "error": "Section must be summary or bullets."}), 400
        if not resume_id or not job_title:
            return jsonify({"success": False, "error": "Resume and job title are required."}), 400

        vault = _load_vault(user["id"])
        doc = _find_doc(vault, resume_id)
        if not doc:
            return jsonify({"success": False, "error": "Saved resume not found."}), 404

        cache_key = f"{section}:{section_key}"
        source_hash = sha256(f"{job_title}\n{source_context}".encode("utf-8")).hexdigest()
        ai_cache = doc.setdefault("ai_cache", {})
        entry = ai_cache.get(cache_key)
        if not isinstance(entry, dict) or entry.get("source_hash") != source_hash:
            entry = {"source_hash": source_hash, "sets": [], "display_index": -1}
            ai_cache[cache_key] = entry

        sets = entry.setdefault("sets", [])
        generated = False
        if len(sets) < _MAX_PRO_AI_SETS:
            previous = [item for group in sets for item in (group if isinstance(group, list) else [])]
            options = _generate_ai_set(section, job_title, source_context, previous)
            sets.append(options)
            entry["display_index"] = len(sets) - 1
            generated = True
        else:
            entry["display_index"] = (int(entry.get("display_index", -1)) + 1) % _MAX_PRO_AI_SETS
            options = sets[entry["display_index"]]

        doc["updated_at"] = _now()
        vault["active_resume_id"] = resume_id
        _save_vault(user["id"], vault)
        return jsonify({
            "success": True,
            "suggestions": options,
            "set_number": int(entry["display_index"]) + 1,
            "generated_sets": len(sets),
            "max_sets": _MAX_PRO_AI_SETS,
            "generated_now": generated,
            "looping": len(sets) >= _MAX_PRO_AI_SETS and not generated,
        })
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 413
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@resume_bp.post("/email")
def email_resume():
    try:
        user = _career_user()
        body = request.get_json(silent=True) or {}
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
            "htmlContent": "<html><body style='font-family:Arial,sans-serif;color:#1a1a2e'><h2>Your resume is attached.</h2><p>You can return to Career Pro anytime to continue editing your saved resume.</p><p>— EggyPDF</p></body></html>",
            "attachment": [{"content": pdf_base64, "name": filename}],
        }
        r = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"accept": "application/json", "api-key": api_key, "content-type": "application/json"},
            json=payload, timeout=30,
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
