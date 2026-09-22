"""Career Pro billing helpers backed by Supabase.

This module owns credit-wallet reads, atomic AI credit charging/refunds and
creator-code redemption. Browser clients never receive the Supabase service key.
"""
from __future__ import annotations

import os
from calendar import monthrange
from datetime import datetime, timezone
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


def _next_month(value: datetime) -> datetime:
    year = value.year + (1 if value.month == 12 else 0)
    month = 1 if value.month == 12 else value.month + 1
    day = min(value.day, monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _read_wallet(user_id: str) -> dict[str, Any] | None:
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
    return rows[0] if rows else None


def _active_entitlement(user_id: str) -> dict[str, Any] | None:
    r = _request(
        "GET",
        "/rest/v1/career_entitlements",
        params={
            "select": "status,monthly_credits,access_ends_at",
            "user_id": f"eq.{user_id}",
            "limit": "1",
        },
    )
    if not r.ok:
        raise RuntimeError(_message(r, "Could not read Career Pro credit entitlement."))
    rows = r.json() or []
    if not rows:
        return None
    row = rows[0]
    if row.get("status") != "active":
        return None
    ends = _parse_dt(row.get("access_ends_at"))
    if ends and ends <= datetime.now(timezone.utc):
        return None
    return row


def _ensure_wallet_fallback(user_id: str) -> dict[str, Any]:
    """Repair/create a wallet without depending on the refresh RPC.

    The database RPC remains the preferred path because AI debits use it for
    atomicity. This fallback prevents a paid account from being stuck on a
    permanent 'Refreshing' state if the wallet row was never initialized.
    """
    existing = _read_wallet(user_id)
    entitlement = _active_entitlement(user_id)
    if not entitlement:
        if existing:
            return existing
        raise RuntimeError("Career Pro access is not active.")

    allowance = max(int(entitlement.get("monthly_credits") or 2000), 0)
    now = datetime.now(timezone.utc)

    if not existing:
        cycle_end = _next_month(now)
        payload = {
            "user_id": user_id,
            "balance": allowance,
            "monthly_allowance": allowance,
            "cycle_start": now.isoformat(),
            "cycle_end": cycle_end.isoformat(),
        }
        r = _request(
            "POST",
            "/rest/v1/career_credit_wallets",
            params={"on_conflict": "user_id"},
            json=payload,
            prefer="resolution=merge-duplicates,return=representation",
        )
        if not r.ok:
            raise RuntimeError(_message(r, "Could not initialize Career Pro credits."))
        rows = r.json() or []
        wallet_row = rows[0] if rows else payload
        # Best-effort ledger entry. A duplicate or ledger issue must not block
        # the visible wallet balance.
        try:
            _request(
                "POST",
                "/rest/v1/career_credit_events",
                json={
                    "user_id": user_id,
                    "event_type": "grant",
                    "action": "subscription_initialization",
                    "amount": allowance,
                    "balance_after": allowance,
                    "metadata": {"source": "wallet_self_heal"},
                },
                prefer="return=minimal",
            )
        except Exception:
            pass
        return wallet_row

    cycle_end = _parse_dt(existing.get("cycle_end"))
    if cycle_end and cycle_end <= now:
        new_end = _next_month(now)
        payload = {
            "balance": allowance,
            "monthly_allowance": allowance,
            "cycle_start": now.isoformat(),
            "cycle_end": new_end.isoformat(),
        }
        r = _request(
            "PATCH",
            "/rest/v1/career_credit_wallets",
            params={"user_id": f"eq.{user_id}"},
            json=payload,
            prefer="return=representation",
        )
        if not r.ok:
            raise RuntimeError(_message(r, "Could not refresh Career Pro credits."))
        rows = r.json() or []
        existing = rows[0] if rows else {**existing, **payload}
        try:
            _request(
                "POST",
                "/rest/v1/career_credit_events",
                json={
                    "user_id": user_id,
                    "event_type": "reset",
                    "action": "monthly_cycle",
                    "amount": allowance,
                    "balance_after": allowance,
                    "metadata": {"source": "wallet_self_heal"},
                },
                prefer="return=minimal",
            )
        except Exception:
            pass

    return existing


def wallet(user_id: str, *, refresh: bool = True) -> dict[str, Any]:
    rpc_error: RuntimeError | None = None
    if refresh:
        try:
            rows = _rpc("refresh_career_credit_cycle", {"p_user": user_id})
            if rows and rows[0]:
                return rows[0]
        except RuntimeError as exc:
            rpc_error = exc

    try:
        return _ensure_wallet_fallback(user_id) if refresh else (_read_wallet(user_id) or {
            "balance": 0,
            "monthly_allowance": 0,
            "cycle_start": None,
            "cycle_end": None,
        })
    except RuntimeError:
        if rpc_error:
            raise rpc_error
        raise


def consume(user_id: str, amount: int, action: str, request_key: str) -> dict[str, Any]:
    # Ensure old paid accounts have a wallet row before the atomic debit RPC.
    wallet(user_id, refresh=True)
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
