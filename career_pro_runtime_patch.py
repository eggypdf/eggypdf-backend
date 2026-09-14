"""Attach Career Pro account/credit guards after Flask registers blueprints."""
from __future__ import annotations

from career_pro_system import CREDIT_COSTS, _credit_wrapper, _enriched_me


def install(app) -> None:
    app.view_functions["account.me"] = _enriched_me

    wrapped = {
        "career.pro_optimize": ("resume_optimizer", CREDIT_COSTS["resume_optimizer"]),
        "career.tailor": ("job_tailoring", CREDIT_COSTS["job_tailoring"]),
        "career.letter": ("cover_letter", CREDIT_COSTS["cover_letter"]),
        "career.pro_regenerate_section": ("section_regeneration", CREDIT_COSTS["section_regeneration"]),
        "career.pro_pdf_summary": ("pdf_summarizer", CREDIT_COSTS["pdf_summarizer"]),
    }
    for endpoint, (action, amount) in wrapped.items():
        original = app.view_functions.get(endpoint)
        if original and not getattr(original, "_eggy_credit_wrapped", False):
            replacement = _credit_wrapper(original, action, amount)
            replacement._eggy_credit_wrapped = True
            app.view_functions[endpoint] = replacement
