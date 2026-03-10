"""
TradingBot V5 — Order Manager

Manages order lifecycle: PENDING → SUBMITTED → FILLED/CANCELLED/REJECTED.
Tracks all active orders and correlates fills back to signals.
"""

import asyncio
import logging
import time
from typing import Optional
from collections import OrderedDict

from core.events import OrderEvent, FillEvent
from core.enums import OrderStatus

log = logging.getLogger("execution.order_manager")


class ManagedOrder:
    """Internal order state tracking."""

    def __init__(
        self,
        db_order_id: int,
        correlation_id: str,
        symbol: str,
        side: str,
        quantity: float,
        expected_price: float,
    ):
        self.db_order_id = db_order_id
        self.correlation_id = correlation_id
        self.symbol = symbol
        self.side = side
        self.quantity = quantity
        self.expected_price = expected_price
        self.broker_order_id: Optional[str] = None
        self.status: str = OrderStatus.PENDING.value
        self.created_at: float = time.time()
        self.filled_qty: float = 0.0
        self.avg_fill_price: float = 0.0

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            OrderStatus.FILLED.value,
            OrderStatus.CANCELLED.value,
            OrderStatus.REJECTED.value,
            OrderStatus.EXPIRED.value,
            OrderStatus.FAILED.value,
        )

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at


class OrderManager:
    """
    Track active orders and handle lifecycle transitions.

    Maps broker_order_id → ManagedOrder for fill correlation.
    """

    def __init__(self):
        # broker_order_id → ManagedOrder
        self._active_orders: dict[str, ManagedOrder] = {}
        # db_order_id → ManagedOrder (for lookup before broker_id is set)
        self._pending_orders: dict[int, ManagedOrder] = {}
        self._total_orders = 0
        self._lock = asyncio.Lock()

    @property
    def active_count(self) -> int:
        return len(self._active_orders)

    @property
    def total_orders(self) -> int:
        return self._total_orders

    async def register_order(self, order: ManagedOrder) -> None:
        """Register a new order in PENDING state."""
        async with self._lock:
            self._pending_orders[order.db_order_id] = order
            self._total_orders += 1
            log.debug(f"[{order.symbol}] Order registered: db_id={order.db_order_id}")

    async def mark_submitted(
        self, db_order_id: int, broker_order_id: str
    ) -> None:
        """Order accepted by broker — move from pending to active."""
        async with self._lock:
            order = self._pending_orders.pop(db_order_id, None)
            if order is None:
                log.warning(f"Cannot mark as submitted: db_id={db_order_id} not found")
                return
            order.broker_order_id = broker_order_id
            order.status = OrderStatus.SUBMITTED.value
            self._active_orders[broker_order_id] = order
            log.info(
                f"[{order.symbol}] Order submitted: "
                f"broker_id={broker_order_id}, {order.side} {order.quantity}"
            )

    async def mark_rejected(
        self, db_order_id: int, reason: str = ""
    ) -> Optional[ManagedOrder]:
        """Order rejected — remove from tracking."""
        async with self._lock:
            order = self._pending_orders.pop(db_order_id, None)
            if order:
                order.status = OrderStatus.REJECTED.value
                log.warning(f"[{order.symbol}] Order rejected: {reason}")
            return order

    async def on_fill(
        self, broker_order_id: str, filled_qty: float, avg_price: float
    ) -> Optional[ManagedOrder]:
        """Process a fill event and return the matched order."""
        async with self._lock:
            order = self._active_orders.get(broker_order_id)
            if order is None:
                log.warning(
                    f"Fill for unknown order: broker_id={broker_order_id}"
                )
                return None

            order.filled_qty += filled_qty
            order.avg_fill_price = avg_price

            if order.filled_qty >= order.quantity:
                order.status = OrderStatus.FILLED.value
                del self._active_orders[broker_order_id]
                log.info(
                    f"[{order.symbol}] Order FILLED: "
                    f"qty={order.filled_qty}, price={avg_price:.2f}"
                )
            else:
                order.status = OrderStatus.PARTIAL_FILL.value
                log.info(
                    f"[{order.symbol}] Partial fill: "
                    f"{order.filled_qty}/{order.quantity} @ {avg_price:.2f}"
                )

            return order

    async def cancel_stale_orders(
        self, max_age_seconds: float = 30.0
    ) -> list[ManagedOrder]:
        """Find and return orders that have been open too long."""
        stale = []
        async with self._lock:
            for broker_id, order in list(self._active_orders.items()):
                if order.age_seconds > max_age_seconds:
                    order.status = OrderStatus.CANCELLED.value
                    stale.append(order)
                    del self._active_orders[broker_id]
                    log.warning(
                        f"[{order.symbol}] Stale order cancelled: "
                        f"broker_id={broker_id}, age={order.age_seconds:.1f}s"
                    )
        return stale

    async def get_active_for_symbol(self, symbol: str) -> list[ManagedOrder]:
        """Get all active orders for a symbol."""
        async with self._lock:
            return [
                o for o in self._active_orders.values()
                if o.symbol == symbol
            ]

    async def clear_all(self) -> None:
        """Clear all tracked orders."""
        async with self._lock:
            self._active_orders.clear()
            self._pending_orders.clear()
