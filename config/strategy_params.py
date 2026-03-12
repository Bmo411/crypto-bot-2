"""
TradingBot V5 — Strategy Hyperparameters

All tunable strategy parameters in one place.
Frozen dataclass for safety — no runtime mutation.

PAPER TRADING — AGGRESSIVE MODE (targeting ~10% monthly)
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MeanReversionParams:
    """Parameters for the Mean Reversion Z-Score strategy."""

    # ── Lookback ────────────────────────────────────────────────
    lookback: int = 200                     # bars in rolling window (was 50 — 4x more history)
    timeframe: str = "1m"                   # bar interval

    # ── Z-Score Thresholds ──────────────────────────────────────
    entry_threshold: float = 2.0            # |Z| > 2.0 → entry signal (was 1.5, stronger signals)
    exit_threshold: float = 0.5             # |Z| < 0.5 → exit signal (was 0.3)

    # ── Stop Loss / Take Profit ─────────────────────────────────
    stop_loss_pct: float = 0.008            # 0.8% (was 1.0% — tighter stops)
    take_profit_pct: float = 0.025          # 2.5% (was 1.2% — let winners run)

    # ── Trend Filter ────────────────────────────────────────────
    trend_sma_period: int = 200             # SMA period for trend
    trend_slope_threshold: float = 0.005    # was 0.0001 — 50x less sensitive, allows more trades

    # ── Volatility Filter ───────────────────────────────────────
    atr_period: int = 14                    # ATR lookback
    vol_low_threshold: float = 0.0002       # was 0.0005 — allow quieter crypto periods
    vol_high_threshold: float = 0.05        # was 0.02 — allow higher volatility (crypto swings)

    # ── Cooldown ────────────────────────────────────────────────
    cooldown_bars: int = 3                  # was 5 — faster re-entry after exits

    # ── Position Sizing Overrides ───────────────────────────────
    max_risk_per_trade: float | None = 0.005    # 0.5% risk per trade (was None → 0.3%)
    max_position_pct: float | None = 0.15       # 15% max per position (was None → 10%)


# Default instance
STRATEGY_PARAMS = MeanReversionParams()
