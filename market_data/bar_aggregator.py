"""
TradingBot V5 — Bar Aggregator

Converts raw ticks into 1-minute OHLCV bars.
Supports carry-forward logic for zero-volume intervals.
Emits BarEvent objects to bar_queue.
"""

import asyncio
import logging
import time
from collections import defaultdict
from typing import Optional

from core.events import Tick, BarEvent
from market_data.tick_normalizer import TickNormalizer

log = logging.getLogger("market_data.aggregator")


class BarAggregator:
    """
    Aggregates ticks into time-based OHLCV bars.

    Two concurrent coroutines:
      1. _consume_ticks: reads tick_queue, buffers by symbol
      2. _emit_bars: on interval, creates BarEvent from buffer
    """

    def __init__(
        self,
        tick_queue: asyncio.Queue,
        bar_queue: asyncio.Queue,
        interval_seconds: int = 60,
    ):
        self._tick_queue = tick_queue
        self._bar_queue = bar_queue
        self._interval = interval_seconds
        self._normalizer = TickNormalizer()

        # Per-symbol tick buffer for current interval
        self._buffers: dict[str, list[Tick]] = defaultdict(list)

        # Last emitted bar per symbol (for carry-forward)
        self._last_bar: dict[str, BarEvent] = {}

        # Tracking symbols we've seen (for carry-forward on quiet symbols)
        self._active_symbols: set[str] = set()

        self._bar_count = 0
        self._running = False

    @property
    def bar_count(self) -> int:
        return self._bar_count

    async def run(self) -> None:
        """Start both tick consumer and bar emitter."""
        self._running = True
        await asyncio.gather(
            self._consume_ticks(),
            self._emit_bars(),
        )

    async def stop(self) -> None:
        self._running = False

    def warm_from_bars(self, symbol: str, last_bar: BarEvent) -> None:
        """Load a historical bar as the carry-forward reference."""
        self._last_bar[symbol] = last_bar
        self._active_symbols.add(symbol)

    async def _consume_ticks(self) -> None:
        """Read ticks from queue, normalize, and buffer."""
        while self._running:
            try:
                tick = await asyncio.wait_for(
                    self._tick_queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            # Normalize
            normalized = self._normalizer.normalize(tick)
            if normalized is not None:
                self._buffers[normalized.symbol].append(normalized)
                self._active_symbols.add(normalized.symbol)

    async def _emit_bars(self) -> None:
        """Periodically aggregate buffered ticks into bars."""
        while self._running:
            await asyncio.sleep(self._interval)
            now = time.time()

            # Process all active symbols (including those with no ticks)
            symbols_to_process = set(self._active_symbols)

            for symbol in symbols_to_process:
                ticks = self._buffers.pop(symbol, [])

                if ticks:
                    bar = self._build_bar(symbol, ticks, now)
                else:
                    bar = self._carry_forward(symbol, now)
                    if bar is None:
                        continue

                self._last_bar[symbol] = bar
                self._bar_count += 1

                await self._bar_queue.put(bar)

                log.debug(
                    f"[BAR] {symbol} O={bar.open:.2f} H={bar.high:.2f} "
                    f"L={bar.low:.2f} C={bar.close:.2f} V={bar.volume:.4f} "
                    f"trades={bar.trade_count} cf={bar.is_carry_forward}"
                )

    def _build_bar(
        self, symbol: str, ticks: list[Tick], timestamp: float
    ) -> BarEvent:
        """Build an OHLCV bar from buffered ticks."""
        prices = [t.price for t in ticks]
        sizes = [t.size for t in ticks]

        # VWAP calculation
        total_volume = sum(sizes)
        vwap = (
            sum(p * s for p, s in zip(prices, sizes)) / total_volume
            if total_volume > 0
            else prices[-1]
        )

        return BarEvent(
            timestamp=timestamp,
            symbol=symbol,
            open=prices[0],
            high=max(prices),
            low=min(prices),
            close=prices[-1],
            volume=total_volume,
            vwap=vwap,
            trade_count=len(ticks),
            is_carry_forward=False,
        )

    def _carry_forward(
        self, symbol: str, timestamp: float
    ) -> Optional[BarEvent]:
        """Create a carry-forward bar from last known price."""
        last = self._last_bar.get(symbol)
        if last is None:
            return None

        return BarEvent(
            timestamp=timestamp,
            symbol=symbol,
            open=last.close,
            high=last.close,
            low=last.close,
            close=last.close,
            volume=0.0,
            vwap=last.close,
            trade_count=0,
            is_carry_forward=True,
        )
