"""
TradingBot V5 — Application Entrypoint

Initializes all components, wires dependencies, runs recovery,
and starts the async event loop with all trading tasks.

Usage:
    python run.py              # Start the trading bot
    python run.py --paper      # Paper trading mode (default)
"""

import asyncio
import logging
import signal
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import SETTINGS
from config.symbols import get_symbol_names
from config.strategy_params import STRATEGY_PARAMS

from core.events import BarEvent, SignalEvent, FillEvent

from storage.database import Database
from storage.migrations import run_migrations
from storage.repository import Repository

from market_data.websocket_client import CryptoWebSocketClient
from market_data.bar_aggregator import BarAggregator

from strategy.mean_reversion import MeanReversionStrategy

from risk.risk_manager import RiskManager

from execution.order_manager import OrderManager
from execution.execution_engine import ExecutionEngine
from execution.slippage_tracker import SlippageTracker

from positions.position_manager import PositionManager

from reconciliation.reconciler import Reconciler

from logging_.trade_logger import setup_logging

from metrics.collector import MetricsCollector
from metrics.dashboard import init_dashboard

from recovery.state_recovery import StateRecoveryService

from api.server import create_app

log = logging.getLogger("main")


class TradingBot:
    """
    Main trading bot — wires all components and runs the event loop.
    """

    def __init__(self):
        # ── Queues ──────────────────────────────────────────────
        self.tick_queue: asyncio.Queue = asyncio.Queue(maxsize=10_000)
        self.bar_queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self.fill_queue: asyncio.Queue = asyncio.Queue(maxsize=100)

        # ── Database ────────────────────────────────────────────
        self.db = Database(SETTINGS.db_path)
        self.repo: Repository | None = None

        # ── Components (initialized in setup) ──────────────────
        self.ws_client: CryptoWebSocketClient | None = None
        self.aggregator: BarAggregator | None = None
        self.strategy: MeanReversionStrategy | None = None
        self.risk_mgr: RiskManager | None = None
        self.order_mgr: OrderManager | None = None
        self.exec_engine: ExecutionEngine | None = None
        self.slippage: SlippageTracker | None = None
        self.pos_mgr: PositionManager | None = None
        self.reconciler: Reconciler | None = None
        self.metrics: MetricsCollector | None = None
        self.recovery: StateRecoveryService | None = None

        self._running = False
        self._tasks: list[asyncio.Task] = []

    async def setup(self) -> None:
        """Initialize all components and run recovery."""
        log.info("=" * 60)
        log.info("  TradingBot V5 — Starting Up")
        log.info(f"  Mode: {'PAPER' if SETTINGS.paper_mode else 'LIVE'}")
        log.info(f"  Capital: ${SETTINGS.initial_capital:,.2f}")
        log.info(f"  Symbols: {get_symbol_names()}")
        log.info("=" * 60)

        # Validate settings
        SETTINGS.validate()

        # Database
        await self.db.connect()
        await run_migrations(self.db)
        self.repo = Repository(self.db)

        # Market data
        symbols = get_symbol_names()
        self.ws_client = CryptoWebSocketClient(
            tick_queue=self.tick_queue,
            symbols=symbols,
        )
        self.aggregator = BarAggregator(
            tick_queue=self.tick_queue,
            bar_queue=self.bar_queue,
            interval_seconds=SETTINGS.bar_interval,
        )

        # Strategy
        self.strategy = MeanReversionStrategy(STRATEGY_PARAMS)

        # Risk
        self.risk_mgr = RiskManager(STRATEGY_PARAMS)

        # Execution
        self.order_mgr = OrderManager()
        self.exec_engine = ExecutionEngine(
            order_manager=self.order_mgr,
            repository=self.repo,
            fill_queue=self.fill_queue,
        )
        self.slippage = SlippageTracker()

        # Position management
        self.pos_mgr = PositionManager(repository=self.repo)

        # Reconciliation
        self.reconciler = Reconciler(
            execution_engine=self.exec_engine,
            position_manager=self.pos_mgr,
            risk_manager=self.risk_mgr,
            repository=self.repo,
        )

        # Metrics
        self.metrics = MetricsCollector(
            position_manager=self.pos_mgr,
            risk_manager=self.risk_mgr,
            repository=self.repo,
        )

        # Dashboard
        init_dashboard(self.metrics, self.pos_mgr)

        # Recovery
        self.recovery = StateRecoveryService(
            repository=self.repo,
            position_manager=self.pos_mgr,
            reconciler=self.reconciler,
            strategy=self.strategy,
            aggregator=self.aggregator,
        )

        # Run state recovery
        await self.recovery.recover()

        log.info("All components initialized")

    async def run(self) -> None:
        """Start all async tasks and run forever."""
        self._running = True

        self._tasks = [
            asyncio.create_task(
                self.ws_client.run(),
                name="websocket_ingestion",
            ),
            asyncio.create_task(
                self.aggregator.run(),
                name="bar_aggregation",
            ),
            asyncio.create_task(
                self._strategy_loop(),
                name="strategy_engine",
            ),
            asyncio.create_task(
                self._fill_processor(),
                name="fill_processor",
            ),
            asyncio.create_task(
                self.exec_engine.run_fill_listener(),
                name="fill_listener",
            ),
            asyncio.create_task(
                self.reconciler.run(),
                name="reconciliation",
            ),
            asyncio.create_task(
                self.metrics.run(),
                name="metrics_collector",
            ),
            asyncio.create_task(
                self._heartbeat_loop(),
                name="heartbeat",
            ),
            asyncio.create_task(
                self._stale_order_cleaner(),
                name="order_cleaner",
            ),
        ]

        log.info(f"Started {len(self._tasks)} async tasks")

        # Wait for all tasks (or until shutdown)
        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            log.info("Tasks cancelled — shutting down")

    async def _strategy_loop(self) -> None:
        """
        Main strategy loop.
        Reads bars from bar_queue, generates signals, validates risk,
        and submits orders.
        """
        while self._running:
            try:
                bar = await asyncio.wait_for(
                    self.bar_queue.get(), timeout=5.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            try:
                # Persist bar to DB
                await self.repo.insert_bar(
                    timestamp=bar.timestamp,
                    symbol=bar.symbol,
                    timeframe="1m",
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    vwap=bar.vwap,
                    trade_count=bar.trade_count,
                    is_carry_forward=bar.is_carry_forward,
                )

                # Get current position state
                pos = self.pos_mgr.get_position(bar.symbol)
                pnl_pct = 0.0
                if pos.is_open and pos.avg_entry_price > 0:
                    if pos.side == "LONG":
                        pnl_pct = (bar.close - pos.avg_entry_price) / pos.avg_entry_price
                    elif pos.side == "SHORT":
                        pnl_pct = (pos.avg_entry_price - bar.close) / pos.avg_entry_price

                # Generate signal
                signal = await self.strategy.on_bar(
                    bar=bar,
                    position_side=pos.side,
                    position_qty=pos.quantity,
                    current_pnl_pct=pnl_pct,
                )

                if signal is None:
                    continue

                # Persist signal
                await self.repo.insert_signal(
                    correlation_id=signal.correlation_id,
                    timestamp=signal.timestamp,
                    symbol=signal.symbol,
                    signal_type=signal.signal_type,
                    strength=signal.strength,
                    price_at_signal=signal.price,
                    zscore=signal.zscore,
                    zscore_ma=signal.zscore_ma,
                    trend_slope=signal.trend_slope,
                    volatility=signal.volatility,
                    atr=signal.atr,
                    position_before=pos.side,
                    position_qty_before=pos.quantity,
                    strategy_name=signal.strategy_name,
                )

                # Validate risk
                approved, risk_event = self.risk_mgr.validate_signal(signal)
                if not approved:
                    log.info(
                        f"[{signal.symbol}] Signal rejected by risk: "
                        f"{risk_event.reason if risk_event else 'unknown'}"
                    )
                    continue

                # Determine side and quantity
                if signal.signal_type in ("LONG_ENTRY", "SHORT_EXIT",
                                           "STOP_LOSS", "TAKE_PROFIT"):
                    if signal.signal_type == "LONG_ENTRY":
                        side = "BUY"
                        qty = self.risk_mgr.calculate_position_size(signal)
                    elif signal.signal_type in ("SHORT_EXIT", "STOP_LOSS",
                                                 "TAKE_PROFIT"):
                        side = "BUY"
                        qty = pos.quantity  # close full position
                    else:
                        continue

                elif signal.signal_type in ("SHORT_ENTRY", "LONG_EXIT"):
                    if signal.signal_type == "SHORT_ENTRY":
                        side = "SELL"
                        qty = self.risk_mgr.calculate_position_size(signal)
                    else:  # LONG_EXIT
                        side = "SELL"
                        qty = pos.quantity  # close full position

                else:
                    continue

                if qty <= 0:
                    log.warning(f"[{signal.symbol}] Zero quantity — skipping")
                    continue

                # Submit order
                await self.exec_engine.submit_order(
                    signal=signal,
                    side=side,
                    quantity=qty,
                )

            except Exception as e:
                log.error(f"Strategy loop error for {bar.symbol}: {e}")

    async def _fill_processor(self) -> None:
        """
        Process fills from fill_queue → update positions + metrics.
        """
        while self._running:
            try:
                fill = await asyncio.wait_for(
                    self.fill_queue.get(), timeout=5.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            try:
                # Match fill to order
                managed = await self.order_mgr.on_fill(
                    broker_order_id=fill.broker_order_id,
                    filled_qty=fill.quantity,
                    avg_price=fill.fill_price,
                )

                correlation_id = managed.correlation_id if managed else ""

                # Track slippage
                expected = managed.expected_price if managed else fill.fill_price
                slippage_bps = self.slippage.record_fill(
                    symbol=fill.symbol,
                    expected_price=expected,
                    fill_price=fill.fill_price,
                    side=fill.side,
                )

                # Get position before fill
                pos_before = self.pos_mgr.get_position(fill.symbol)
                before_qty = pos_before.quantity

                # Update position (returns TradeRecord if round-trip complete)
                trade_record = await self.pos_mgr.on_fill(fill)

                # Get position after fill
                pos_after = self.pos_mgr.get_position(fill.symbol)

                # Persist fill to DB
                order_db = None
                if managed:
                    order_db = await self.repo.get_order_by_broker_id(
                        fill.broker_order_id
                    )

                await self.repo.insert_fill(
                    correlation_id=correlation_id,
                    timestamp=fill.timestamp,
                    symbol=fill.symbol,
                    broker_order_id=fill.broker_order_id,
                    side=fill.side,
                    quantity=fill.quantity,
                    fill_price=fill.fill_price,
                    expected_price=expected,
                    slippage_bps=slippage_bps,
                    position_before_qty=before_qty,
                    position_after_qty=pos_after.quantity,
                    position_side=pos_after.side,
                    realized_pnl=trade_record.pnl if trade_record else 0.0,
                    order_id=order_db["id"] if order_db else None,
                )

                # Record trade in metrics
                if trade_record:
                    self.metrics.record_trade(trade_record)

                # Update risk manager position count
                self.risk_mgr.update_position_count(
                    self.pos_mgr.open_count
                )

            except Exception as e:
                log.error(f"Fill processing error: {e}")

    async def _heartbeat_loop(self) -> None:
        """Periodic heartbeat for external monitoring."""
        while self._running:
            await asyncio.sleep(SETTINGS.heartbeat_interval)
            log.debug(
                f"[HEARTBEAT] "
                f"positions={self.pos_mgr.open_count}, "
                f"orders={self.order_mgr.active_count}, "
                f"bars={self.aggregator.bar_count}, "
                f"ticks={self.ws_client.tick_count}, "
                f"ws={'UP' if self.ws_client.is_connected else 'DOWN'}"
            )

    async def _stale_order_cleaner(self) -> None:
        """Periodically cancel stale orders."""
        while self._running:
            await asyncio.sleep(SETTINGS.fill_timeout)
            stale = await self.order_mgr.cancel_stale_orders(
                max_age_seconds=SETTINGS.fill_timeout
            )
            for order in stale:
                if order.broker_order_id:
                    await self.exec_engine.cancel_order(order.broker_order_id)
                    await self.repo.update_order_status(
                        order.db_order_id, "CANCELLED",
                        rejection_reason="Stale order — no fill received",
                    )

    async def shutdown(self) -> None:
        """Graceful shutdown sequence."""
        log.info("=" * 60)
        log.info("  SHUTTING DOWN")
        log.info("=" * 60)

        self._running = False

        # Cancel all tasks
        for task in self._tasks:
            task.cancel()

        # Wait for tasks to finish
        await asyncio.gather(*self._tasks, return_exceptions=True)

        # Stop components
        if self.ws_client:
            await self.ws_client.stop()
        if self.aggregator:
            await self.aggregator.stop()
        if self.exec_engine:
            await self.exec_engine.stop()
        if self.reconciler:
            await self.reconciler.stop()
        if self.metrics:
            await self.metrics.stop()

        # Log shutdown event
        if self.repo:
            await self.repo.insert_system_event(
                timestamp=time.time(),
                event_type="SYSTEM_SHUTDOWN",
                severity="INFO",
                message="Graceful shutdown completed",
            )

        # Close DB
        await self.db.close()

        # Release PID lock
        StateRecoveryService.release_pid_lock()

        log.info("Shutdown complete")


async def main():
    """Application entry point."""
    setup_logging()

    bot = TradingBot()

    # Register signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()

    def _signal_handler():
        log.info("Shutdown signal received")
        asyncio.create_task(bot.shutdown())

    try:
        loop.add_signal_handler(signal.SIGINT, _signal_handler)
        loop.add_signal_handler(signal.SIGTERM, _signal_handler)
    except NotImplementedError:
        # signal handlers not available on Windows for the event loop
        pass

    try:
        await bot.setup()

        # Start FastAPI in background
        import uvicorn
        config = uvicorn.Config(
            app=create_app(),
            host=SETTINGS.api_host,
            port=SETTINGS.api_port,
            log_level="warning",
        )
        server = uvicorn.Server(config)

        # Run bot and API server concurrently
        await asyncio.gather(
            bot.run(),
            server.serve(),
        )

    except KeyboardInterrupt:
        log.info("KeyboardInterrupt received")
    except Exception as e:
        log.critical(f"Fatal error: {e}", exc_info=True)
    finally:
        await bot.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
