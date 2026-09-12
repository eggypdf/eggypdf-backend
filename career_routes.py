"""EggyPDF Career Pro API routes."""
from __future__ import annotations

import io
import os
import requests
from flask import Blueprint, jsonify, request, send_file
from werkzeug.utils import secure_filename

from account_routes import current_account_user, grant_career_pro, user_has_career_pro
from career_engine import analyze_resume, extract_keywords, extract_skills
from career_v2 import extract_resume_upload, optimize_with_gemini
from career_ai import generate_cover_letter_with_gemini
from career_export import build_resume_export
from career_regen import regenerate_section
from career_pdf_ai import extract_pdf_text, summarize_pdf_text

career_bp = Blueprint("career", __name__, url_prefix="/api/career")
MAX_TEXT_LENGTH = 100_000
DEFAULT_DODO_PRODUCT_ID = "pdt_0Nmk7wwSsTDKzOvbI7z9n"
DODO_PRODUCT_ID = os.getenv("DODO_PRODUCT_ID", DEFAULT_DODO_PRODUCT_ID).strip()
DODO_API_BASE = os.getenv("DODO_API_BASE", "https://live.dodopayments.com").rstrip("/")
CAREER_PRO_RETURN_URL = os.getenv(
    "CAREER_PRO_RETURN_URL",
    "https://eggypdf.com/ats-checker.html?career_pro=return",
)


def _validate_text(text, label):
    if not text:
        raise ValueError(f"{label} is required.")
    if len(text) > MAX_TEXT_LENGTH:
        raise ValueError(
            f"{label} is too long. Please keep it under {MAX_TEXT_LENGTH:,} characters."
        )


def _headers():
    key = os.getenv("DODO_PAYMENTS_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Dodo Payments is not configured.")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _payerr(status):
    if status in (401, 403):
        return "Dodo authentication failed. Check that the API key matches the selected live/test environment."
    if status == 404:
        return "Dodo could not find the requested checkout resource or product. Check the Career Pro product ID and environment."
    if status in (400, 409, 422):
        return "Dodo rejected the checkout configuration. Check the product, return URL, and account environment."
    if status == 429:
        return "Dodo is temporarily rate-limiting checkout requests. Please try again shortly."
    return f"Payment service rejected the request (HTTP {status})."


def _dodo(method, path, **kwargs):
    try:
        response = requests.request(
            method,
            f"{DODO_API_BASE}{path}",
            headers=_headers(),
            timeout=20,
            **kwargs,
        )
    except requests.RequestException as exc:
        raise RuntimeError("Payment service is temporarily unavailable.") from exc
    if not response.ok:
        raise RuntimeError(_payerr(response.status_code))
    return response.json()


def _valid(value, prefix):
    return bool(
        value
        and value.startswith(prefix)
        and len(value) <= 200
        and all(char.isalnum() or char in "_-" for char in value)
    )


def _ispro(payment, checkout_session_id=None):
    if payment.get("status") != "succeeded":
        return False
    if checkout_session_id and payment.get("checkout_session_id") != checkout_session_id:
        return False
    return any(
        item.get("product_id") == DODO_PRODUCT_ID
        and int(item.get("quantity") or 0) >= 1
        for item in (payment.get("product_cart") or [])
    )


def _verify_record(identifier):
    """Verify a Dodo checkout/payment and return details needed for account linking."""
    if _valid(identifier, "pay_"):
        payment = _dodo("GET", f"/payments/{identifier}")
        return {
            "paid": _ispro(payment),
            "status": payment.get("status"),
            "checkout_id": (payment.get("checkout_session_id") or "").strip() or None,
            "payment_id": identifier,
            "metadata": payment.get("metadata") or {},
        }

    if not _valid(identifier, "cks_"):
        raise ValueError("Invalid checkout or payment identifier.")

    checkout = _dodo("GET", f"/checkouts/{identifier}")
    status = checkout.get("payment_status") or checkout.get("status")
    metadata = checkout.get("metadata") or {}
    payment_id = (checkout.get("payment_id") or "").strip()

    # Dodo checkout verification historically unlocks Career Pro when the
    # successful checkout contains our server-created Career Pro metadata.
    if status == "succeeded" and metadata.get("product") == "career_pro":
        return {
            "paid": True,
            "status": status,
            "checkout_id": identifier,
            "payment_id": payment_id or None,
            "metadata": metadata,
        }

    if _valid(payment_id, "pay_"):
        payment = _dodo("GET", f"/payments/{payment_id}")
        payment_metadata = payment.get("metadata") or metadata
        return {
            "paid": _ispro(payment, identifier),
            "status": payment.get("status") or status,
            "checkout_id": identifier,
            "payment_id": payment_id,
            "metadata": payment_metadata,
        }

    return {
        "paid": False,
        "status": status,
        "checkout_id": identifier,
        "payment_id": payment_id or None,
        "metadata": metadata,
    }


def _verify(identifier):
    record = _verify_record(identifier)
    return record["paid"], record["status"]


def _account_user():
    """Return the signed-in user when a valid Bearer token is supplied."""
    return current_account_user(required=False)


def _link_paid_record_to_account(record, request_user=None):
    """Persist a verified Career Pro purchase to Supabase when an account is known."""
    if not record.get("paid"):
        return None

    metadata = record.get("metadata") or {}
    metadata_user_id = (metadata.get("account_user_id") or "").strip()
    request_user_id = (request_user or {}).get("id") if request_user else None

    # New account-aware checkouts carry account_user_id in server-created Dodo
    # metadata. For older/anonymous checkouts, possession of the verified
    # checkout plus an authenticated session can migrate that purchase once.
    user_id = metadata_user_id or request_user_id
    if not user_id:
        return None

    entitlement = grant_career_pro(
        user_id,
        product_id=DODO_PRODUCT_ID,
        checkout_id=record.get("checkout_id"),
        payment_id=record.get("payment_id"),
    )
    return entitlement


def _require(data):
    """Allow Career Pro via account entitlement first, then legacy Dodo session."""
    user = _account_user()
    if user and user_has_career_pro(user["id"]):
        return {"source": "account", "user": user}

    identifier = (data.get("session_id") or data.get("payment_id") or "").strip()
    if not identifier:
        raise PermissionError("Sign in with an active Career Pro account or verify your Career Pro purchase.")

    record = _verify_record(identifier)
    if not record["paid"]:
        raise PermissionError("Career Pro purchase could not be verified.")

    # If a signed-in user presents a valid legacy purchase, migrate it to the
    # account so future browsers/devices can rely on the database entitlement.
    if user:
        _link_paid_record_to_account(record, user)

    return {"source": "payment", "user": user, "payment": record}


@career_bp.get("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "service": "EggyPDF Career Pro",
            "features": [
                "ats-analysis",
                "job-matching",
                "career-pro-checkout",
                "career-pro-account-entitlement",
                "resume-upload",
                "resume-optimizer",
                "section-regeneration",
                "resume-export",
                "ai-cover-letter",
                "ai-pdf-summarizer",
            ],
            "payments_configured": bool(os.getenv("DODO_PAYMENTS_API_KEY", "").strip()),
            "payment_environment": "test" if "test" in DODO_API_BASE.lower() else "live",
            "career_pro_product_configured": bool(DODO_PRODUCT_ID),
            "account_entitlements_configured": bool(
                os.getenv("SUPABASE_URL", "").strip()
                and os.getenv("SUPABASE_ANON_KEY", "").strip()
                and os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
            ),
            "ai_optimizer_configured": bool(
                (os.getenv("GEMINI_API") or os.getenv("GEMINI_API_KEY") or "").strip()
            ),
            "ai_cover_letter_configured": bool(
                (os.getenv("GEMINI_API") or os.getenv("GEMINI_API_KEY") or "").strip()
            ),
            "ai_section_regeneration_configured": bool(
                (os.getenv("GEMINI_API") or os.getenv("GEMINI_API_KEY") or "").strip()
            ),
            "ai_pdf_summarizer_configured": bool(
                (os.getenv("GEMINI_API") or os.getenv("GEMINI_API_KEY") or "").strip()
            ),
        }
    )


@career_bp.post("/checkout")
def checkout():
    try:
        user = _account_user()
        metadata = {"product": "career_pro", "source": "eggypdf"}
        if user:
            metadata["account_user_id"] = user["id"]

        checkout_record = _dodo(
            "POST",
            "/checkouts",
            json={
                "product_cart": [{"product_id": DODO_PRODUCT_ID, "quantity": 1}],
                "return_url": CAREER_PRO_RETURN_URL,
                "metadata": metadata,
            },
        )
        checkout_url = checkout_record.get("checkout_url")
        session_id = checkout_record.get("session_id")
        if not checkout_url or not session_id:
            raise RuntimeError("Payment service returned an incomplete checkout session.")
        return jsonify(
            {
                "success": True,
                "checkout_url": checkout_url,
                "session_id": session_id,
                "account_linked_checkout": bool(user),
            }
        )
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 401
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@career_bp.get("/checkout/<identifier>")
def verify(identifier):
    try:
        record = _verify_record(identifier)
        user = _account_user()
        entitlement = _link_paid_record_to_account(record, user) if record["paid"] else None
        return jsonify(
            {
                "success": True,
                "paid": record["paid"],
                "payment_status": record["status"],
                "feature_id": "career_pro" if record["paid"] else None,
                "account_linked": bool(entitlement),
            }
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 401
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@career_bp.post("/pro/extract-resume")
def pro_extract():
    try:
        session_id = (request.form.get("session_id") or "").strip()
        _require({"session_id": session_id})
        upload = request.files.get("resume") or request.files.get("file")
        if not upload:
            raise ValueError("Choose a resume file first.")
        text = extract_resume_upload(upload)
        _validate_text(text, "Resume text")
        return jsonify(
            {
                "success": True,
                "resume_text": text,
                "filename": secure_filename(upload.filename),
                "characters": len(text),
            }
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503
    except Exception:
        return jsonify(
            {
                "success": False,
                "error": "We could not read this resume. Try a text-based PDF, DOCX, or TXT file.",
            }
        ), 500


@career_bp.post("/pro/optimize")
def pro_optimize():
    try:
        data = request.get_json(silent=True) or {}
        _require(data)
        resume = (data.get("resume_text") or "").strip()
        job = (data.get("job_description") or "").strip()
        _validate_text(resume, "Resume text")
        _validate_text(job, "Job description")
        return jsonify(
            {"success": True, "optimization": optimize_with_gemini(resume, job)}
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@career_bp.post("/pro/regenerate-section")
def pro_regenerate_section():
    try:
        data = request.get_json(silent=True) or {}
        _require(data)
        source = (data.get("source_resume") or "").strip()
        optimized = (data.get("optimized_resume") or "").strip()
        job = (data.get("job_description") or "").strip()
        section = (data.get("section_type") or "").strip()
        current = (data.get("current_text") or "").strip()
        _validate_text(source, "Source resume")
        _validate_text(optimized, "Optimized resume")
        _validate_text(job, "Job description")
        result = regenerate_section(source, optimized, job, section, current)
        return jsonify({"success": True, "regeneration": result})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@career_bp.post("/pro/export-resume")
def pro_export_resume():
    try:
        data = request.get_json(silent=True) or {}
        _require(data)
        resume = (data.get("resume_text") or "").strip()
        fmt = (data.get("format") or "").strip().lower()
        _validate_text(resume, "Optimized resume text")
        export_data, mime, name = build_resume_export(resume, fmt)
        return send_file(
            io.BytesIO(export_data),
            mimetype=mime,
            as_attachment=True,
            download_name=name,
            max_age=0,
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@career_bp.post("/pro/pdf-summary")
def pro_pdf_summary():
    try:
        session_id = (request.form.get("session_id") or "").strip()
        _require({"session_id": session_id})
        upload = request.files.get("pdf") or request.files.get("file")
        if not upload:
            raise ValueError("Choose a PDF file first.")
        detail = (request.form.get("detail") or "short").strip().lower()
        extracted = extract_pdf_text(upload)
        summary = summarize_pdf_text(extracted["text"], detail)
        return jsonify(
            {
                "success": True,
                "document": {
                    "filename": secure_filename(extracted["filename"]),
                    "page_count": extracted["page_count"],
                    "characters": extracted["characters"],
                },
                "summary": summary,
            }
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503
    except Exception:
        return jsonify(
            {
                "success": False,
                "error": "We could not summarize this PDF. Please try another text-based PDF.",
            }
        ), 500


@career_bp.post("/pro/tailor")
def tailor():
    try:
        data = request.get_json(silent=True) or {}
        _require(data)
        resume = (data.get("resume_text") or "").strip()
        job = (data.get("job_description") or "").strip()
        _validate_text(resume, "Resume text")
        _validate_text(job, "Job description")
        return jsonify(
            {"success": True, "tailoring": optimize_with_gemini(resume, job)}
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@career_bp.post("/pro/cover-letter")
def letter():
    try:
        data = request.get_json(silent=True) or {}
        _require(data)
        resume = (data.get("resume_text") or "").strip()
        job = (data.get("job_description") or "").strip()
        _validate_text(resume, "Resume text")
        _validate_text(job, "Job description")
        result = generate_cover_letter_with_gemini(
            resume,
            job,
            (data.get("applicant_name") or "").strip(),
            (data.get("company") or "").strip(),
            (data.get("role") or "").strip(),
            (data.get("tone") or "professional").strip(),
        )
        return jsonify({"success": True, **result})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


def _gettext():
    if request.is_json:
        return ((request.get_json(silent=True) or {}).get("resume_text") or "").strip()
    upload = request.files.get("resume") or request.files.get("file")
    if not upload:
        return ""
    return extract_resume_upload(upload)


def _job():
    if request.is_json:
        data = request.get_json(silent=True) or {}
        return (data.get("job_description") or data.get("job_text") or "").strip()
    return (
        request.form.get("job_description") or request.form.get("job_text") or ""
    ).strip()


@career_bp.post("/ats/analyze")
def ats():
    try:
        resume = _gettext()
        job = _job()
        _validate_text(resume, "Resume text")
        return jsonify(
            {
                "success": True,
                "analysis": analyze_resume(resume, job),
                "resume_text": resume,
            }
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception:
        return jsonify(
            {
                "success": False,
                "error": "We could not analyze this resume. Please try another file.",
            }
        ), 500


@career_bp.post("/job-match")
def match():
    try:
        resume = _gettext()
        job = _job()
        _validate_text(resume, "Resume text")
        _validate_text(job, "Job description")
        analysis = analyze_resume(resume, job)
        return jsonify(
            {
                "success": True,
                "match": {
                    "score": analysis["keyword_analysis"]["match_percentage"],
                    "matched_keywords": analysis["keyword_analysis"]["matched"],
                    "missing_keywords": analysis["keyword_analysis"]["missing"],
                    "skills_detected": analysis["skills_detected"],
                    "recommendations": analysis["recommendations"],
                },
            }
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@career_bp.post("/keywords")
def keywords():
    try:
        data = request.get_json(silent=True) or {}
        text = (data.get("text") or "").strip()
        _validate_text(text, "Text")
        return jsonify(
            {
                "success": True,
                "keywords": extract_keywords(text),
                "skills": extract_skills(text),
            }
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
