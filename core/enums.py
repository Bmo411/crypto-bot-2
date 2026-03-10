"""
TradingBot V5 — Enumerations

Central enum definitions used across all modules.
"""

from enum import Enum, auto


class Side(str, Enum):
    """Order / position side."""
    BUY = "BUY"
    SELL = "SELL"


class PositionSide(str, Enum):
    """Current position direction."""
    FLAT = "FLAT"
    LONG = "LONG"
    SHORT = "SHORT"


class SignalType(str, Enum):
    """Strategy signal classification."""
    LONG_ENTRY = "LONG_ENTRY"
    LONG_EXIT = "LONG_EXIT"
    SHORT_ENTRY = "SHORT_ENTRY"
    SHORT_EXIT = "SHORT_EXIT"
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"


class OrderStatus(str, Enum):
    """Order lifecycle states."""
    PENDING = "PENDING"             # created locally, not yet sent
    SUBMITTED = "SUBMITTED"         # sent to broker
    ACCEPTED = "ACCEPTED"           # broker acknowledged
    PARTIAL_FILL = "PARTIAL_FILL"   # partially executed
    FILLED = "FILLED"               # fully executed
    CANCELLED = "CANCELLED"         # cancelled by us or broker
    REJECTED = "REJECTED"           # broker rejected
    EXPIRED = "EXPIRED"             # time-in-force expired
    FAILED = "FAILED"               # submission error


class EventType(str, Enum):
    """Logged event categories."""
    BAR_CREATED = "BAR_CREATED"
    SIGNAL_GENERATED = "SIGNAL_GENERATED"
    SIGNAL_REJECTED_RISK = "SIGNAL_REJECTED_RISK"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_ACCEPTED = "ORDER_ACCEPTED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    FILL_RECEIVED = "FILL_RECEIVED"
    POSITION_UPDATED = "POSITION_UPDATED"
    PNL_UPDATE = "PNL_UPDATE"
    RISK_BREACH = "RISK_BREACH"
    RECONCILIATION = "RECONCILIATION"
    SYSTEM_STARTUP = "SYSTEM_STARTUP"
    SYSTEM_SHUTDOWN = "SYSTEM_SHUTDOWN"
    SYSTEM_RECONNECT = "SYSTEM_RECONNECT"
    SYSTEM_ERROR = "SYSTEM_ERROR"
    HEARTBEAT = "HEARTBEAT"


class Severity(str, Enum):
    """Log severity levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
