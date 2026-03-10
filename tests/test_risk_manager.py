"""
Tests for RiskManager — position sizing, daily loss limits, and signal validation.
"""

import pytest
from config.strategy_params import MeanReversionParams
from core.events import SignalEvent
from risk.risk_manager import RiskManager


@pytest.fixture
def risk_mgr():
    params = MeanReversionParams(stop_loss_pct=0.01)
    mgr = RiskManager(params)
    mgr.update_equity(84000.0, 168000.0)
    return mgr


class TestPositionSizing:
    """Test fixed-risk position sizing."""

    def test_basic_sizing(self, risk_mgr):
        """Position size should respect risk budget and max position cap."""
        signal = SignalEvent(
            symbol="BTC/USD",
            signal_type="LONG_ENTRY",
            price=50000.0,
            strength=2.0,
        )

        qty = risk_mgr.calculate_position_size(signal)
        assert qty > 0

        # Risk budget: 84000 * 0.003 = $252
        # Stop distance: 50000 * 0.01 = $500
        # Risk qty: 252 / 500 = 0.504
        # BUT max position: 84000 * 0.10 = $8,400 → 8400 / 50000 = 0.168
        # 0.168 < 0.504 → capped at max position
        expected_qty = 8400.0 / 50000.0  # 0.168
        assert qty == pytest.approx(expected_qty, rel=0.01)

    def test_max_position_cap(self, risk_mgr):
        """Position should be capped at 10% of equity."""
        signal = SignalEvent(
            symbol="MATIC/USD",
            signal_type="LONG_ENTRY",
            price=0.50,  # very cheap → risk qty would be huge
            strength=2.0,
        )

        qty = risk_mgr.calculate_position_size(signal)

        # Max notional: 84000 * 0.10 = $8,400
        # Max qty: 8400 / 0.50 = 16,800
        max_qty = 8400.0 / 0.50
        assert qty <= max_qty + 1  # allow small float tolerance

    def test_zero_price_returns_zero(self, risk_mgr):
        """Zero price should return zero quantity."""
        signal = SignalEvent(
            symbol="BTC/USD",
            signal_type="LONG_ENTRY",
            price=0.0,
        )
        assert risk_mgr.calculate_position_size(signal) == 0.0


class TestSignalValidation:
    """Test risk manager signal approval/rejection."""

    def test_approve_entry(self, risk_mgr):
        """Normal entry signal should be approved."""
        signal = SignalEvent(
            symbol="BTC/USD",
            signal_type="LONG_ENTRY",
            price=50000.0,
        )
        approved, event = risk_mgr.validate_signal(signal)
        assert approved is True
        assert event is None

    def test_approve_exit_always(self, risk_mgr):
        """Exit signals should always be approved."""
        risk_mgr._trading_halted = True
        risk_mgr._halt_reason = "TEST"

        signal = SignalEvent(
            symbol="BTC/USD",
            signal_type="LONG_EXIT",
            price=50000.0,
        )
        approved, event = risk_mgr.validate_signal(signal)
        assert approved is True

    def test_reject_max_positions(self, risk_mgr):
        """Should reject when max positions reached."""
        risk_mgr.update_position_count(5)  # max is 5

        signal = SignalEvent(
            symbol="BTC/USD",
            signal_type="LONG_ENTRY",
            price=50000.0,
        )
        approved, event = risk_mgr.validate_signal(signal)
        assert approved is False
        assert "Max positions" in event.reason

    def test_reject_when_halted(self, risk_mgr):
        """Should reject entries when trading is halted."""
        risk_mgr._trading_halted = True
        risk_mgr._halt_reason = "DAILY DRAWDOWN"

        signal = SignalEvent(
            symbol="BTC/USD",
            signal_type="LONG_ENTRY",
            price=50000.0,
        )
        approved, event = risk_mgr.validate_signal(signal)
        assert approved is False
        assert "halted" in event.reason.lower()


class TestDailyDrawdown:
    """Test daily loss circuit breaker."""

    def test_drawdown_halt(self, risk_mgr):
        """Should halt trading when daily loss exceeds limit."""
        # 3% of 84000 = $2,520
        risk_mgr.update_daily_pnl(-2600.0)
        assert risk_mgr.is_halted is True
        assert "DRAWDOWN" in risk_mgr.halt_reason

    def test_drawdown_reset(self, risk_mgr):
        """Daily reset should lift the halt."""
        risk_mgr.update_daily_pnl(-2600.0)
        assert risk_mgr.is_halted is True

        risk_mgr.reset_daily()
        assert risk_mgr.is_halted is False
