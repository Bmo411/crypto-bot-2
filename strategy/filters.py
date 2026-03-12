"""
TradingBot V5 — Trend and Volatility Filters

Applied before signal generation to avoid trading in
unfavorable market regimes.

BUG FIX: Volatility filter now skips carry-forward bars
(where open == high == low == close) before computing ATR.
Without this fix, quiet crypto periods would zero-out ATR
and silently block all signals.
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

    def __init__(self, period: int = 200, slope_threshold: float = 0.005):
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

    IMPORTANT: Carry-forward bars (high == low == close, zero real movement)
    are excluded from the ATR calculation so quiet crypto periods do not
    mistakenly collapse ATR to zero and block all signals.
    """

    def __init__(
        self,
        atr_period: int = 14,
        low_threshold: float = 0.0002,
        high_threshold: float = 0.05,
    ):
        self._atr_period = atr_period
        self._low_threshold = low_threshold
        self._high_threshold = high_threshold

    def _real_closes(self, closes: np.ndarray) -> np.ndarray:
        """
        Filter out carry-forward bars (consecutive identical prices).

        A carry-forward bar emits open == high == low == close == last_close.
        When consecutive closes are identical, no real price movement occurred —
        including them in ATR calculation drives ATR to zero.

        We keep a close only if it differs from its predecessor.
        We always keep the final close (current price reference).
        """
        if len(closes) < 2:
            return closes

        # Build mask: keep index i if closes[i] != closes[i-1], always keep last
        diffs = np.diff(closes)
        keep = np.append(diffs != 0, True)   # True at positions with movement + last
        filtered = closes[keep]

        # Need at least atr_period + 1 real bars; if not, return all (fallback)
        if len(filtered) < self._atr_period + 1:
            return closes           # not enough real bars — use all (may return True below)
        return filtered

    def is_tradeable(self, closes: np.ndarray) -> bool:
        """Check if current volatility is within acceptable range."""
        atr_ratio = self.compute_atr(closes)

        if atr_ratio == 0.0:
            # Could not compute meaningful ATR — allow trading rather than silently block
            log.debug("ATR = 0 after filtering carry-forward bars — allowing signal.")
            return True

        return self._low_threshold <= atr_ratio <= self._high_threshold

    def compute_atr(self, closes: np.ndarray) -> float:
        """Compute the ATR ratio, excluding carry-forward bars."""
        real = self._real_closes(closes)

        if len(real) < self._atr_period + 1:
            return 0.0

        returns = np.abs(np.diff(real[-self._atr_period - 1:]))
        atr = np.mean(returns)
        current_price = closes[-1]    # always use the actual last price
        return atr / current_price if current_price > 0 else 0.0
