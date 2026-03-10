"""
Tests for BarAggregator — tick-to-bar conversion and carry-forward logic.
"""

import asyncio
import pytest
import time
from core.events import Tick, BarEvent
from market_data.bar_aggregator import BarAggregator


@pytest.fixture
def queues():
    return asyncio.Queue(), asyncio.Queue()


@pytest.fixture
def aggregator(queues):
    tick_q, bar_q = queues
    return BarAggregator(tick_q, bar_q, interval_seconds=1)


class TestBarAggregation:
    """Test OHLCV bar creation from ticks."""

    @pytest.mark.asyncio
    async def test_single_tick_bar(self, queues, aggregator):
        """A single tick should produce a valid bar."""
        tick_q, bar_q = queues

        tick = Tick(timestamp=time.time(), symbol="BTC/USD", price=50000.0, size=0.1)
        await tick_q.put(tick)

        # Start aggregator for one cycle
        task = asyncio.create_task(aggregator.run())
        await asyncio.sleep(1.5)
        aggregator._running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        bar = bar_q.get_nowait()
        assert bar.symbol == "BTC/USD"
        assert bar.open == 50000.0
        assert bar.high == 50000.0
        assert bar.low == 50000.0
        assert bar.close == 50000.0
        assert bar.volume == 0.1
        assert bar.trade_count == 1
        assert bar.is_carry_forward is False

    @pytest.mark.asyncio
    async def test_multi_tick_ohlcv(self, queues, aggregator):
        """Multiple ticks should produce correct OHLCV."""
        tick_q, bar_q = queues

        now = time.time()
        ticks = [
            Tick(timestamp=now, symbol="ETH/USD", price=3000.0, size=1.0),
            Tick(timestamp=now + 0.1, symbol="ETH/USD", price=3050.0, size=0.5),
            Tick(timestamp=now + 0.2, symbol="ETH/USD", price=2980.0, size=2.0),
            Tick(timestamp=now + 0.3, symbol="ETH/USD", price=3020.0, size=0.8),
        ]
        for t in ticks:
            await tick_q.put(t)

        task = asyncio.create_task(aggregator.run())
        await asyncio.sleep(1.5)
        aggregator._running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        bar = bar_q.get_nowait()
        assert bar.open == 3000.0
        assert bar.high == 3050.0
        assert bar.low == 2980.0
        assert bar.close == 3020.0
        assert bar.volume == pytest.approx(4.3)
        assert bar.trade_count == 4

    @pytest.mark.asyncio
    async def test_carry_forward(self, queues, aggregator):
        """Carry-forward should repeat last close when no ticks arrive."""
        tick_q, bar_q = queues

        # Warm the aggregator with a previous bar
        prev = BarEvent(
            timestamp=time.time(),
            symbol="SOL/USD",
            open=100.0, high=105.0, low=98.0, close=102.0,
            volume=500.0, trade_count=10,
        )
        aggregator.warm_from_bars("SOL/USD", prev)

        # No ticks submitted — should get carry-forward
        task = asyncio.create_task(aggregator.run())
        await asyncio.sleep(1.5)
        aggregator._running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        bar = bar_q.get_nowait()
        assert bar.symbol == "SOL/USD"
        assert bar.open == 102.0
        assert bar.close == 102.0
        assert bar.volume == 0.0
        assert bar.is_carry_forward is True

    @pytest.mark.asyncio
    async def test_multi_symbol(self, queues, aggregator):
        """Bars should be created independently per symbol."""
        tick_q, bar_q = queues

        now = time.time()
        await tick_q.put(Tick(now, "BTC/USD", 50000.0, 0.1))
        await tick_q.put(Tick(now, "ETH/USD", 3000.0, 1.0))

        task = asyncio.create_task(aggregator.run())
        await asyncio.sleep(1.5)
        aggregator._running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        bars = []
        while not bar_q.empty():
            bars.append(bar_q.get_nowait())

        symbols = {b.symbol for b in bars}
        assert "BTC/USD" in symbols
        assert "ETH/USD" in symbols
