"""
TradingBot V5 — Metrics Collector

Aggregates real-time events into periodic metric snapshots.
Persists equity curve and strategy metrics to DB.

Alpaca is the source of truth:
  - Account data (equity/cash/buying_power) refreshed every 30s
  - Position data (unrealized PnL / current price) refreshed every 10s
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

    Two background refresh loops (started by run()):
      _account_refresh_loop  — every 30s: pulls equity/cash/buying_power from Alpaca
      _positions_refresh_loop — every 10s: pulls open positions + unrealized PnL from Alpaca

    Periodically (metrics_snapshot_interval):
      1. Snapshot equity curve → DB
      2. Update risk manager daily PnL
    """

    def __init__(
        self,
        position_manager: PositionManager,
        risk_manager: RiskManager,
        repository: Repository,
        broker_client=None,   # execution.broker_client.BrokerClient (optional for tests)
    ):
        self._pos_mgr = position_manager
        self._risk_mgr = risk_manager
        self._repo = repository
        self._broker = broker_client

        # ── Account state (sourced from Alpaca, NOT SETTINGS.initial_capital) ──
        # Initialise to initial_capital only as a safe default before first fetch
        self._high_water_mark: float = SETTINGS.initial_capital
        self._daily_start_equity: float = SETTINGS.initial_capital
        self._equity: float = SETTINGS.initial_capital
        self._cash: float = SETTINGS.initial_capital
        self._buying_power: float = SETTINGS.initial_capital * 2
        self._account_initialized: bool = False   # True after first real fetch

        self._completed_trades: list[TradeRecord] = []
        self._running = False

    # ── Properties ───────────────────────────────────────────────

    @property
    def equity(self) -> float:
        return self._equity

    @property
    def high_water_mark(self) -> float:
        return self._high_water_mark

    # ── Trade Recording ──────────────────────────────────────────

    def record_trade(self, trade: TradeRecord) -> None:
        """Called when a round-trip trade is completed."""
        self._completed_trades.append(trade)

    def update_account(
        self, equity: float, cash: float, buying_power: float
    ) -> None:
        """
        Update account data — called by Reconciler and the account refresh loop.
        This is the primary mechanism that makes the broker the source of truth.

        Also updates RiskManager so position sizing always reflects real equity.
        """
        if equity <= 0:
            log.warning(f"Ignoring invalid equity value: {equity}")
            return

        self._equity = equity
        self._cash = cash
        self._buying_power = buying_power

        if equity > self._high_water_mark:
            self._high_water_mark = equity

        # Keep RiskManager in sync — avoids stale $84K position sizing
        self._risk_mgr.update_equity(equity, buying_power)

        # On first real fetch, set the daily start baseline
        if not self._account_initialized:
            self._daily_start_equity = equity
            self._account_initialized = True
            log.info(
                f"Account initialized from Alpaca — "
                f"equity=${equity:,.2f}, daily_start=${equity:,.2f}"
            )

    # ── Main Run Loop ────────────────────────────────────────────

    async def run(self) -> None:
        """Start all metric loops concurrently."""
        self._running = True

        # Do an immediate account fetch before the loops start so the
        # dashboard shows real data from minute one
        if self._broker:
            await self._fetch_account_now()
            await self._fetch_positions_now()

        tasks = [
            asyncio.create_task(self._snapshot_loop(), name="metrics_snapshot"),
        ]
        if self._broker:
            tasks += [
                asyncio.create_task(
                    self._account_refresh_loop(), name="account_refresh"
                ),
                asyncio.create_task(
                    self._positions_refresh_loop(), name="positions_refresh"
                ),
            ]
        else:
            log.warning(
                "MetricsCollector started without BrokerClient — "
                "equity will not auto-refresh from Alpaca"
            )

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        self._running = False

    # ── Refresh Loops ────────────────────────────────────────────

    async def _account_refresh_loop(self) -> None:
        """Poll Alpaca account every account_refresh_interval seconds."""
        while self._running:
            await asyncio.sleep(SETTINGS.account_refresh_interval)
            if not self._running:
                break
            try:
                await self._fetch_account_now()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Account refresh error: {e}")

    async def _fetch_account_now(self) -> None:
        """Single account fetch + update."""
        try:
            account = await self._broker.get_account()
            if account is None:
                log.warning("BrokerClient returned None for account — skipping update")
                return
            self.update_account(
                equity=float(account.equity),
                cash=float(account.cash),
                buying_power=float(account.buying_power),
            )
        except Exception as e:
            log.error(f"_fetch_account_now failed: {e}")

    async def _positions_refresh_loop(self) -> None:
        """Poll Alpaca positions every positions_refresh_interval seconds."""
        while self._running:
            await asyncio.sleep(SETTINGS.positions_refresh_interval)
            if not self._running:
                break
            try:
                await self._fetch_positions_now()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Positions refresh error: {e}")

    async def _fetch_positions_now(self) -> None:
        """Single positions fetch + sync."""
        try:
            positions = await self._broker.get_all_positions()
            await self._pos_mgr.sync_from_broker(positions)
        except Exception as e:
            log.error(f"_fetch_positions_now failed: {e}")

    # ── Snapshot Loop ────────────────────────────────────────────

    async def _snapshot_loop(self) -> None:
        """Periodic metric snapshot loop (persists to DB)."""
        while self._running:
            await asyncio.sleep(SETTINGS.metrics_snapshot_interval)
            try:
                await self._snapshot()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Metrics snapshot error: {e}")

    async def _snapshot(self) -> None:
        """Take a metrics snapshot and persist to equity_curve table."""
        now = time.time()

        # Compute positions value (use notional value as fallback)
        total_pos_value = 0.0
        for pos in self._pos_mgr.positions.values():
            total_pos_value += pos.notional_value

        # Daily PnL
        daily_pnl = self._equity - self._daily_start_equity
        daily_pnl_pct = (
            daily_pnl / self._daily_start_equity
            if self._daily_start_equity > 0 else 0.0
        )

        # Drawdown — guard against NaN when high_water_mark == 0
        drawdown_pct = 0.0
        if self._high_water_mark > 0 and self._equity > 0:
            raw = (self._equity - self._high_water_mark) / self._high_water_mark
            # drawdown is the negative excursion below HWM (expressed as negative %)
            drawdown_pct = min(raw, 0.0)

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

    # ── Dashboard Snapshot ───────────────────────────────────────

    def get_metrics_snapshot(self) -> dict:
        """Get full metrics dict for dashboard API."""
        perf = PerformanceCalculator.compute(
            self._completed_trades,
            equity=self._equity,
            high_water_mark=self._high_water_mark,
        )

        daily_pnl = self._equity - self._daily_start_equity
        daily_pnl_pct = (
            daily_pnl / self._daily_start_equity
            if self._daily_start_equity > 0 else 0.0
        )

        # Compute total unrealized PnL from all open positions
        total_unrealized_pnl = sum(
            pos.unrealized_pnl
            for pos in self._pos_mgr.positions.values()
            if pos.is_open
        )

        # Drawdown guard
        drawdown_pct = 0.0
        if self._high_water_mark > 0 and self._equity > 0:
            drawdown_pct = min(
                (self._equity - self._high_water_mark) / self._high_water_mark,
                0.0,
            )

        return {
            "equity": self._equity,
            "cash": self._cash,
            "buying_power": self._buying_power,
            "daily_pnl": daily_pnl,
            "daily_pnl_pct": daily_pnl_pct,
            "high_water_mark": self._high_water_mark,
            "open_positions": self._pos_mgr.open_count,
            "total_unrealized_pnl": total_unrealized_pnl,
            "max_drawdown": drawdown_pct,
            "trading_halted": self._risk_mgr.is_halted,
            "halt_reason": self._risk_mgr.halt_reason,
            **perf,
        }

    def reset_daily(self) -> None:
        """Reset daily counters at UTC midnight."""
        self._daily_start_equity = self._equity
        self._risk_mgr.reset_daily()
        log.info(f"Daily metrics reset — start equity: ${self._equity:.2f}")
