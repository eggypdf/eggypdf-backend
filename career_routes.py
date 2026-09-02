"""EggyPDF Career Pro API routes.

Career features live in a Blueprint so the existing PDF API remains stable.
Payment checkout is created and verified server-side; Dodo API credentials are
never exposed to the browser.
"""
from __future__ import annotations

import io
import os

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
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n\n".join(pages).strip()


def _get_resume_text():
    """Accept JSON text or a PDF/TXT upload without persisting user files."""
    if request.is_json:
        data = request.get_json(silent=True) or {}
        return (data.get("resume_text") or "").strip()

    uploaded = request.files.get("resume") or request.files.get("file")
    if not uploaded or not uploaded.filename:
        return ""

    filename = secure_filename(uploaded.filename)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_RESUME_EXTENSIONS:
        raise ValueError("Please upload a PDF or TXT resume.")

    if ext == "pdf":
        return _extract_pdf_text(uploaded)
    return uploaded.read().decode("utf-8", errors="replace").strip()


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
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _dodo_request(method, path, **kwargs):
    try:
        response = requests.request(
            method,
            f"{DODO_API_BASE}{path}",
            headers=_dodo_headers(),
            timeout=20,
            **kwargs,
        )
    except requests.RequestException as exc:
        raise RuntimeError("Payment service is temporarily unavailable.") from exc

    if not response.ok:
        raise RuntimeError("Payment service rejected the request.")
    return response.json()


@career_bp.get("/health")
def career_health():
    return jsonify({
        "status": "ok",
        "service": "EggyPDF Career Pro",
        "features": ["ats-analysis", "job-matching", "career-pro-checkout"],
        "payments_configured": bool(os.getenv("DODO_PAYMENTS_API_KEY", "").strip()),
    })


@career_bp.post("/checkout")
def create_career_pro_checkout():
    """Create a hosted Dodo checkout without exposing the API key to clients."""
    try:
        payload = {
            "product_cart": [{"product_id": DODO_PRODUCT_ID, "quantity": 1}],
            "return_url": CAREER_PRO_RETURN_URL,
            "metadata": {"product": "career_pro", "source": "eggypdf"},
        }
        checkout = _dodo_request("POST", "/checkouts", json=payload)
        checkout_url = checkout.get("checkout_url")
        session_id = checkout.get("session_id")
        if not checkout_url or not session_id:
            raise RuntimeError("Payment service returned an incomplete checkout session.")
        return jsonify({
            "success": True,
            "checkout_url": checkout_url,
            "session_id": session_id,
        })
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@career_bp.get("/checkout/<session_id>")
def verify_career_pro_checkout(session_id):
    """Verify a checkout directly with Dodo before granting paid access."""
    if not session_id or len(session_id) > 200 or not all(c.isalnum() or c in "_-" for c in session_id):
        return jsonify({"success": False, "error": "Invalid checkout session."}), 400

    try:
        checkout = _dodo_request("GET", f"/checkouts/{session_id}")
        payment_status = checkout.get("payment_status") or checkout.get("status")
        metadata = checkout.get("metadata") or {}
        paid = payment_status == "succeeded" and metadata.get("product") == "career_pro"
        return jsonify({
            "success": True,
            "paid": paid,
            "payment_status": payment_status,
            "feature_id": "career_pro" if paid else None,
        })
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@career_bp.post("/ats/analyze")
def ats_analyze():
    try:
        resume_text = _get_resume_text()
        job_text = _job_text()
        _validate_text(resume_text, "Resume text")
        if job_text:
            _validate_text(job_text, "Job description")

        result = analyze_resume(resume_text, job_text)
        return jsonify({"success": True, "analysis": result})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception:
        return jsonify({"success": False, "error": "We could not analyze this resume. Please try another file."}), 500


@career_bp.post("/job-match")
def job_match():
    try:
        resume_text = _get_resume_text()
        job_text = _job_text()
        _validate_text(resume_text, "Resume text")
        _validate_text(job_text, "Job description")

        result = analyze_resume(resume_text, job_text)
        return jsonify({
            "success": True,
            "match": {
                "score": result["keyword_analysis"]["match_percentage"],
                "matched_keywords": result["keyword_analysis"]["matched"],
                "missing_keywords": result["keyword_analysis"]["missing"],
                "skills_detected": result["skills_detected"],
                "recommendations": result["recommendations"],
            },
        })
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception:
        return jsonify({"success": False, "error": "We could not compare this resume with the job description."}), 500


@career_bp.post("/keywords")
def career_keywords():
    """Small utility endpoint used by the frontend during development/testing."""
    try:
        if request.is_json:
            data = request.get_json(silent=True) or {}
            text = (data.get("text") or "").strip()
        else:
            text = (request.form.get("text") or "").strip()
        _validate_text(text, "Text")
        return jsonify({
            "success": True,
            "keywords": extract_keywords(text),
            "skills": extract_skills(text),
        })
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
