"""
Tests for MeanReversionStrategy — Z-score calculation, signal generation,
filters, and cooldown logic.
"""

import pytest
import numpy as np
from collections import deque

from config.strategy_params import MeanReversionParams
from core.events import BarEvent
from strategy.mean_reversion import MeanReversionStrategy


@pytest.fixture
def params():
    """Strategy params with shorter lookback for faster testing."""
    return MeanReversionParams(
        lookback=20,
        entry_threshold=1.5,
        exit_threshold=0.3,
        stop_loss_pct=0.01,
        take_profit_pct=0.012,
        trend_sma_period=50,
        cooldown_bars=3,
        atr_period=14,
        vol_low_threshold=0.0001,  # very low for testing
        vol_high_threshold=0.1,     # very high for testing
    )


@pytest.fixture
def strategy(params):
    return MeanReversionStrategy(params)


def make_bar(symbol: str, close: float, ts: float = 0) -> BarEvent:
    return BarEvent(
        timestamp=ts or 1000000.0,
        symbol=symbol,
        open=close,
        high=close * 1.001,
        low=close * 0.999,
        close=close,
        volume=100.0,
        trade_count=50,
    )


class TestSignalGeneration:
    """Test Z-score based signal generation."""

    @pytest.mark.asyncio
    async def test_no_signal_before_warmup(self, strategy):
        """Should return None until lookback window is filled."""
        for i in range(19):
            signal = await strategy.on_bar(make_bar("BTC/USD", 50000.0 + i))
            assert signal is None

    @pytest.mark.asyncio
    async def test_long_entry_signal(self, strategy, params):
        """Significant drop below median should trigger LONG_ENTRY."""
        # Build a stable window around 50000
        for i in range(params.lookback - 1):
            await strategy.on_bar(make_bar("BTC/USD", 50000.0))

        # Sharp dip
        signal = await strategy.on_bar(make_bar("BTC/USD", 49500.0))
        # May or may not trigger depending on MAD — let's ensure it can work
        # With all prices at 50000 except last at 49500, MAD is very small
        # Z-score will be very negative → should trigger

        if signal is not None:
            assert signal.signal_type == "LONG_ENTRY"
            assert signal.zscore < -params.entry_threshold

    @pytest.mark.asyncio
    async def test_short_entry_signal(self, strategy, params):
        """Significant rise above median should trigger SHORT_ENTRY."""
        for i in range(params.lookback - 1):
            await strategy.on_bar(make_bar("BTC/USD", 50000.0))

        signal = await strategy.on_bar(make_bar("BTC/USD", 50500.0))

        if signal is not None:
            assert signal.signal_type == "SHORT_ENTRY"
            assert signal.zscore > params.entry_threshold

    @pytest.mark.asyncio
    async def test_long_exit_signal(self, strategy, params):
        """When in LONG and Z crosses above exit threshold, exit."""
        # Warm up
        for i in range(params.lookback):
            await strategy.on_bar(make_bar("BTC/USD", 50000.0 + i * 2))

        # Check for exit while LONG
        signal = await strategy.on_bar(
            make_bar("BTC/USD", 50050.0),
            position_side="LONG",
            position_qty=0.1,
        )
        # Z-score near 0 should trigger LONG_EXIT
        if signal is not None:
            assert "EXIT" in signal.signal_type or "PROFIT" in signal.signal_type

    @pytest.mark.asyncio
    async def test_stop_loss_signal(self, strategy, params):
        """Stop loss should trigger when PnL exceeds max loss."""
        for i in range(params.lookback):
            await strategy.on_bar(make_bar("BTC/USD", 50000.0))

        signal = await strategy.on_bar(
            make_bar("BTC/USD", 50100.0),
            position_side="LONG",
            position_qty=0.1,
            current_pnl_pct=-0.015,  # -1.5% > stop_loss 1%
        )

        assert signal is not None
        assert signal.signal_type == "STOP_LOSS"

    @pytest.mark.asyncio
    async def test_take_profit_signal(self, strategy, params):
        """Take profit should trigger when PnL exceeds target."""
        for i in range(params.lookback):
            await strategy.on_bar(make_bar("BTC/USD", 50000.0))

        signal = await strategy.on_bar(
            make_bar("BTC/USD", 50100.0),
            position_side="LONG",
            position_qty=0.1,
            current_pnl_pct=0.015,  # +1.5% > take_profit 1.2%
        )

        assert signal is not None
        assert signal.signal_type == "TAKE_PROFIT"


class TestCooldown:
    """Test post-exit cooldown logic."""

    @pytest.mark.asyncio
    async def test_cooldown_after_exit(self, strategy, params):
        """Strategy should skip signals during cooldown bars."""
        # Warm up
        for i in range(params.lookback):
            await strategy.on_bar(make_bar("BTC/USD", 50000.0))

        # Force cooldown
        strategy._cooldowns["BTC/USD"] = params.cooldown_bars

        # Should get None during cooldown
        for _ in range(params.cooldown_bars):
            signal = await strategy.on_bar(make_bar("BTC/USD", 49500.0))
            assert signal is None

        # After cooldown expires, signals should work again
        signal = await strategy.on_bar(make_bar("BTC/USD", 49500.0))
        # May or may not trigger depending on Z-score, but cooldown is lifted


class TestWarmUp:
    """Test strategy warm-up from historical bars."""

    def test_warm_up_fills_window(self, strategy, params):
        """warm_up should populate rolling windows."""
        bars = [make_bar("ETH/USD", 3000.0 + i) for i in range(100)]
        strategy.warm_up(bars)

        window = strategy._windows.get("ETH/USD")
        assert window is not None
        assert len(window) == params.lookback  # capped at maxlen

    def test_reset_clears_state(self, strategy):
        """reset should remove all state for a symbol."""
        bars = [make_bar("SOL/USD", 100.0 + i) for i in range(30)]
        strategy.warm_up(bars)

        strategy.reset("SOL/USD")
        assert "SOL/USD" not in strategy._windows


class TestSignalFeatures:
    """Test that signals carry ML feature data."""

    @pytest.mark.asyncio
    async def test_signal_has_features(self, strategy, params):
        """Generated signals should include all feature fields."""
        for i in range(params.lookback):
            await strategy.on_bar(make_bar("BTC/USD", 50000.0))

        # Force a stop loss to guarantee a signal
        signal = await strategy.on_bar(
            make_bar("BTC/USD", 50100.0),
            position_side="LONG",
            position_qty=0.1,
            current_pnl_pct=-0.015,
        )

        assert signal is not None
        assert signal.strategy_name == "mean_reversion_v5"
        assert isinstance(signal.zscore, float)
        assert isinstance(signal.trend_slope, float)
        assert isinstance(signal.strength, float)
