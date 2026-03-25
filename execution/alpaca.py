"""
execution/alpaca.py

Alpaca Markets broker connector for stocks and ETFs.
Implements BrokerBase — drop-in replacement if you switch stock brokers.

API docs: https://docs.alpaca.markets/reference/

Setup (.env):
    ALPACA_API_KEY=your_api_key
    ALPACA_SECRET_KEY=your_secret_key
    PAPER_TRADING=true   # true = paper.alpaca.markets | false = api.alpaca.markets

Install:
    pip install alpaca-py

Supported instruments: US stocks, ETFs (SPY, QQQ, AAPL, etc.)
NOT for futures — use tradovate.py for MES/MGC/SIL.

Bracket order implementation:
    Alpaca supports native bracket orders via the orders API.
    A bracket order = market entry + take-profit limit + stop-loss stop.
    All three legs are atomic — if one fills, the others auto-cancel.
"""

import logging
from typing import Optional

from config import settings
from execution.base import BrokerBase

logger = logging.getLogger(__name__)

# ── Lazy import — only required if Alpaca is actually used ─────────────────────
try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import (
        MarketOrderRequest,
        TakeProfitRequest,
        StopLossRequest,
    )
    from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
    _ALPACA_AVAILABLE = True
except ImportError:
    _ALPACA_AVAILABLE = False
    logger.warning(
        "alpaca-py not installed. Run: pip install alpaca-py\n"
        "Alpaca broker will be unavailable until installed."
    )


class AlpacaBroker(BrokerBase):
    """
    Alpaca Markets connector for US stocks and ETFs.

    Paper trading: https://paper-api.alpaca.markets
    Live trading:  https://api.alpaca.markets

    Credentials are read from settings / .env:
        ALPACA_API_KEY
        ALPACA_SECRET_KEY
        PAPER_TRADING (true/false)
    """

    def __init__(self):
        self._client: Optional["TradingClient"] = None
        self._paper = settings.PAPER_TRADING

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "alpaca"

    @property
    def paper(self) -> bool:
        return self._paper

    # ── Connection ────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """
        Authenticate with Alpaca. Creates a TradingClient session.
        Safe to call multiple times — reconnects if not already connected.
        """
        if not _ALPACA_AVAILABLE:
            raise RuntimeError("alpaca-py not installed. Run: pip install alpaca-py")

        if self._client is not None and self.is_connected():
            return

        api_key    = getattr(settings, "ALPACA_API_KEY", "")
        secret_key = getattr(settings, "ALPACA_SECRET_KEY", "")

        if not api_key or not secret_key:
            raise RuntimeError(
                "Alpaca credentials not set. Add ALPACA_API_KEY and "
                "ALPACA_SECRET_KEY to your .env file."
            )

        self._client = TradingClient(
            api_key=api_key,
            secret_key=secret_key,
            paper=self._paper,
        )

        # Verify connection by fetching account
        acct = self._client.get_account()
        logger.info(
            f"Alpaca connected | account={acct.id} | "
            f"equity=${float(acct.equity):,.2f} | "
            f"{'PAPER' if self._paper else 'LIVE'}"
        )

    def is_connected(self) -> bool:
        if self._client is None:
            return False
        try:
            self._client.get_account()
            return True
        except Exception:
            return False

    def _ensure_connected(self):
        if not self.is_connected():
            self.connect()

    # ── Account ───────────────────────────────────────────────────────────────

    def get_account_equity(self) -> float:
        """Return portfolio equity (cash + long market value - short market value)."""
        self._ensure_connected()
        acct = self._client.get_account()
        return float(acct.equity)

    def get_buying_power(self) -> float:
        """
        Return non-marginable buying power for new positions.
        For a cash account this equals settled cash.
        For a margin account this includes 2:1 leverage on settled cash.
        """
        self._ensure_connected()
        acct = self._client.get_account()
        return float(acct.buying_power)

    # ── Positions ─────────────────────────────────────────────────────────────

    def get_position(self, symbol: str) -> int:
        """Return net position for symbol (positive = long, negative = short, 0 = flat)."""
        self._ensure_connected()
        try:
            pos = self._client.get_open_position(symbol.upper())
            return int(float(pos.qty))
        except Exception:
            # Alpaca raises an exception if no position exists
            return 0

    def get_all_positions(self) -> dict[str, int]:
        """Return all open positions as {symbol: net_qty}."""
        self._ensure_connected()
        positions = self._client.get_all_positions()
        return {
            pos.symbol: int(float(pos.qty))
            for pos in positions
        }

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
        Place a native Alpaca bracket order.

        Alpaca's bracket order class submits three legs atomically:
            1. Market order (entry)
            2. Limit order at tp_price (take profit)
            3. Stop order at sl_price (stop loss)

        Args:
            symbol    : Ticker symbol (e.g. 'SPY', 'AAPL')
            qty       : Number of shares
            sl_price  : Stop loss price
            tp_price  : Take profit price
            direction : 1 = long (Buy), -1 = short (Sell short)

        Returns standard result dict.
        """
        self._ensure_connected()

        side = OrderSide.BUY if direction == 1 else OrderSide.SELL

        request = MarketOrderRequest(
            symbol        = symbol.upper(),
            qty           = qty,
            side          = side,
            time_in_force = TimeInForce.GTC,
            order_class   = OrderClass.BRACKET,
            take_profit   = TakeProfitRequest(limit_price=round(tp_price, 2)),
            stop_loss     = StopLossRequest(stop_price=round(sl_price, 2)),
        )

        logger.info(
            f"Alpaca bracket | {symbol} x{qty} {'LONG' if direction==1 else 'SHORT'} | "
            f"SL={sl_price:.2f}  TP={tp_price:.2f}"
        )

        order = self._client.submit_order(request)

        result = {
            "order_id":  str(order.id),
            "symbol":    symbol.upper(),
            "qty":       qty,
            "direction": direction,
            "sl":        sl_price,
            "tp":        tp_price,
            "status":    str(order.status),
            "broker":    self.name,
        }

        logger.info(f"Alpaca order submitted: {result}")
        return result

    def cancel_all_orders(self, symbol: str) -> int:
        """Cancel all working orders for symbol. Returns count cancelled."""
        self._ensure_connected()
        cancel_statuses = self._client.cancel_orders_for_symbol(symbol.upper())
        cancelled = len(cancel_statuses) if cancel_statuses else 0
        if cancelled:
            logger.warning(f"Alpaca: cancelled {cancelled} orders for {symbol}")
        return cancelled

    def close_position(self, symbol: str) -> dict:
        """
        Flatten any open position in symbol at market immediately.
        Used for emergency exits and end-of-day flattening.
        """
        self._ensure_connected()

        current_qty = self.get_position(symbol)
        if current_qty == 0:
            logger.info(f"Alpaca close_position: no open position in {symbol}")
            return {"symbol": symbol, "qty": 0, "status": "no_position"}

        try:
            result = self._client.close_position(symbol.upper())
            logger.warning(f"Alpaca: closed {symbol} position (was {current_qty:+d})")
            return {
                "order_id":  str(result.id),
                "symbol":    symbol.upper(),
                "qty":       abs(current_qty),
                "direction": -1 if current_qty > 0 else 1,
                "status":    str(result.status),
                "broker":    self.name,
            }
        except Exception as e:
            logger.error(f"Alpaca close_position failed for {symbol}: {e}")
            raise RuntimeError(f"Failed to close {symbol} position: {e}") from e

    # ── Market Data ───────────────────────────────────────────────────────────

    def get_last_price(self, symbol: str) -> float | None:
        """Return last trade price for symbol from Alpaca's data feed."""
        self._ensure_connected()
        try:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.requests import StockLatestTradeRequest

            data_client = StockHistoricalDataClient(
                api_key    = getattr(settings, "ALPACA_API_KEY", ""),
                secret_key = getattr(settings, "ALPACA_SECRET_KEY", ""),
            )
            req   = StockLatestTradeRequest(symbol_or_symbols=symbol.upper())
            trade = data_client.get_stock_latest_trade(req)
            return float(trade[symbol.upper()].price)
        except Exception:
            return None
