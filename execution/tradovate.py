"""
execution/tradovate.py

Tradovate REST API client for MES futures.

Demo base URL : https://demo.tradovateapi.com/v1
Live base URL : https://live.tradovateapi.com/v1

Authentication:
    POST /auth/accesstokenrequest  →  returns access_token (valid 80 min)
    POST /auth/renewaccesstoken    →  renew before expiry

Setup (.env):
    TRADOVATE_USERNAME=your_username
    TRADOVATE_PASSWORD=your_password
    TRADOVATE_APP_ID=your_app_id          # from Tradovate API settings
    TRADOVATE_APP_VERSION=1.0
    TRADOVATE_DEVICE_ID=your_device_id    # any unique string
    TRADOVATE_CID=your_cid                # client id (from API settings)
    TRADOVATE_SEC=your_sec                # secret key  (from API settings)
    PAPER_TRADING=true                    # true = demo, false = live
"""

import logging
import time
from datetime import datetime, timedelta

import requests

from config import settings

logger = logging.getLogger(__name__)

# ─── Base URLs ────────────────────────────────────────────────────────────────

DEMO_URL = "https://demo.tradovateapi.com/v1"
LIVE_URL = "https://live.tradovateapi.com/v1"


def _base_url() -> str:
    return DEMO_URL if settings.PAPER_TRADING else LIVE_URL


# ─── Session state ────────────────────────────────────────────────────────────

_session = {
    "access_token":  None,
    "expires_at":    None,   # datetime
    "account_id":    None,
    "account_spec":  None,
}


# ─── Authentication ───────────────────────────────────────────────────────────

def authenticate() -> str:
    """
    Request a new access token from Tradovate.
    Stores it in _session and returns the token string.
    Reads credentials from settings / .env.
    """
    url  = f"{_base_url()}/auth/accesstokenrequest"
    body = {
        "name":       settings.TRADOVATE_USERNAME,
        "password":   settings.TRADOVATE_PASSWORD,
        "appId":      settings.TRADOVATE_APP_ID,
        "appVersion": settings.TRADOVATE_APP_VERSION,
        "deviceId":   settings.TRADOVATE_DEVICE_ID,
        "cid":        settings.TRADOVATE_CID,
        "sec":        settings.TRADOVATE_SEC,
    }

    resp = requests.post(url, json=body, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if "errorText" in data:
        raise RuntimeError(f"Tradovate auth failed: {data['errorText']}")

    token = data["accessToken"]
    _session["access_token"] = token
    _session["expires_at"]   = datetime.utcnow() + timedelta(minutes=80)

    # Cache account info
    _session["account_id"]   = data.get("userId")
    accounts = data.get("accounts", [])
    if accounts:
        _session["account_id"]  = accounts[0]["id"]
        _session["account_spec"] = accounts[0]["name"]

    logger.info(
        f"Tradovate authenticated | account={_session['account_spec']} "
        f"({'DEMO' if settings.PAPER_TRADING else 'LIVE'})"
    )
    return token


def _get_token() -> str:
    """Return a valid access token, refreshing if within 15 min of expiry."""
    if _session["access_token"] is None:
        return authenticate()

    remaining = (_session["expires_at"] - datetime.utcnow()).total_seconds()
    if remaining < 900:   # < 15 minutes left — renew
        logger.info("Renewing Tradovate access token")
        url  = f"{_base_url()}/auth/renewaccesstoken"
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {_session['access_token']}"},
            timeout=10,
        )
        if resp.ok:
            data = resp.json()
            _session["access_token"] = data.get("accessToken", _session["access_token"])
            _session["expires_at"]   = datetime.utcnow() + timedelta(minutes=80)
        else:
            # Renewal failed — get a fresh token
            return authenticate()

    return _session["access_token"]


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_token()}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
    }


def _get(path: str, params: dict = None) -> dict:
    url  = f"{_base_url()}{path}"
    resp = requests.get(url, headers=_headers(), params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, body: dict) -> dict:
    url  = f"{_base_url()}{path}"
    resp = requests.post(url, headers=_headers(), json=body, timeout=15)
    resp.raise_for_status()
    return resp.json()


# ─── Account ──────────────────────────────────────────────────────────────────

def get_account_equity() -> float:
    """Return current net liquidation value of the Tradovate account."""
    if _session["account_id"] is None:
        _get_token()  # triggers authenticate() which sets account_id

    data = _get(f"/cashBalance/getcashbalancesnapshot",
                params={"accountId": _session["account_id"]})

    # Response contains 'totalCashValue' or 'realizedPnL' + 'openPnL'
    cash       = data.get("totalCashValue", 0) or 0
    open_pnl   = data.get("openTradingPnL", 0) or 0
    return float(cash) + float(open_pnl)


# ─── Positions ────────────────────────────────────────────────────────────────

def get_open_mes_position() -> int:
    """
    Return current MES net position (positive = long, negative = short, 0 = flat).
    """
    positions = _get("/position/list")
    for pos in positions:
        contract = pos.get("contract", {})
        symbol   = contract.get("name", "") if isinstance(contract, dict) else ""
        if "MES" in symbol:
            net = int(pos.get("netPos", 0))
            logger.info(f"Open MES position: {net:+d}")
            return net
    return 0


def _get_mes_contract_id() -> int:
    """
    Find the front-month MES contract ID from Tradovate.
    Looks for the nearest-expiry active MES contract.
    """
    contracts = _get("/contract/suggest", params={"t": "MES", "l": 10})
    mes = [c for c in contracts if c.get("name", "").startswith("MES")]
    if not mes:
        raise RuntimeError("No MES contracts found on Tradovate.")
    # Sort by name (MESM5, MESU5, etc.) — alphabetical ≈ chronological
    mes.sort(key=lambda c: c["name"])
    contract = mes[0]
    logger.info(f"MES contract: {contract['name']} (id={contract['id']})")
    return contract["id"]


# ─── Orders ───────────────────────────────────────────────────────────────────

def place_bracket_order(
    contracts: int,
    sl_price:  float,
    tp_price:  float,
    direction: int = 1,    # 1 = long, -1 = short
) -> dict:
    """
    Place a bracket order on Tradovate for MES.

    Uses /orderStrategy/startorderstrategy which submits:
        Parent  — Market order (entry)
        Child 1 — Limit order  (take profit)
        Child 2 — Stop order   (stop loss)

    Returns the API response dict.
    """
    action      = "Buy"  if direction == 1 else "Sell"
    exit_action = "Sell" if direction == 1 else "Buy"

    contract_id = _get_mes_contract_id()
    account_id  = _session["account_id"]
    account_spec = _session["account_spec"]

    if account_id is None:
        raise RuntimeError("Not authenticated — call authenticate() first.")

    # Tradovate bracket via startorderstrategy
    body = {
        "accountId":           account_id,
        "accountSpec":         account_spec,
        "contractId":          contract_id,
        "orderStrategyTypeId": 2,          # 2 = bracket
        "action":              action,
        "params": {
            "entryVersion": {
                "orderQty":  contracts,
                "orderType": "Market",
            },
            "brackets": [
                {
                    "qty":       contracts,
                    "profitTarget": round(tp_price, 2),
                    "stopLoss":     round(sl_price, 2),
                    "trailingStop": False,
                }
            ],
        },
    }

    # params must be JSON string per Tradovate spec
    import json
    body["params"] = json.dumps(body["params"])

    logger.info(
        f"Placing bracket | MES x{contracts} {action} | "
        f"SL={sl_price:.2f}  TP={tp_price:.2f}"
    )

    result = _post("/orderStrategy/startorderstrategy", body)

    if result.get("failureReason"):
        raise RuntimeError(f"Tradovate order failed: {result['failureReason']}")

    logger.info(f"Bracket order placed: {result}")
    return result


def cancel_all_mes_orders() -> None:
    """Cancel all open MES orders."""
    orders = _get("/order/list")
    cancelled = 0
    for order in orders:
        contract = order.get("contract", {})
        symbol   = contract.get("name", "") if isinstance(contract, dict) else ""
        status   = order.get("ordStatus", "")
        if "MES" in symbol and status in ("Working", "PendingNew"):
            _post("/order/cancelorder", {"orderId": order["id"]})
            cancelled += 1
    if cancelled:
        logger.warning(f"Cancelled {cancelled} open MES orders")
