import logging
import sys
import os
from config import settings
from data.fetcher import fetch_historical
from data.fundamentals import get_live_fundamentals, print_fundamentals
from strategy.indicators import add_indicators
from strategy.signals import generate_signals, get_latest_signal
from strategy.break_retest import prepare_break_retest, get_latest_brt_signal
from strategy.donchian import prepare_donchian, get_latest_donchian_signal

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/tradez.log"),
    ],
)
logger = logging.getLogger("TRADEZ")


# ─────────────────────────────────────────────────────────────────────────────
# MES — Break & Retest with live fundamentals gate
# ─────────────────────────────────────────────────────────────────────────────

def run_mes_brt(fundamentals: dict) -> dict:
    """
    Run Break & Retest strategy check for MES.
    Uses live fundamentals to gate and annotate the signal.
    """
    logger.info("--- MES (Break & Retest) ---")

    df = fetch_historical("MES", timeframe_minutes=settings.BRT_TIMEFRAME)
    df = prepare_break_retest(df, long_only=True)
    latest = get_latest_brt_signal(df)

    signal_label = {1: "LONG", -1: "SHORT", 0: "FLAT"}.get(latest["signal"], "FLAT")

    logger.info(f"Signal      : {signal_label}")
    logger.info(f"Close       : {latest['close']:.2f}")
    logger.info(f"EMA20       : {latest['ema20']:.2f}  "
                f"| ADX: {latest['adx']:.1f}  "
                f"| RSI: {latest['rsi']:.1f}  "
                f"| ATR: {latest['atr']:.2f}")
    logger.info(f"PDH/PDL     : {latest['pdh']} / {latest['pdl']}")
    logger.info(f"Swing Hi/Lo : {latest['swing_hi']} / {latest['swing_lo']}")

    if latest["signal"] != 0:
        logger.info(f"Level Type  : {latest['level_type']}")
        logger.info(f"Retest Level: {latest['retest_level']}")
        logger.info(f"Stop Loss   : {latest['stop_loss']}")
        logger.info(f"Take Profit : {latest['take_profit']}")

        risk = abs(latest["close"] - latest["stop_loss"]) if latest["stop_loss"] else 0
        reward = abs(latest["take_profit"] - latest["close"]) if latest["take_profit"] else 0
        rr = round(reward / risk, 2) if risk > 0 else 0
        logger.info(f"R:R         : {rr}:1")

        # ── Fundamentals gate ──────────────────────────────────────────
        regime = fundamentals.get("regime", "CAUTIOUS")
        if regime == "NO_TRADE":
            logger.warning("SIGNAL BLOCKED — Regime: NO_TRADE (VIX extreme)")
            latest["signal"] = 0
            latest["blocked_reason"] = "NO_TRADE regime"
        elif regime == "RISK_OFF":
            logger.warning("SIGNAL BLOCKED — Regime: RISK_OFF (multiple headwinds)")
            latest["signal"] = 0
            latest["blocked_reason"] = "RISK_OFF regime"
        else:
            if regime == "CAUTIOUS":
                logger.info("NOTE: CAUTIOUS regime — trade but stay selective")
            latest["blocked_reason"] = None

    latest["regime"] = fundamentals.get("regime", "UNKNOWN")
    return latest


# ─────────────────────────────────────────────────────────────────────────────
# Generic strategy runner (non-MES symbols)
# ─────────────────────────────────────────────────────────────────────────────

def run_strategy_check(symbol: str) -> dict:
    """Pull data, calculate indicators, and print latest signal for a symbol."""
    strategy = settings.SYMBOL_STRATEGY.get(symbol, "DONCHIAN")
    logger.info(f"--- {symbol} ({strategy}) ---")

    if strategy == "DONCHIAN":
        df = fetch_historical(symbol, timeframe_minutes=1440)
        long_only = symbol in settings.LONG_ONLY_SYMBOLS
        df = prepare_donchian(df, long_only=long_only)
        latest = get_latest_donchian_signal(df)
        signal_label = {1: "LONG", -1: "SHORT", 0: "FLAT"}.get(latest["signal"], "FLAT")
        logger.info(f"Signal     : {signal_label}")
        logger.info(f"Close      : {latest['close']:.2f}")
        logger.info(f"DC Upper   : {latest['dc_upper']:.2f}  |  DC Lower: {latest['dc_lower']:.2f}")
        logger.info(f"ATR        : {latest['atr']:.2f}")
        if latest["signal"] != 0:
            logger.info(f"Stop Loss  : {latest['stop_loss']}")
    else:
        df = fetch_historical(symbol, timeframe_minutes=settings.TIMEFRAME)
        df = add_indicators(df)
        df = generate_signals(df)
        latest = get_latest_signal(df)
        signal_label = {1: "LONG", -1: "SHORT", 0: "FLAT"}.get(latest["signal"], "FLAT")
        logger.info(f"Signal     : {signal_label}")
        logger.info(f"Close      : {latest['close']:.2f}")
        logger.info(f"EMA Fast   : {latest['ema_fast']:.2f}  |  EMA Slow: {latest['ema_slow']:.2f}")
        logger.info(f"ADX        : {latest['adx']:.2f}  |  ATR: {latest['atr']:.2f}")
        if latest["signal"] != 0:
            logger.info(f"Stop Loss  : {latest['stop_loss']}")
            logger.info(f"Take Profit: {latest['take_profit']}")

    return latest


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    logger.info("=== TRADEZ Bot Starting ===")
    logger.info(f"Mode     : {'PAPER' if settings.PAPER_TRADING else 'LIVE'}")
    logger.info(f"Symbols  : {settings.SYMBOLS}")
    logger.info(f"Risk/trade: {settings.RISK_PER_TRADE * 100}%")

    # ── Live fundamentals (MES-specific) ────────────────────────────────
    logger.info("Fetching live market fundamentals...")
    fundamentals = get_live_fundamentals()
    print_fundamentals(fundamentals)

    # ── Run strategy checks ──────────────────────────────────────────────
    results = {}
    for symbol in settings.SYMBOLS:
        if symbol == "MES":
            results[symbol] = run_mes_brt(fundamentals)
        else:
            results[symbol] = run_strategy_check(symbol)

    logger.info("=== Strategy check complete ===")
    return results


if __name__ == "__main__":
    main()
