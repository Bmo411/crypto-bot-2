"""
TradingBot V5 — Tick Normalizer

Normalizes raw Tick objects into a standard format.
Handles edge cases like zero-price ticks or duplicate timestamps.
"""

import logging
from typing import Optional
from core.events import Tick

log = logging.getLogger("market_data.normalizer")


class TickNormalizer:
    """Filter and normalize incoming ticks."""

    def __init__(self):
        self._last_prices: dict[str, float] = {}
        self._last_timestamps: dict[str, float] = {}
        self._filtered_count = 0

    def normalize(self, tick: Tick) -> Optional[Tick]:
        """
        Validate and normalize a tick.
        Returns None if the tick should be dropped.
        """
        # Drop zero or negative prices
        if tick.price <= 0:
            self._filtered_count += 1
            return None

        # Drop zero-size trades
        if tick.size <= 0:
            self._filtered_count += 1
            return None

        # Drop exact duplicate timestamps for same symbol
        last_ts = self._last_timestamps.get(tick.symbol, 0)
        if tick.timestamp <= last_ts:
            # Allow same-timestamp if price differs (multiple fills)
            last_price = self._last_prices.get(tick.symbol, 0)
            if tick.price == last_price:
                self._filtered_count += 1
                return None

        self._last_prices[tick.symbol] = tick.price
        self._last_timestamps[tick.symbol] = tick.timestamp

        return tick

    @property
    def filtered_count(self) -> int:
        return self._filtered_count
