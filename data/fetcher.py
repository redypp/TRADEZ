import logging
import pandas as pd
import yfinance as yf
from config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Historical data (yfinance) — used for backtesting, no IBKR needed
# ---------------------------------------------------------------------------

INTERVAL_MAP = {
    1:   "1m",
    5:   "5m",
    15:  "15m",
    30:  "30m",
    60:  "1h",
    240: "1h",   # yfinance max intraday is 1h; use daily for longer
    1440: "1d",
}

def fetch_historical(symbol: str, period: str = None, timeframe_minutes: int = 60) -> pd.DataFrame:
    """
    Pull historical OHLCV data from Yahoo Finance.
    Used for backtesting. No IBKR connection required.

    yfinance intraday limits:
        1m  — max 7 days
        5m  — max 60 days
        1h  — max 730 days
        1d  — unlimited

    Args:
        symbol: TRADEZ symbol e.g. 'MES', 'MGC'
        period: lookback override. If None, auto-selects max safe period.
        timeframe_minutes: candle size in minutes

    Returns:
        DataFrame with columns: open, high, low, close, volume
    """
    ticker = settings.BACKTEST_TICKER_MAP.get(symbol, symbol)
    interval = INTERVAL_MAP.get(timeframe_minutes, "1d")

    # Auto-select max safe period for each interval
    if period is None:
        period = {
            "1m": "7d",
            "5m": "60d",
            "15m": "60d",
            "30m": "60d",
            "1h": "730d",
            "1d": "5y",
        }.get(interval, "1y")

    logger.info(f"Fetching historical data: {ticker} | period={period} | interval={interval}")
    df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)

    if df.empty:
        raise ValueError(f"No data returned for {ticker}. Check symbol or period.")

    # yfinance 1.x returns multi-level columns (Price, Ticker) — flatten to single level
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df.columns = [c.lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    logger.info(f"Fetched {len(df)} candles for {symbol} ({ticker})")
    return df


# ---------------------------------------------------------------------------
# Live data (IBKR) — used when account is approved and TWS is running
# ---------------------------------------------------------------------------

def get_ibkr_connection():
    """
    Connect to IBKR TWS or Gateway.
    Requires TWS/Gateway to be running with API access enabled.
    """
    from ib_insync import IB
    ib = IB()
    ib.connect(settings.IBKR_HOST, settings.IBKR_PORT, clientId=settings.IBKR_CLIENT_ID)
    logger.info(f"Connected to IBKR at {settings.IBKR_HOST}:{settings.IBKR_PORT}")
    return ib


def fetch_live_bars(ib, symbol: str, duration: str = "2 D", bar_size: str = "1 hour") -> pd.DataFrame:
    """
    Fetch recent historical bars from IBKR for a futures contract.

    Args:
        ib: active IB connection
        symbol: e.g. 'MES', 'MGC'
        duration: IBKR duration string e.g. '2 D', '5 D', '1 M'
        bar_size: IBKR bar size e.g. '1 hour', '30 mins', '1 day'

    Returns:
        DataFrame with columns: open, high, low, close, volume
    """
    from ib_insync import Future
    contract = Future(symbol=symbol, exchange=settings.EXCHANGE, currency=settings.CURRENCY)
    ib.qualifyContracts(contract)

    bars = ib.reqHistoricalData(
        contract,
        endDateTime="",
        durationStr=duration,
        barSizeSetting=bar_size,
        whatToShow="TRADES",
        useRTH=True,
    )
    df = pd.DataFrame([{
        "timestamp": b.date,
        "open": b.open,
        "high": b.high,
        "low": b.low,
        "close": b.close,
        "volume": b.volume,
    } for b in bars])
    df.set_index("timestamp", inplace=True)
    logger.info(f"Fetched {len(df)} live bars for {symbol}")
    return df


def fetch_account_balance(ib) -> dict:
    """Return net liquidation value and available funds from IBKR."""
    account_values = ib.accountValues()
    result = {}
    for av in account_values:
        if av.tag == "NetLiquidation" and av.currency == "USD":
            result["net_liquidation"] = float(av.value)
        if av.tag == "AvailableFunds" and av.currency == "USD":
            result["available_funds"] = float(av.value)
    return result


def fetch_open_positions(ib) -> list:
    """Return all open IBKR positions."""
    return [p for p in ib.positions() if p.position != 0]
