"""
TradingBot V5 — State Recovery Service

Reconstructs system state on startup after a restart or crash.

Steps:
  1. Check PID lockfile
  2. Load positions from DB
  3. Reconcile with broker
  4. Warm up strategy buffers from DB bars
  5. Resume trading
"""

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Optional

from config.settings import SETTINGS
from core.events import BarEvent
from positions.position_manager import PositionManager
from reconciliation.reconciler import Reconciler
from strategy.base import AbstractStrategy
from market_data.bar_aggregator import BarAggregator
from storage.repository import Repository

log = logging.getLogger("recovery")


class StateRecoveryService:
    """
    Startup state reconstruction.

    Ensures the bot can safely resume after a crash or restart.
    """

    def __init__(
        self,
        repository: Repository,
        position_manager: PositionManager,
        reconciler: Reconciler,
        strategy: AbstractStrategy,
        aggregator: BarAggregator,
    ):
        self._repo = repository
        self._pos_mgr = position_manager
        self._reconciler = reconciler
        self._strategy = strategy
        self._aggregator = aggregator

    async def recover(self) -> dict:
        """
        Execute full state recovery sequence.

        Returns recovery summary.
        """
        log.info("=" * 60)
        log.info("STARTING STATE RECOVERY")
        log.info("=" * 60)

        summary = {
            "pid_check": False,
            "positions_loaded": 0,
            "bars_loaded": 0,
            "reconciliation": {},
        }

        # ── 1. PID lockfile check ───────────────────────────────
        if not self._acquire_pid_lock():
            raise RuntimeError(
                "Another instance is already running! "
                f"Check PID file: {SETTINGS.pid_file}"
            )
        summary["pid_check"] = True
        log.info("PID lockfile acquired")

        # ── 2. Load positions from DB ───────────────────────────
        await self._pos_mgr.load_from_db()
        summary["positions_loaded"] = len(self._pos_mgr.positions)
        log.info(f"Loaded {summary['positions_loaded']} positions from DB")

        # ── 3. Reconcile with broker ────────────────────────────
        try:
            recon_result = await self._reconciler.reconcile()
            summary["reconciliation"] = recon_result
            log.info(f"Broker reconciliation complete: {recon_result}")
        except Exception as e:
            log.error(f"Broker reconciliation failed: {e}")
            summary["reconciliation"] = {"error": str(e)}

        # ── 4. Warm up strategy buffers ─────────────────────────
        total_bars = 0
        from config.symbols import get_symbol_names
        symbols = get_symbol_names()

        for symbol in symbols:
            bars_data = await self._repo.get_recent_bars(
                symbol=symbol,
                limit=SETTINGS.warmup_bars,
            )

            if bars_data:
                # Convert to BarEvent objects (oldest first)
                bar_events = [
                    BarEvent(
                        timestamp=row["timestamp"],
                        symbol=row["symbol"],
                        open=row["open"],
                        high=row["high"],
                        low=row["low"],
                        close=row["close"],
                        volume=row["volume"],
                        vwap=row.get("vwap"),
                        trade_count=row.get("trade_count", 0),
                        is_carry_forward=bool(row.get("is_carry_forward", 0)),
                    )
                    for row in reversed(bars_data)  # DB returns DESC, need ASC
                ]

                # Warm strategy
                self._strategy.warm_up(bar_events)

                # Warm aggregator (set last bar for carry-forward)
                if bar_events:
                    self._aggregator.warm_from_bars(symbol, bar_events[-1])

                total_bars += len(bar_events)
                log.info(
                    f"[{symbol}] Warmed with {len(bar_events)} bars"
                )

        summary["bars_loaded"] = total_bars

        # ── 5. Log system event ─────────────────────────────────
        await self._repo.insert_system_event(
            timestamp=time.time(),
            event_type="SYSTEM_STARTUP",
            severity="INFO",
            message="State recovery completed",
            details=summary,
        )

        log.info("=" * 60)
        log.info("STATE RECOVERY COMPLETE")
        log.info(f"  Positions: {summary['positions_loaded']}")
        log.info(f"  Bars loaded: {summary['bars_loaded']}")
        log.info("=" * 60)

        return summary

    def _acquire_pid_lock(self) -> bool:
        """
        Check and acquire PID lockfile.
        Returns False if another instance is running.
        """
        pid_path = Path(SETTINGS.pid_file)
        pid_path.parent.mkdir(parents=True, exist_ok=True)

        if pid_path.exists():
            try:
                old_pid = int(pid_path.read_text().strip())
                # Check if old process is still running
                try:
                    os.kill(old_pid, 0)  # signal 0 = check existence
                    return False  # Process still running
                except (OSError, ProcessLookupError):
                    log.warning(
                        f"Stale PID file found (pid={old_pid}), removing"
                    )
            except ValueError:
                log.warning("Corrupted PID file, removing")

        # Write our PID
        pid_path.write_text(str(os.getpid()))
        return True

    @staticmethod
    def release_pid_lock() -> None:
        """Remove PID lockfile on clean shutdown."""
        pid_path = Path(SETTINGS.pid_file)
        if pid_path.exists():
            pid_path.unlink()
            log.info("PID lockfile released")
