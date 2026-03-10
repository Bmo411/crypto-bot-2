"""
Tests for PositionManager — fill-only position updates and PnL calculation.
"""

import asyncio
import pytest
import time
from unittest.mock import AsyncMock, MagicMock

from core.events import FillEvent
from core.models import Position
from positions.position_manager import PositionManager


@pytest.fixture
def mock_repo():
    """Create a mock repository."""
    repo = MagicMock()
    repo.upsert_position = AsyncMock()
    repo.get_all_positions = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def pos_mgr(mock_repo):
    return PositionManager(mock_repo)


class TestFillProcessing:
    """Test position state updates from fills."""

    @pytest.mark.asyncio
    async def test_open_long_from_flat(self, pos_mgr):
        """BUY fill from FLAT → LONG position."""
        fill = FillEvent(
            timestamp=time.time(),
            symbol="BTC/USD",
            broker_order_id="abc",
            side="BUY",
            quantity=0.1,
            fill_price=50000.0,
        )

        trade = await pos_mgr.on_fill(fill)

        pos = pos_mgr.get_position("BTC/USD")
        assert pos.side == "LONG"
        assert pos.quantity == 0.1
        assert pos.avg_entry_price == 50000.0
        assert trade is None  # no round-trip yet

    @pytest.mark.asyncio
    async def test_close_long(self, pos_mgr):
        """SELL fill that closes LONG → FLAT + TradeRecord."""
        # Open long
        open_fill = FillEvent(
            timestamp=time.time(),
            symbol="ETH/USD",
            broker_order_id="open1",
            side="BUY",
            quantity=1.0,
            fill_price=3000.0,
        )
        await pos_mgr.on_fill(open_fill)

        # Close long with profit
        close_fill = FillEvent(
            timestamp=time.time() + 60,
            symbol="ETH/USD",
            broker_order_id="close1",
            side="SELL",
            quantity=1.0,
            fill_price=3100.0,
        )
        trade = await pos_mgr.on_fill(close_fill)

        pos = pos_mgr.get_position("ETH/USD")
        assert pos.side == "FLAT"
        assert pos.quantity == 0.0

        # Trade record should show profit
        assert trade is not None
        assert trade.pnl == pytest.approx(100.0)  # (3100 - 3000) * 1.0
        assert trade.pnl_pct > 0

    @pytest.mark.asyncio
    async def test_close_short(self, pos_mgr):
        """BUY fill that closes SHORT → FLAT + TradeRecord."""
        # Open short
        await pos_mgr.on_fill(FillEvent(
            timestamp=time.time(),
            symbol="SOL/USD",
            broker_order_id="s1",
            side="SELL",
            quantity=10.0,
            fill_price=100.0,
        ))

        # Close short with profit
        trade = await pos_mgr.on_fill(FillEvent(
            timestamp=time.time() + 60,
            symbol="SOL/USD",
            broker_order_id="s2",
            side="BUY",
            quantity=10.0,
            fill_price=95.0,
        ))

        pos = pos_mgr.get_position("SOL/USD")
        assert pos.side == "FLAT"
        assert trade is not None
        assert trade.pnl == pytest.approx(50.0)  # (100 - 95) * 10

    @pytest.mark.asyncio
    async def test_add_to_position(self, pos_mgr):
        """Additional BUY should increase quantity and update avg price."""
        await pos_mgr.on_fill(FillEvent(
            timestamp=time.time(),
            symbol="BTC/USD",
            broker_order_id="a1",
            side="BUY",
            quantity=0.1,
            fill_price=50000.0,
        ))

        await pos_mgr.on_fill(FillEvent(
            timestamp=time.time(),
            symbol="BTC/USD",
            broker_order_id="a2",
            side="BUY",
            quantity=0.1,
            fill_price=51000.0,
        ))

        pos = pos_mgr.get_position("BTC/USD")
        assert pos.quantity == pytest.approx(0.2)
        assert pos.avg_entry_price == pytest.approx(50500.0)

    @pytest.mark.asyncio
    async def test_partial_close(self, pos_mgr):
        """Partial SELL should reduce quantity but stay LONG."""
        await pos_mgr.on_fill(FillEvent(
            timestamp=time.time(),
            symbol="ETH/USD",
            broker_order_id="p1",
            side="BUY",
            quantity=2.0,
            fill_price=3000.0,
        ))

        trade = await pos_mgr.on_fill(FillEvent(
            timestamp=time.time(),
            symbol="ETH/USD",
            broker_order_id="p2",
            side="SELL",
            quantity=1.0,
            fill_price=3100.0,
        ))

        pos = pos_mgr.get_position("ETH/USD")
        assert pos.side == "LONG"
        assert pos.quantity == pytest.approx(1.0)
        assert trade is None  # partial close, no round-trip


class TestPositionModel:
    """Test Position model methods."""

    def test_pnl_long(self):
        pos = Position(
            symbol="BTC/USD", side="LONG",
            quantity=0.1, avg_entry_price=50000.0,
        )
        pnl = pos.calculate_unrealized_pnl(51000.0)
        assert pnl == pytest.approx(100.0)  # (51000-50000)*0.1

    def test_pnl_short(self):
        pos = Position(
            symbol="ETH/USD", side="SHORT",
            quantity=1.0, avg_entry_price=3000.0,
        )
        pnl = pos.calculate_unrealized_pnl(2900.0)
        assert pnl == pytest.approx(100.0)  # (3000-2900)*1.0

    def test_pnl_flat(self):
        pos = Position(symbol="SOL/USD")
        pnl = pos.calculate_unrealized_pnl(100.0)
        assert pnl == 0.0

    def test_is_open(self):
        pos = Position(symbol="X", side="LONG", quantity=1.0)
        assert pos.is_open is True

        flat = Position(symbol="Y")
        assert flat.is_open is False
