"""
TradingBot V5 — Domain Models

Mutable state models used by PositionManager and other components.
These are NOT events — they represent live, updateable state.
"""

from dataclasses import dataclass, field
from typing import Optional
import time


@dataclass
class Position:
    """Live position state for a single symbol."""
    symbol: str
    side: str = "FLAT"              # FLAT, LONG, SHORT
    quantity: float = 0.0
    avg_entry_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    entry_time: Optional[float] = None
    last_update: float = field(default_factory=time.time)

    @property
    def is_open(self) -> bool:
        return self.side != "FLAT" and self.quantity > 0

    @property
    def notional_value(self) -> float:
        return self.quantity * self.avg_entry_price if self.is_open else 0.0

    def calculate_unrealized_pnl(self, current_price: float) -> float:
        """Update and return unrealized PnL."""
        if not self.is_open:
            self.unrealized_pnl = 0.0
            return 0.0
        if self.side == "LONG":
            self.unrealized_pnl = (current_price - self.avg_entry_price) * self.quantity
        elif self.side == "SHORT":
            self.unrealized_pnl = (self.avg_entry_price - current_price) * self.quantity
        return self.unrealized_pnl


@dataclass
class TradeRecord:
    """Completed round-trip trade for performance tracking."""
    symbol: str
    side: str                       # which side was the entry
    entry_price: float
    exit_price: float
    quantity: float
    entry_time: float
    exit_time: float
    pnl: float = 0.0
    pnl_pct: float = 0.0
    hold_time_seconds: float = 0.0
    slippage_entry_bps: float = 0.0
    slippage_exit_bps: float = 0.0
    strategy_name: str = ""
    entry_signal_id: str = ""
    exit_signal_id: str = ""

    def __post_init__(self):
        self.hold_time_seconds = self.exit_time - self.entry_time
        if self.side == "LONG":
            self.pnl = (self.exit_price - self.entry_price) * self.quantity
        else:
            self.pnl = (self.entry_price - self.exit_price) * self.quantity
        if self.entry_price > 0:
            self.pnl_pct = self.pnl / (self.entry_price * self.quantity)


@dataclass
class EquitySnapshot:
    """Point-in-time account snapshot."""
    timestamp: float = field(default_factory=time.time)
    equity: float = 0.0
    cash: float = 0.0
    buying_power: float = 0.0
    total_positions_value: float = 0.0
    open_position_count: int = 0
    daily_pnl: float = 0.0
    daily_pnl_pct: float = 0.0
    drawdown_pct: float = 0.0
    high_water_mark: float = 0.0
