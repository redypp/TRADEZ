"""
strategy/registry.py

Central strategy registry. Strategies self-register via the @register decorator.

Usage
-----
Decorate any AbstractStrategy subclass to register it:

    from strategy.registry import register
    from strategy.base import AbstractStrategy

    @register
    class MyStrategy(AbstractStrategy):
        name = "MY"
        symbols = ["MES"]
        timeframe_minutes = 15
        priority = 10

        def is_eligible(self, symbol, regime, session_hour, fundamentals):
            return True

        def prepare(self, df, **kwargs):
            ...

        def get_signal(self, df, **kwargs):
            ...

Query
-----
    from strategy.registry import get_eligible, get_all, get_by_name

    # All strategies eligible to trade MES right now:
    strategies = get_eligible("MES", regime="TRENDING", session_hour=10, fundamentals={...})

    # All registered strategies regardless of eligibility:
    all_strats = get_all()

    # Lookup by name:
    brt = get_by_name("BRT")

Notes
-----
- Each strategy class is instantiated once at decoration time.
- Strategies are sorted by priority (ascending) in get_eligible().
- STRATEGY_ENABLED in settings.py acts as a hard on/off per strategy name.
  A strategy whose name is not in STRATEGY_ENABLED defaults to disabled.
"""

from __future__ import annotations
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from strategy.base import AbstractStrategy

logger = logging.getLogger(__name__)

_registry: list[AbstractStrategy] = []


def register(cls):
    """
    Class decorator — instantiates and registers a strategy.

    The decorator preserves and returns the original class so the class
    itself is still importable by name after decoration.
    """
    instance = cls()
    _registry.append(instance)
    logger.debug(
        f"Strategy registered: {instance.name!r} "
        f"symbols={instance.symbols} tf={instance.timeframe_minutes}m "
        f"priority={instance.priority}"
    )
    return cls


def get_eligible(
    symbol: str,
    regime: str,
    session_hour: int,
    fundamentals: dict,
) -> list[AbstractStrategy]:
    """
    Return all registered strategies eligible to trade *symbol* right now.

    A strategy is eligible when:
      1. symbol is in strategy.symbols
      2. strategy.name is enabled in settings.STRATEGY_ENABLED
      3. strategy.is_eligible() returns True

    Result is sorted by strategy.priority ascending (lower = higher priority).
    """
    from config import settings  # local import — avoids circular dependency

    eligible: list[AbstractStrategy] = []
    for strategy in _registry:
        if symbol not in strategy.symbols:
            continue
        if not settings.STRATEGY_ENABLED.get(strategy.name, False):
            continue
        try:
            if strategy.is_eligible(symbol, regime, session_hour, fundamentals):
                eligible.append(strategy)
        except Exception as exc:
            logger.warning(
                f"is_eligible() raised for {strategy.name!r} on {symbol}: {exc}"
            )

    eligible.sort(key=lambda s: s.priority)
    return eligible


def get_all() -> list[AbstractStrategy]:
    """Return every registered strategy (regardless of eligibility or enabled state)."""
    return list(_registry)


def get_by_name(name: str) -> AbstractStrategy | None:
    """Return the registered strategy with the given name, or None."""
    for s in _registry:
        if s.name == name:
            return s
    return None
