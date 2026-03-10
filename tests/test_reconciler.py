"""
Tests for Reconciler — discrepancy detection and auto-correction.
"""

import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch

from reconciliation.reconciler import Reconciler
from positions.position_manager import PositionManager
from risk.risk_manager import RiskManager
from config.strategy_params import MeanReversionParams


@pytest.fixture
def mock_components():
    """Create mock components for reconciler."""
    exec_engine = MagicMock()
    repo = MagicMock()
    repo.insert_reconciliation = AsyncMock()
    repo.upsert_position = AsyncMock()
    repo.get_all_positions = AsyncMock(return_value=[])

    pos_mgr = PositionManager(repo)
    risk_mgr = RiskManager(MeanReversionParams())
    risk_mgr.update_equity(84000.0, 168000.0)

    return exec_engine, pos_mgr, risk_mgr, repo


@pytest.fixture
def reconciler(mock_components):
    exec_engine, pos_mgr, risk_mgr, repo = mock_components
    return Reconciler(exec_engine, pos_mgr, risk_mgr, repo)


class TestDiscrepancyDetection:
    """Test broker vs local state comparison."""

    @pytest.mark.asyncio
    async def test_no_discrepancies(self, reconciler, mock_components):
        """No action when broker and local match."""
        exec_engine, pos_mgr, risk_mgr, repo = mock_components

        # Mock broker returns empty
        mock_account = MagicMock()
        mock_account.equity = "84000.0"
        mock_account.buying_power = "168000.0"

        exec_engine.get_account_sync = MagicMock(return_value=mock_account)
        exec_engine.get_positions_sync = MagicMock(return_value=[])

        result = await reconciler.reconcile()

        assert result["discrepancies"] == 0
        assert result["action"] == "NONE"

    @pytest.mark.asyncio
    async def test_detect_missing_local(self, reconciler, mock_components):
        """Should detect position at broker but not locally."""
        exec_engine, pos_mgr, risk_mgr, repo = mock_components

        mock_account = MagicMock()
        mock_account.equity = "84000.0"
        mock_account.buying_power = "168000.0"

        mock_pos = MagicMock()
        mock_pos.symbol = "BTC/USD"
        mock_pos.qty = "0.1"
        mock_pos.avg_entry_price = "50000.0"
        mock_pos.market_value = "5000.0"
        mock_pos.unrealized_pl = "100.0"

        exec_engine.get_account_sync = MagicMock(return_value=mock_account)
        exec_engine.get_positions_sync = MagicMock(return_value=[mock_pos])

        result = await reconciler.reconcile()

        assert result["discrepancies"] == 1
        assert result["action"] == "AUTO_CORRECTED"

        # Position should now be in local state
        pos = pos_mgr.get_position("BTC/USD")
        assert pos.side == "LONG"
        assert pos.quantity == 0.1

    @pytest.mark.asyncio
    async def test_detect_stale_local(self, reconciler, mock_components):
        """Should detect position locally but not at broker."""
        exec_engine, pos_mgr, risk_mgr, repo = mock_components

        # Set local position
        await pos_mgr.set_from_broker("ETH/USD", "LONG", 1.0, 3000.0)

        mock_account = MagicMock()
        mock_account.equity = "84000.0"
        mock_account.buying_power = "168000.0"

        exec_engine.get_account_sync = MagicMock(return_value=mock_account)
        exec_engine.get_positions_sync = MagicMock(return_value=[])

        result = await reconciler.reconcile()

        assert result["discrepancies"] == 1

        # Local position should be cleared
        pos = pos_mgr.get_position("ETH/USD")
        assert pos.side == "FLAT"
