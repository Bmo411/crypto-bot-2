"""
TradingBot V5 — Broker Client

Async wrapper around Alpaca TradingClient with TTL caching.
This is the single gateway through which *all* components read
live account and position data from Alpaca.

Design rules:
  - Account data is cached for SETTINGS.account_refresh_interval (30s)
  - Position data is cached for SETTINGS.positions_refresh_interval (10s)
  - Every method returns None / [] on error — never raises
  - All blocking SDK calls run via asyncio.to_thread
"""

import asyncio
import logging
import time
from typing import Optional

from alpaca.trading.client import TradingClient

from config.settings import SETTINGS

log = logging.getLogger("execution.broker_client")


class BrokerClient:
    """
    Cached async interface to Alpaca's REST API.

    Two caches:
      - _account_cache  : refreshed every account_refresh_interval (30s)
      - _positions_cache: refreshed every positions_refresh_interval (10s)

    Callers get cached data instantly; caches are refreshed lazily on
    first expired access (no background thread needed).
    """

    def __init__(self) -> None:
        self._client = TradingClient(
            api_key=SETTINGS.alpaca_api_key,
            secret_key=SETTINGS.alpaca_secret_key,
            paper=SETTINGS.paper_mode,
        )

        self._account_cache = None
        self._account_fetched_at: float = 0.0
        self._account_lock = asyncio.Lock()

        self._positions_cache: list = []
        self._positions_fetched_at: float = 0.0
        self._positions_lock = asyncio.Lock()

    # ── Public API ───────────────────────────────────────────────

    async def get_account(self):
        """
        Return Alpaca account object (cached, max 30s stale).

        Returns None if Alpaca is unreachable.
        """
        now = time.time()
        if now - self._account_fetched_at < SETTINGS.account_refresh_interval:
            return self._account_cache

        async with self._account_lock:
            # Double-checked locking
            now = time.time()
            if now - self._account_fetched_at < SETTINGS.account_refresh_interval:
                return self._account_cache

            try:
                account = await asyncio.wait_for(
                    asyncio.to_thread(self._client.get_account),
                    timeout=15.0,
                )
                self._account_cache = account
                self._account_fetched_at = time.time()
                log.debug(
                    f"Account refreshed — equity=${float(account.equity):,.2f}"
                )
                return account
            except asyncio.TimeoutError:
                log.warning("Alpaca account fetch timed out — using cached data")
                return self._account_cache
            except Exception as e:
                log.error(f"Alpaca account fetch failed: {e} — using cached data")
                return self._account_cache

    async def get_all_positions(self) -> list:
        """
        Return list of Alpaca Position objects (cached, max 10s stale).

        Returns [] if Alpaca is unreachable.
        """
        now = time.time()
        if now - self._positions_fetched_at < SETTINGS.positions_refresh_interval:
            return self._positions_cache

        async with self._positions_lock:
            now = time.time()
            if now - self._positions_fetched_at < SETTINGS.positions_refresh_interval:
                return self._positions_cache

            try:
                positions = await asyncio.wait_for(
                    asyncio.to_thread(self._client.get_all_positions),
                    timeout=15.0,
                )
                self._positions_cache = positions if positions else []
                self._positions_fetched_at = time.time()
                log.debug(f"Positions refreshed — {len(self._positions_cache)} open")
                return self._positions_cache
            except asyncio.TimeoutError:
                log.warning("Alpaca positions fetch timed out — using cached data")
                return self._positions_cache
            except Exception as e:
                log.error(f"Alpaca positions fetch failed: {e} — using cached data")
                return self._positions_cache

    def get_account_sync(self):
        """Synchronous wrapper for use in reconciler threads."""
        return self._client.get_account()

    def get_positions_sync(self) -> list:
        """Synchronous wrapper for use in reconciler threads."""
        positions = self._client.get_all_positions()
        return positions if positions else []

    def invalidate(self) -> None:
        """Force cache expiry — call after submitting orders."""
        self._account_fetched_at = 0.0
        self._positions_fetched_at = 0.0
