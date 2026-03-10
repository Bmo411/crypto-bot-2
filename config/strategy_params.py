"""
TradingBot V5 — Strategy Hyperparameters

All tunable strategy parameters in one place.
Frozen dataclass for safety — no runtime mutation.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MeanReversionParams:
    """Parameters for the Mean Reversion Z-Score strategy."""

    # ── Lookback ────────────────────────────────────────────────
    lookback: int = 50                      # bars in rolling window
    timeframe: str = "1m"                   # bar interval

    # ── Z-Score Thresholds ──────────────────────────────────────
    entry_threshold: float = 1.5            # |Z| > 1.5 → entry signal
    exit_threshold: float = 0.3             # |Z| < 0.3 → exit signal

    # ── Stop Loss / Take Profit ─────────────────────────────────
    stop_loss_pct: float = 0.01             # 1.0%
    take_profit_pct: float = 0.012          # 1.2%

    # ── Trend Filter ────────────────────────────────────────────
    trend_sma_period: int = 200             # SMA period for trend
    trend_slope_threshold: float = 0.0001   # minimum slope to declare trend

    # ── Volatility Filter ───────────────────────────────────────
    atr_period: int = 14                    # ATR lookback
    vol_low_threshold: float = 0.0005       # ATR/price ratio — skip if below
    vol_high_threshold: float = 0.02        # ATR/price ratio — skip if above

    # ── Cooldown ────────────────────────────────────────────────
    cooldown_bars: int = 5                  # bars to wait after exit

    # ── Position Sizing Overrides ───────────────────────────────
    # (defaults come from Settings, but strategy can narrow them)
    max_risk_per_trade: float | None = None
    max_position_pct: float | None = None


# Default instance
STRATEGY_PARAMS = MeanReversionParams()
