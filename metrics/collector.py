"""
TradingBot V5 — Metrics Collector

Aggregates real-time events into periodic metric snapshots.
Persists equity curve and strategy metrics to DB.
"""

import asyncio
import logging
import time
from typing import Optional

from config.settings import SETTINGS
from core.models import TradeRecord, EquitySnapshot
from metrics.performance import PerformanceCalculator
from positions.position_manager import PositionManager
from risk.risk_manager import RiskManager
from storage.repository import Repository

log = logging.getLogger("metrics.collector")


class MetricsCollector:
    """
    Real-time metric aggregation.

    Periodically:
      1. Compute performance metrics from trade history
      2. Snapshot equity curve
      3. Persist to DB
    """

    def __init__(
        self,
        position_manager: PositionManager,
        risk_manager: RiskManager,
        repository: Repository,
    ):
        self._pos_mgr = position_manager
        self._risk_mgr = risk_manager
        self._repo = repository

        self._high_water_mark: float = SETTINGS.initial_capital
        self._daily_start_equity: float = SETTINGS.initial_capital
        self._equity: float = SETTINGS.initial_capital
        self._cash: float = SETTINGS.initial_capital
        self._buying_power: float = SETTINGS.initial_capital * 2

        self._completed_trades: list[TradeRecord] = []
        self._running = False

    @property
    def equity(self) -> float:
        return self._equity

    @property
    def high_water_mark(self) -> float:
        return self._high_water_mark

    def record_trade(self, trade: TradeRecord) -> None:
        """Called when a round-trip trade is completed."""
        self._completed_trades.append(trade)

    def update_account(
        self, equity: float, cash: float, buying_power: float
    ) -> None:
        """Update from reconciliation."""
        self._equity = equity
        self._cash = cash
        self._buying_power = buying_power
        if equity > self._high_water_mark:
            self._high_water_mark = equity

    async def run(self) -> None:
        """Periodic metric snapshot loop."""
        self._running = True
        while self._running:
            await asyncio.sleep(SETTINGS.metrics_snapshot_interval)
            try:
                await self._snapshot()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Metrics snapshot error: {e}")

    async def stop(self) -> None:
        self._running = False

    async def _snapshot(self) -> None:
        """Take a metrics snapshot and persist."""
        now = time.time()

        # Compute positions value
        total_pos_value = 0.0
        for pos in self._pos_mgr.positions.values():
            total_pos_value += pos.notional_value

        # Daily PnL
        daily_pnl = self._equity - self._daily_start_equity
        daily_pnl_pct = (
            daily_pnl / self._daily_start_equity
            if self._daily_start_equity > 0 else 0.0
        )

        # Drawdown
        drawdown_pct = 0.0
        if self._high_water_mark > 0:
            drawdown_pct = (
                (self._equity - self._high_water_mark)
                / self._high_water_mark
            )

        # Persist equity snapshot
        await self._repo.insert_equity_snapshot(
            timestamp=now,
            equity=self._equity,
            cash=self._cash,
            buying_power=self._buying_power,
            total_positions=total_pos_value,
            open_positions=self._pos_mgr.open_count,
            daily_pnl=daily_pnl,
            daily_pnl_pct=daily_pnl_pct,
            drawdown_pct=drawdown_pct,
            high_water_mark=self._high_water_mark,
        )

        # Update risk manager
        self._risk_mgr.update_daily_pnl(daily_pnl)

    def get_metrics_snapshot(self) -> dict:
        """Get full metrics for dashboard API."""
        perf = PerformanceCalculator.compute(
            self._completed_trades,
            equity=self._equity,
            high_water_mark=self._high_water_mark,
        )

        daily_pnl = self._equity - self._daily_start_equity

        return {
            "equity": self._equity,
            "cash": self._cash,
            "buying_power": self._buying_power,
            "daily_pnl": daily_pnl,
            "daily_pnl_pct": (
                daily_pnl / self._daily_start_equity
                if self._daily_start_equity > 0 else 0.0
            ),
            "high_water_mark": self._high_water_mark,
            "open_positions": self._pos_mgr.open_count,
            "trading_halted": self._risk_mgr.is_halted,
            "halt_reason": self._risk_mgr.halt_reason,
            **perf,
        }

    def reset_daily(self) -> None:
        """Reset daily counters at UTC midnight."""
        self._daily_start_equity = self._equity
        self._risk_mgr.reset_daily()
        log.info(f"Daily metrics reset — start equity: ${self._equity:.2f}")
