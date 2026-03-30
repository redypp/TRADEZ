"""
monitor/alerts.py

Telegram notifications for every trade event.

Setup (one-time):
    1. Open Telegram, search @BotFather
    2. Send /newbot, follow prompts, copy the token
    3. Start a chat with your new bot
    4. Get your chat ID: https://api.telegram.org/bot<TOKEN>/getUpdates
    5. Add to .env:
           TELEGRAM_TOKEN=your_token_here
           TELEGRAM_CHAT_ID=your_chat_id_here

If token/chat_id are not set, alerts are silently skipped
(the bot still runs, you just won't get messages).
"""

import logging
import requests
from datetime import datetime
from config import settings

logger = logging.getLogger(__name__)


def _send(message: str) -> None:
    """Send a Telegram message. Silently skips if credentials are not set."""
    token   = settings.TELEGRAM_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID

    if not token or not chat_id:
        logger.debug("Telegram not configured — skipping alert")
        return

    try:
        url  = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(
            url,
            data={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=10,
        )
        if not resp.ok:
            logger.warning(f"Telegram send failed: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.warning(f"Telegram error: {e}")


def notify_signal_check(signal: dict, fundamentals: dict) -> None:
    """Hourly check summary — only sends if a signal fired or regime changed."""
    regime = fundamentals.get("regime", "UNKNOWN")
    sig    = signal.get("signal", 0)

    if sig == 0 and regime == "RISK_ON":
        return  # quiet hour, don't spam

    ts   = datetime.now().strftime("%H:%M ET")
    icon = "🔍" if sig == 0 else ("📈" if sig == 1 else "📉")
    sig_label = {1: "LONG", -1: "SHORT", 0: "FLAT"}.get(sig, "FLAT")

    lines = [
        f"{icon} <b>MES B&R — {ts}</b>",
        f"Signal : <b>{sig_label}</b>",
        f"Close  : {signal.get('close', '?'):.2f}",
        f"ADX    : {signal.get('adx', 0):.1f}  |  RSI: {signal.get('rsi', 0):.1f}",
        f"Regime : {regime}",
    ]

    if fundamentals.get("headwinds"):
        lines.append("⚠️ " + " | ".join(fundamentals["headwinds"]))

    _send("\n".join(lines))


def notify_entry(
    contracts:     int,
    entry_price:   float,
    sl_price:      float,
    tp_price:      float,
    level_type:    str,
    retest_level:  float,
    direction:     str = "LONG",
) -> None:
    """Send alert when a trade is entered."""
    risk_pts  = round(abs(entry_price - sl_price), 2)
    reward_pts = round(abs(tp_price - entry_price), 2)
    rr        = round(reward_pts / risk_pts, 1) if risk_pts > 0 else 0
    risk_usd  = round(risk_pts * settings.BRT_POINT_VALUE * contracts, 2)

    ts   = datetime.now().strftime("%H:%M ET")
    icon = "📈" if direction == "LONG" else "📉"

    msg = (
        f"{icon} <b>MES {direction} ENTRY — {ts}</b>\n"
        f"Contracts : {contracts}\n"
        f"Entry     : {entry_price:.2f}\n"
        f"Stop Loss : {sl_price:.2f}  (−{risk_pts} pts)\n"
        f"Take Profit: {tp_price:.2f}  (+{reward_pts} pts)\n"
        f"R:R       : {rr}:1\n"
        f"$ at Risk  : ${risk_usd:.2f}\n"
        f"Level     : {level_type} @ {retest_level:.2f}"
    )
    _send(msg)
    logger.info(f"ENTRY alert sent: MES {direction} x{contracts} @ {entry_price:.2f}")


def notify_exit(
    direction:   str,
    contracts:   int,
    entry_price: float,
    exit_price:  float,
    pnl:         float,
    reason:      str,   # 'TP' or 'SL'
) -> None:
    """Send alert when a trade exits."""
    icon = "✅" if reason == "TP" else "❌"
    pts  = round((exit_price - entry_price) * (1 if direction == "LONG" else -1), 2)
    ts   = datetime.now().strftime("%H:%M ET")

    msg = (
        f"{icon} <b>MES {direction} EXIT ({reason}) — {ts}</b>\n"
        f"Contracts : {contracts}\n"
        f"Entry     : {entry_price:.2f}\n"
        f"Exit      : {exit_price:.2f}  ({pts:+.2f} pts)\n"
        f"Net P&L   : ${pnl:+.2f}"
    )
    _send(msg)
    logger.info(f"EXIT alert sent: {reason} | P&L ${pnl:+.2f}")


def notify_brt_signal(signal: dict) -> None:
    """Fire immediately when BRT detects a valid entry signal (before execution).

    This fires regardless of whether credentials are set — useful for dry-run
    validation while waiting for Tradovate credentials.
    """
    sig       = signal.get("signal", 0)
    direction = {1: "LONG", -1: "SHORT"}.get(sig, "FLAT")
    if sig == 0:
        return

    ts         = datetime.now().strftime("%H:%M ET")
    icon       = "📈" if sig == 1 else "📉"
    entry      = signal.get("close", 0)
    sl         = signal.get("stop_loss", 0)
    tp         = signal.get("take_profit", 0)
    level_type = signal.get("level_type", "?")
    retest_lvl = signal.get("retest_level", 0)
    sweep      = signal.get("liquidity_sweep", 0)
    adx        = signal.get("adx", 0)
    rsi        = signal.get("rsi", 0)
    atr        = signal.get("atr", 0)

    risk_pts   = round(abs(entry - sl), 2) if sl else 0
    reward_pts = round(abs(tp - entry), 2) if tp else 0
    rr         = round(reward_pts / risk_pts, 1) if risk_pts > 0 else 0

    sweep_tag  = "  ✅ Liquidity sweep" if sweep else ""

    msg = (
        f"{icon} <b>BRT SIGNAL: MES {direction} — {ts}</b>\n"
        f"Level    : {level_type} @ {retest_lvl:.2f}{sweep_tag}\n"
        f"Entry    : {entry:.2f}\n"
        f"SL / TP  : {sl:.2f} / {tp:.2f}  ({rr}:1 R:R)\n"
        f"Risk     : {risk_pts} pts  |  ATR: {atr:.2f}\n"
        f"ADX      : {adx:.1f}  |  RSI: {rsi:.1f}\n"
        f"<i>⏸ No execution (credentials pending)</i>"
    )
    _send(msg)
    logger.info(f"BRT signal alert sent: {direction} @ {entry:.2f} | {level_type}")


def notify_vwap_signal(signal: dict) -> None:
    """Fire immediately when VWAP_MR detects a valid entry signal (before execution).

    Fires regardless of whether Tradovate credentials are set — useful for
    dry-run validation while waiting for credentials.
    """
    sig = signal.get("signal", 0)
    if sig == 0:
        return

    direction  = {1: "LONG", -1: "SHORT"}.get(sig, "FLAT")
    icon       = "📈" if sig == 1 else "📉"
    ts         = datetime.now().strftime("%H:%M ET")
    entry      = signal.get("close", 0)
    sl         = signal.get("stop_loss") or 0
    tp         = signal.get("take_profit") or 0
    vwap       = signal.get("vwap", 0)
    vwap_upper = signal.get("vwap_upper", 0)
    vwap_lower = signal.get("vwap_lower", 0)
    rsi5       = signal.get("rsi5", 0)
    adx        = signal.get("adx", 0)

    risk_pts   = round(abs(entry - sl), 2) if sl else 0
    reward_pts = round(abs(tp - entry), 2) if tp else 0
    rr         = round(reward_pts / risk_pts, 1) if risk_pts > 0 else 0
    dev_pct    = round((entry - vwap) / vwap * 100, 2) if vwap else 0

    msg = (
        f"{icon} <b>VWAP MR SIGNAL: MES {direction} — {ts}</b>\n"
        f"Entry    : {entry:.2f}  (dev {dev_pct:+.2f}% from VWAP)\n"
        f"VWAP     : {vwap:.2f}  [{vwap_lower:.2f} – {vwap_upper:.2f}]\n"
        f"SL / TP  : {sl:.2f} / {tp:.2f}  ({rr}:1 R:R)\n"
        f"Risk     : {risk_pts} pts\n"
        f"ADX      : {adx:.1f}  |  RSI5: {rsi5:.1f}\n"
        f"<i>⏸ No execution (credentials pending)</i>"
    )
    _send(msg)
    logger.info(f"VWAP MR signal alert sent: {direction} @ {entry:.2f} | dev {dev_pct:+.2f}%")


def notify_risk_block(reason: str) -> None:
    """Send alert when a trade is blocked by risk manager."""
    ts  = datetime.now().strftime("%H:%M ET")
    msg = f"🚫 <b>TRADE BLOCKED — {ts}</b>\n{reason}"
    _send(msg)
    logger.info(f"Risk block alert sent: {reason}")


def notify_daily_summary(
    trades_today: int,
    pnl_today:    float,
    equity:       float,
) -> None:
    """End-of-day summary sent at session close."""
    icon = "📊"
    ts   = datetime.now().strftime("%Y-%m-%d")
    msg  = (
        f"{icon} <b>MES Daily Summary — {ts}</b>\n"
        f"Trades today : {trades_today}\n"
        f"P&L today    : ${pnl_today:+.2f}\n"
        f"Account      : ${equity:,.2f}"
    )
    _send(msg)


def notify_news_trade_signal(
    direction:  str,
    confidence: float,
    reason:     str,
    headline:   str,
    source:     str,
) -> None:
    """Alert when Grok has assessed a directional trade signal from breaking news."""
    icon = "📈" if direction == "BULLISH" else "📉"
    ts = datetime.now().strftime("%H:%M ET")
    conf_pct = f"{confidence:.0%}"

    msg = (
        f"{icon} <b>NEWS TRADE SIGNAL [{direction}] — {ts}</b>\n"
        f"Confidence : {conf_pct}\n"
        f"Reason     : {reason}\n"
        f"Source     : {headline[:70]}\n"
        f"<i>Bot will block opposing BRT entries for {settings.NEWS_SIGNAL_EXPIRY_MINUTES} min</i>"
    )
    _send(msg)
    logger.info(f"News trade signal alert: {direction} {conf_pct} — {headline[:50]}")


def notify_news_trade_block(
    brt_direction:  str,
    news_direction: str,
    confidence:     float,
    headline:       str,
    reason:         str,
) -> None:
    """Alert when a BRT entry is blocked because news opposes it."""
    ts = datetime.now().strftime("%H:%M ET")
    msg = (
        f"🚫 <b>ENTRY BLOCKED BY NEWS — {ts}</b>\n"
        f"BRT wanted  : {brt_direction}\n"
        f"News signal : {news_direction} ({confidence:.0%} conf)\n"
        f"Reason      : {reason}\n"
        f"News        : {headline[:70]}"
    )
    _send(msg)
    logger.info(f"News trade block alert: BRT {brt_direction} blocked by {news_direction} news")


def notify_breaking_news(
    source:   str,
    headline: str,
    summary:  str,
    impact:   str,
    assets:   str,
    link:     str = "",
) -> None:
    """Send immediate Telegram alert when breaking news is detected."""
    impact_icon = {"HIGH": "🚨", "MEDIUM": "⚡"}.get(impact, "📰")
    ts = datetime.now().strftime("%H:%M ET")

    lines = [
        f"{impact_icon} <b>BREAKING NEWS [{impact}] — {ts}</b>",
        f"<b>{headline}</b>",
    ]

    if summary:
        lines += ["", summary]

    if assets:
        lines.append(f"\nAssets : {assets}")

    lines.append(f"Source : {source}")

    if link:
        lines.append(f"<a href=\"{link}\">Read more</a>")

    if impact == "HIGH":
        from config import settings
        halt_min = getattr(settings, "NEWS_HALT_MINUTES", 15)
        halt_enabled = getattr(settings, "NEWS_HALT_ENABLED", False)
        if halt_enabled:
            lines.append(f"\n⏸ New entries paused for {halt_min} min")

    _send("\n".join(lines))
    logger.info(f"Breaking news alert sent: [{impact}] {headline}")


def notify_error(error: str) -> None:
    """Send alert on unhandled errors."""
    ts  = datetime.now().strftime("%H:%M ET")
    msg = f"⚠️ <b>BOT ERROR — {ts}</b>\n{error}"
    _send(msg)


def notify_llm_advisory(advisory: dict) -> None:
    """Send AI advisory brief via Telegram."""
    trigger   = advisory.get("trigger", "HOURLY")
    sentiment = advisory.get("sentiment", "NEUTRAL")
    quality   = advisory.get("signal_quality", "N/A")
    headline  = advisory.get("headline", "AI Advisory")
    brief     = advisory.get("brief", "")
    flags     = advisory.get("risk_flags", [])
    ts        = advisory.get("timestamp", datetime.now().strftime("%H:%M ET"))

    sentiment_icon = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}.get(sentiment, "⚪")
    trigger_icon   = {"SIGNAL": "📡", "PRE_MARKET": "🌅", "HOURLY": "🤖"}.get(trigger, "🤖")
    quality_icon   = {"HIGH": "✅", "MEDIUM": "🟡", "LOW": "🟠", "N/A": "⚪"}.get(quality, "⚪")

    lines = [
        f"{trigger_icon} <b>AI Advisory — {ts}</b>",
        f"{headline}",
        "",
        f"Sentiment : {sentiment_icon} {sentiment}",
    ]

    if quality != "N/A":
        lines.append(f"Setup quality : {quality_icon} {quality}")

    if brief:
        lines += ["", brief]

    if flags:
        lines.append("")
        for flag in flags[:3]:
            lines.append(f"⚠️ {flag}")

    watch = advisory.get("watch_for", "")
    if watch and watch != "n/a":
        lines += ["", f"Watch : {watch}"]

    _send("\n".join(lines))


def notify_llm_gate_block(
    strategy_name: str,
    direction:     str,
    llm_strategy:  str,
    llm_bias:      str,
    confidence:    float,
    reasoning:     str,
) -> None:
    """Alert when the LLM gate blocks a trade the algo wanted to take."""
    ts = datetime.now().strftime("%H:%M ET")
    msg = (
        f"🤖🚫 <b>LLM GATE BLOCKED — {ts}</b>\n"
        f"Algo wanted  : {strategy_name} {direction}\n"
        f"LLM decision : {llm_strategy} / {llm_bias} ({confidence:.0%} conf)\n"
        f"Reason       : {reasoning[:100]}"
    )
    _send(msg)
    logger.info(f"LLM gate block alert: {strategy_name} {direction} blocked — LLM={llm_strategy}/{llm_bias}")


def notify_llm_quality_gate_block(
    strategy_name:  str,
    direction:      str,
    signal_quality: str,
    macro_supports: bool,
    risk_flags:     list,
) -> None:
    """Alert when the advisory quality gate blocks a trade."""
    ts    = datetime.now().strftime("%H:%M ET")
    flags = " | ".join(risk_flags[:3]) if risk_flags else "none"
    msg = (
        f"🤖🚫 <b>AI QUALITY GATE BLOCKED — {ts}</b>\n"
        f"Algo wanted   : {strategy_name} {direction}\n"
        f"Signal quality: {signal_quality}\n"
        f"Macro supports: {'Yes' if macro_supports else 'No'}\n"
        f"Risk flags    : {flags}"
    )
    _send(msg)
    logger.info(f"AI quality gate block: {strategy_name} {direction} | quality={signal_quality} macro={macro_supports}")


def notify_news_size_boost(
    direction:  str,
    confidence: float,
    boost:      float,
    contracts:  int,
    headline:   str,
) -> None:
    """Alert when a news confirmation boosts position size."""
    ts = datetime.now().strftime("%H:%M ET")
    msg = (
        f"📰📈 <b>NEWS SIZE BOOST — {ts}</b>\n"
        f"Direction  : {direction}\n"
        f"News conf  : {confidence:.0%}  →  size {boost:.2f}x\n"
        f"Contracts  : {contracts}\n"
        f"News       : {headline[:70]}"
    )
    _send(msg)
    logger.info(f"News size boost: {direction} {boost:.2f}x ({confidence:.0%} conf)")
