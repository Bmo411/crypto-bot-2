"""
TradingBot V5 — Mean Reversion Strategy

Z-Score based mean reversion with trend and volatility filters.
Uses robust statistics (median/MAD) to reduce outlier sensitivity.

Strategy Flow:
  1. Update rolling window
  2. Compute Z-Score (close vs median, scaled by MAD)
  3. Apply trend filter (SMA slope)
  4. Apply volatility filter (ATR regime)
  5. Check entry/exit conditions
  6. Apply cooldown
  7. Emit SignalEvent or None
"""

import logging
import numpy as np
from collections import deque
from typing import Optional

from config.strategy_params import MeanReversionParams
from core.events import BarEvent, SignalEvent
from core.enums import SignalType
from strategy.base import AbstractStrategy
from strategy.filters import TrendFilter, VolatilityFilter

log = logging.getLogger("strategy.mean_reversion")


class MeanReversionStrategy(AbstractStrategy):
    """Robust Z-Score mean reversion with trend/volatility filters."""

    def __init__(self, params: MeanReversionParams):
        self._params = params

        # Per-symbol rolling price windows
        self._windows: dict[str, deque] = {}

        # Filters
        self._trend_filter = TrendFilter(
            period=params.trend_sma_period,
            slope_threshold=params.trend_slope_threshold,
        )
        self._vol_filter = VolatilityFilter(
            atr_period=params.atr_period,
            low_threshold=params.vol_low_threshold,
            high_threshold=params.vol_high_threshold,
        )

        # Per-symbol cooldown counter (bars remaining)
        self._cooldowns: dict[str, int] = {}

        # Running Z-score MA for feature tracking
        self._zscore_history: dict[str, deque] = {}

    @property
    def name(self) -> str:
        return "mean_reversion_v5"

    async def on_bar(
        self,
        bar: BarEvent,
        position_side: str = "FLAT",
        position_qty: float = 0.0,
        current_pnl_pct: float = 0.0,
    ) -> Optional[SignalEvent]:
        """Process a new bar and generate a signal if conditions are met."""
        symbol = bar.symbol

        # ── 1. Update rolling window ────────────────────────────
        if symbol not in self._windows:
            self._windows[symbol] = deque(maxlen=self._params.lookback)
            self._zscore_history[symbol] = deque(maxlen=20)

        self._windows[symbol].append(bar.close)

        # Need full window before generating signals
        if len(self._windows[symbol]) < self._params.lookback:
            return None

        closes = np.array(self._windows[symbol])

        # ── 2. Stop loss / take profit (ALWAYS checked first) ──
        # These are risk management exits and must fire regardless of
        # Z-score, volatility, or cooldown state.
        if position_side != "FLAT":
            atr_ratio = self._vol_filter.compute_atr(closes)

            if current_pnl_pct <= -self._params.stop_loss_pct:
                log.info(
                    f"[{symbol}] STOP LOSS triggered: PnL={current_pnl_pct:.4%}"
                )
                self._cooldowns[symbol] = self._params.cooldown_bars
                return self._make_signal(
                    bar, SignalType.STOP_LOSS.value, 0.0, 0.0, 0, atr_ratio
                )

            if current_pnl_pct >= self._params.take_profit_pct:
                log.info(
                    f"[{symbol}] TAKE PROFIT triggered: PnL={current_pnl_pct:.4%}"
                )
                self._cooldowns[symbol] = self._params.cooldown_bars
                return self._make_signal(
                    bar, SignalType.TAKE_PROFIT.value, 0.0, 0.0, 0, atr_ratio
                )

        # ── 3. Cooldown check ───────────────────────────────────
        if self._cooldowns.get(symbol, 0) > 0:
            self._cooldowns[symbol] -= 1
            return None

        # ── 4. Compute Z-Score (robust: median/MAD) ────────────
        median = float(np.median(closes))
        mad = float(np.median(np.abs(closes - median))) * 1.4826  # scale to σ
        if mad < 1e-10:
            return None  # perfectly flat — no signal

        zscore = (bar.close - median) / mad

        # Track Z-score MA for features
        self._zscore_history[symbol].append(zscore)
        zscore_ma = float(np.mean(self._zscore_history[symbol]))

        # ── 5. Apply trend filter ───────────────────────────────
        trend = self._trend_filter.evaluate(closes)

        # ── 6. Apply volatility filter ──────────────────────────
        vol_ok = self._vol_filter.is_tradeable(closes)
        atr_ratio = self._vol_filter.compute_atr(closes)

        if not vol_ok:
            log.debug(f"[{symbol}] Vol filter rejected: ATR ratio={atr_ratio:.6f}")
            return None

        # ── 7. Entry signals ────────────────────────────────────
        if position_side == "FLAT":
            # Long entry: Z < -threshold and trend is not down
            if zscore < -self._params.entry_threshold and trend >= 0:
                log.info(
                    f"[{symbol}] LONG ENTRY signal: Z={zscore:.3f}, "
                    f"trend={trend}, ATR={atr_ratio:.6f}"
                )
                return self._make_signal(
                    bar, SignalType.LONG_ENTRY.value,
                    zscore, zscore_ma, trend, atr_ratio,
                )

            # Short entry: Z > +threshold and trend is not up
            if zscore > self._params.entry_threshold and trend <= 0:
                log.info(
                    f"[{symbol}] SHORT ENTRY signal: Z={zscore:.3f}, "
                    f"trend={trend}, ATR={atr_ratio:.6f}"
                )
                return self._make_signal(
                    bar, SignalType.SHORT_ENTRY.value,
                    zscore, zscore_ma, trend, atr_ratio,
                )

        # ── 8. Exit signals ─────────────────────────────────────
        elif position_side == "LONG":
            if zscore > -self._params.exit_threshold:
                log.info(
                    f"[{symbol}] LONG EXIT signal: Z={zscore:.3f} "
                    f"crossed above {-self._params.exit_threshold}"
                )
                self._cooldowns[symbol] = self._params.cooldown_bars
                return self._make_signal(
                    bar, SignalType.LONG_EXIT.value,
                    zscore, zscore_ma, trend, atr_ratio,
                )

        elif position_side == "SHORT":
            if zscore < self._params.exit_threshold:
                log.info(
                    f"[{symbol}] SHORT EXIT signal: Z={zscore:.3f} "
                    f"crossed below {self._params.exit_threshold}"
                )
                self._cooldowns[symbol] = self._params.cooldown_bars
                return self._make_signal(
                    bar, SignalType.SHORT_EXIT.value,
                    zscore, zscore_ma, trend, atr_ratio,
                )

        return None

    def _make_signal(
        self,
        bar: BarEvent,
        signal_type: str,
        zscore: float,
        zscore_ma: float,
        trend: int,
        atr_ratio: float,
    ) -> SignalEvent:
        """Construct a SignalEvent with all feature data."""
        return SignalEvent(
            symbol=bar.symbol,
            signal_type=signal_type,
            price=bar.close,
            strength=abs(zscore),
            strategy_name=self.name,
            zscore=zscore,
            zscore_ma=zscore_ma,
            trend_slope=float(trend),
            volatility=atr_ratio,
            atr=atr_ratio,
        )

    def warm_up(self, bars: list[BarEvent]) -> None:
        """Feed historical bars to populate rolling windows."""
        for bar in bars:
            symbol = bar.symbol
            if symbol not in self._windows:
                self._windows[symbol] = deque(maxlen=self._params.lookback)
                self._zscore_history[symbol] = deque(maxlen=20)
            self._windows[symbol].append(bar.close)

        for symbol in self._windows:
            count = len(self._windows[symbol])
            log.info(f"[{symbol}] Strategy warmed up with {count} bars")

    def reset(self, symbol: str) -> None:
        """Reset internal state for a symbol."""
        self._windows.pop(symbol, None)
        self._zscore_history.pop(symbol, None)
        self._cooldowns.pop(symbol, None)
        log.info(f"[{symbol}] Strategy state reset")
