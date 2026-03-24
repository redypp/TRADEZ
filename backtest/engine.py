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

    Returns:
        dict with trades DataFrame and performance data
    """
    if strategy == "ORB":
        return _run_orb(df, initial_capital)
    elif strategy == "DONCHIAN":
        return _run_donchian(df, initial_capital)
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
