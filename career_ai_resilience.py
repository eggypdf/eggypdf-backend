"""Resilient Gemini request wrapper for Career Pro resume optimization."""
from __future__ import annotations

import json
import re

import requests


def _model_candidates(primary: str) -> list[str]:
    ordered = [
        primary,
        "gemini-3.8-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
    ]
    out: list[str] = []
    for model in ordered:
        model = (model or "").strip()
        if model and model not in out:
            out.append(model)
    return out


def _generation_config(model: str) -> dict:
    config = {
        "responseMimeType": "application/json",
        "maxOutputTokens": 8192,
    }
    # Gemini 3.x migration guidance recommends omitting legacy sampling fields.
    if model.startswith("gemini-2."):
        config["temperature"] = 0.25
    return config


def _patched_gemini_request(key: str, model: str, prompt: str):
    import career_v2

    transient_seen = False
    rate_limited = False
    invalid_output_seen = False

    for candidate_model in _model_candidates(model):
        try:
            response = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{candidate_model}:generateContent",
                params={"key": key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": _generation_config(candidate_model),
                },
                timeout=45,
            )
        except requests.RequestException:
            transient_seen = True
            continue

        if response.status_code in (401, 403):
            raise RuntimeError(
                "The AI resume optimizer is not authenticated correctly on the server."
            )

        if response.status_code == 429:
            rate_limited = True
            continue

        if response.status_code in (500, 502, 503, 504):
            transient_seen = True
            continue

        # A model may be unavailable to this project or no longer supported.
        # Move to the next current model rather than failing the whole request.
        if response.status_code in (400, 404):
            continue

        if not response.ok:
            continue

        try:
            payload = response.json()
            candidates = payload.get("candidates") or []
            if not candidates:
                invalid_output_seen = True
                continue
            parts = (candidates[0].get("content") or {}).get("parts") or []
            if not parts or not parts[0].get("text"):
                invalid_output_seen = True
                continue
            text = parts[0]["text"].strip()
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S)
            result = career_v2._required_output(json.loads(text))
            result["_model_used"] = candidate_model
            return result
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            invalid_output_seen = True
            continue

    if rate_limited:
        raise RuntimeError(
            "The AI resume optimizer is busy right now. Please try again in a minute."
        )
    if transient_seen:
        raise RuntimeError(
            "The AI resume optimizer is temporarily unavailable. Please try again shortly."
        )
    if invalid_output_seen:
        raise RuntimeError(
            "The AI resume optimizer returned an incomplete response. Please try again."
        )
    raise RuntimeError(
        "The AI resume optimizer could not reach an available AI model. Please try again shortly."
    )


def install() -> None:
    """Patch career_v2's Gemini helper once at process startup."""
    import career_v2

    if getattr(career_v2, "_eggy_resilient_optimizer_installed", False):
        return
    career_v2._gemini_request = _patched_gemini_request
    career_v2._eggy_resilient_optimizer_installed = True
