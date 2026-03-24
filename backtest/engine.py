import pandas as pd
import numpy as np
import logging
from config import settings

logger = logging.getLogger(__name__)


def run_backtest(df: pd.DataFrame, strategy: str, initial_capital: float = 3000.0) -> dict:
    """
    Simulate a strategy on historical data.

    Supports:
        'ORB'      — Opening Range Breakout (intraday, EOD exit)
        'DONCHIAN' — Donchian Channel Breakout (daily, trailing exit)
        'BRT'      — Break & Retest (hourly, fixed R:R exit)

    Returns:
        dict with trades DataFrame and performance data
    """
    if strategy == "ORB":
        return _run_orb(df, initial_capital)
    elif strategy == "DONCHIAN":
        return _run_donchian(df, initial_capital)
    elif strategy == "BRT":
        return _run_brt(df, initial_capital)
    else:
        raise ValueError(f"Unknown strategy: {strategy}")


def _run_orb(df: pd.DataFrame, initial_capital: float) -> dict:
    """ORB backtest — intraday, exits EOD or on SL/TP hit."""
    capital = initial_capital
    equity_curve = [capital]
    trades = []
    position = None

    for ts, row in df.iterrows():
        if position is not None:
            hit_sl = hit_tp = eod = False
            exit_price = None

            if position["direction"] == 1:
                if row["low"] <= position["stop_loss"]:
                    hit_sl = True
                    exit_price = position["stop_loss"]
                elif row["high"] >= position["take_profit"]:
                    hit_tp = True
                    exit_price = position["take_profit"]
                elif row.get("eod_exit", False):
                    eod = True
                    exit_price = row["close"]
            else:
                if row["high"] >= position["stop_loss"]:
                    hit_sl = True
                    exit_price = position["stop_loss"]
                elif row["low"] <= position["take_profit"]:
                    hit_tp = True
                    exit_price = position["take_profit"]
                elif row.get("eod_exit", False):
                    eod = True
                    exit_price = row["close"]

            if hit_sl or hit_tp or eod:
                pnl = (exit_price - position["entry_price"]) * position["direction"] * position["contracts"]
                capital += pnl
                equity_curve.append(capital)
                trades.append({
                    "entry_time": position["entry_time"],
                    "exit_time": ts,
                    "direction": "LONG" if position["direction"] == 1 else "SHORT",
                    "entry_price": position["entry_price"],
                    "exit_price": exit_price,
                    "contracts": position["contracts"],
                    "pnl": round(pnl, 2),
                    "result": "TP" if hit_tp else ("SL" if hit_sl else "EOD"),
                    "capital_after": round(capital, 2),
                })
                position = None

        if position is None and row["signal"] != 0 and pd.notna(row.get("stop_loss")):
            risk_amount = capital * settings.RISK_PER_TRADE
            risk_per_contract = abs(row["close"] - row["stop_loss"])
            if risk_per_contract > 0:
                contracts = max(1, int(risk_amount / risk_per_contract))
                position = {
                    "entry_time": ts,
                    "entry_price": row["close"],
                    "direction": int(row["signal"]),
                    "stop_loss": row["stop_loss"],
                    "take_profit": row["take_profit"],
                    "contracts": contracts,
                }

    return {"trades": pd.DataFrame(trades), "equity_curve": equity_curve,
            "initial_capital": initial_capital, "final_capital": round(capital, 2)}


def _run_brt(df: pd.DataFrame, initial_capital: float) -> dict:
    """
    Break & Retest backtest — hourly, exits on SL or fixed TP.

    Realistic cost model for MES (Micro E-mini S&P 500):
        Point value : $5.00 per point per contract
        Commission  : $0.85/side × 2 = $1.70 round trip (IBKR rate)
        Exchange fee: $0.35/side × 2 = $0.70 round trip (CME)
        NFA fee     : $0.02/side × 2 = $0.04 round trip
        Slippage    : 1 tick ($0.25) per side = $0.50 round trip (conservative)
        Total drag  : ~$2.94 per round trip per contract

    P&L formula:
        raw_pnl  = (exit - entry) × direction × contracts × POINT_VALUE
        net_pnl  = raw_pnl - (COST_PER_RT × contracts)
    """
    MES_POINT_VALUE  = settings.BRT_POINT_VALUE       # $5 per point for MES
    COST_PER_RT      = settings.BRT_COST_PER_RT        # total round-trip cost per contract

    capital = initial_capital
    equity_curve = [capital]
    trades = []
    position = None

    for ts, row in df.iterrows():
        # ── Manage open position ──────────────────────────────────────
        if position is not None:
            hit_sl = hit_tp = False
            exit_price = None

            if position["direction"] == 1:  # long
                if row["low"] <= position["stop_loss"]:
                    hit_sl = True
                    exit_price = position["stop_loss"]
                elif row["high"] >= position["take_profit"]:
                    hit_tp = True
                    exit_price = position["take_profit"]
            else:  # short
                if row["high"] >= position["stop_loss"]:
                    hit_sl = True
                    exit_price = position["stop_loss"]
                elif row["low"] <= position["take_profit"]:
                    hit_tp = True
                    exit_price = position["take_profit"]

            if hit_sl or hit_tp:
                contracts = position["contracts"]
                raw_pnl   = (exit_price - position["entry_price"]) * position["direction"] * contracts * MES_POINT_VALUE
                costs     = COST_PER_RT * contracts
                net_pnl   = raw_pnl - costs
                capital  += net_pnl
                equity_curve.append(capital)
                trades.append({
                    "entry_time":    position["entry_time"],
                    "exit_time":     ts,
                    "direction":     "LONG" if position["direction"] == 1 else "SHORT",
                    "entry_price":   position["entry_price"],
                    "exit_price":    exit_price,
                    "stop_loss":     position["stop_loss"],
                    "take_profit":   position["take_profit"],
                    "retest_level":  position.get("retest_level"),
                    "level_type":    position.get("level_type", ""),
                    "contracts":     contracts,
                    "raw_pnl":       round(raw_pnl, 2),
                    "costs":         round(costs, 2),
                    "pnl":           round(net_pnl, 2),
                    "result":        "TP" if hit_tp else "SL",
                    "capital_after": round(capital, 2),
                })
                position = None

        # ── Check for new entry ───────────────────────────────────────
        if (position is None
                and row["signal"] != 0
                and pd.notna(row.get("stop_loss"))
                and pd.notna(row.get("take_profit"))):

            risk_amount = capital * settings.RISK_PER_TRADE
            # Risk per contract in dollars (points × point value)
            risk_per_contract = abs(row["close"] - row["stop_loss"]) * MES_POINT_VALUE

            # Hard cap: skip if even 1 contract exceeds max allowed risk.
            # Handles wide-stop outliers that can't be sized down further.
            max_allowed = capital * settings.BRT_MAX_TRADE_RISK
            if risk_per_contract > max_allowed:
                continue
            if risk_per_contract > 0:
                contracts = max(1, int(risk_amount / risk_per_contract))
                position = {
                    "entry_time":   ts,
                    "entry_price":  row["close"],
                    "direction":    int(row["signal"]),
                    "stop_loss":    row["stop_loss"],
                    "take_profit":  row["take_profit"],
                    "retest_level": row.get("retest_level"),
                    "level_type":   row.get("level_type", ""),
                    "contracts":    contracts,
                }

    return {
        "trades":          pd.DataFrame(trades),
        "equity_curve":    equity_curve,
        "initial_capital": initial_capital,
        "final_capital":   round(capital, 2),
    }

def _run_donchian(df: pd.DataFrame, initial_capital: float) -> dict:
    """Donchian backtest — daily, exits on trailing channel or hard stop."""
    capital = initial_capital
    equity_curve = [capital]
    trades = []
    position = None

    for ts, row in df.iterrows():
        if position is not None:
            hit_sl = hit_trail = False
            exit_price = None

            if position["direction"] == 1:
                if row["low"] <= position["stop_loss"]:
                    hit_sl = True
                    exit_price = position["stop_loss"]
                elif row["close"] < row["dc_exit_low"]:
                    hit_trail = True
                    exit_price = row["close"]
            else:
                if row["high"] >= position["stop_loss"]:
                    hit_sl = True
                    exit_price = position["stop_loss"]
                elif row["close"] > row["dc_exit_high"]:
                    hit_trail = True
                    exit_price = row["close"]

            if hit_sl or hit_trail:
                pnl = (exit_price - position["entry_price"]) * position["direction"] * position["contracts"]
                capital += pnl
                equity_curve.append(capital)
                trades.append({
                    "entry_time": position["entry_time"],
                    "exit_time": ts,
                    "direction": "LONG" if position["direction"] == 1 else "SHORT",
                    "entry_price": position["entry_price"],
                    "exit_price": exit_price,
                    "contracts": position["contracts"],
                    "pnl": round(pnl, 2),
                    "result": "SL" if hit_sl else "TRAIL",
                    "capital_after": round(capital, 2),
                })
                position = None

        if position is None and row["signal"] != 0 and pd.notna(row.get("stop_loss")):
            risk_amount = capital * settings.RISK_PER_TRADE
            risk_per_contract = abs(row["close"] - row["stop_loss"])
            if risk_per_contract > 0:
                contracts = max(1, int(risk_amount / risk_per_contract))
                position = {
                    "entry_time": ts,
                    "entry_price": row["close"],
                    "direction": int(row["signal"]),
                    "stop_loss": row["stop_loss"],
                    "contracts": contracts,
                }

    return {"trades": pd.DataFrame(trades), "equity_curve": equity_curve,
            "initial_capital": initial_capital, "final_capital": round(capital, 2)}
