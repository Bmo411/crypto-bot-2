"""
TradingBot V5 — Abstract Strategy Interface

All strategies must implement this interface.
"""

from abc import ABC, abstractmethod
from typing import Optional
from core.events import BarEvent, SignalEvent


class AbstractStrategy(ABC):
    """Base class for all trading strategies."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique strategy identifier."""
        ...

    @abstractmethod
    async def on_bar(
        self,
        bar: BarEvent,
        position_side: str = "FLAT",
        position_qty: float = 0.0,
        current_pnl_pct: float = 0.0,
    ) -> Optional[SignalEvent]:
        """
        Process a new bar and optionally emit a signal.

        Args:
            bar: The new OHLCV bar
            position_side: Current position (FLAT, LONG, SHORT)
            position_qty: Current position quantity
            current_pnl_pct: Current unrealized PnL as decimal

        Returns:
            SignalEvent if a trade action is warranted, None otherwise
        """
        ...

    @abstractmethod
    def warm_up(self, bars: list[BarEvent]) -> None:
        """
        Feed historical bars to warm up internal state.
        Called during recovery to restore rolling windows.
        """
        ...

    @abstractmethod
    def reset(self, symbol: str) -> None:
        """Reset internal state for a symbol."""
        ...
