"""
execution/router.py

Central execution router. Routes every order to the correct broker
based on the instrument type, and provides a unified view of the
full portfolio across ALL brokers.

Architecture:
    strategy signal
        ↓
    router.place_bracket_order(symbol, ...)
        ↓
    looks up INSTRUMENT_BROKER_MAP
        ↓
    delegates to tradovate.py  (futures)
         or  alpaca.py         (stocks / ETFs)
         or  ibkr.py           (if added later)

Swapping a broker = change ONE entry in INSTRUMENT_BROKER_MAP.
No strategy code changes required.

Portfolio view:
    router.get_portfolio()  →  unified positions + equity across ALL brokers
    router.get_total_equity()  →  sum of all broker account equities
    router.get_portfolio_heat()  →  total dollar risk at stop across all open trades
"""

import logging
from dataclasses import dataclass, field

from config import settings
from execution.base import BrokerBase

logger = logging.getLogger(__name__)


# ─── Instrument → Broker Mapping ──────────────────────────────────────────────
# Change the broker name here to reroute any instrument. No other code changes needed.
# Broker names must match keys in BROKER_REGISTRY below.

INSTRUMENT_BROKER_MAP: dict[str, str] = {
    # ── Futures (Tradovate) ──────────────────────────────────────────────────
    "MES":  "tradovate",
    "ES":   "tradovate",
    "MNQ":  "tradovate",
    "NQ":   "tradovate",
    "MYM":  "tradovate",
    "MGC":  "tradovate",
    "GC":   "tradovate",
    "SIL":  "tradovate",
    "SI":   "tradovate",
    "MCL":  "tradovate",
    "CL":   "tradovate",
    # ── Stocks / ETFs (Alpaca) ───────────────────────────────────────────────
    "SPY":  "alpaca",
    "QQQ":  "alpaca",
    "IWM":  "alpaca",
    "GLD":  "alpaca",
    "SLV":  "alpaca",
    "TLT":  "alpaca",
    "USO":  "alpaca",
    "AAPL": "alpaca",
    "MSFT": "alpaca",
    "TSLA": "alpaca",
    "NVDA": "alpaca",
    "AMZN": "alpaca",
    "GOOGL":"alpaca",
    "META": "alpaca",
}

# ── Asset class classifier (for position sizing and risk logic) ───────────────
FUTURES_SYMBOLS  = {k for k, v in INSTRUMENT_BROKER_MAP.items() if v == "tradovate"}
STOCK_SYMBOLS    = {k for k, v in INSTRUMENT_BROKER_MAP.items() if v == "alpaca"}


# ─── Broker Registry ──────────────────────────────────────────────────────────
# Lazy-loaded: brokers are only instantiated when first needed.
# Add new broker implementations here.

def _build_broker_registry() -> dict[str, BrokerBase]:
    """Build the registry of available broker connectors."""
    registry: dict[str, BrokerBase] = {}

    # Tradovate — always available (futures)
    try:
        from execution.tradovate_broker import TradovateBroker
        registry["tradovate"] = TradovateBroker()
    except ImportError:
        # Fall back to the functional tradovate.py API (not yet wrapped in BrokerBase)
        registry["tradovate"] = _TradovateLegacyAdapter()
        logger.info("Using tradovate legacy adapter")

    # Alpaca — stocks/ETFs
    try:
        from execution.alpaca import AlpacaBroker
        registry["alpaca"] = AlpacaBroker()
    except Exception as e:
        logger.warning(f"Alpaca broker unavailable: {e}")

    return registry


# ─── Tradovate Legacy Adapter ─────────────────────────────────────────────────
# Wraps the existing functional tradovate.py API into the BrokerBase interface
# until tradovate.py is refactored into a class.

class _TradovateLegacyAdapter(BrokerBase):
    """
    Adapter that wraps the existing tradovate.py module functions
    into the BrokerBase interface. This allows the router to use
    tradovate.py as-is while the rest of the system uses the clean interface.
    """

    @property
    def name(self) -> str:
        return "tradovate"

    @property
    def paper(self) -> bool:
        return settings.PAPER_TRADING

    def connect(self) -> None:
        from execution import tradovate
        tradovate.authenticate()

    def is_connected(self) -> bool:
        from execution import tradovate
        try:
            tradovate._get_token()
            return True
        except Exception:
            return False

    def get_account_equity(self) -> float:
        from execution import tradovate
        return tradovate.get_account_equity()

    def get_buying_power(self) -> float:
        # Tradovate doesn't expose buying power directly — return equity as proxy
        return self.get_account_equity()

    def get_position(self, symbol: str) -> int:
        from execution import tradovate
        if "MES" in symbol.upper():
            return tradovate.get_open_mes_position()
        # For other futures, return 0 until extended
        return 0

    def get_all_positions(self) -> dict[str, int]:
        from execution import tradovate
        try:
            positions = tradovate._get("/position/list")
            result = {}
            for pos in positions:
                contract = pos.get("contract", {})
                name = contract.get("name", "") if isinstance(contract, dict) else ""
                qty  = int(pos.get("netPos", 0))
                if name and qty != 0:
                    # Strip expiry suffix: MESM5 → MES
                    root = "".join(c for c in name if c.isalpha())
                    result[root] = qty
            return result
        except Exception as e:
            logger.warning(f"Tradovate get_all_positions failed: {e}")
            return {}

    def place_bracket_order(
        self,
        symbol:    str,
        qty:       int,
        sl_price:  float,
        tp_price:  float,
        direction: int = 1,
    ) -> dict:
        from execution import tradovate
        result = tradovate.place_bracket_order(
            contracts=qty,
            sl_price=sl_price,
            tp_price=tp_price,
            direction=direction,
        )
        return {
            "order_id":  str(result.get("orderId", "unknown")),
            "symbol":    symbol.upper(),
            "qty":       qty,
            "direction": direction,
            "sl":        sl_price,
            "tp":        tp_price,
            "status":    "submitted",
            "broker":    self.name,
            "raw":       result,
        }

    def cancel_all_orders(self, symbol: str) -> int:
        from execution import tradovate
        tradovate.cancel_all_mes_orders()
        return 0  # tradovate.py doesn't return a count

    def close_position(self, symbol: str) -> dict:
        # Emergency market flatten — Tradovate: cancel orders then send opposite market
        self.cancel_all_orders(symbol)
        qty = abs(self.get_position(symbol))
        if qty == 0:
            return {"symbol": symbol, "qty": 0, "status": "no_position"}
        direction = -1 if self.get_position(symbol) > 0 else 1
        return self.place_bracket_order(
            symbol=symbol, qty=qty,
            sl_price=0, tp_price=9999999,   # flat order — SL/TP won't trigger
            direction=direction,
        )


# ─── Portfolio State ───────────────────────────────────────────────────────────

@dataclass
class PortfolioState:
    """Unified view of the full portfolio across all brokers."""
    # Total equity across all brokers
    total_equity: float = 0.0

    # Per-broker equity breakdown
    equity_by_broker: dict[str, float] = field(default_factory=dict)

    # All open positions {symbol: qty} merged across all brokers
    positions: dict[str, int] = field(default_factory=dict)

    # Total dollar heat: sum of (risk_per_trade) for all open positions
    # Requires open_trades to be tracked externally (see risk/manager.py)
    portfolio_heat_pct: float = 0.0

    # Any broker connection errors
    errors: list[str] = field(default_factory=list)


# ─── Router ───────────────────────────────────────────────────────────────────

class ExecutionRouter:
    """
    Central execution router. All strategy code calls this — never calls
    broker connectors directly.

    Usage:
        router = ExecutionRouter()
        router.connect_all()

        # Place an order — router figures out which broker
        router.place_bracket_order("MES", qty=1, sl=5000.0, tp=5020.0, direction=1)
        router.place_bracket_order("SPY", qty=10, sl=498.0, tp=502.0, direction=1)

        # Unified portfolio view
        state = router.get_portfolio()
        print(state.total_equity)
        print(state.positions)
    """

    def __init__(self):
        self._brokers: dict[str, BrokerBase] = _build_broker_registry()
        logger.info(
            f"ExecutionRouter initialized | brokers: {list(self._brokers.keys())}"
        )

    # ── Connection ────────────────────────────────────────────────────────────

    def connect_all(self) -> None:
        """Connect all registered brokers. Logs and continues if one fails."""
        for name, broker in self._brokers.items():
            try:
                broker.connect()
                logger.info(f"Connected: {broker}")
            except Exception as e:
                logger.error(f"Failed to connect {name}: {e}")

    def connect(self, broker_name: str) -> None:
        """Connect a specific broker by name."""
        broker = self._get_broker_by_name(broker_name)
        broker.connect()

    # ── Routing ───────────────────────────────────────────────────────────────

    def get_broker_for(self, symbol: str) -> BrokerBase:
        """Return the broker responsible for the given symbol."""
        symbol = symbol.upper()
        # Strip futures expiry suffix (MESM5 → MES)
        root = "".join(c for c in symbol if c.isalpha())

        broker_name = INSTRUMENT_BROKER_MAP.get(root) or INSTRUMENT_BROKER_MAP.get(symbol)
        if broker_name is None:
            raise ValueError(
                f"No broker mapped for symbol '{symbol}'. "
                f"Add it to INSTRUMENT_BROKER_MAP in execution/router.py."
            )

        broker = self._brokers.get(broker_name)
        if broker is None:
            raise RuntimeError(
                f"Broker '{broker_name}' is mapped for '{symbol}' "
                f"but not available in the registry. "
                f"Check credentials and installation."
            )
        return broker

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
        Place a bracket order on the correct broker for symbol.
        This is the ONLY method strategy code should call to place orders.
        """
        broker = self.get_broker_for(symbol)
        logger.info(
            f"Router → {broker.name} | {symbol} x{qty} "
            f"{'LONG' if direction==1 else 'SHORT'} "
            f"SL={sl_price:.2f} TP={tp_price:.2f}"
        )
        return broker.place_bracket_order(
            symbol=symbol, qty=qty,
            sl_price=sl_price, tp_price=tp_price,
            direction=direction,
        )

    def cancel_all_orders(self, symbol: str) -> int:
        """Cancel all orders for symbol on its assigned broker."""
        return self.get_broker_for(symbol).cancel_all_orders(symbol)

    def close_position(self, symbol: str) -> dict:
        """Emergency flatten: close any open position in symbol at market."""
        return self.get_broker_for(symbol).close_position(symbol)

    def close_all_positions(self) -> list[dict]:
        """Emergency: flatten ALL positions across ALL brokers."""
        results = []
        for broker in self._brokers.values():
            try:
                positions = broker.get_all_positions()
                for symbol, qty in positions.items():
                    if qty != 0:
                        results.append(broker.close_position(symbol))
            except Exception as e:
                logger.error(f"close_all_positions failed on {broker.name}: {e}")
        return results

    # ── Portfolio View ────────────────────────────────────────────────────────

    def get_portfolio(self) -> PortfolioState:
        """
        Fetch unified portfolio state across ALL brokers.
        Aggregates equity, positions, and any errors.
        Called by risk/manager.py for total portfolio heat calculations.
        """
        state = PortfolioState()

        for name, broker in self._brokers.items():
            try:
                equity    = broker.get_account_equity()
                positions = broker.get_all_positions()

                state.equity_by_broker[name] = equity
                state.total_equity += equity
                state.positions.update(positions)

            except Exception as e:
                err = f"{name}: {e}"
                state.errors.append(err)
                logger.warning(f"Portfolio fetch error — {err}")

        return state

    def get_total_equity(self) -> float:
        """Return total equity across all brokers."""
        return self.get_portfolio().total_equity

    def get_position(self, symbol: str) -> int:
        """Return position for symbol on its assigned broker."""
        return self.get_broker_for(symbol).get_position(symbol)

    def is_flat(self, symbol: str) -> bool:
        """Return True if no open position in symbol."""
        return self.get_position(symbol) == 0

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_broker_by_name(self, name: str) -> BrokerBase:
        broker = self._brokers.get(name)
        if broker is None:
            raise ValueError(
                f"No broker named '{name}'. "
                f"Available: {list(self._brokers.keys())}"
            )
        return broker

    def status(self) -> dict:
        """Return connection and account status for all brokers."""
        result = {}
        for name, broker in self._brokers.items():
            try:
                result[name] = {
                    "connected": broker.is_connected(),
                    "paper":     broker.paper,
                    "equity":    broker.get_account_equity() if broker.is_connected() else None,
                }
            except Exception as e:
                result[name] = {"connected": False, "error": str(e)}
        return result


# ─── Module-level singleton ────────────────────────────────────────────────────
# Import this in scheduler.py and strategy modules.
# Calling router.connect_all() once at startup is enough.

router = ExecutionRouter()
