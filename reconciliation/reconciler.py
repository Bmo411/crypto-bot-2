"""
TradingBot V5 — Broker Reconciliation Service

Periodically verifies local state against Alpaca broker state.
Trust-but-verify: the broker is the source of truth on conflict.

After each reconciliation the live account equity is pushed into
MetricsCollector so the dashboard always shows real values.
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
      4. Push account equity to MetricsCollector
      5. Sync positions (incl. unrealized PnL) via PositionManager.sync_from_broker()
      6. Log everything
    """

    def __init__(
        self,
        execution_engine: ExecutionEngine,
        position_manager: PositionManager,
        risk_manager: RiskManager,
        repository: Repository,
        metrics_collector=None,  # metrics.collector.MetricsCollector (optional for tests)
    ):
        self._engine = execution_engine
        self._pos_mgr = position_manager
        self._risk_mgr = risk_manager
        self._repo = repository
        self._metrics = metrics_collector
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

        # ── 1. Update equity in MetricsCollector (dashboard source of truth) ──
        equity = float(broker_account.equity)
        buying_power = float(broker_account.buying_power)
        cash = float(getattr(broker_account, "cash", 0.0) or 0.0)
        self._risk_mgr.update_equity(equity, buying_power)

        if self._metrics is not None:
            self._metrics.update_account(
                equity=equity,
                cash=cash,
                buying_power=buying_power,
            )
            log.info(
                f"Metrics updated from broker — equity=${equity:,.2f}, "
                f"cash=${cash:,.2f}, buying_power=${buying_power:,.2f}"
            )

        # ── 2. Build broker position map (before sync for discrepancy check) ──
        broker_pos_map = {}
        for bp in (broker_positions or []):
            try:
                symbol = str(bp.symbol)
                qty = float(bp.qty)
                side = "LONG" if qty > 0 else "SHORT" if qty < 0 else "FLAT"
                broker_pos_map[symbol] = {
                    "side": side,
                    "quantity": abs(qty),
                    "avg_entry": float(bp.avg_entry_price),
                    "market_value": float(getattr(bp, "market_value", 0) or 0),
                    "unrealized_pnl": float(bp.unrealized_pl),
                    "current_price": float(getattr(bp, "current_price", 0) or 0),
                }
            except Exception as e:
                log.error(f"Error parsing broker position {getattr(bp, 'symbol', '?')}: {e}")

        # ── 3. Snapshot local state BEFORE sync (for discrepancy detection) ─
        local_pos_map_before = {}
        for symbol, pos in self._pos_mgr.positions.items():
            local_pos_map_before[symbol] = {
                "side": pos.side,
                "quantity": pos.quantity,
                "avg_entry": pos.avg_entry_price,
            }

        # ── 4. Detect structural discrepancies ──────────────────────────────
        # Check for positions at broker but not locally (or mismatched)
        for symbol, bp in broker_pos_map.items():
            local = local_pos_map_before.get(symbol)
            if local is None:
                discrepancies.append({
                    "type": "MISSING_LOCAL",
                    "symbol": symbol,
                    "broker": bp,
                    "local": None,
                })
                log.warning(
                    f"[{symbol}] Position missing locally — "
                    f"will be synced from broker: {bp['side']} {bp['quantity']}"
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
                log.warning(
                    f"[{symbol}] Position mismatch — corrected to broker: "
                    f"{bp['side']} {bp['quantity']}"
                )

        # Check for positions locally but not at broker
        for symbol, local in local_pos_map_before.items():
            if local["side"] != "FLAT" and symbol not in broker_pos_map:
                discrepancies.append({
                    "type": "STALE_LOCAL",
                    "symbol": symbol,
                    "broker": None,
                    "local": local,
                })
                log.warning(f"[{symbol}] Stale local position — will be marked FLAT by sync")

        # ── 5. Sync positions from broker (applies all corrections + PnL) ───
        await self._pos_mgr.sync_from_broker(broker_positions if broker_positions else [])

        # Build final local_pos_map for persistence (post-sync state)
        local_pos_map = {}
        for symbol, pos in self._pos_mgr.positions.items():
            local_pos_map[symbol] = {
                "side": pos.side,
                "quantity": pos.quantity,
                "avg_entry": pos.avg_entry_price,
            }

        # ── 4. Update position count for risk manager ───────────────────────
        self._risk_mgr.update_position_count(self._pos_mgr.open_count)

        # ── 5. Persist reconciliation log ──────────────────────────────────
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
