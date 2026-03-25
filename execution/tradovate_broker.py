"""
execution/tradovate_broker.py

TradovateBroker — BrokerBase implementation for Tradovate futures.

Wraps the functional tradovate.py module (REST API client) into the
BrokerBase interface so the ExecutionRouter can use it uniformly
alongside AlpacaBroker without any strategy code knowing which broker
handled the trade.

This is the preferred import path. execution/router.py tries this first
and falls back to _TradovateLegacyAdapter only if this file is missing.
"""

from __future__ import annotations

import logging

from config import settings
from execution.base import BrokerBase

logger = logging.getLogger(__name__)


class TradovateBroker(BrokerBase):
    """
    Tradovate futures broker connector implementing BrokerBase.

    Delegates all API calls to execution.tradovate (the REST client module).
    Supports MES, ES, MGC, GC, SIL, SI, MCL, CL, and any other futures
    instruments tradable on Tradovate.

    Paper trading:
        Set PAPER_TRADING=true in .env → uses Tradovate DEMO environment.
        Paper account behaves identically to live (same API, same fills).
    """

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "tradovate"

    @property
    def paper(self) -> bool:
        return settings.PAPER_TRADING

    # ── Connection ────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Authenticate with Tradovate and cache the access token."""
        from execution import tradovate
        tradovate.authenticate()

    def is_connected(self) -> bool:
        """Return True if a valid (non-expired) access token exists."""
        from execution import tradovate
        try:
            tradovate._get_token()
            return True
        except Exception:
            return False

    # ── Account ───────────────────────────────────────────────────────────────

    def get_account_equity(self) -> float:
        """Return net liquidation value: cash + open PnL."""
        from execution import tradovate
        return tradovate.get_account_equity()

    def get_buying_power(self) -> float:
        """
        Return available buying power.
        Tradovate doesn't expose this directly via REST — return equity as proxy.
        Futures margin is ~5–10% of notional; risk manager gates trade size separately.
        """
        return self.get_account_equity()

    # ── Positions ─────────────────────────────────────────────────────────────

    def get_position(self, symbol: str) -> int:
        """Return net position for symbol (+long, -short, 0 flat)."""
        from execution import tradovate
        symbol_upper = symbol.upper()
        if "MES" in symbol_upper:
            return tradovate.get_open_mes_position()
        # Generic path: scan all positions
        try:
            positions = tradovate._get("/position/list")
            for pos in positions:
                contract = pos.get("contract", {})
                name = contract.get("name", "") if isinstance(contract, dict) else ""
                # Match by root symbol (strip expiry: MESM5 → MES)
                root = "".join(c for c in name if c.isalpha())
                target_root = "".join(c for c in symbol_upper if c.isalpha())
                if root == target_root:
                    return int(pos.get("netPos", 0))
        except Exception as e:
            logger.warning(f"get_position({symbol}) failed: {e}")
        return 0

    def get_all_positions(self) -> dict[str, int]:
        """Return all non-zero positions as {root_symbol: net_qty}."""
        from execution import tradovate
        try:
            positions = tradovate._get("/position/list")
            result: dict[str, int] = {}
            for pos in positions:
                contract = pos.get("contract", {})
                name = contract.get("name", "") if isinstance(contract, dict) else ""
                qty  = int(pos.get("netPos", 0))
                if name and qty != 0:
                    root = "".join(c for c in name if c.isalpha())
                    result[root] = qty
            return result
        except Exception as e:
            logger.warning(f"get_all_positions failed: {e}")
            return {}

    # ── Orders ────────────────────────────────────────────────────────────────

    def place_bracket_order(
        self,
        symbol:    str,
        qty:       int,
        sl_price:  float,
        tp_price:  float,
        direction: int = 1,
    ) -> dict:
        """
        Place a bracket order on Tradovate.

        Currently routes all orders through MES contract lookup.
        Extend _get_contract_id() in tradovate.py to support other symbols
        (MGC, SIL, etc.) when those strategies go live.

        Returns:
            dict with order_id, symbol, qty, direction, sl, tp, status, broker
        """
        from execution import tradovate
        result = tradovate.place_bracket_order(
            contracts=qty,
            sl_price=sl_price,
            tp_price=tp_price,
            direction=direction,
        )
        # Normalise to the standard broker response format
        return {
            "order_id":  str(result.get("orderId", result.get("orderStrategyId", "unknown"))),
            "symbol":    symbol.upper(),
            "qty":       qty,
            "direction": direction,
            "sl":        sl_price,
            "tp":        tp_price,
            "status":    "submitted",
            "broker":    self.name,
            "paper":     self.paper,
            "raw":       result,
        }

    def cancel_all_orders(self, symbol: str) -> int:
        """Cancel all working orders for symbol. Returns 0 (count not available from API)."""
        from execution import tradovate
        tradovate.cancel_all_mes_orders()
        return 0

    def close_position(self, symbol: str) -> dict:
        """
        Emergency flatten: cancel all orders then send an opposing market order.

        The bracket order is used as a market close by setting SL far below
        and TP far above — neither trigger will be hit before the market fill.
        """
        self.cancel_all_orders(symbol)
        qty = abs(self.get_position(symbol))
        if qty == 0:
            return {"symbol": symbol, "qty": 0, "status": "no_position", "broker": self.name}
        current_pos = self.get_position(symbol)
        direction   = -1 if current_pos > 0 else 1
        return self.place_bracket_order(
            symbol=symbol, qty=qty,
            sl_price=0.01, tp_price=999_999.0,
            direction=direction,
        )

    # ── Market Data ───────────────────────────────────────────────────────────

    def get_last_price(self, symbol: str) -> float | None:
        """
        Fetch last traded price from Tradovate market data endpoint.
        Returns None on failure (router falls back to yfinance).
        """
        from execution import tradovate
        try:
            data = tradovate._get("/md/getChart", params={
                "symbol": symbol.upper(),
                "chartDescription": {
                    "underlyingType": "Contract",
                    "elementSize": 1,
                    "elementSizeUnit": "Minute",
                    "withHistogram": False,
                },
                "timeRange": {"asMuchAsElements": 1},
            })
            bars = data.get("bars", [])
            if bars:
                return float(bars[-1].get("close", 0)) or None
        except Exception as e:
            logger.debug(f"get_last_price({symbol}) via Tradovate failed: {e}")
        return None
