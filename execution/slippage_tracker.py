"""
TradingBot V5 — Slippage Tracker

Tracks and analyzes the difference between expected and actual fill prices.
"""

import logging
from collections import defaultdict, deque
from typing import Optional

log = logging.getLogger("execution.slippage")


class SlippageTracker:
    """
    Track slippage statistics per symbol and overall.
    Slippage is measured in basis points (bps).
    """

    def __init__(self, window_size: int = 100):
        self._window_size = window_size
        # Per-symbol slippage history
        self._history: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=window_size)
        )
        self._total_fills = 0

    def record_fill(
        self,
        symbol: str,
        expected_price: float,
        fill_price: float,
        side: str,
    ) -> float:
        """
        Record a fill and return the slippage in basis points.

        Positive slippage = unfavorable (paid more for BUY or got less for SELL)
        Negative slippage = favorable
        """
        if expected_price <= 0:
            return 0.0

        if side == "BUY":
            slippage_bps = ((fill_price - expected_price) / expected_price) * 10000
        else:
            slippage_bps = ((expected_price - fill_price) / expected_price) * 10000

        self._history[symbol].append(slippage_bps)
        self._total_fills += 1

        if abs(slippage_bps) > 10:
            log.warning(
                f"[{symbol}] High slippage: {slippage_bps:.1f} bps "
                f"(expected=${expected_price:.2f}, got=${fill_price:.2f})"
            )

        return slippage_bps

    def get_avg_slippage(self, symbol: Optional[str] = None) -> float:
        """Get average slippage in bps for a symbol or overall."""
        if symbol:
            history = self._history.get(symbol, deque())
            return sum(history) / len(history) if history else 0.0

        # Overall
        all_slips = []
        for h in self._history.values():
            all_slips.extend(h)
        return sum(all_slips) / len(all_slips) if all_slips else 0.0

    def get_stats(self, symbol: Optional[str] = None) -> dict:
        """Get detailed slippage statistics."""
        if symbol:
            history = list(self._history.get(symbol, []))
        else:
            history = []
            for h in self._history.values():
                history.extend(h)

        if not history:
            return {"avg_bps": 0.0, "max_bps": 0.0, "min_bps": 0.0, "count": 0}

        return {
            "avg_bps": sum(history) / len(history),
            "max_bps": max(history),
            "min_bps": min(history),
            "count": len(history),
        }
