"""
TradingBot V5 — Alpaca Crypto WebSocket Client

Maintains a single persistent WebSocket connection to Alpaca's crypto data feed.
Reconnects with exponential backoff on disconnection.
Pushes normalized Tick events to tick_queue.
"""

import asyncio
import logging
import time
from typing import Optional

from alpaca.data.live import CryptoDataStream

from config.settings import SETTINGS
from core.events import Tick

log = logging.getLogger("market_data.websocket")


class CryptoWebSocketClient:
    """Alpaca crypto WebSocket client with auto-reconnect."""

    def __init__(
        self,
        tick_queue: asyncio.Queue,
        symbols: list[str],
    ):
        self._tick_queue = tick_queue
        self._symbols = symbols
        self._stream: Optional[CryptoDataStream] = None
        self._running = False
        self._reconnect_delay = SETTINGS.ws_reconnect_min
        self._connected = False
        self._tick_count = 0
        self._last_tick_time: float = 0.0

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def tick_count(self) -> int:
        return self._tick_count

    async def run(self) -> None:
        """Main loop — connect and reconnect forever."""
        self._running = True
        while self._running:
            try:
                await self._connect_and_subscribe()
            except asyncio.CancelledError:
                log.info("WebSocket client cancelled — shutting down")
                self._running = False
                break
            except Exception as e:
                self._connected = False
                log.error(
                    f"WebSocket error: {e}. "
                    f"Reconnecting in {self._reconnect_delay:.1f}s..."
                )
                await asyncio.sleep(self._reconnect_delay)
                # Exponential backoff
                self._reconnect_delay = min(
                    self._reconnect_delay * SETTINGS.ws_reconnect_factor,
                    SETTINGS.ws_reconnect_max,
                )

    async def stop(self) -> None:
        """Gracefully stop the WebSocket connection."""
        self._running = False
        if self._stream:
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(self._stream.stop),
                    timeout=5.0,
                )
            except Exception:
                pass
        self._connected = False
        log.info("WebSocket client stopped")

    async def _connect_and_subscribe(self) -> None:
        """Create a new stream, subscribe, and run."""
        log.info(f"Connecting to Alpaca crypto WebSocket for {self._symbols}...")

        self._stream = CryptoDataStream(
            api_key=SETTINGS.alpaca_api_key,
            secret_key=SETTINGS.alpaca_secret_key,
        )

        # Register trade handler
        self._stream.subscribe_trades(self._on_trade, *self._symbols)

        self._connected = True
        self._reconnect_delay = SETTINGS.ws_reconnect_min  # reset on success
        log.info(f"WebSocket connected — subscribed to {len(self._symbols)} symbols")

        # This blocks until disconnected
        await asyncio.to_thread(self._stream.run)

    def _on_trade(self, trade) -> None:
        """
        Callback from Alpaca SDK — runs in a thread.
        Normalize the raw trade object and push to tick_queue.
        """
        try:
            tick = Tick(
                timestamp=trade.timestamp.timestamp()
                if hasattr(trade.timestamp, "timestamp")
                else time.time(),
                symbol=str(trade.symbol),
                price=float(trade.price),
                size=float(trade.size),
            )

            # Non-blocking put — drop if queue is full (backpressure)
            try:
                self._tick_queue.put_nowait(tick)
                self._tick_count += 1
                self._last_tick_time = tick.timestamp
            except asyncio.QueueFull:
                pass  # Drop tick rather than block the WebSocket thread

        except Exception as e:
            log.error(f"Error processing trade: {e}")
