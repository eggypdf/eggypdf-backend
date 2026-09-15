"""Install atomic Career Pro AI credit charging around paid AI endpoints."""
from __future__ import annotations

import os
import uuid
from functools import wraps

from flask import jsonify, request

from account_routes import current_account_user
from career_billing import InsufficientCredits, consume, refund

# V1 credit economics. Non-AI actions (ATS, extraction, exports, PDF tools) are
# intentionally absent and remain free/unmetered.
COSTS = {
    "career.pro_optimize": (100, "resume_optimizer"),
    "career.tailor": (100, "job_tailoring"),
    "career.letter": (50, "cover_letter"),
    "career.pro_regenerate_section": (20, "section_regeneration"),
}


def _enabled() -> bool:
    return os.getenv("CAREER_CREDITS_ENFORCED", "false").strip().lower() in {"1", "true", "yes", "on"}


def _request_key() -> str:
    supplied = (request.headers.get("X-Idempotency-Key") or "").strip()
    if supplied:
        return supplied[:120]
    # Existing clients remain compatible. New clients should send a stable key
    # per button click so a network retry cannot be charged twice.
    return uuid.uuid4().hex


def _pdf_summary_cost() -> int:
    upload = request.files.get("pdf") or request.files.get("file")
    if not upload:
        return 25
    stream = upload.stream
    try:
        pos = stream.tell()
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(pos)
    except Exception:
        size = int(request.content_length or 0)
    if size <= 2 * 1024 * 1024:
        return 25
    if size <= 5 * 1024 * 1024:
        return 50
    return 100


def _wrap(view, amount_getter, action: str):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not _enabled():
            return view(*args, **kwargs)
        try:
            user = current_account_user(required=True)
            amount = amount_getter() if callable(amount_getter) else int(amount_getter)
            key = _request_key()
            debit = consume(user["id"], amount, action, key)
        except PermissionError as exc:
            return jsonify({"success": False, "error": str(exc)}), 401
        except InsufficientCredits as exc:
            return jsonify({"success": False, "error": str(exc), "code": "insufficient_credits"}), 402
        except RuntimeError as exc:
            return jsonify({"success": False, "error": str(exc)}), 503

        try:
            response = view(*args, **kwargs)
            status = response[1] if isinstance(response, tuple) and len(response) > 1 else getattr(response, "status_code", 200)
            if int(status) >= 400:
                refund(user["id"], key)
                return response

            # Add the remaining balance to JSON responses without changing the
            # existing payload contract.
            target = response[0] if isinstance(response, tuple) else response
            if hasattr(target, "get_json"):
                payload = target.get_json(silent=True)
                if isinstance(payload, dict):
                    payload["credits"] = {
                        "charged": debit.get("charged", amount),
                        "balance": debit.get("balance"),
                    }
                    target.set_data(jsonify(payload).get_data())
                    target.mimetype = "application/json"
            return response
        except Exception:
            try:
                refund(user["id"], key)
            except Exception:
                pass
            raise

    return wrapped


def install(app) -> None:
    """Wrap registered Career Pro AI endpoints after blueprints are installed."""
    for endpoint, (amount, action) in COSTS.items():
        view = app.view_functions.get(endpoint)
        if view:
            app.view_functions[endpoint] = _wrap(view, amount, action)

    pdf_view = app.view_functions.get("career.pro_pdf_summary")
    if pdf_view:
        app.view_functions["career.pro_pdf_summary"] = _wrap(pdf_view, _pdf_summary_cost, "pdf_summarizer")
