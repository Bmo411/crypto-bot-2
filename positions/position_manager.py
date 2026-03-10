"""
TradingBot V5 — Position Manager

Maintains live position state. Positions are updated ONLY from FillEvents.
This is the single source of truth for the bot's position state.
"""

import asyncio
import logging
import time
from typing import Optional

from core.models import Position, TradeRecord
from core.events import FillEvent
from core.enums import PositionSide
from storage.repository import Repository

log = logging.getLogger("positions.manager")


class PositionManager:
    """
    Position state management — updated exclusively from fills.

    Design rule: NEVER update positions from signals, orders, or
    manual overrides. Only FillEvents from the broker mutate state.
    (Exception: reconciliation can correct state to match broker.)
    """

    def __init__(self, repository: Repository):
        self._repo = repository
        self._positions: dict[str, Position] = {}
        self._completed_trades: list[TradeRecord] = []
        self._lock = asyncio.Lock()

    @property
    def positions(self) -> dict[str, Position]:
        return dict(self._positions)

    @property
    def open_positions(self) -> dict[str, Position]:
        return {s: p for s, p in self._positions.items() if p.is_open}

    @property
    def open_count(self) -> int:
        return len(self.open_positions)

    def get_position(self, symbol: str) -> Position:
        """Get position for a symbol (FLAT if not tracked)."""
        if symbol not in self._positions:
            self._positions[symbol] = Position(symbol=symbol)
        return self._positions[symbol]

    async def on_fill(self, fill: FillEvent) -> Optional[TradeRecord]:
        """
        Process a fill event and update position state.

        Returns a TradeRecord if the fill completed a round trip.
        """
        async with self._lock:
            pos = self.get_position(fill.symbol)
            before_qty = pos.quantity
            before_side = pos.side

            if fill.side == "BUY":
                trade_record = self._apply_buy(pos, fill)
            else:
                trade_record = self._apply_sell(pos, fill)

            pos.last_update = time.time()

            # Persist to DB
            await self._repo.upsert_position(
                symbol=pos.symbol,
                side=pos.side,
                quantity=pos.quantity,
                avg_entry_price=pos.avg_entry_price,
                unrealized_pnl=pos.unrealized_pnl,
                realized_pnl=pos.realized_pnl,
                entry_time=pos.entry_time,
            )

            log.info(
                f"[{fill.symbol}] Position updated: "
                f"{before_side} {before_qty:.6f} → "
                f"{pos.side} {pos.quantity:.6f} "
                f"@ avg_entry=${pos.avg_entry_price:.2f}"
            )

            if trade_record:
                self._completed_trades.append(trade_record)
                log.info(
                    f"[{fill.symbol}] Trade completed: "
                    f"PnL=${trade_record.pnl:.2f} ({trade_record.pnl_pct:.4%}), "
                    f"hold={trade_record.hold_time_seconds:.0f}s"
                )

            return trade_record

    def _apply_buy(
        self, pos: Position, fill: FillEvent
    ) -> Optional[TradeRecord]:
        """Apply a BUY fill to position state."""
        trade_record = None

        if pos.side == "SHORT":
            # Closing short (or partial close)
            if fill.quantity >= pos.quantity:
                # Full close
                pnl = (pos.avg_entry_price - fill.fill_price) * pos.quantity
                trade_record = TradeRecord(
                    symbol=pos.symbol,
                    side="SHORT",
                    entry_price=pos.avg_entry_price,
                    exit_price=fill.fill_price,
                    quantity=pos.quantity,
                    entry_time=pos.entry_time or 0,
                    exit_time=fill.timestamp,
                    strategy_name="mean_reversion_v5",
                )
                pos.realized_pnl += pnl

                remaining = fill.quantity - pos.quantity
                if remaining > 0:
                    # Flip to long
                    pos.side = PositionSide.LONG.value
                    pos.quantity = remaining
                    pos.avg_entry_price = fill.fill_price
                    pos.entry_time = fill.timestamp
                else:
                    pos.side = PositionSide.FLAT.value
                    pos.quantity = 0.0
                    pos.avg_entry_price = 0.0
                    pos.entry_time = None
            else:
                # Partial close
                pnl = (pos.avg_entry_price - fill.fill_price) * fill.quantity
                pos.realized_pnl += pnl
                pos.quantity -= fill.quantity

        elif pos.side == "LONG":
            # Adding to long
            total_cost = (pos.avg_entry_price * pos.quantity) + (
                fill.fill_price * fill.quantity
            )
            pos.quantity += fill.quantity
            pos.avg_entry_price = total_cost / pos.quantity if pos.quantity > 0 else 0

        else:
            # Opening long from FLAT
            pos.side = PositionSide.LONG.value
            pos.quantity = fill.quantity
            pos.avg_entry_price = fill.fill_price
            pos.entry_time = fill.timestamp

        pos.unrealized_pnl = 0.0
        return trade_record

    def _apply_sell(
        self, pos: Position, fill: FillEvent
    ) -> Optional[TradeRecord]:
        """Apply a SELL fill to position state."""
        trade_record = None

        if pos.side == "LONG":
            # Closing long (or partial close)
            if fill.quantity >= pos.quantity:
                # Full close
                pnl = (fill.fill_price - pos.avg_entry_price) * pos.quantity
                trade_record = TradeRecord(
                    symbol=pos.symbol,
                    side="LONG",
                    entry_price=pos.avg_entry_price,
                    exit_price=fill.fill_price,
                    quantity=pos.quantity,
                    entry_time=pos.entry_time or 0,
                    exit_time=fill.timestamp,
                    strategy_name="mean_reversion_v5",
                )
                pos.realized_pnl += pnl

                remaining = fill.quantity - pos.quantity
                if remaining > 0:
                    # Flip to short
                    pos.side = PositionSide.SHORT.value
                    pos.quantity = remaining
                    pos.avg_entry_price = fill.fill_price
                    pos.entry_time = fill.timestamp
                else:
                    pos.side = PositionSide.FLAT.value
                    pos.quantity = 0.0
                    pos.avg_entry_price = 0.0
                    pos.entry_time = None
            else:
                # Partial close
                pnl = (fill.fill_price - pos.avg_entry_price) * fill.quantity
                pos.realized_pnl += pnl
                pos.quantity -= fill.quantity

        elif pos.side == "SHORT":
            # Adding to short
            total_cost = (pos.avg_entry_price * pos.quantity) + (
                fill.fill_price * fill.quantity
            )
            pos.quantity += fill.quantity
            pos.avg_entry_price = total_cost / pos.quantity if pos.quantity > 0 else 0

        else:
            # Opening short from FLAT
            pos.side = PositionSide.SHORT.value
            pos.quantity = fill.quantity
            pos.avg_entry_price = fill.fill_price
            pos.entry_time = fill.timestamp

        pos.unrealized_pnl = 0.0
        return trade_record

    async def set_from_broker(
        self, symbol: str, side: str, quantity: float,
        avg_entry: float, entry_time: Optional[float] = None
    ) -> None:
        """Override position from broker data (used by reconciler)."""
        async with self._lock:
            pos = self.get_position(symbol)
            pos.side = side
            pos.quantity = quantity
            pos.avg_entry_price = avg_entry
            pos.entry_time = entry_time or time.time()

            await self._repo.upsert_position(
                symbol=pos.symbol,
                side=pos.side,
                quantity=pos.quantity,
                avg_entry_price=pos.avg_entry_price,
                entry_time=pos.entry_time,
            )

            log.info(
                f"[{symbol}] Position set from broker: "
                f"{side} {quantity:.6f} @ ${avg_entry:.2f}"
            )

    async def load_from_db(self) -> None:
        """Load positions from database on startup."""
        rows = await self._repo.get_all_positions()
        for row in rows:
            pos = Position(
                symbol=row["symbol"],
                side=row["side"],
                quantity=row["quantity"],
                avg_entry_price=row["avg_entry_price"],
                unrealized_pnl=row.get("unrealized_pnl", 0.0),
                realized_pnl=row.get("realized_pnl", 0.0),
                entry_time=row.get("entry_time"),
            )
            self._positions[pos.symbol] = pos

        log.info(
            f"Loaded {len(rows)} positions from DB "
            f"({len(self.open_positions)} open)"
        )
