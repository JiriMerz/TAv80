"""
Signal Management & Presentation Module
Handles signal lifecycle, notifications and history
Version 1.1.0 (merged patches)

25-08-27 08:31
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from uuid import uuid4
import logging

logger = logging.getLogger(__name__)


class SignalStatus(Enum):
    """Signal lifecycle states"""
    PENDING = "PENDING"         # Waiting for entry
    TRIGGERED = "TRIGGERED"     # Entry price reached
    EXECUTED = "EXECUTED"       # User confirmed execution
    EXPIRED = "EXPIRED"         # Time expired
    CANCELLED = "CANCELLED"     # Manually cancelled
    MISSED = "MISSED"           # Price moved away


@dataclass
class ManagedSignal:
    """Extended signal with lifecycle management"""
    # Core signal data
    signal_id: str
    symbol: str
    signal_type: str          # BUY/SELL
    entry_kind: str           # LIMIT or STOP
    created_at: datetime
    expires_at: datetime

    # Price levels
    entry_price: float
    stop_loss: float
    take_profit: float
    current_price: float

    # Signal metadata
    patterns: List[str]
    confidence: float
    quality: float
    risk_reward: float

    # Status
    status: SignalStatus
    status_changed_at: datetime

    # Tracking
    distance_to_entry: float        # points
    distance_to_entry_atr: float    # ATR units
    time_remaining: int             # minutes

    # ATR tracking (for MISSED/trigger logic in price units)
    atr_at_creation: float = 0.0
    last_atr: float = 0.0

    # Risk management (from ticket if generated)
    position_size: Optional[float] = None
    risk_amount: Optional[float] = None

    # User actions
    user_notes: str = ""
    execution_price: Optional[float] = None
    execution_time: Optional[datetime] = None


class SignalManager:
    """
    Manages signal lifecycle and presentation
    """

    def __init__(self, hass_app, config: Dict):
        """
        Initialize signal manager

        Args:
            hass_app: Reference to main AppDaemon app for HA integration
            config: Configuration dictionary
        """
        self.hass = hass_app
        self.config = config or {}

        # Signal validity periods (minutes)
        self.signal_validity = {
            'AGGRESSIVE': self.config.get('validity_aggressive', 3),   # Quick scalps
            'NORMAL':     self.config.get('validity_normal', 5),       # Standard signals
            'PATIENT':    self.config.get('validity_patient', 10),     # Swing entries
            'LIMIT':      self.config.get('validity_limit', 30)        # Limit orders
        }

        # Trigger zones / missed logic
        self.trigger_zone_atr = float(self.config.get('trigger_zone_atr', 0.2))   # <= this ATR from entry shows "approaching"
        self.missed_atr_multiple = float(self.config.get('missed_atr_multiple', 1.0))  # how far away in ATR to mark as MISSED

        # Storage
        self.active_signals: Dict[str, ManagedSignal] = {}
        self.signal_history: List[ManagedSignal] = []
        self.max_history = int(self.config.get('max_history', 100))

        # Notification settings
        self.notify_on_new = bool(self.config.get('notify_on_new', True))
        self.notify_on_trigger = bool(self.config.get('notify_on_trigger', True))
        self.notify_on_expire = bool(self.config.get('notify_on_expire', False))

    # -------------------------------
    # Public API
    # -------------------------------
    def add_signal(self, signal: Dict, current_price: float, atr: float) -> ManagedSignal:
        """
        Add new signal to management system

        Args:
            signal: Raw signal from edge detector (dict-like)
            current_price: Current market price
            atr: Current ATR for distance calculations
        """
        # Time / symbol / id
        timestamp = datetime.now(timezone.utc)
        symbol = signal.get('symbol', 'UNKNOWN')
        signal_id = f"{symbol}_{timestamp.strftime('%H%M%S')}_{str(uuid4())[:6]}"

        # Determine entry kind (LIMIT vs STOP) from relation of entry to current price
        stype = signal.get('signal_type', 'UNKNOWN')
        entry = float(signal.get('entry', 0.0))
        if stype == "BUY":
            entry_kind = "STOP" if entry > current_price else "LIMIT"
        elif stype == "SELL":
            entry_kind = "STOP" if entry < current_price else "LIMIT"
        else:
            entry_kind = "LIMIT"  # fallback

        # Validity period
        validity_mode = self._determine_validity_mode(signal)
        validity_minutes = self.signal_validity['LIMIT'] if entry_kind == "LIMIT" else self.signal_validity[validity_mode]
        expires_at = timestamp + timedelta(minutes=int(validity_minutes))

        # Distances
        distance = abs(current_price - entry)
        atr = float(atr or 0.0)
        distance_atr = (distance / atr) if atr > 0 else 0.0

        # Build managed instance
        managed = ManagedSignal(
            signal_id=signal_id,
            symbol=symbol,
            signal_type=stype,
            entry_kind=entry_kind,
            created_at=timestamp,
            expires_at=expires_at,
            entry_price=entry,
            stop_loss=float(signal.get('stop_loss', 0.0)),
            take_profit=float(signal.get('take_profit', 0.0)),
            current_price=float(current_price),
            patterns=list(signal.get('patterns', [])),
            confidence=float(signal.get('confidence', 0.0)),
            quality=float(signal.get('signal_quality', 0.0)),
            risk_reward=float(signal.get('risk_reward', 0.0)),
            status=SignalStatus.PENDING,
            status_changed_at=timestamp,
            distance_to_entry=distance,
            distance_to_entry_atr=distance_atr,
            time_remaining=int(validity_minutes),
            atr_at_creation=atr,
            last_atr=atr
        )

        # Store
        self.active_signals[signal_id] = managed

        # HA sensor
        self._update_ha_sensor(managed)

        # Notify
        if self.notify_on_new:
            self._send_notification(managed, "NEW")

        logger.info(f"New signal: {signal_id} {managed.signal_type}({managed.entry_kind}) @ {managed.entry_price}")
        return managed

    def update_signals(self, market_prices: Dict[str, float], current_atr: Dict[str, float]):
        """
        Update all active signals with current market data

        Args:
            market_prices: Dict of symbol -> current price
            current_atr: Dict of symbol -> current ATR (price units)
        """
        now = datetime.now(timezone.utc)

        for signal_id, signal in list(self.active_signals.items()):
            # Skip terminated
            if signal.status in (SignalStatus.EXECUTED, SignalStatus.EXPIRED, SignalStatus.CANCELLED, SignalStatus.MISSED):
                continue

            # Update live price & distances
            if signal.symbol in market_prices:
                signal.current_price = float(market_prices[signal.symbol])
                signal.distance_to_entry = abs(signal.current_price - signal.entry_price)

            # Update ATR info
            if signal.symbol in (current_atr or {}):
                last_atr = float(current_atr[signal.symbol] or 0.0)
                if last_atr > 0:
                    signal.last_atr = last_atr
                    signal.distance_to_entry_atr = signal.distance_to_entry / last_atr
                else:
                    signal.distance_to_entry_atr = 0.0

            # Time remaining
            time_left = (signal.expires_at - now).total_seconds() / 60.0
            signal.time_remaining = max(0, int(time_left))

            # Status transition
            old_status = signal.status
            new_status = self._determine_status(signal, now)

            if new_status != old_status:
                signal.status = new_status
                signal.status_changed_at = now
                self._handle_status_change(signal, old_status, new_status)

            # Update HA entity each tick
            self._update_ha_sensor(signal)

    def mark_executed(self, signal_id: str, execution_price: Optional[float] = None):
        """Mark signal as executed by user"""
        if signal_id in self.active_signals:
            signal = self.active_signals[signal_id]
            signal.status = SignalStatus.EXECUTED
            signal.status_changed_at = datetime.now(timezone.utc)
            signal.execution_price = float(execution_price) if execution_price is not None else float(signal.current_price)
            signal.execution_time = datetime.now(timezone.utc)

            # Move to history and remove from active
            self.signal_history.append(signal)
            if len(self.signal_history) > self.max_history:
                self.signal_history.pop(0)
            del self.active_signals[signal_id]

            # Update HA once more to show final state
            self._update_ha_sensor(signal)
            logger.info(f"Signal {signal_id} marked as executed @ {signal.execution_price}")

    def cancel_signal(self, signal_id: str):
        """Cancel active signal"""
        if signal_id in self.active_signals:
            signal = self.active_signals[signal_id]
            signal.status = SignalStatus.CANCELLED
            signal.status_changed_at = datetime.now(timezone.utc)

            # Move to history and remove from active
            self.signal_history.append(signal)
            if len(self.signal_history) > self.max_history:
                self.signal_history.pop(0)
            del self.active_signals[signal_id]

            # Update HA final state
            self._update_ha_sensor(signal)
            logger.info(f"Signal {signal_id} cancelled")

    def get_active_summary(self) -> List[Dict]:
        """Get summary of active signals for dashboard"""
        summary = []
        for signal in self.active_signals.values():
            summary.append({
                'id': signal.signal_id,
                'symbol': signal.symbol,
                'type': signal.signal_type,
                'kind': signal.entry_kind,
                'status': signal.status.value,
                'entry': signal.entry_price,
                'current': signal.current_price,
                'distance': signal.distance_to_entry,
                'expires_in': signal.time_remaining,
                'confidence': signal.confidence
            })
        return summary

    def get_performance_stats(self) -> Dict:
        """Calculate performance statistics from history"""
        if not self.signal_history:
            return {}
        executed = [s for s in self.signal_history if s.status == SignalStatus.EXECUTED]
        expired = [s for s in self.signal_history if s.status == SignalStatus.EXPIRED]
        missed  = [s for s in self.signal_history if s.status == SignalStatus.MISSED]
        avg_conf = sum(s.confidence for s in self.signal_history) / len(self.signal_history)
        avg_quality = sum(s.quality for s in self.signal_history) / len(self.signal_history)
        return {
            'total_signals': len(self.signal_history),
            'executed': len(executed),
            'expired': len(expired),
            'missed': len(missed),
            'avg_confidence': round(avg_conf, 1),
            'avg_quality': round(avg_quality, 1),
        }

    # -------------------------------
    # Internals
    # -------------------------------
    def _determine_status(self, signal: ManagedSignal, now: datetime) -> SignalStatus:
        """Determine current signal status (PENDING → TRIGGERED/MISSED/EXPIRED)"""
        # Expiration
        if now >= signal.expires_at:
            return SignalStatus.EXPIRED

        # Only consider triggers/missed while pending
        if signal.status != SignalStatus.PENDING:
            return signal.status

        atr_px = signal.last_atr or signal.atr_at_creation or 0.0
        miss_k = self.missed_atr_multiple

        # Decide trigger direction based on entry kind + signal type
        if signal.signal_type == "BUY":
            # BUY LIMIT → expecting price down to entry; BUY STOP → expecting up to entry
            trigger_up = (signal.entry_kind == "STOP")
        elif signal.signal_type == "SELL":
            # SELL LIMIT → expecting price up to entry; SELL STOP → expecting down to entry
            trigger_up = (signal.entry_kind == "LIMIT")
        else:
            trigger_up = False  # fallback

        # Trigger condition
        if trigger_up:
            if signal.current_price >= signal.entry_price:
                return SignalStatus.TRIGGERED
            # Missed if price moves sufficiently away below entry
            if atr_px > 0 and signal.current_price <= signal.entry_price - miss_k * atr_px:
                return SignalStatus.MISSED
        else:
            if signal.current_price <= signal.entry_price:
                return SignalStatus.TRIGGERED
            # Missed if price moves sufficiently away above entry
            if atr_px > 0 and signal.current_price >= signal.entry_price + miss_k * atr_px:
                return SignalStatus.MISSED

        return signal.status

    def _determine_validity_mode(self, signal: Dict) -> str:
        """Determine signal validity mode based on characteristics"""
        confidence = float(signal.get('confidence', 0.0))
        quality = float(signal.get('signal_quality', 0.0))
        if confidence >= 80.0 and quality >= 80.0:
            return 'PATIENT'   # High quality - give more time
        elif confidence >= 60.0:
            return 'NORMAL'    # Standard signal
        else:
            return 'AGGRESSIVE'  # Lower confidence - quick decision

    def _handle_status_change(self, signal: ManagedSignal, old_status: SignalStatus, new_status: SignalStatus):
        """Handle signal status transitions"""
        logger.info(f"Signal {signal.signal_id} status: {old_status.value} -> {new_status.value}")

        if new_status == SignalStatus.TRIGGERED and self.notify_on_trigger:
            self._send_notification(signal, "TRIGGERED")

        elif new_status in (SignalStatus.EXPIRED, SignalStatus.MISSED):
            # Move to history & trim
            self.signal_history.append(signal)
            if len(self.signal_history) > self.max_history:
                self.signal_history.pop(0)
            # Remove from active
            if signal.signal_id in self.active_signals:
                del self.active_signals[signal.signal_id]

            if new_status == SignalStatus.EXPIRED and self.notify_on_expire:
                self._send_notification(signal, "EXPIRED")

    def _update_ha_sensor(self, signal: ManagedSignal):
        """Update Home Assistant sensor(s) for signal"""
        # Per-signal entity to avoid overwriting when multiple signals exist
        sensor_name = f"sensor.signal_{signal.signal_id.lower()}"
        state = self._compose_state(signal)
        attributes = self._compose_attributes(signal)
        self.hass.set_state(sensor_name, state=state, attributes=attributes)

        # Optional headline per symbol (latest state)
        head_name = f"sensor.signal_{signal.symbol.lower()}_headline"
        head_attr = dict(attributes)
        head_attr["latest_id"] = signal.signal_id
        self.hass.set_state(head_name, state=state, attributes=head_attr)

    def _compose_state(self, signal: ManagedSignal) -> str:
        """Human-friendly state for HA"""
        if signal.status == SignalStatus.TRIGGERED:
            return "🔥 ENTRY NOW"
        if signal.status == SignalStatus.PENDING:
            if signal.distance_to_entry_atr <= self.trigger_zone_atr and (signal.last_atr > 0 or signal.atr_at_creation > 0):
                return "⚡ APPROACHING"
            return "⏳ WAITING"
        return signal.status.value

    def _compose_attributes(self, signal: ManagedSignal) -> Dict:
        """Attributes dict for HA entity"""
        attrs = {
            'signal_id': signal.signal_id,
            'symbol': signal.symbol,
            'type': signal.signal_type,
            'kind': signal.entry_kind,
            'entry': signal.entry_price,
            'current': signal.current_price,
            'distance': round(signal.distance_to_entry, 5),
            'distance_atr': round(signal.distance_to_entry_atr, 3),
            'sl': signal.stop_loss,
            'tp': signal.take_profit,
            'rr': signal.risk_reward,
            'confidence': f"{signal.confidence:.0f}%",
            'quality': f"{signal.quality:.0f}%",
            'patterns': ', '.join(signal.patterns),
            'expires_in': f"{signal.time_remaining}m",
            'status': signal.status.value,
            'created': signal.created_at.isoformat(),
            'last_atr': round(signal.last_atr, 5),
            'atr_at_creation': round(signal.atr_at_creation, 5),
        }
        if signal.position_size is not None:
            attrs['lots'] = signal.position_size
        if signal.execution_price is not None:
            attrs['executed_price'] = signal.execution_price
        if signal.execution_time is not None:
            attrs['executed_time'] = signal.execution_time.isoformat()
        return attrs

    def _send_notification(self, signal: ManagedSignal, event_type: str):
        """Send notification via HA notify service"""
        if not self.hass:
            return

        if event_type == "NEW":
            title = f"📊 New {signal.signal_type} ({signal.entry_kind})"
            message = (f"{signal.symbol} @ {signal.entry_price:.1f}\n"
                       f"SL: {signal.stop_loss:.1f} | TP: {signal.take_profit:.1f}\n"
                       f"RR: {signal.risk_reward:.1f} | Conf: {signal.confidence:.0f}%")
        elif event_type == "TRIGGERED":
            title = "🔥 ENTRY TRIGGERED"
            message = (f"{signal.symbol} {signal.signal_type} {signal.entry_kind}\n"
                       f"Entry: {signal.entry_price:.1f} | Now: {signal.current_price:.1f}\n"
                       f"EXECUTE NOW!")
        elif event_type == "EXPIRED":
            title = "⏰ Signal Expired"
            message = f"{signal.symbol} {signal.signal_type} expired (not triggered in time)"
        else:
            return

        # Send via HA notify (default)
        try:
            self.hass.call_service("notify/notify", title=title, message=message)
        except Exception as e:
            logger.warning(f"notify/notify failed: {e}")

        # Also persistent notification
        try:
            self.hass.call_service(
                "persistent_notification/create",
                title=title,
                message=message,
                notification_id=f"signal_{signal.signal_id}"
            )
        except Exception as e:
            logger.warning(f"persistent_notification failed: {e}")
            
    