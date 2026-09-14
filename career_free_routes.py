"""Free Career helper routes used by the ATS checker."""
from __future__ import annotations

from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename

from career_v2 import extract_resume_upload

career_free_bp = Blueprint("career_free", __name__)
MAX_TEXT_LENGTH = 100_000


@career_free_bp.post("/api/career/ats/extract-resume")
def extract_resume_for_ats():
    """Extract readable CV content without requiring Career Pro."""
    try:
        upload = request.files.get("resume") or request.files.get("file")
        if not upload:
            raise ValueError("Choose a resume file first.")

        text = (extract_resume_upload(upload) or "").strip()
        if not text:
            raise ValueError("We could not find readable text in this resume.")
        if len(text) > MAX_TEXT_LENGTH:
            raise ValueError(
                f"Resume text is too long. Please keep it under {MAX_TEXT_LENGTH:,} characters."
            )

        return jsonify(
            {
                "success": True,
                "resume_text": text,
                "filename": secure_filename(upload.filename or "resume"),
                "characters": len(text),
                "free_preview": True,
            }
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "We could not extract text from this resume. Try a text-based PDF, DOCX, or TXT file.",
                }
            ),
            500,
        )
