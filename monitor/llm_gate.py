"""
monitor/llm_gate.py

Thread-safe caches for LLM selector and advisory results.

Updated by the scheduler at the start of each tick.
Read by the orchestrator inside _execute_signal() — zero latency,
no blocking of the execution path.

Why caches instead of calling LLMs at execution time:
  The LLM selector takes ~12-20s (async Grok + GPT-4 in parallel, then Claude).
  Calling it inside _execute_signal() would block every trade by 20s.
  Instead, scheduler pre-runs it at the start of each tick and stores the result
  here. By the time _execute_signal() runs, the result is already available.

Advisory cache:
  The advisory runs in a background thread AFTER execution. Its signal_quality
  and macro_supports fields are stored here and used as a soft gate on the
  NEXT tick's trades — using recent AI assessment as context without circular logic.
"""

import logging
import threading
from datetime import datetime
from typing import Optional

import pytz

logger = logging.getLogger(__name__)
ET = pytz.timezone("America/New_York")

_lock = threading.Lock()

# ── LLM strategy selector cache ───────────────────────────────────────────────
# Populated by scheduler at the start of each tick.
# Schema: {strategy, bias, confidence, reasoning, votes, source}
_llm_selection: dict = {}
_llm_selection_at: Optional[datetime] = None


def update_llm_selection(result: dict) -> None:
    """Store the latest LLM selector result. Called by scheduler each tick."""
    global _llm_selection, _llm_selection_at
    with _lock:
        _llm_selection = dict(result)
        _llm_selection_at = datetime.now(ET)
    logger.info(
        f"[LLMGate] Selector cached — strategy={result.get('strategy')} "
        f"bias={result.get('bias')} conf={result.get('confidence', 0):.2f} "
        f"source={result.get('source', '?')}"
    )


def get_llm_selection() -> dict:
    """Read the cached LLM selector result. Safe to call from any thread."""
    with _lock:
        return dict(_llm_selection)


def clear_llm_selection() -> None:
    """Clear the cache (called at session start to avoid stale state)."""
    global _llm_selection, _llm_selection_at
    with _lock:
        _llm_selection = {}
        _llm_selection_at = None


# ── Advisory result cache ─────────────────────────────────────────────────────
# Populated by the advisory background thread after each execution tick.
# Schema: {signal_quality, macro_supports, risk_flags, sentiment, headline, brief, ...}
_advisory_result: dict = {}
_advisory_at: Optional[datetime] = None


def update_advisory(result: dict) -> None:
    """Store the latest advisory result. Called by the advisory background thread."""
    global _advisory_result, _advisory_at
    with _lock:
        _advisory_result = dict(result)
        _advisory_at = datetime.now(ET)
    logger.debug(
        f"[LLMGate] Advisory cached — quality={result.get('signal_quality')} "
        f"macro_ok={result.get('macro_supports')} "
        f"flags={len(result.get('risk_flags', []))}"
    )


def get_advisory_result() -> dict:
    """Read the cached advisory result. Safe to call from any thread."""
    with _lock:
        return dict(_advisory_result)


# ── Diagnostics ───────────────────────────────────────────────────────────────

def get_status() -> dict:
    """Return cache status for dashboard / logging."""
    with _lock:
        return {
            "llm_selection_strategy":   _llm_selection.get("strategy"),
            "llm_selection_bias":       _llm_selection.get("bias"),
            "llm_selection_confidence": _llm_selection.get("confidence"),
            "llm_selection_at":         _llm_selection_at.strftime("%H:%M ET") if _llm_selection_at else None,
            "advisory_quality":         _advisory_result.get("signal_quality"),
            "advisory_macro_supports":  _advisory_result.get("macro_supports"),
            "advisory_flags":           _advisory_result.get("risk_flags", []),
            "advisory_at":              _advisory_at.strftime("%H:%M ET") if _advisory_at else None,
        }
