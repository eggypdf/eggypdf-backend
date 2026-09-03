"""EggyPDF Career Pro API routes.

Career features live in a Blueprint so the existing PDF API remains stable.
Payment checkout is created and verified server-side; Dodo API credentials are
never exposed to the browser.
"""
from __future__ import annotations

import io
import os
import re

import requests
from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename

from career_engine import analyze_resume, extract_keywords, extract_skills

career_bp = Blueprint("career", __name__, url_prefix="/api/career")

MAX_TEXT_LENGTH = 100_000
ALLOWED_RESUME_EXTENSIONS = {"pdf", "txt"}
DODO_PRODUCT_ID = "pdt_0Nmk7wwSsTDKzOvbI7z9n"
DODO_API_BASE = os.getenv("DODO_API_BASE", "https://live.dodopayments.com").rstrip("/")
CAREER_PRO_RETURN_URL = os.getenv(
    "CAREER_PRO_RETURN_URL", "https://eggypdf.com/ats-checker.html?career_pro=return"
)


def _extract_pdf_text(file_storage):
    from pypdf import PdfReader
    raw = file_storage.read()
    if not raw:
        raise ValueError("The uploaded resume is empty.")
    reader = PdfReader(io.BytesIO(raw))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages).strip()


def _get_resume_text():
    if request.is_json:
        return ((request.get_json(silent=True) or {}).get("resume_text") or "").strip()
    uploaded = request.files.get("resume") or request.files.get("file")
    if not uploaded or not uploaded.filename:
        return ""
    filename = secure_filename(uploaded.filename)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_RESUME_EXTENSIONS:
        raise ValueError("Please upload a PDF or TXT resume.")
    return _extract_pdf_text(uploaded) if ext == "pdf" else uploaded.read().decode("utf-8", errors="replace").strip()


def _job_text():
    if request.is_json:
        data = request.get_json(silent=True) or {}
        return (data.get("job_description") or data.get("job_text") or "").strip()
    return (request.form.get("job_description") or request.form.get("job_text") or "").strip()


def _validate_text(text, label):
    if not text:
        raise ValueError(f"{label} is required.")
    if len(text) > MAX_TEXT_LENGTH:
        raise ValueError(f"{label} is too long. Please keep it under {MAX_TEXT_LENGTH:,} characters.")


def _dodo_headers():
    api_key = os.getenv("DODO_PAYMENTS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Dodo Payments is not configured.")
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "application/json"}


def _dodo_request(method, path, **kwargs):
    try:
        response = requests.request(method, f"{DODO_API_BASE}{path}", headers=_dodo_headers(), timeout=20, **kwargs)
    except requests.RequestException as exc:
        raise RuntimeError("Payment service is temporarily unavailable.") from exc
    if not response.ok:
        raise RuntimeError("Payment service rejected the request.")
    return response.json()


def _verify_paid_session(session_id):
    if not session_id or len(session_id) > 200 or not all(c.isalnum() or c in "_-" for c in session_id):
        raise ValueError("Invalid checkout session.")
    checkout = _dodo_request("GET", f"/checkouts/{session_id}")
    status = checkout.get("payment_status") or checkout.get("status")
    metadata = checkout.get("metadata") or {}
    return status == "succeeded" and metadata.get("product") == "career_pro", status


def _require_pro(data):
    session_id = (data.get("session_id") or "").strip()
    paid, _ = _verify_paid_session(session_id)
    if not paid:
        raise PermissionError("Career Pro purchase could not be verified.")


def _clean_lines(text):
    return [re.sub(r"^[\s•*\-]+", "", x).strip() for x in text.splitlines() if x.strip()]


def _tailoring_plan(resume_text, job_text):
    analysis = analyze_resume(resume_text, job_text)
    missing = analysis["keyword_analysis"]["missing"][:12]
    matched = analysis["keyword_analysis"]["matched"][:12]
    skills = analysis.get("skills_detected", [])[:12]
    return {
        "match_score": analysis["keyword_analysis"]["match_percentage"],
        "priority_keywords": missing,
        "matched_keywords": matched,
        "skills_detected": skills,
        "actions": [
            f"Use '{kw}' naturally where it truthfully matches your experience." for kw in missing[:6]
        ] or ["Your keyword alignment is already strong. Focus on evidence, clarity, and measurable outcomes."],
        "summary_guidance": "Lead with the target role, strongest relevant skills, and 1–2 outcomes you can defend in an interview.",
        "bullet_guidance": "Start experience bullets with strong action verbs, keep only relevant responsibilities, and quantify outcomes when you have real numbers.",
        "integrity_note": "Only add keywords, skills, metrics, and claims that are true. EggyPDF will not invent experience for you.",
    }


def _cover_letter_draft(resume_text, job_text, applicant_name="", company="", role=""):
    analysis = analyze_resume(resume_text, job_text)
    matched = analysis["keyword_analysis"]["matched"][:5]
    skills = analysis.get("skills_detected", [])[:5]
    evidence = matched or skills
    name = applicant_name or "Your Name"
    company_name = company or "the hiring team"
    role_name = role or "this role"
    evidence_text = ", ".join(evidence) if evidence else "relevant experience and transferable skills"
    return (
        f"Dear {company_name},\n\n"
        f"I am applying for {role_name}. My background includes {evidence_text}, which aligns with several of the priorities in your job description. "
        "I am particularly interested in bringing this experience to a role where I can contribute quickly while continuing to grow.\n\n"
        "In my previous work, I have developed practical experience that relates to the responsibilities described for this position. "
        "I would welcome the opportunity to discuss the specific results, projects, and examples from my background that are most relevant to your team.\n\n"
        f"Thank you for considering my application. I would be glad to discuss how my experience could support {company_name}.\n\n"
        f"Sincerely,\n{name}"
    )


@career_bp.get("/health")
def career_health():
    return jsonify({"status": "ok", "service": "EggyPDF Career Pro", "features": ["ats-analysis", "job-matching", "career-pro-checkout", "resume-tailoring", "cover-letter"], "payments_configured": bool(os.getenv("DODO_PAYMENTS_API_KEY", "").strip())})


@career_bp.post("/checkout")
def create_career_pro_checkout():
    try:
        payload = {"product_cart": [{"product_id": DODO_PRODUCT_ID, "quantity": 1}], "return_url": CAREER_PRO_RETURN_URL, "metadata": {"product": "career_pro", "source": "eggypdf"}}
        checkout = _dodo_request("POST", "/checkouts", json=payload)
        checkout_url, session_id = checkout.get("checkout_url"), checkout.get("session_id")
        if not checkout_url or not session_id:
            raise RuntimeError("Payment service returned an incomplete checkout session.")
        return jsonify({"success": True, "checkout_url": checkout_url, "session_id": session_id})
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@career_bp.get("/checkout/<session_id>")
def verify_career_pro_checkout(session_id):
    try:
        paid, status = _verify_paid_session(session_id)
        return jsonify({"success": True, "paid": paid, "payment_status": status, "feature_id": "career_pro" if paid else None})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@career_bp.post("/pro/tailor")
def career_pro_tailor():
    try:
        data = request.get_json(silent=True) or {}
        _require_pro(data)
        resume_text = (data.get("resume_text") or "").strip()
        job_text = (data.get("job_description") or "").strip()
        _validate_text(resume_text, "Resume text")
        _validate_text(job_text, "Job description")
        return jsonify({"success": True, "tailoring": _tailoring_plan(resume_text, job_text)})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@career_bp.post("/pro/cover-letter")
def career_pro_cover_letter():
    try:
        data = request.get_json(silent=True) or {}
        _require_pro(data)
        resume_text = (data.get("resume_text") or "").strip()
        job_text = (data.get("job_description") or "").strip()
        _validate_text(resume_text, "Resume text")
        _validate_text(job_text, "Job description")
        draft = _cover_letter_draft(resume_text, job_text, (data.get("applicant_name") or "").strip(), (data.get("company") or "").strip(), (data.get("role") or "").strip())
        return jsonify({"success": True, "cover_letter": draft, "integrity_note": "Review and personalize this draft before sending. Keep every claim accurate."})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@career_bp.post("/ats/analyze")
def ats_analyze():
    try:
        resume_text = _get_resume_text(); job_text = _job_text(); _validate_text(resume_text, "Resume text")
        if job_text: _validate_text(job_text, "Job description")
        return jsonify({"success": True, "analysis": analyze_resume(resume_text, job_text)})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception:
        return jsonify({"success": False, "error": "We could not analyze this resume. Please try another file."}), 500


@career_bp.post("/job-match")
def job_match():
    try:
        resume_text = _get_resume_text(); job_text = _job_text(); _validate_text(resume_text, "Resume text"); _validate_text(job_text, "Job description")
        result = analyze_resume(resume_text, job_text)
        return jsonify({"success": True, "match": {"score": result["keyword_analysis"]["match_percentage"], "matched_keywords": result["keyword_analysis"]["matched"], "missing_keywords": result["keyword_analysis"]["missing"], "skills_detected": result["skills_detected"], "recommendations": result["recommendations"]}})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception:
        return jsonify({"success": False, "error": "We could not compare this resume with the job description."}), 500


@career_bp.post("/keywords")
def career_keywords():
    try:
        data = request.get_json(silent=True) or {} if request.is_json else {}
        text = (data.get("text") or "").strip() if request.is_json else (request.form.get("text") or "").strip()
        _validate_text(text, "Text")
        return jsonify({"success": True, "keywords": extract_keywords(text), "skills": extract_skills(text)})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
