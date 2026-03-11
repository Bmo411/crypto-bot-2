"""
TradingBot V5 — Execution Engine

Handles order submission to Alpaca and fill processing from TradingStream.
All Alpaca SDK calls are wrapped with asyncio.to_thread + timeout.
"""

import asyncio
import logging
import time
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.stream import TradingStream

from config.settings import SETTINGS
from core.events import SignalEvent, FillEvent
from core.enums import OrderStatus
from execution.order_manager import OrderManager, ManagedOrder
from storage.repository import Repository

log = logging.getLogger("execution.engine")


class ExecutionEngine:
    """
    Submits orders to Alpaca and listens for fills.

    Two main operations:
      1. submit_order() — send market order to Alpaca
      2. run_fill_listener() — WebSocket listener for execution updates
    """

    def __init__(
        self,
        order_manager: OrderManager,
        repository: Repository,
        fill_queue: asyncio.Queue,
    ):
        self._client = TradingClient(
            api_key=SETTINGS.alpaca_api_key,
            secret_key=SETTINGS.alpaca_secret_key,
            paper=SETTINGS.paper_mode,
        )
        self._order_mgr = order_manager
        self._repo = repository
        self._fill_queue = fill_queue

        self._trading_stream: Optional[TradingStream] = None
        self._running = False

    async def submit_order(
        self,
        signal: SignalEvent,
        side: str,
        quantity: float,
    ) -> bool:
        """
        Submit a market order to Alpaca.

        Steps:
          1. Log order intent to DB (before submission)
          2. Submit to Alpaca API
          3. Update DB with broker order ID
          4. Register with OrderManager

        Returns True if order was accepted by Alpaca.
        """
        db_order_id = None
        try:
            # Pre-flight: check account buying power
            account = await asyncio.wait_for(
                asyncio.to_thread(self._client.get_account),
                timeout=SETTINGS.order_timeout,
            )
            buying_power = float(account.buying_power)
            notional = quantity * signal.price

            if notional > buying_power * SETTINGS.buying_power_buffer:
                log.warning(
                    f"[{signal.symbol}] Insufficient buying power: "
                    f"need ${notional:.2f}, have ${buying_power:.2f}"
                )
                return False

            # 1. Log order intent BEFORE submission
            db_order_id = await self._repo.insert_order(
                correlation_id=signal.correlation_id,
                symbol=signal.symbol,
                side=side,
                quantity=quantity,
                expected_price=signal.price,
                status=OrderStatus.SUBMITTED.value,
                account_equity=float(account.equity),
                buying_power=buying_power,
                risk_amount=SETTINGS.risk_per_trade * float(account.equity),
            )

            # Create ManagedOrder for tracking
            managed = ManagedOrder(
                db_order_id=db_order_id,
                correlation_id=signal.correlation_id,
                symbol=signal.symbol,
                side=side,
                quantity=quantity,
                expected_price=signal.price,
            )
            await self._order_mgr.register_order(managed)

            # 2. Submit to Alpaca
            # Convert symbol from "BTC/USD" to "BTC/USD" (Alpaca crypto format)
            request = MarketOrderRequest(
                symbol=signal.symbol,
                qty=quantity,
                side=OrderSide.BUY if side == "BUY" else OrderSide.SELL,
                time_in_force=TimeInForce.GTC,
            )

            order = await asyncio.wait_for(
                asyncio.to_thread(self._client.submit_order, request),
                timeout=SETTINGS.order_timeout,
            )

            broker_id = str(order.id)

            # 3. Update DB with broker order ID
            await self._repo.update_order_broker_id(db_order_id, broker_id)

            # 4. Register with OrderManager
            await self._order_mgr.mark_submitted(db_order_id, broker_id)

            log.info(
                f"[{signal.symbol}] Order submitted: {side} {quantity:.6f} "
                f"@ ~${signal.price:.2f} | broker_id={broker_id}"
            )
            return True

        except asyncio.TimeoutError:
            log.error(f"[{signal.symbol}] Order submission timed out")
            if db_order_id:
                await self._repo.update_order_status(
                    db_order_id, OrderStatus.FAILED.value,
                    rejection_reason="Submission timed out",
                )
                await self._order_mgr.mark_rejected(db_order_id, "Timeout")
            return False

        except Exception as e:
            log.error(f"[{signal.symbol}] Order submission failed: {e}")
            if db_order_id:
                await self._repo.update_order_status(
                    db_order_id, OrderStatus.REJECTED.value,
                    rejection_reason=str(e),
                )
                await self._order_mgr.mark_rejected(db_order_id, str(e))
            return False

    async def run_fill_listener(self) -> None:
        """
        Listen for execution updates via Alpaca TradingStream WebSocket.
        Pushes FillEvent to fill_queue for position manager to process.
        """
        self._running = True

        while self._running:
            try:
                self._trading_stream = TradingStream(
                    api_key=SETTINGS.alpaca_api_key,
                    secret_key=SETTINGS.alpaca_secret_key,
                    paper=SETTINGS.paper_mode,
                )

                self._trading_stream.subscribe_trade_updates(
                    self._on_trade_update
                )

                log.info("Fill listener connected to TradingStream")
                await asyncio.to_thread(self._trading_stream.run)

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Fill listener error: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)

    async def stop(self) -> None:
        """Stop the fill listener."""
        self._running = False
        if self._trading_stream:
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(self._trading_stream.stop),
                    timeout=5.0,
                )
            except Exception:
                pass

    async def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel an order at the broker."""
        try:
            await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.cancel_order_by_id, broker_order_id
                ),
                timeout=SETTINGS.order_timeout,
            )
            log.info(f"Order cancelled: broker_id={broker_order_id}")
            return True
        except Exception as e:
            log.error(f"Failed to cancel order {broker_order_id}: {e}")
            return False

    async def close_all_positions(self) -> None:
        """Emergency close all positions at broker."""
        try:
            await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.close_all_positions, cancel_orders=True
                ),
                timeout=30.0,
            )
            log.critical("All positions closed at broker")
        except Exception as e:
            log.critical(f"Failed to close all positions: {e}")

    def get_account_sync(self):
        """Synchronous account fetch for reconciliation."""
        return self._client.get_account()

    def get_positions_sync(self):
        """Synchronous positions fetch for reconciliation."""
        return self._client.get_all_positions()

    def get_orders_sync(self, **kwargs):
        """Synchronous orders fetch for reconciliation."""
        from alpaca.trading.requests import GetOrdersRequest
        request = GetOrdersRequest(**kwargs)
        return self._client.get_orders(filter=request)

    async def _on_trade_update(self, data) -> None:
        """
        Callback from TradingStream — runs in thread.
        Parse the fill event and push to fill_queue.
        """
        try:
            event = data.event
            order = data.order

            if event in ("fill", "partial_fill"):
                fill = FillEvent(
                    correlation_id="",  # will be matched by order manager
                    timestamp=time.time(),
                    symbol=str(order.symbol),
                    broker_order_id=str(order.id),
                    side=str(order.side).upper(),
                    quantity=float(order.filled_qty),
                    fill_price=float(order.filled_avg_price),
                )

                # Non-blocking put to fill_queue
                try:
                    self._fill_queue.put_nowait(fill)
                except asyncio.QueueFull:
                    log.error("Fill queue full — CRITICAL: fill event dropped!")

                log.info(
                    f"[{order.symbol}] FILL: {order.side} "
                    f"{order.filled_qty} @ ${order.filled_avg_price}"
                )

            elif event in ("canceled", "cancelled"):
                log.info(f"[{order.symbol}] Order cancelled: {order.id}")

            elif event == "rejected":
                log.warning(
                    f"[{order.symbol}] Order rejected: {order.id}"
                )

        except Exception as e:
            log.error(f"Error processing trade update: {e}")
