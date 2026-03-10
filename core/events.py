"""
TradingBot V5 — Event Dataclasses

Immutable event objects passed between components via asyncio.Queue.
Each event carries a correlation_id to trace the full lifecycle:
  Signal → Order → Fill
"""

from dataclasses import dataclass, field
from typing import Optional
import time
import uuid


def _short_uuid() -> str:
    return uuid.uuid4().hex[:8]


# ── Market Data Events ──────────────────────────────────────────

@dataclass(frozen=True)
class Tick:
    """Normalized raw trade tick from WebSocket."""
    timestamp: float
    symbol: str
    price: float
    size: float


@dataclass(frozen=True)
class BarEvent:
    """Aggregated OHLCV bar."""
    timestamp: float
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: Optional[float] = None
    trade_count: int = 0
    is_carry_forward: bool = False


# ── Strategy Events ─────────────────────────────────────────────

@dataclass(frozen=True)
class SignalEvent:
    """Strategy decision to enter or exit a position."""
    correlation_id: str = field(default_factory=_short_uuid)
    timestamp: float = field(default_factory=time.time)
    symbol: str = ""
    signal_type: str = ""           # SignalType value
    price: float = 0.0
    strength: float = 0.0           # |z-score|
    strategy_name: str = ""
    # ── Features (persisted for ML) ─────────────────────────────
    zscore: float = 0.0
    zscore_ma: float = 0.0
    trend_slope: float = 0.0
    volatility: float = 0.0
    atr: float = 0.0
    rsi: float = 0.0
    volume_ratio: float = 0.0
    spread: float = 0.0
    position_before: str = "FLAT"
    position_qty_before: float = 0.0


# ── Execution Events ────────────────────────────────────────────

@dataclass(frozen=True)
class OrderEvent:
    """Order intent or status update."""
    correlation_id: str = ""
    timestamp: float = field(default_factory=time.time)
    symbol: str = ""
    side: str = ""                  # BUY or SELL
    quantity: float = 0.0
    expected_price: float = 0.0
    order_type: str = "market"
    broker_order_id: Optional[str] = None
    status: str = "PENDING"         # OrderStatus value
    signal_id: Optional[str] = None
    rejection_reason: Optional[str] = None


@dataclass(frozen=True)
class FillEvent:
    """Execution confirmation from broker."""
    correlation_id: str = ""
    timestamp: float = field(default_factory=time.time)
    symbol: str = ""
    broker_order_id: str = ""
    side: str = ""
    quantity: float = 0.0
    fill_price: float = 0.0
    expected_price: float = 0.0
    # Computed post-fill
    slippage_bps: float = 0.0
    position_before_qty: float = 0.0
    position_after_qty: float = 0.0
    position_side: str = "FLAT"
    realized_pnl: float = 0.0
    commission: float = 0.0


# ── System Events ───────────────────────────────────────────────

@dataclass(frozen=True)
class RiskEvent:
    """Risk manager decision or breach notification."""
    timestamp: float = field(default_factory=time.time)
    symbol: str = ""
    event_type: str = ""            # SIGNAL_REJECTED_RISK, RISK_BREACH, etc.
    reason: str = ""
    details: Optional[dict] = None


@dataclass(frozen=True)
class SystemEvent:
    """System lifecycle event."""
    timestamp: float = field(default_factory=time.time)
    event_type: str = ""            # EventType value
    severity: str = "INFO"
    message: str = ""
    details: Optional[dict] = None
