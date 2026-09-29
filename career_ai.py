"""AI helpers for paid EggyPDF Career Pro application documents."""
from __future__ import annotations

import json
import os
import random
import re
import time

import requests


ALLOWED_TONES = {"professional", "confident", "concise"}
TRANSIENT_STATUSES = {408, 429, 500, 502, 503, 504}


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


def _cover_letter_models():
    """Prefer current production Flash models, then retain 2.5 as legacy fallbacks."""
    configured = (
        os.getenv("GEMINI_COVER_LETTER_MODEL")
        or os.getenv("GEMINI_MODEL")
        or ""
    ).strip()
    configured_fallback = (
        os.getenv("GEMINI_COVER_LETTER_FALLBACK_MODEL")
        or ""
    ).strip()

    models = []
    for model in (
        configured,
        "gemini-3.8-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.6-flash",
        configured_fallback,
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
    ):
        if model and model not in models:
            models.append(model)
    return models


def _cover_letter_log(model: str, event: str, detail: str = ""):
    """Server-safe diagnostics. Never log API keys, prompts, or resume content."""
    message = f"[career-cover-letter] model={model} event={event}"
    if detail:
        message += f" detail={detail[:160]}"
    print(message, flush=True)


def _gemini_cover_letter_request(key: str, model: str, prompt: str):
    """Call one model with a short bounded retry before cross-model fallback."""
    last_error = None
    last_response = None

    for attempt in range(2):
        try:
            response = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                params={"key": key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "maxOutputTokens": 4096,
                    },
                },
                timeout=(10, 75),
            )
            last_response = response
        except requests.RequestException as exc:
            last_error = exc
            _cover_letter_log(model, "transport_error", exc.__class__.__name__)
            if attempt == 0:
                time.sleep(0.8 + random.uniform(0.10, 0.35))
                continue
            return None, last_error

        if response.ok:
            _cover_letter_log(model, "success")
            return response, None

        _cover_letter_log(model, "http_error", str(response.status_code))
        if response.status_code in TRANSIENT_STATUSES and attempt == 0:
            time.sleep(0.8 + random.uniform(0.10, 0.35))
            continue

        return response, None

    return last_response, last_error


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

    failures = []
    permission_failures = 0

    for model in _cover_letter_models():
        response, transport_error = _gemini_cover_letter_request(key, model, prompt)

        if transport_error is not None and response is None:
            failures.append(f"{model}: network")
            continue

        if response is None:
            failures.append(f"{model}: unavailable")
            continue

        if not response.ok:
            status = response.status_code
            if status == 401:
                raise RuntimeError("The AI cover letter generator is not authenticated correctly on the server.")
            if status == 403:
                permission_failures += 1
                failures.append(f"{model}: HTTP 403")
                continue
            if status in (400, 404) or status in TRANSIENT_STATUSES:
                failures.append(f"{model}: HTTP {status}")
                continue
            failures.append(f"{model}: HTTP {status}")
            continue

        try:
            out = _extract_json_text(response.json())
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            _cover_letter_log(model, "invalid_json")
            failures.append(f"{model}: incomplete response")
            continue

        letter = str(out.get("cover_letter") or "").strip()
        subject = str(out.get("subject_line") or "").strip()
        strengths = [str(x).strip() for x in (out.get("strengths_used") or []) if str(x).strip()]
        unsupported = [str(x).strip() for x in (out.get("unsupported_requirements") or []) if str(x).strip()]

        if len(letter) < 180:
            _cover_letter_log(model, "short_response", str(len(letter)))
            failures.append(f"{model}: short response")
            continue

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

    _cover_letter_log("all", "failed_after_retries", "; ".join(failures))
    if permission_failures and permission_failures == len(_cover_letter_models()):
        raise RuntimeError("The AI cover letter generator does not currently have access to an available AI model.")
    raise RuntimeError(
        "The AI cover letter service is temporarily unavailable after automatic model fallback. Please try again shortly."
    )
