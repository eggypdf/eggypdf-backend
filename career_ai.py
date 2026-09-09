"""AI helpers for paid EggyPDF Career Pro application documents."""
from __future__ import annotations

import json
import os
import re

import requests


ALLOWED_TONES = {"professional", "confident", "concise"}


def _gemini_key():
    return (os.getenv("GEMINI_API") or os.getenv("GEMINI_API_KEY") or "").strip()


def _extract_json_text(payload):
    candidates = payload.get("candidates") or []
    if not candidates:
        raise ValueError("No AI candidate returned.")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    if not parts or not parts[0].get("text"):
        raise ValueError("No AI text returned.")
    text = parts[0]["text"].strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S)
    return json.loads(text)


def generate_cover_letter_with_gemini(
    resume: str,
    job: str,
    applicant_name: str = "",
    company: str = "",
    role: str = "",
    tone: str = "professional",
):
    """Create a job-specific cover letter using only facts supported by the resume."""
    key = _gemini_key()
    if not key:
        raise RuntimeError("The AI cover letter generator is not configured on the server.")

    tone = (tone or "professional").strip().lower()
    if tone not in ALLOWED_TONES:
        raise ValueError("Tone must be professional, confident, or concise.")

    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
    applicant_name = (applicant_name or "").strip()
    company = (company or "").strip()
    role = (role or "").strip()

    prompt = f"""You are EggyPDF Career Pro, an expert job-application writing assistant.

TASK
Write a specific, polished cover letter for the target job using ONLY facts supported by the candidate's resume.

TRUTH AND SAFETY RULES
- Never invent employers, job titles, dates, education, certifications, software, skills, responsibilities, achievements, metrics, projects, awards, locations, or years of experience.
- Never claim the candidate meets a requirement unless the resume provides direct evidence.
- You may rephrase and prioritize existing experience for clarity and relevance.
- Do not copy unsupported requirements from the job description into the candidate's background.
- Avoid generic claims such as "I am the perfect candidate" or "I have extensive experience" unless clearly supported.

WRITING REQUIREMENTS
- Tone: {tone}.
- Aim for about 220-320 words unless the tone is concise, then aim for about 160-220 words.
- Use 3-5 short paragraphs.
- Open directly and specifically.
- Mention the target company or role only when provided below.
- Connect 2-4 of the strongest resume-supported facts to the job's priorities.
- Keep the closing natural and professional.
- Do not include markdown, bullet points, placeholders, or bracketed instructions.

Return JSON only with exactly these keys:
cover_letter (string)
subject_line (string)
strengths_used (array of strings)
unsupported_requirements (array of strings)

APPLICANT NAME:
{applicant_name or 'Not provided'}

TARGET COMPANY:
{company or 'Not provided'}

TARGET ROLE:
{role or 'Not provided'}

RESUME — SOURCE OF TRUTH:
{resume}

TARGET JOB DESCRIPTION:
{job}
"""

    try:
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "temperature": 0.35,
                    "maxOutputTokens": 4096,
                },
            },
            timeout=45,
        )
    except requests.RequestException as exc:
        raise RuntimeError("The AI cover letter generator is temporarily unreachable. Please try again in a moment.") from exc

    if not response.ok:
        if response.status_code == 429:
            raise RuntimeError("The AI cover letter generator is busy right now. Please try again in a minute.")
        if response.status_code in (401, 403):
            raise RuntimeError("The AI cover letter generator is not authenticated correctly on the server.")
        raise RuntimeError(f"The AI cover letter generator failed on the server (HTTP {response.status_code}).")

    try:
        out = _extract_json_text(response.json())
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise RuntimeError("The AI cover letter generator returned an incomplete response. Please try again.") from exc

    letter = str(out.get("cover_letter") or "").strip()
    subject = str(out.get("subject_line") or "").strip()
    strengths = [str(x).strip() for x in (out.get("strengths_used") or []) if str(x).strip()]
    unsupported = [str(x).strip() for x in (out.get("unsupported_requirements") or []) if str(x).strip()]

    if len(letter) < 180:
        raise RuntimeError("The AI cover letter generator returned an incomplete letter. Please try again.")

    return {
        "cover_letter": letter,
        "subject_line": subject,
        "strengths_used": strengths,
        "unsupported_requirements": unsupported,
        "mode": "ai",
        "provider": "gemini",
        "model": model,
        "tone": tone,
        "integrity_note": (
            "AI-generated from the resume and job description. Review every claim before sending; EggyPDF is instructed not to invent experience, skills, metrics, education, employers, certifications, or achievements."
        ),
    }
