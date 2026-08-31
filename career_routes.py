"""EggyPDF Career Pro API routes.

Kept in a Blueprint so the existing PDF API can remain stable while Career Pro
is developed independently. No database or payment dependency is required for
this first MVP.
"""
from __future__ import annotations

import io
import os
from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename

from career_engine import analyze_resume, extract_keywords, extract_skills

career_bp = Blueprint("career", __name__, url_prefix="/api/career")

MAX_TEXT_LENGTH = 100_000
ALLOWED_RESUME_EXTENSIONS = {"pdf", "txt"}


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
        text = (data.get("resume_text") or "").strip()
        return text

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


@career_bp.get("/health")
def career_health():
    return jsonify({
        "status": "ok",
        "service": "EggyPDF Career Pro",
        "features": ["ats-analysis", "job-matching"],
    })


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
