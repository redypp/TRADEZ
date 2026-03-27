"""
execution/base.py

Abstract broker interface. Every broker connector (Tradovate, Alpaca, IBKR, etc.)
must implement this interface. The router and risk manager only talk to this
interface — swapping a broker is a config change, not a code change.

To add a new broker:
    1. Create execution/mybroker.py
    2. Subclass BrokerBase and implement all abstract methods
    3. Add to BROKER_REGISTRY in execution/router.py
    4. Map your instruments in config/settings.py INSTRUMENT_BROKER_MAP
"""

from abc import ABC, abstractmethod


class BrokerBase(ABC):
    """
    Abstract interface every broker connector must implement.
    All price/size values are raw floats — no broker-specific types.
    """

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable broker name, e.g. 'tradovate', 'alpaca'."""
        ...

    @property
    @abstractmethod
    def paper(self) -> bool:
        """True if this connector is pointed at a paper/sim account."""
        ...

    # ── Connection ────────────────────────────────────────────────────────────

    @abstractmethod
    def connect(self) -> None:
        """Authenticate / establish session. Idempotent — safe to call multiple times."""
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if the session is active and authenticated."""
        ...

    # ── Account ───────────────────────────────────────────────────────────────

    @abstractmethod
    def get_account_equity(self) -> float:
        """
        Return current net liquidation value of the account in USD.
        For futures: cash + open PnL.
        For stocks: portfolio value + cash.
        """
        ...

    @abstractmethod
    def get_buying_power(self) -> float:
        """
        Return available buying power / margin in USD.
        Used by the risk manager to gate new entries.
        """
        ...

    # ── Positions ─────────────────────────────────────────────────────────────

    @abstractmethod
    def get_position(self, symbol: str) -> int:
        """
        Return current net position for symbol.
            Positive  = long
            Negative  = short
            0         = flat
        For fractional stocks (Alpaca), round to nearest int.
        """
        ...

    @abstractmethod
    def get_all_positions(self) -> dict[str, int]:
        """
        Return all open positions as {symbol: net_qty}.
        Used by the risk manager to compute total portfolio heat.
        """
        ...

    # ── Orders ────────────────────────────────────────────────────────────────

    @abstractmethod
    def place_bracket_order(
        self,
        symbol:    str,
        qty:       int,
        sl_price:  float,
        tp_price:  float,
        direction: int,        # 1 = long, -1 = short
    ) -> dict:
        """
        Place a bracket order: market entry + limit TP + stop SL.
        Returns a dict with at minimum:
            {
                "order_id":  str,
                "symbol":    str,
                "qty":       int,
                "direction": int,
                "sl":        float,
                "tp":        float,
                "status":    str,   # "submitted" | "filled" | "error"
            }
        Raises RuntimeError on hard failure.
        """
        ...

    @abstractmethod
    def cancel_all_orders(self, symbol: str) -> int:
        """
        Cancel all working orders for symbol.
        Returns count of orders cancelled.
        """
        ...

    @abstractmethod
    def close_position(self, symbol: str) -> dict:
        """
        Immediately flatten any open position in symbol at market.
        Returns same dict format as place_bracket_order.
        Used for emergency exits and end-of-day flattening.
        """
        ...

    # ── Market Data (optional — brokers that provide it) ─────────────────────

    def get_last_price(self, symbol: str) -> float | None:
        """
        Return last traded price for symbol if the broker provides it.
        Optional — return None if not supported (router falls back to yfinance).
        """
        return None

    def modify_stop(self, symbol: str, new_stop: float) -> bool:
        """
        Modify the stop-loss price of an existing open order for symbol.
        Used by the breakeven stop management system (BRT_BREAKEVEN_AT_1R).

        Returns True if the modification was accepted, False if not supported.

        Brokers that support stop modification should override this method.
        The default implementation logs a warning and returns False (graceful no-op).
        """
        import logging
        logging.getLogger(__name__).warning(
            f"modify_stop not implemented for {self.__class__.__name__} — "
            f"breakeven stop move skipped for {symbol} @ {new_stop:.2f}. "
            f"Override modify_stop() in the broker connector to enable this feature."
        )
        return False

    # ── Helpers ───────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        mode = "PAPER" if self.paper else "LIVE"
        connected = "connected" if self.is_connected() else "disconnected"
        return f"<{self.__class__.__name__} [{self.name}|{mode}|{connected}]>"
