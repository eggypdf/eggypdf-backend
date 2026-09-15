"""Dodo Standard Webhooks signature verification patch.

Dodo/Standard Webhooks sends webhook-signature as space-delimited `v1,<base64>`
values. Keep verification in one small auditable function and install it before
requests are served.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

from flask import request

import career_pro_system


def verify_dodo_webhook(raw_body: bytes) -> str:
    secret = (
        os.getenv("DODO_PAYMENTS_WEBHOOK_SECRET")
        or os.getenv("DODO_PAYMENTS_WEBHOOK_KEY")
        or ""
    ).strip()
    if not secret:
        raise RuntimeError("Dodo webhook signing secret is not configured.")

    webhook_id = (request.headers.get("webhook-id") or "").strip()
    timestamp = (request.headers.get("webhook-timestamp") or "").strip()
    signature_header = (request.headers.get("webhook-signature") or "").strip()
    if not webhook_id or not timestamp or not signature_header:
        raise PermissionError("Missing webhook signature headers.")

    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise PermissionError("Invalid webhook timestamp.") from exc
    if abs(int(time.time()) - ts) > 300:
        raise PermissionError("Webhook timestamp is outside the allowed replay window.")

    encoded = secret[6:] if secret.startswith("whsec_") else secret
    try:
        key = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise RuntimeError("Dodo webhook signing secret is invalid.") from exc

    signed = webhook_id.encode() + b"." + timestamp.encode() + b"." + raw_body
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()

    supplied = []
    for token in signature_header.split():
        if token.startswith("v1,"):
            supplied.append(token[3:])
        elif token.startswith("v1="):
            supplied.append(token[3:])

    if not supplied or not any(hmac.compare_digest(expected, value) for value in supplied):
        raise PermissionError("Invalid webhook signature.")
    return webhook_id


def install() -> None:
    career_pro_system._verify_standard_webhook = verify_dodo_webhook
