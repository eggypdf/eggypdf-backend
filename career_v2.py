"""Career Pro V2 helpers: upload extraction and truthful resume optimization."""
from __future__ import annotations

import io
import json
import os
import re
from difflib import SequenceMatcher

import requests

from career_engine import analyze_resume

MAX_UPLOAD_BYTES = 8 * 1024 * 1024


def extract_resume_upload(f):
    name = (f.filename or "").lower()
    raw = f.read(MAX_UPLOAD_BYTES + 1)
    if not raw:
        raise ValueError("The uploaded resume is empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError("Resume file is too large. Please keep it under 8 MB.")

    if name.endswith(".pdf"):
        from pypdf import PdfReader

        text = "\n\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(raw)).pages).strip()
    elif name.endswith(".docx"):
        from docx import Document

        d = Document(io.BytesIO(raw))
        parts = [p.text.strip() for p in d.paragraphs if p.text.strip()]
        for table in d.tables:
            for row in table.rows:
                line = " | ".join(c.text.strip() for c in row.cells if c.text.strip())
                if line:
                    parts.append(line)
        text = "\n".join(parts).strip()
    elif name.endswith(".txt"):
        text = raw.decode("utf-8", errors="replace").strip()
    else:
        raise ValueError("Please upload a PDF, DOCX, or TXT resume.")

    if len(text) < 40:
        raise ValueError(
            "We couldn't extract enough readable text. If this is a scanned PDF, upload a text-based PDF or DOCX instead."
        )
    return text


def _compact_for_compare(text):
    return re.sub(r"\W+", " ", (text or "").lower()).strip()


def _change_ratio(original, rewritten):
    """Return an approximate 0..100 percentage of textual change."""
    a = _compact_for_compare(original)
    b = _compact_for_compare(rewritten)
    if not a or not b:
        return 0
    similarity = SequenceMatcher(None, a, b).ratio()
    return max(0, min(100, round((1 - similarity) * 100)))


def _required_output(out):
    if not isinstance(out, dict):
        raise ValueError("Optimizer returned an invalid response.")

    list_keys = ("optimized_bullets", "skills_to_highlight", "keywords_to_review", "changes")
    for key in list_keys:
        if not isinstance(out.get(key), list):
            out[key] = []
        out[key] = [str(x).strip() for x in out[key] if str(x).strip()]

    for key in ("optimized_summary", "optimized_resume"):
        value = out.get(key)
        out[key] = str(value).strip() if value is not None else ""

    if not out["optimized_resume"]:
        raise ValueError("Optimizer did not return a complete rewritten resume.")
    return out


def _gemini_request(key, model, prompt):
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "temperature": 0.25,
                    "maxOutputTokens": 8192,
                },
            },
            timeout=45,
        )
    except requests.RequestException as exc:
        raise RuntimeError("The AI resume optimizer is temporarily unreachable. Please try again in a moment.") from exc

    if not r.ok:
        if r.status_code == 429:
            raise RuntimeError("The AI resume optimizer is busy right now. Please try again in a minute.")
        if r.status_code in (401, 403):
            raise RuntimeError("The AI resume optimizer is not authenticated correctly on the server.")
        raise RuntimeError(f"The AI resume optimizer failed on the server (HTTP {r.status_code}).")

    try:
        payload = r.json()
        candidates = payload.get("candidates") or []
        if not candidates:
            raise ValueError("No AI candidate returned.")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        if not parts or not parts[0].get("text"):
            raise ValueError("No AI text returned.")
        text = parts[0]["text"].strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S)
        return _required_output(json.loads(text))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("The AI resume optimizer returned an incomplete response. Please try again.") from exc


def _base_prompt(resume, job):
    return f"""You are EggyPDF Career Pro, a job-specific resume rewriting engine.

TASK
Rewrite the candidate's resume so it is materially stronger and more relevant to the target job while remaining completely truthful.

NON-NEGOTIABLE TRUTH RULES
- NEVER invent or assume facts.
- Preserve the candidate's employers, job titles, dates, education, locations and contact facts exactly unless only formatting changes.
- NEVER invent metrics, certifications, software/tools, skills, responsibilities, projects or achievements.
- A target-job keyword may be inserted only when the original resume contains direct evidence that the candidate has that skill/responsibility.
- If a job requirement is unsupported by the resume, put it in keywords_to_review instead of pretending the candidate has it.

REWRITE REQUIREMENTS
- optimized_resume must be a COMPLETE, copy-ready rewritten resume, not advice and not the original pasted back unchanged.
- Rewrite the professional summary around the strongest existing evidence that matches the target role.
- Rewrite experience descriptions/bullets into clearer, action-oriented language using only facts already present.
- Reorder or prioritize existing skills and experience when that improves relevance.
- Keep factual identity/contact/date lines intact.
- Make meaningful wording improvements wherever the source resume gives enough information to do so.
- optimized_bullets should contain the strongest rewritten experience bullets created from existing facts.
- skills_to_highlight must contain only skills already evidenced in the resume.
- changes must describe specific rewrites you actually made.

Return JSON only with exactly these keys:
optimized_summary (string)
optimized_bullets (array of strings)
skills_to_highlight (array of strings)
keywords_to_review (array of strings)
optimized_resume (string)
changes (array of strings)

ORIGINAL RESUME:
{resume}

TARGET JOB DESCRIPTION:
{job}
"""


def _revision_prompt(resume, job, first_output):
    return f"""You are revising a previous EggyPDF Career Pro attempt because it did not change the resume enough.

Produce a genuinely rewritten, copy-ready resume while preserving every factual claim. Do NOT invent anything. Change phrasing, prioritization and structure where supported by the source. The final optimized_resume must not simply repeat the original resume.

Use only the ORIGINAL RESUME as the factual source of truth. The TARGET JOB tells you what to emphasize, not what facts to invent.

Return JSON only with exactly these keys: optimized_summary, optimized_bullets, skills_to_highlight, keywords_to_review, optimized_resume, changes.

ORIGINAL RESUME:
{resume}

TARGET JOB DESCRIPTION:
{job}

PREVIOUS WEAK ATTEMPT:
{json.dumps(first_output, ensure_ascii=False)}
"""


def optimize_with_gemini(resume, job):
    key = (os.getenv("GEMINI_API") or os.getenv("GEMINI_API_KEY") or "").strip()
    if not key:
        # A paid optimizer must never pretend optimization succeeded by returning the original resume.
        raise RuntimeError("The AI resume optimizer is not configured on the server.")

    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
    before = analyze_resume(resume, job)["keyword_analysis"]["match_percentage"]

    out = _gemini_request(key, model, _base_prompt(resume, job))
    change_ratio = _change_ratio(resume, out["optimized_resume"])

    # The old implementation silently returned the original resume whenever Gemini failed.
    # It could therefore look like a successful optimization with zero changes. Never do that.
    if change_ratio < 3:
        out = _gemini_request(key, model, _revision_prompt(resume, job, out))
        change_ratio = _change_ratio(resume, out["optimized_resume"])

    if change_ratio < 3:
        raise RuntimeError(
            "The AI optimizer could not produce a meaningful truthful rewrite from this resume. Try adding more detail to your experience or use a fuller job description."
        )

    after = analyze_resume(out["optimized_resume"], job)["keyword_analysis"]["match_percentage"]
    out.update(
        {
            "mode": "ai",
            "provider": "gemini",
            "model": model,
            "current_match": before,
            "optimized_match": after,
            "change_ratio": change_ratio,
            "rewrite_applied": True,
            "integrity_note": (
                "AI rewrite applied. Review every line before use. EggyPDF is instructed not to invent experience, metrics, skills, education, employers, certifications, or achievements."
            ),
        }
    )
    return out
