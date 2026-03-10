"""
TradingBot V5 — Broker Reconciliation Service

Periodically verifies local state against Alpaca broker state.
Trust-but-verify: the broker is the source of truth on conflict.
"""

import asyncio
import logging
import time
from typing import Optional

from config.settings import SETTINGS
from execution.execution_engine import ExecutionEngine
from positions.position_manager import PositionManager
from risk.risk_manager import RiskManager
from storage.repository import Repository

log = logging.getLogger("reconciliation")


class Reconciler:
    """
    Periodic broker state verification.

    Every RECONCILIATION_INTERVAL seconds:
      1. Fetch broker positions, orders, account
      2. Compare to local state
      3. Auto-correct if safe (broker wins)
      4. Log everything
    """

    def __init__(
        self,
        execution_engine: ExecutionEngine,
        position_manager: PositionManager,
        risk_manager: RiskManager,
        repository: Repository,
    ):
        self._engine = execution_engine
        self._pos_mgr = position_manager
        self._risk_mgr = risk_manager
        self._repo = repository
        self._running = False
        self._last_reconciliation: float = 0

    async def run(self) -> None:
        """Periodic reconciliation loop."""
        self._running = True
        while self._running:
            await asyncio.sleep(SETTINGS.reconciliation_interval)
            try:
                await self.reconcile()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Reconciliation error: {e}")

    async def stop(self) -> None:
        self._running = False

    async def reconcile(self) -> dict:
        """
        Perform a full state reconciliation.
        Returns summary of findings.
        """
        log.info("Starting broker reconciliation...")
        now = time.time()
        discrepancies = []

        try:
            # Fetch broker state (sync calls in thread)
            broker_account = await asyncio.wait_for(
                asyncio.to_thread(self._engine.get_account_sync),
                timeout=15.0,
            )
            broker_positions = await asyncio.wait_for(
                asyncio.to_thread(self._engine.get_positions_sync),
                timeout=15.0,
            )
        except Exception as e:
            log.error(f"Failed to fetch broker state: {e}")
            return {"error": str(e)}

        # ── 1. Update equity cache ──────────────────────────────
        equity = float(broker_account.equity)
        buying_power = float(broker_account.buying_power)
        self._risk_mgr.update_equity(equity, buying_power)

        # ── 2. Compare positions ────────────────────────────────
        broker_pos_map = {}
        for bp in broker_positions:
            symbol = str(bp.symbol)
            qty = float(bp.qty)
            side = "LONG" if qty > 0 else "SHORT" if qty < 0 else "FLAT"
            broker_pos_map[symbol] = {
                "side": side,
                "quantity": abs(qty),
                "avg_entry": float(bp.avg_entry_price),
                "market_value": float(bp.market_value),
                "unrealized_pnl": float(bp.unrealized_pl),
            }

        local_pos_map = {}
        for symbol, pos in self._pos_mgr.positions.items():
            local_pos_map[symbol] = {
                "side": pos.side,
                "quantity": pos.quantity,
                "avg_entry": pos.avg_entry_price,
            }

        # Check for positions at broker but not locally
        for symbol, bp in broker_pos_map.items():
            local = local_pos_map.get(symbol)
            if local is None:
                discrepancies.append({
                    "type": "MISSING_LOCAL",
                    "symbol": symbol,
                    "broker": bp,
                    "local": None,
                })
                # Auto-correct: add to local
                await self._pos_mgr.set_from_broker(
                    symbol=symbol,
                    side=bp["side"],
                    quantity=bp["quantity"],
                    avg_entry=bp["avg_entry"],
                )
                log.warning(
                    f"[{symbol}] Position missing locally — "
                    f"synced from broker: {bp['side']} {bp['quantity']}"
                )

            elif (
                local["side"] != bp["side"]
                or abs(local["quantity"] - bp["quantity"]) > 0.0001
            ):
                discrepancies.append({
                    "type": "MISMATCH",
                    "symbol": symbol,
                    "broker": bp,
                    "local": local,
                })
                # Auto-correct: broker wins
                await self._pos_mgr.set_from_broker(
                    symbol=symbol,
                    side=bp["side"],
                    quantity=bp["quantity"],
                    avg_entry=bp["avg_entry"],
                )
                log.warning(
                    f"[{symbol}] Position mismatch — corrected to broker: "
                    f"{bp['side']} {bp['quantity']}"
                )

        # Check for positions locally but not at broker
        for symbol, local in local_pos_map.items():
            if local["side"] != "FLAT" and symbol not in broker_pos_map:
                discrepancies.append({
                    "type": "STALE_LOCAL",
                    "symbol": symbol,
                    "broker": None,
                    "local": local,
                })
                # Auto-correct: mark as FLAT
                await self._pos_mgr.set_from_broker(
                    symbol=symbol,
                    side="FLAT",
                    quantity=0.0,
                    avg_entry=0.0,
                )
                log.warning(
                    f"[{symbol}] Stale local position — marked FLAT"
                )

        # ── 3. Update position count for risk manager ───────────
        self._risk_mgr.update_position_count(self._pos_mgr.open_count)

        # ── 4. Log reconciliation ───────────────────────────────
        action = "NONE" if not discrepancies else "AUTO_CORRECTED"
        await self._repo.insert_reconciliation(
            timestamp=now,
            broker_positions=broker_pos_map,
            local_positions=local_pos_map,
            discrepancies=discrepancies,
            action_taken=action,
        )

        self._last_reconciliation = now

        if discrepancies:
            log.warning(
                f"Reconciliation found {len(discrepancies)} discrepancies — "
                f"auto-corrected"
            )
        else:
            log.info("Reconciliation complete — no discrepancies")

        return {
            "timestamp": now,
            "equity": equity,
            "buying_power": buying_power,
            "broker_positions": len(broker_pos_map),
            "discrepancies": len(discrepancies),
            "action": action,
        }
