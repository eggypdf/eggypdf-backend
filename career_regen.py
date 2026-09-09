"""Truthful section-level regeneration for EggyPDF Career Pro."""
from __future__ import annotations

import json
import os
import re
from difflib import SequenceMatcher

import requests

ALLOWED_SECTIONS = {"summary", "bullet"}
MAX_SECTION_CHARS = 6000


def _compact(text: str) -> str:
    return re.sub(r"\W+", " ", (text or "").lower()).strip()


def _change_ratio(a: str, b: str) -> int:
    left, right = _compact(a), _compact(b)
    if not left or not right:
        return 0
    return max(0, min(100, round((1 - SequenceMatcher(None, left, right).ratio()) * 100)))


def _extract_json(payload):
    candidates = payload.get("candidates") or []
    if not candidates:
        raise ValueError("No AI candidate returned.")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    if not parts or not parts[0].get("text"):
        raise ValueError("No AI text returned.")
    text = parts[0]["text"].strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S)
    out = json.loads(text)
    regenerated = str(out.get("regenerated_text") or "").strip()
    reason = str(out.get("reason") or "").strip()
    if not regenerated:
        raise ValueError("Missing regenerated text.")
    return regenerated, reason


def _call_gemini(key: str, model: str, prompt: str):
    try:
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "temperature": 0.45,
                    "maxOutputTokens": 2048,
                },
            },
            timeout=45,
        )
    except requests.RequestException as exc:
        raise RuntimeError("The AI section rewriter is temporarily unreachable. Please try again in a moment.") from exc

    if not response.ok:
        if response.status_code == 429:
            raise RuntimeError("The AI section rewriter is busy right now. Please try again in a minute.")
        if response.status_code in (401, 403):
            raise RuntimeError("The AI section rewriter is not authenticated correctly on the server.")
        raise RuntimeError(f"The AI section rewriter failed on the server (HTTP {response.status_code}).")

    try:
        return _extract_json(response.json())
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise RuntimeError("The AI section rewriter returned an incomplete response. Please try again.") from exc


def _prompt(section_type: str, source_resume: str, optimized_resume: str, job: str, current_text: str, stronger: bool = False) -> str:
    if section_type == "summary":
        rules = "Rewrite only the professional summary. Keep it concise, specific, and job-relevant. Use 2-4 sentences."
    else:
        rules = "Rewrite only this single experience bullet. Keep it one bullet-length sentence, action-oriented and specific. Preserve every factual detail and metric exactly."

    extra = "The first attempt was too similar. Make the wording materially different while keeping every fact unchanged." if stronger else "Create a fresh alternative, not a cosmetic synonym swap."

    return f"""You are EggyPDF Career Pro. Regenerate ONE resume section for a job application.

SECTION TYPE: {section_type}

NON-NEGOTIABLE TRUTH RULES
- SOURCE RESUME is the only factual source of truth.
- Never invent or assume employers, titles, dates, locations, education, certifications, software, skills, responsibilities, projects, achievements, metrics, or years of experience.
- The job description is for emphasis only. Never copy an unsupported requirement into the candidate's experience.
- Preserve all facts already present in CURRENT SECTION TEXT.
- Do not add facts from other resume sections unless they are clearly present in SOURCE RESUME and naturally belong in this section.

REWRITE RULES
- {rules}
- {extra}
- Do not use markdown, labels, quotation marks, or commentary inside regenerated_text.

Return JSON only with exactly these keys:
regenerated_text (string)
reason (one short sentence explaining what improved)

SOURCE RESUME:
{source_resume}

CURRENT OPTIMIZED RESUME:
{optimized_resume}

TARGET JOB DESCRIPTION:
{job}

CURRENT SECTION TEXT:
{current_text}
"""


def _replace_once(resume: str, old: str, new: str) -> str:
    if old in resume:
        return resume.replace(old, new, 1)
    old_norm = " ".join(old.split())
    for line in resume.splitlines():
        plain = re.sub(r"^[•●▪◦*\-]\s*", "", line.strip())
        if " ".join(plain.split()) == old_norm:
            return resume.replace(line, line.replace(plain, new, 1), 1)
    return resume


def regenerate_section(source_resume: str, optimized_resume: str, job: str, section_type: str, current_text: str):
    section_type = (section_type or "").strip().lower()
    current_text = (current_text or "").strip()
    if section_type not in ALLOWED_SECTIONS:
        raise ValueError("Section type must be summary or bullet.")
    if not current_text:
        raise ValueError("Current section text is required.")
    if len(current_text) > MAX_SECTION_CHARS:
        raise ValueError("The selected section is too long to regenerate.")

    key = (os.getenv("GEMINI_API") or os.getenv("GEMINI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("The AI section rewriter is not configured on the server.")
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"

    regenerated, reason = _call_gemini(key, model, _prompt(section_type, source_resume, optimized_resume, job, current_text))
    ratio = _change_ratio(current_text, regenerated)
    if ratio < 3:
        regenerated, reason = _call_gemini(key, model, _prompt(section_type, source_resume, optimized_resume, job, current_text, True))
        ratio = _change_ratio(current_text, regenerated)
    if ratio < 3:
        raise RuntimeError("The AI could not create a meaningfully different truthful alternative. Try again or edit this section manually.")

    updated_resume = _replace_once(optimized_resume, current_text, regenerated)
    if updated_resume == optimized_resume:
        raise RuntimeError("The regenerated section could not be safely applied to the optimized resume. Please optimize the resume again and retry.")

    return {
        "section_type": section_type,
        "original_text": current_text,
        "regenerated_text": regenerated,
        "updated_resume": updated_resume,
        "reason": reason,
        "change_ratio": ratio,
        "mode": "ai",
        "provider": "gemini",
        "model": model,
        "integrity_note": "This alternative was generated from facts already present in your resume. Review it before using or exporting the resume.",
    }
