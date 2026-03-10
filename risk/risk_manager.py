"""
TradingBot V5 — Risk Manager

Pre-trade validation and position sizing.
Enforces:
  - Risk per trade (0.3%)
  - Max position size (10% of equity)
  - Max daily loss (3% circuit breaker)
  - Max simultaneous positions (5)
  - Buying power check
"""

import logging
import time
from typing import Optional

from config.settings import SETTINGS
from config.strategy_params import MeanReversionParams
from core.events import SignalEvent, RiskEvent

log = logging.getLogger("risk.manager")


class RiskManager:
    """
    Gate between strategy signals and order execution.
    Every signal must pass through validate_signal() before execution.
    """

    def __init__(self, params: MeanReversionParams):
        self._params = params

        # Live state (updated by position manager / reconciler)
        self._equity: float = SETTINGS.initial_capital
        self._buying_power: float = SETTINGS.initial_capital * 2
        self._open_position_count: int = 0
        self._daily_pnl: float = 0.0
        self._daily_start_equity: float = SETTINGS.initial_capital

        # Risk parameters
        self._risk_per_trade = (
            params.max_risk_per_trade
            if params.max_risk_per_trade is not None
            else SETTINGS.risk_per_trade
        )
        self._max_position_pct = (
            params.max_position_pct
            if params.max_position_pct is not None
            else SETTINGS.max_position_pct
        )

        # Trading halt flag
        self._trading_halted = False
        self._halt_reason: str = ""

    @property
    def is_halted(self) -> bool:
        return self._trading_halted

    @property
    def halt_reason(self) -> str:
        return self._halt_reason

    def update_equity(self, equity: float, buying_power: float) -> None:
        """Called by reconciler / equity snapshot with latest account state."""
        self._equity = equity
        self._buying_power = buying_power

    def update_daily_pnl(self, daily_pnl: float) -> None:
        """Called by metrics collector with today's realized + unrealized PnL."""
        self._daily_pnl = daily_pnl
        self._check_daily_drawdown()

    def update_position_count(self, count: int) -> None:
        """Called by position manager when positions change."""
        self._open_position_count = count

    def reset_daily(self) -> None:
        """Reset daily counters (call at UTC midnight)."""
        self._daily_pnl = 0.0
        self._daily_start_equity = self._equity
        if self._trading_halted and "DAILY" in self._halt_reason:
            self._trading_halted = False
            self._halt_reason = ""
            log.info("Daily drawdown halt lifted — trading resumed")

    def validate_signal(
        self, signal: SignalEvent
    ) -> tuple[bool, Optional[RiskEvent]]:
        """
        Validate a signal against all risk rules.

        Returns:
            (True, None) if approved
            (False, RiskEvent) if rejected with reason
        """
        # Exit signals are ALWAYS approved — even when halted
        # (we must be able to close positions to reduce risk)
        if "EXIT" in signal.signal_type or signal.signal_type in (
            "STOP_LOSS", "TAKE_PROFIT"
        ):
            return True, None

        # Check trading halt (only blocks new entries)
        if self._trading_halted:
            return False, RiskEvent(
                symbol=signal.symbol,
                event_type="SIGNAL_REJECTED_RISK",
                reason=f"Trading halted: {self._halt_reason}",
            )

        # Check max positions
        if self._open_position_count >= SETTINGS.max_positions:
            return False, RiskEvent(
                symbol=signal.symbol,
                event_type="SIGNAL_REJECTED_RISK",
                reason=f"Max positions reached ({SETTINGS.max_positions})",
            )

        # Check daily drawdown
        daily_loss_pct = abs(self._daily_pnl / self._equity) if self._equity > 0 else 0
        if daily_loss_pct >= SETTINGS.max_daily_loss_pct:
            self._halt_trading(
                f"DAILY DRAWDOWN: {daily_loss_pct:.2%} >= {SETTINGS.max_daily_loss_pct:.2%}"
            )
            return False, RiskEvent(
                symbol=signal.symbol,
                event_type="RISK_BREACH",
                reason="Daily drawdown limit exceeded",
                details={
                    "daily_pnl": self._daily_pnl,
                    "daily_loss_pct": daily_loss_pct,
                    "limit": SETTINGS.max_daily_loss_pct,
                },
            )

        return True, None

    def calculate_position_size(
        self, signal: SignalEvent
    ) -> float:
        """
        Calculate the position quantity based on risk budget.

        Uses fixed-risk sizing:
          qty = risk_amount / (price * stop_loss_pct)
        Capped at max_position_pct of equity.
        """
        if signal.price <= 0 or self._equity <= 0:
            return 0.0

        # Risk budget
        risk_amount = self._equity * self._risk_per_trade  # e.g. $252

        # Stop distance
        stop_pct = self._params.stop_loss_pct  # e.g. 1%
        stop_distance = signal.price * stop_pct

        if stop_distance <= 0:
            return 0.0

        # Risk-based quantity
        risk_qty = risk_amount / stop_distance

        # Cap at max position size
        max_notional = self._equity * self._max_position_pct  # e.g. $8,400
        max_qty = max_notional / signal.price

        # Cap at buying power (with buffer)
        bp_notional = self._buying_power * SETTINGS.buying_power_buffer
        bp_qty = bp_notional / signal.price

        qty = min(risk_qty, max_qty, bp_qty)

        log.info(
            f"[{signal.symbol}] Position size: "
            f"risk_qty={risk_qty:.6f}, max_qty={max_qty:.6f}, "
            f"bp_qty={bp_qty:.6f} → final={qty:.6f} "
            f"(notional=${qty * signal.price:.2f})"
        )

        return max(qty, 0.0)

    def _check_daily_drawdown(self) -> None:
        """Check if daily drawdown limit has been hit."""
        if self._equity <= 0:
            return
        daily_loss_pct = abs(self._daily_pnl / self._equity)
        if self._daily_pnl < 0 and daily_loss_pct >= SETTINGS.max_daily_loss_pct:
            self._halt_trading(
                f"DAILY DRAWDOWN: {daily_loss_pct:.2%} >= {SETTINGS.max_daily_loss_pct:.2%}"
            )

    def _halt_trading(self, reason: str) -> None:
        """Halt all new entries."""
        if not self._trading_halted:
            self._trading_halted = True
            self._halt_reason = reason
            log.critical(f"TRADING HALTED: {reason}")
