"""
Market Regime Engine — adaptive BRT strategy parameters based on VIX.

Regime classification:
    TRENDING  — VIX < 15  | calm, directional market → tighter entries, bigger targets
    NORMAL    — VIX 15-20 | baseline conditions → standard parameters
    CAUTIOUS  — VIX 20-30 | elevated volatility → stricter filters, shorter targets
    HIGH_VOL  — VIX 30-40 | high volatility → only best setups, wide stops
    NO_TRADE  — VIX > 40  | extreme panic → all entries blocked

Each regime returns a parameter dict that overrides the static BRT settings.
The parameters are still ATR-relative fractions (no absolute price values),
so they adapt to intrabar volatility and remain regime-agnostic at execution.
"""

import logging
from config import settings

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Regime parameter table
# ─────────────────────────────────────────────────────────────────────────────

REGIME_PARAMS: dict[str, dict | None] = {
    # VIX < 15: calm, low-fear environment. Markets trend more cleanly.
    # → Require stronger trend confirmation (ADX 25), tighter retests,
    #   but let winners run further (2.5 R:R) and give more retest time.
    "TRENDING": {
        "adx_min":         25,
        "sl_buffer":       0.25,
        "tp_rr":           2.5,
        "max_retest_bars": 14,
        "level_tolerance": 0.20,
        "break_body_min":  0.25,
    },

    # VIX 15-20: standard market conditions. Use all configured defaults.
    "NORMAL": {
        "adx_min":         settings.BRT_ADX_MIN,
        "sl_buffer":       settings.BRT_SL_BUFFER,
        "tp_rr":           settings.BRT_TP_RR,
        "max_retest_bars": settings.BRT_MAX_RETEST_BARS,
        "level_tolerance": settings.BRT_LEVEL_TOLERANCE,
        "break_body_min":  settings.BRT_BREAK_BODY_MIN,
    },

    # VIX 20-30: elevated volatility. Whipsaws are more common.
    # → Demand stronger ADX, wider SL to survive noise, shorter hold time,
    #   tighter retest zone so we only take precise retests.
    "CAUTIOUS": {
        "adx_min":         25,
        "sl_buffer":       0.40,
        "tp_rr":           1.5,
        "max_retest_bars": 10,
        "level_tolerance": 0.20,
        "break_body_min":  0.30,
    },

    # VIX 30-40: high volatility. Moves are large and fast.
    # → Only take the highest-conviction breaks (big bodies, strong ADX),
    #   use wide stops so we're not stopped out by noise, but cut TP short
    #   because mean-reversion is faster in high-vol environments.
    "HIGH_VOL": {
        "adx_min":         30,
        "sl_buffer":       0.50,
        "tp_rr":           2.0,
        "max_retest_bars": 8,
        "level_tolerance": 0.15,
        "break_body_min":  0.40,
    },

    # VIX > 40: market panic. Do not trade. Returns None to signal block.
    "NO_TRADE": None,
}

REGIME_DESCRIPTIONS: dict[str, str] = {
    "TRENDING": "VIX < 15 — calm market, tighter entries, extended targets",
    "NORMAL":   "VIX 15-20 — baseline conditions, standard parameters",
    "CAUTIOUS": "VIX 20-30 — elevated volatility, stricter filters, shorter targets",
    "HIGH_VOL": "VIX 30-40 — high volatility, only best setups",
    "NO_TRADE": "VIX > 40 — extreme fear, all entries blocked",
}

REGIME_COLORS: dict[str, str] = {
    "TRENDING": "#00c853",
    "NORMAL":   "#2196f3",
    "CAUTIOUS": "#ff9800",
    "HIGH_VOL": "#f44336",
    "NO_TRADE": "#b71c1c",
}


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def classify_regime(vix: float | None) -> str:
    """
    Classify market regime from current VIX level.

    Args:
        vix: Current VIX index value (None = treat as NORMAL)

    Returns:
        Regime string: 'TRENDING' | 'NORMAL' | 'CAUTIOUS' | 'HIGH_VOL' | 'NO_TRADE'
    """
    if vix is None:
        logger.warning("VIX unavailable — defaulting to NORMAL regime")
        return "NORMAL"

    if vix > 40:
        regime = "NO_TRADE"
    elif vix > 30:
        regime = "HIGH_VOL"
    elif vix > 20:
        regime = "CAUTIOUS"
    elif vix > 15:
        regime = "NORMAL"
    else:
        regime = "TRENDING"

    logger.info(f"Regime: {regime}  (VIX={vix:.1f}) — {REGIME_DESCRIPTIONS[regime]}")
    return regime


def get_regime_params(vix: float | None) -> dict | None:
    """
    Return adaptive BRT parameters for the current VIX regime.

    Returns:
        Dict of overriding BRT params, or None if regime is NO_TRADE.
    """
    regime = classify_regime(vix)
    return REGIME_PARAMS.get(regime)


def get_regime_info(vix: float | None) -> dict:
    """
    Return full regime context dict for logging, API, and dashboard.

    Returns:
        {
            regime, description, color, params,
            vix, can_trade,
            adx_min, sl_buffer, tp_rr, max_retest_bars,
            level_tolerance, break_body_min
        }
    """
    regime = classify_regime(vix)
    params = REGIME_PARAMS.get(regime)

    info: dict = {
        "regime":      regime,
        "description": REGIME_DESCRIPTIONS[regime],
        "color":       REGIME_COLORS[regime],
        "vix":         vix,
        "can_trade":   params is not None,
    }

    if params:
        info.update(params)
    else:
        # NO_TRADE — fill with None so dashboard can render gracefully
        info.update({
            "adx_min":         None,
            "sl_buffer":       None,
            "tp_rr":           None,
            "max_retest_bars": None,
            "level_tolerance": None,
            "break_body_min":  None,
        })

    return info
