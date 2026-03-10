"""
TradingBot V5 — Data Repository

Typed async CRUD operations for every table.
Each method maps directly to a domain event or query.
"""

import json
import logging
import time
from typing import Optional

from storage.database import Database

log = logging.getLogger("storage.repository")


class Repository:
    """Async CRUD layer over the trading database."""

    def __init__(self, db: Database):
        self._db = db

    # ── Bars ────────────────────────────────────────────────────

    async def insert_bar(
        self, *, timestamp: float, symbol: str, timeframe: str,
        open: float, high: float, low: float, close: float,
        volume: float, vwap: Optional[float] = None,
        trade_count: int = 0, is_carry_forward: bool = False,
    ) -> int:
        return await self._db.insert(
            """INSERT OR IGNORE INTO bars
               (timestamp, symbol, timeframe, open, high, low, close,
                volume, vwap, trade_count, is_carry_forward)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (timestamp, symbol, timeframe, open, high, low, close,
             volume, vwap, trade_count, 1 if is_carry_forward else 0),
        )

    async def get_recent_bars(
        self, symbol: str, limit: int = 200, timeframe: str = "1m"
    ) -> list[dict]:
        return await self._db.fetch_all(
            """SELECT * FROM bars
               WHERE symbol = ? AND timeframe = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (symbol, timeframe, limit),
        )

    # ── Signals ─────────────────────────────────────────────────

    async def insert_signal(
        self, *, correlation_id: str, timestamp: float, symbol: str,
        signal_type: str, strength: float, price_at_signal: float,
        zscore: float = 0.0, zscore_ma: float = 0.0,
        trend_slope: float = 0.0, volatility: float = 0.0,
        atr: float = 0.0, rsi: float = 0.0,
        volume_ratio: float = 0.0, spread: float = 0.0,
        bar_id: Optional[int] = None,
        position_before: str = "FLAT", position_qty_before: float = 0.0,
        strategy_name: str = "",
    ) -> int:
        return await self._db.insert(
            """INSERT INTO signals
               (correlation_id, timestamp, symbol, signal_type, strength,
                price_at_signal, zscore, zscore_ma, trend_slope, volatility,
                atr, rsi, volume_ratio, spread, bar_id,
                position_before, position_qty_before, strategy_name)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (correlation_id, timestamp, symbol, signal_type, strength,
             price_at_signal, zscore, zscore_ma, trend_slope, volatility,
             atr, rsi, volume_ratio, spread, bar_id,
             position_before, position_qty_before, strategy_name),
        )

    async def get_recent_signals(
        self, symbol: Optional[str] = None, limit: int = 100
    ) -> list[dict]:
        if symbol:
            return await self._db.fetch_all(
                "SELECT * FROM signals WHERE symbol = ? ORDER BY timestamp DESC LIMIT ?",
                (symbol, limit),
            )
        return await self._db.fetch_all(
            "SELECT * FROM signals ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )

    # ── Orders ──────────────────────────────────────────────────

    async def insert_order(
        self, *, correlation_id: str = "", timestamp: Optional[float] = None,
        symbol: str, side: str, quantity: float,
        expected_price: float = 0.0, signal_id: Optional[int] = None,
        status: str = "SUBMITTED",
        account_equity: float = 0.0, buying_power: float = 0.0,
        risk_amount: float = 0.0,
    ) -> int:
        ts = timestamp or time.time()
        return await self._db.insert(
            """INSERT INTO orders
               (correlation_id, timestamp, symbol, side, quantity,
                expected_price, signal_id, status,
                account_equity, buying_power, risk_amount)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (correlation_id, ts, symbol, side, quantity,
             expected_price, signal_id, status,
             account_equity, buying_power, risk_amount),
        )

    async def update_order_broker_id(
        self, order_id: int, broker_order_id: str
    ) -> None:
        await self._db.execute(
            "UPDATE orders SET broker_order_id = ?, updated_at = ? WHERE id = ?",
            (broker_order_id, time.time(), order_id),
        )

    async def update_order_status(
        self, order_id: int, status: str,
        rejection_reason: Optional[str] = None,
    ) -> None:
        await self._db.execute(
            "UPDATE orders SET status = ?, rejection_reason = ?, updated_at = ? WHERE id = ?",
            (status, rejection_reason, time.time(), order_id),
        )

    async def get_order_by_broker_id(self, broker_order_id: str) -> Optional[dict]:
        return await self._db.fetch_one(
            "SELECT * FROM orders WHERE broker_order_id = ?",
            (broker_order_id,),
        )

    async def get_pending_orders(self) -> list[dict]:
        return await self._db.fetch_all(
            "SELECT * FROM orders WHERE status IN ('PENDING', 'SUBMITTED', 'ACCEPTED')"
        )

    # ── Fills ───────────────────────────────────────────────────

    async def insert_fill(
        self, *, correlation_id: str = "", timestamp: float,
        symbol: str, broker_order_id: str, side: str,
        quantity: float, fill_price: float,
        expected_price: float = 0.0, slippage_bps: float = 0.0,
        position_before_qty: float = 0.0, position_after_qty: float = 0.0,
        position_side: str = "FLAT", realized_pnl: float = 0.0,
        commission: float = 0.0, order_id: Optional[int] = None,
    ) -> int:
        return await self._db.insert(
            """INSERT INTO fills
               (correlation_id, timestamp, symbol, broker_order_id, side,
                quantity, fill_price, expected_price, slippage_bps,
                position_before_qty, position_after_qty, position_side,
                realized_pnl, commission, order_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (correlation_id, timestamp, symbol, broker_order_id, side,
             quantity, fill_price, expected_price, slippage_bps,
             position_before_qty, position_after_qty, position_side,
             realized_pnl, commission, order_id),
        )

    # ── Positions ───────────────────────────────────────────────

    async def upsert_position(
        self, *, symbol: str, side: str, quantity: float,
        avg_entry_price: float = 0.0, unrealized_pnl: float = 0.0,
        realized_pnl: float = 0.0, entry_time: Optional[float] = None,
        last_fill_id: Optional[int] = None,
    ) -> None:
        await self._db.execute(
            """INSERT INTO positions
               (symbol, side, quantity, avg_entry_price,
                unrealized_pnl, realized_pnl, entry_time,
                last_fill_id, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(symbol) DO UPDATE SET
                 side = excluded.side,
                 quantity = excluded.quantity,
                 avg_entry_price = excluded.avg_entry_price,
                 unrealized_pnl = excluded.unrealized_pnl,
                 realized_pnl = excluded.realized_pnl,
                 entry_time = excluded.entry_time,
                 last_fill_id = excluded.last_fill_id,
                 updated_at = excluded.updated_at""",
            (symbol, side, quantity, avg_entry_price,
             unrealized_pnl, realized_pnl, entry_time,
             last_fill_id, time.time()),
        )

    async def get_all_positions(self) -> list[dict]:
        return await self._db.fetch_all("SELECT * FROM positions")

    async def get_position(self, symbol: str) -> Optional[dict]:
        return await self._db.fetch_one(
            "SELECT * FROM positions WHERE symbol = ?", (symbol,),
        )

    # ── Equity Curve ────────────────────────────────────────────

    async def insert_equity_snapshot(
        self, *, timestamp: float, equity: float, cash: float,
        buying_power: float, total_positions: float,
        open_positions: int, daily_pnl: float = 0.0,
        daily_pnl_pct: float = 0.0, drawdown_pct: float = 0.0,
        high_water_mark: float = 0.0,
    ) -> int:
        return await self._db.insert(
            """INSERT INTO equity_curve
               (timestamp, equity, cash, buying_power, total_positions,
                open_positions, daily_pnl, daily_pnl_pct,
                drawdown_pct, high_water_mark)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (timestamp, equity, cash, buying_power, total_positions,
             open_positions, daily_pnl, daily_pnl_pct,
             drawdown_pct, high_water_mark),
        )

    async def get_equity_curve(self, hours: int = 24) -> list[dict]:
        since = time.time() - (hours * 3600)
        return await self._db.fetch_all(
            "SELECT * FROM equity_curve WHERE timestamp > ? ORDER BY timestamp",
            (since,),
        )

    # ── Strategy Metrics ────────────────────────────────────────

    async def insert_strategy_metrics(self, metrics: dict) -> int:
        metrics["timestamp"] = metrics.get("timestamp", time.time())
        cols = ", ".join(metrics.keys())
        placeholders = ", ".join(["?"] * len(metrics))
        return await self._db.insert(
            f"INSERT INTO strategy_metrics ({cols}) VALUES ({placeholders})",
            tuple(metrics.values()),
        )

    # ── Reconciliation ──────────────────────────────────────────

    async def insert_reconciliation(
        self, *, timestamp: float, broker_positions: dict,
        local_positions: dict, discrepancies: list,
        action_taken: str = "NONE",
    ) -> int:
        return await self._db.insert(
            """INSERT INTO reconciliation_log
               (timestamp, broker_positions, local_positions,
                discrepancies, action_taken)
               VALUES (?, ?, ?, ?, ?)""",
            (timestamp, json.dumps(broker_positions),
             json.dumps(local_positions), json.dumps(discrepancies),
             action_taken),
        )

    # ── System Events ───────────────────────────────────────────

    async def insert_system_event(
        self, *, timestamp: float, event_type: str,
        severity: str, message: str,
        details: Optional[dict] = None,
    ) -> int:
        return await self._db.insert(
            """INSERT INTO system_events
               (timestamp, event_type, severity, message, details)
               VALUES (?, ?, ?, ?, ?)""",
            (timestamp, event_type, severity, message,
             json.dumps(details) if details else None),
        )

    # ── Aggregate Queries (for metrics) ─────────────────────────

    async def get_daily_trades(self, strategy_name: str = "") -> list[dict]:
        """Get all fills from the current UTC day."""
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        since = start_of_day.timestamp()
        return await self._db.fetch_all(
            "SELECT * FROM fills WHERE timestamp > ? ORDER BY timestamp",
            (since,),
        )

    async def get_total_realized_pnl(self) -> float:
        row = await self._db.fetch_one(
            "SELECT COALESCE(SUM(realized_pnl), 0) as total FROM fills"
        )
        return row["total"] if row else 0.0
