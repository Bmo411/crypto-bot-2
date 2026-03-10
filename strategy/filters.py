"""
TradingBot V5 — Trend and Volatility Filters

Applied before signal generation to avoid trading in
unfavorable market regimes.
"""

import numpy as np
import logging

log = logging.getLogger("strategy.filters")


class TrendFilter:
    """
    Simple Moving Average slope-based trend detection.

    Returns:
        +1  = uptrend (only longs allowed)
        -1  = downtrend (only shorts allowed)
         0  = ranging (both allowed)
    """

    def __init__(self, period: int = 200, slope_threshold: float = 0.0001):
        self._period = period
        self._slope_threshold = slope_threshold

    def evaluate(self, closes: np.ndarray) -> int:
        """
        Compute trend direction from SMA slope.

        Uses the last `period` closes. If fewer bars are available,
        uses all available data but requires at least 20 bars.
        """
        if len(closes) < 20:
            return 0  # not enough data → neutral

        # Use min(period, available) for SMA
        window = min(self._period, len(closes))
        sma = np.mean(closes[-window:])
        sma_prev = np.mean(closes[-window - 1:-1]) if len(closes) > window else sma

        # Normalized slope (price-independent)
        if sma == 0:
            return 0
        slope = (sma - sma_prev) / sma

        if slope > self._slope_threshold:
            return 1   # uptrend
        elif slope < -self._slope_threshold:
            return -1  # downtrend
        else:
            return 0   # ranging


class VolatilityFilter:
    """
    ATR-based volatility regime filter.

    Rejects signals in:
      - Extremely low volatility (choppy, whipsaw-prone)
      - Extremely high volatility (crash/spike, unpredictable)
    """

    def __init__(
        self,
        atr_period: int = 14,
        low_threshold: float = 0.0005,
        high_threshold: float = 0.02,
    ):
        self._atr_period = atr_period
        self._low_threshold = low_threshold
        self._high_threshold = high_threshold

    def is_tradeable(self, closes: np.ndarray) -> bool:
        """
        Check if current volatility is within acceptable range.

        Uses ATR approximation from close-to-close changes (since we
        only have close prices in the rolling window, not full OHLC).
        """
        if len(closes) < self._atr_period + 1:
            return True  # not enough data → allow

        # ATR approximation: average of absolute returns
        returns = np.abs(np.diff(closes[-self._atr_period - 1:])) 
        atr = np.mean(returns)

        # Normalize by current price
        current_price = closes[-1]
        if current_price <= 0:
            return False
        atr_ratio = atr / current_price

        return self._low_threshold <= atr_ratio <= self._high_threshold

    def compute_atr(self, closes: np.ndarray) -> float:
        """Compute the ATR ratio for logging/features."""
        if len(closes) < self._atr_period + 1:
            return 0.0
        returns = np.abs(np.diff(closes[-self._atr_period - 1:]))
        atr = np.mean(returns)
        current_price = closes[-1]
        return atr / current_price if current_price > 0 else 0.0
