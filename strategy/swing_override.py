"""
One-shot SWING override mechanism.

Drop a JSON file at `data/.swing_override.json` and the next
`run_eod_swing_scan` execution will:
  1. Snapshot the affected settings
  2. Patch settings in-memory (universe, risk %, filter thresholds, gates)
  3. Run the swing scan with the relaxed/expanded config
  4. Restore the original settings
  5. Delete the override file (one-shot — won't repeat)

Used for live test runs where we want to guarantee a fire on a relaxed
universe with shrunken risk, then revert to normal config without manual
cleanup.

Override JSON schema (all fields optional):
{
  "universe":               ["AAPL", "MSFT", ...],   # replaces SWING_UNIVERSE entirely
  "risk_per_trade_daily":   0.0025,                  # patches RISK_PER_TRADE_DAILY
  "volume_mult":            1.2,                     # patches SWING_VOLUME_MULT
  "min_avg_volume":         500000,                  # patches SWING_MIN_AVG_VOLUME
  "pullback_ema_tol":       0.04,                    # patches SWING_PULLBACK_EMA_TOL
  "skip_fundamental_gate":  true,                    # forces FUNDAMENTAL_GATE_ENABLED False
  "skip_vix_cap":           true,                    # bypasses VIX>35 hard block in is_eligible
  "note":                   "free-form description"
}
"""

import json
import logging
from pathlib import Path
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)

OVERRIDE_PATH = Path(__file__).resolve().parents[1] / "data" / ".swing_override.json"

# Cached active override dict (None when not active)
_active_override: Optional[dict] = None
# Snapshot of original settings values, restored on restore()
_snapshot: Optional[dict] = None


def load_override() -> Optional[dict]:
    """Read the override file if it exists. Returns None if absent or invalid."""
    if not OVERRIDE_PATH.exists():
        return None
    try:
        with OVERRIDE_PATH.open() as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.warning(f"[swing_override] {OVERRIDE_PATH} is not a dict — ignoring")
            return None
        return data
    except Exception as e:
        logger.warning(f"[swing_override] failed to read {OVERRIDE_PATH}: {e}")
        return None


def apply(override: dict) -> None:
    """Patch settings in-place from an override dict. Snapshots prior values."""
    global _active_override, _snapshot

    _snapshot = {
        "SWING_UNIVERSE":           getattr(settings, "SWING_UNIVERSE", ""),
        "ACTIVE_SYMBOLS":           list(getattr(settings, "ACTIVE_SYMBOLS", [])),
        "RISK_PER_TRADE_DAILY":     getattr(settings, "RISK_PER_TRADE_DAILY", 0.005),
        "SWING_VOLUME_MULT":        getattr(settings, "SWING_VOLUME_MULT", 1.5),
        "SWING_MIN_AVG_VOLUME":     getattr(settings, "SWING_MIN_AVG_VOLUME", 1_000_000),
        "SWING_PULLBACK_EMA_TOL":   getattr(settings, "SWING_PULLBACK_EMA_TOL", 0.02),
        "FUNDAMENTAL_GATE_ENABLED": getattr(settings, "FUNDAMENTAL_GATE_ENABLED", True),
    }

    universe = override.get("universe")
    if universe:
        csv = ",".join(universe)
        settings.SWING_UNIVERSE = csv
        # ACTIVE_SYMBOLS is intersected in orchestrator._active_symbols — extend it
        settings.ACTIVE_SYMBOLS = sorted(set(settings.ACTIVE_SYMBOLS) | set(universe))

    if "risk_per_trade_daily" in override:
        settings.RISK_PER_TRADE_DAILY = float(override["risk_per_trade_daily"])
    if "volume_mult" in override:
        settings.SWING_VOLUME_MULT = float(override["volume_mult"])
    if "min_avg_volume" in override:
        settings.SWING_MIN_AVG_VOLUME = int(override["min_avg_volume"])
    if "pullback_ema_tol" in override:
        settings.SWING_PULLBACK_EMA_TOL = float(override["pullback_ema_tol"])
    if override.get("skip_fundamental_gate"):
        settings.FUNDAMENTAL_GATE_ENABLED = False

    _active_override = dict(override)
    logger.warning(
        f"[swing_override] APPLIED | "
        f"universe={len(universe or [])} symbols | "
        f"risk_daily={settings.RISK_PER_TRADE_DAILY*100:.3f}% | "
        f"vol_mult={settings.SWING_VOLUME_MULT} | "
        f"min_vol={settings.SWING_MIN_AVG_VOLUME} | "
        f"pullback_tol={settings.SWING_PULLBACK_EMA_TOL} | "
        f"fundamental_gate={settings.FUNDAMENTAL_GATE_ENABLED} | "
        f"skip_vix_cap={override.get('skip_vix_cap', False)} | "
        f"note={override.get('note', '')}"
    )


def restore() -> None:
    """Restore the snapshot values."""
    global _active_override, _snapshot
    if _snapshot is None:
        return
    for k, v in _snapshot.items():
        setattr(settings, k, v)
    _snapshot = None
    _active_override = None
    logger.warning("[swing_override] RESTORED original settings")


def consume() -> None:
    """Delete the override file so it never fires twice."""
    try:
        if OVERRIDE_PATH.exists():
            OVERRIDE_PATH.unlink()
            logger.warning(f"[swing_override] deleted {OVERRIDE_PATH} (one-shot consumed)")
    except Exception as e:
        logger.error(f"[swing_override] could not delete file: {e}")


def is_active() -> bool:
    return _active_override is not None


def get_active() -> Optional[dict]:
    return _active_override


def is_skip_vix() -> bool:
    """True if the active override bypasses the VIX>35 hard block."""
    return bool(_active_override and _active_override.get("skip_vix_cap"))
