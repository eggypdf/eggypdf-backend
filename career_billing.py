"""Career Pro billing helpers backed by Supabase.

This module owns credit-wallet reads, atomic AI credit charging/refunds and
creator-code redemption. Browser clients never receive the Supabase service key.
"""
from __future__ import annotations

import os
from typing import Any

import requests


class InsufficientCredits(RuntimeError):
    pass


def _cfg() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    service = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not service:
        raise RuntimeError("Career Pro billing database is not configured yet.")
    return url, service


def _headers(prefer: str | None = None) -> dict[str, str]:
    _, service = _cfg()
    h = {
        "apikey": service,
        "Authorization": f"Bearer {service}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h


def _message(resp: requests.Response, fallback: str) -> str:
    try:
        body = resp.json()
        return str(
            body.get("message")
            or body.get("msg")
            or body.get("error_description")
            or body.get("error")
            or fallback
        )
    except Exception:
        return fallback


def _request(method: str, path: str, **kwargs) -> requests.Response:
    url, _ = _cfg()
    try:
        return requests.request(
            method,
            f"{url}{path}",
            headers=_headers(kwargs.pop("prefer", None)),
            timeout=15,
            **kwargs,
        )
    except requests.RequestException as exc:
        raise RuntimeError("Career Pro billing database is temporarily unavailable.") from exc


def _rpc(name: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    r = _request("POST", f"/rest/v1/rpc/{name}", json=payload)
    if not r.ok:
        msg = _message(r, "Career Pro billing operation failed.")
        if "not enough career pro credits" in msg.lower():
            raise InsufficientCredits("You do not have enough Career Pro credits for this action.")
        raise RuntimeError(msg)
    data = r.json()
    return data if isinstance(data, list) else [data]


def wallet(user_id: str, *, refresh: bool = True) -> dict[str, Any]:
    if refresh:
        rows = _rpc("refresh_career_credit_cycle", {"p_user": user_id})
        if rows:
            return rows[0]
    r = _request(
        "GET",
        "/rest/v1/career_credit_wallets",
        params={
            "select": "balance,monthly_allowance,cycle_start,cycle_end,updated_at",
            "user_id": f"eq.{user_id}",
            "limit": "1",
        },
    )
    if not r.ok:
        raise RuntimeError(_message(r, "Could not read Career Pro credits."))
    rows = r.json() or []
    return rows[0] if rows else {
        "balance": 0,
        "monthly_allowance": 0,
        "cycle_start": None,
        "cycle_end": None,
    }


def consume(user_id: str, amount: int, action: str, request_key: str) -> dict[str, Any]:
    rows = _rpc(
        "consume_career_credits",
        {
            "p_user": user_id,
            "p_amount": int(amount),
            "p_action": action,
            "p_request_key": request_key,
        },
    )
    return rows[0] if rows else {"balance": None, "charged": amount}


def refund(user_id: str, request_key: str) -> dict[str, Any]:
    rows = _rpc(
        "refund_career_credits",
        {"p_user": user_id, "p_request_key": request_key},
    )
    return rows[0] if rows else {"balance": None, "refunded": 0}


def redeem_creator_code(user_id: str, code: str) -> dict[str, Any]:
    code = (code or "").strip()
    if not code:
        raise ValueError("Enter a creator code.")
    if len(code) > 80:
        raise ValueError("Creator code is too long.")
    rows = _rpc("redeem_creator_code", {"p_user": user_id, "p_code": code})
    result = rows[0] if rows else {"success": False, "message": "Could not redeem creator code."}
    return result


def recent_events(user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 100))
    r = _request(
        "GET",
        "/rest/v1/career_credit_events",
        params={
            "select": "event_type,action,amount,balance_after,created_at",
            "user_id": f"eq.{user_id}",
            "order": "created_at.desc",
            "limit": str(limit),
        },
    )
    if not r.ok:
        raise RuntimeError(_message(r, "Could not read Career Pro credit history."))
    return r.json() or []
