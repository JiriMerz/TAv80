"""
Account State Monitor for TAv50
- Based exactly on working demo: /Users/jirimerz/Projects/ctrader-python-app-ws/ctrader-json-client.py
- Works with existing callback architecture
- Account balance from deals using balanceVersion
- Open positions from PT_TRADER_RES
- Daily realized PnL from closed deals only

2025-01-03
"""

import threading
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional
from aiohttp import ClientResponseError

logger = logging.getLogger(__name__)

# Import PositionSize for risk manager sync (with try-except to handle missing module gracefully)
try:
    from .risk_manager import PositionSize
    RISK_MANAGER_AVAILABLE = True
except ImportError:
    logger.warning("[ACCOUNT_MONITOR] ⚠️ risk_manager module not available - position sync disabled")
    PositionSize = None
    RISK_MANAGER_AVAILABLE = False

class AccountStateMonitor:
    """
    Account monitor based exactly on working demo but adapted for existing client callbacks
    """

    def __init__(self, ctrader_client, app_instance, config: Dict = None, risk_manager=None, balance_tracker=None):
        self.client = ctrader_client
        self.app = app_instance
        self.config = config or {}
        self.risk_manager = risk_manager  # CRITICAL FIX: Add risk manager reference
        self.balance_tracker = balance_tracker  # CRITICAL: Add balance tracker reference for execution event updates

        # Thread-safe state
        self._lock = threading.RLock()
        self._account_state = {
            "balance": 0,
            "equity": 0,
            "open_positions": [],
            "daily_realized_pnl": 0,
            "closed_positions_today": 0,
            "last_update": None
        }

        # Configuration
        account_config = config.get('account_monitoring', {})
        self.enabled = account_config.get('enabled', False)

        # NEW: Event-driven configuration
        self.update_on_execution_only = account_config.get('update_on_execution_only', True)
        self.fallback_update_interval = account_config.get('fallback_update_interval', 300)  # 5 minutes
        self.legacy_periodic_interval = account_config.get('legacy_periodic_interval', 30)  # 30 seconds (fallback)

        # Track last execution event for fallback logic
        self._last_execution_time = None

        # Guard against double initialization
        self._started = False

        # CRITICAL FIX: Thread protection for timer scheduling
        self._timer_running = False
        self._timer_lock = threading.Lock()

        logger.info(f"[ACCOUNT_MONITOR] Initialized (enabled: {self.enabled})")
        logger.info(f"[ACCOUNT_MONITOR] Event-driven mode: {self.update_on_execution_only}")
        logger.info(f"[ACCOUNT_MONITOR] Fallback interval: {self.fallback_update_interval}s")

    def _jsonify_attrs(self, attrs: dict) -> dict:
        """Convert non-JSON-serializable types to JSON-safe types"""
        import decimal
        def conv(v):
            if isinstance(v, (datetime,)):
                return v.isoformat()
            if hasattr(v, 'isoformat'):  # date, time objects
                return v.isoformat()
            if isinstance(v, decimal.Decimal):
                return float(v)
            return v
        return {k: conv(v) for k, v in (attrs or {}).items()}

    def _set_state_safe(self, entity_id: str, state, attributes=None, retries=(0, 1, 2)):
        """
        Safe set_state with retry and serialization

        Retry pattern: 0s, 1s, 2s before giving up
        """
        import time
        attrs = self._jsonify_attrs(attributes or {})

        for delay in retries:
            try:
                if delay > 0:
                    time.sleep(delay)
                return self.app.set_state(entity_id, state=state, attributes=attrs)
            except Exception as e:
                self.app.log(f"[SAFE_SET_STATE] {entity_id} failed: {e!r}; retry in {delay}s", level="WARNING")

        self.app.log(f"[SAFE_SET_STATE] ❌ Giving up on {entity_id} after {len(retries)} attempts", level="ERROR")
        return None

    def register_with_client(self):
        """Register callbacks with existing cTrader client"""
        # Guard against duplicate registration
        if hasattr(self, '_callbacks_registered') and self._callbacks_registered:
            logger.debug("[ACCOUNT_MONITOR] Callbacks already registered, skipping")
            return
        
        logger.info(f"[ACCOUNT_MONITOR] Registering callbacks (enabled: {self.enabled})")

        if not self.enabled:
            logger.info("[ACCOUNT_MONITOR] Account monitoring disabled in config")
            return

        try:
            # Register for account updates (PT_TRADER_RES)
            logger.info(f"[ACCOUNT_MONITOR] Registering account callbacks...")
            if hasattr(self.client, 'add_account_callback'):
                logger.info(f"[ACCOUNT_MONITOR] Registering account callback")
                self.client.add_account_callback(self._handle_account_update)
                logger.info("[ACCOUNT_MONITOR] ✅ Registered account callbacks")
            else:
                logger.error("[ACCOUNT_MONITOR] ❌ Client missing callback methods")

            # Register for execution events
            if hasattr(self.client, 'add_execution_callback'):
                # Client will handle duplicate check internally (logs as debug if duplicate)
                self.client.add_execution_callback(self._handle_execution_event)
                logger.info("[ACCOUNT_MONITOR] ✅ Registered execution callbacks")
            else:
                logger.error("[ACCOUNT_MONITOR] ❌ Client missing add_execution_callback method")
            
            # Mark as registered
            self._callbacks_registered = True

        except Exception as e:
            import traceback
            logger.error(f"[ACCOUNT_MONITOR] Exception in register_with_client(): {e}")
            logger.error(f"[ACCOUNT_MONITOR] Traceback: {traceback.format_exc()}")
            logger.error(f"[ACCOUNT_MONITOR] Error registering callbacks: {e}")

    def extract_balance_from_deals(self, deals: List[Dict]) -> Optional[float]:
        """Extract account balance from deals using balanceVersion (from demo)"""
        try:
            last_balance = 0
            last_version = 0

            for deal in deals:
                close_detail = deal.get("closePositionDetail", {})
                if close_detail:
                    version = close_detail.get("balanceVersion", 0)
                    balance_raw = close_detail.get("balance", 0)
                    if version > last_version:
                        last_version = version
                        last_balance = balance_raw

            # CRITICAL FIX: Return None if no balance found (instead of 0)
            if last_balance > 0 and last_version > 0:
                balance = last_balance / 100
                logger.info(f"[ACCOUNT_MONITOR] ✅ Balance extracted: {balance:.2f} CZK (v{last_version})")
                return balance
            else:
                logger.warning(f"[ACCOUNT_MONITOR] ⚠️ No balance found in deals (version={last_version})")
                return None

        except Exception as e:
            logger.error(f"[ACCOUNT_MONITOR] Error extracting balance: {e}")
            return None

    def _calculate_position_pnl(self, position: Dict) -> float:
        """Calculate unrealized PnL for a single position"""
        try:
            # Get position data
            trade_data = position.get('tradeData', {})
            volume = trade_data.get('volume', 0)
            side = trade_data.get('tradeSide', 0)  # 1=BUY, 2=SELL

            # Get prices
            entry_price = position.get('price', 0)

            # Get current market price if available
            current_price = position.get('currentPrice', 0)
            if current_price == 0:
                # Try to get from spot prices if we have them
                symbol_id = trade_data.get('symbolId')
                current_price = self._get_current_price(symbol_id)

            if current_price == 0 or entry_price == 0:
                return None  # Can't calculate without prices

            # Calculate PnL based on side
            if side == 1:  # BUY
                price_diff = current_price - entry_price
            else:  # SELL
                price_diff = entry_price - current_price

            # Calculate PnL in CZK (assuming pip value calculation)
            # Volume is in lots * 100 (e.g., 1440 = 14.40 lots)
            lots = volume / 100
            # For DAX: 1 pip = 0.24 CZK per lot (approximate)
            pip_value_czk = 0.24  # This should be dynamic based on symbol
            pnl_czk = price_diff * lots * pip_value_czk * 100  # price diff in points, *100 for pips

            return pnl_czk

        except Exception as e:
            logger.debug(f"[ACCOUNT_MONITOR] Could not calculate PnL for position: {e}")
            return None

    def _get_current_price(self, symbol_id: int) -> float:
        """Get current market price for a symbol"""
        try:
            # Try to get current price from cTrader client
            if self.client and hasattr(self.client, 'm5_aggregator'):
                # Get symbol name from ID
                symbol = self.client.id_to_symbol.get(symbol_id)
                if symbol and symbol in self.client.m5_aggregator.current_bars:
                    current_bar = self.client.m5_aggregator.current_bars[symbol]
                    if current_bar:
                        # Use last price from current bar
                        return current_bar.close
            return 0  # Price not available
        except Exception as e:
            logger.debug(f"[ACCOUNT_MONITOR] Could not get current price for symbol {symbol_id}: {e}")
            return 0

    def calculate_daily_realized_pnl(self, deals: List[Dict]) -> Dict:
        """Calculate realized PnL for today from closed deals (from demo)"""
        try:
            today = datetime.now(timezone.utc).date()
            total_pnl = 0
            closed_positions = 0

            # CRITICAL: Check if we need to reset for new day
            last_update = self._account_state.get('last_update')
            if last_update and last_update.date() < today:
                logger.info(f"[ACCOUNT_MONITOR] 🌅 New trading day detected - resetting daily PnL")
                # Reset for new day regardless of what we find in deals
                self._account_state['daily_realized_pnl'] = 0
                self._account_state['closed_positions_today'] = 0

            for deal in deals:
                close_detail = deal.get("closePositionDetail")
                if close_detail:
                    # Use executionTimestamp for when the position was CLOSED
                    execution_timestamp = deal.get('executionTimestamp', 0)
                    if execution_timestamp:
                        deal_date = datetime.fromtimestamp(execution_timestamp / 1000, tz=timezone.utc).date()
                        if deal_date == today:
                            gross_profit = close_detail.get("grossProfit", 0)
                            commission = close_detail.get("commission", 0)
                            swap = close_detail.get("swap", 0)
                            net_pnl = (gross_profit + commission + swap) / 100
                            total_pnl += net_pnl
                            closed_positions += 1

            if closed_positions > 0:
                logger.info(f"[ACCOUNT_MONITOR] 📊 Daily PnL calculated: {total_pnl:.2f} CZK ({closed_positions} positions closed today)")
            else:
                logger.debug(f"[ACCOUNT_MONITOR] No positions closed today in {len(deals)} deals")

            return {
                "daily_pnl": total_pnl,
                "closed_positions_today": closed_positions
            }

        except Exception as e:
            logger.error(f"[ACCOUNT_MONITOR] Error calculating daily PnL: {e}")
            return {"daily_pnl": 0, "closed_positions_today": 0}

    def _handle_account_update(self, account_data: Dict):
        """Handle account update from cTrader WebSocket (PT_TRADER_RES or PT_DEAL_LIST_RES)"""
        logger.debug(f"[💰 ACCOUNT_UPDATE] ENTRY: _handle_account_update called")
        try:
            source = account_data.get('source', 'unknown')
            logger.debug(f"[💰 ACCOUNT_UPDATE] Source: {source}")
            current_positions_count = len(self._account_state['open_positions'])
            logger.info(f"[ACCOUNT_MONITOR] Processing {source} callback")

            with self._lock:
                updated = False

                # Handle PT_TRADER_RES (positions data)
                if source == "PT_TRADER_RES":
                    position_data = account_data.get('position', {})
                    trader_data = account_data.get('trader', {})

                    # Check if position_data is a single position or list of positions
                    if isinstance(position_data, dict):
                        positions = [position_data] if position_data else []
                    elif isinstance(position_data, list):
                        positions = position_data
                    else:
                        positions = []

                    logger.info(f"[ACCOUNT_MONITOR] PT_TRADER_RES: Found {len(positions)} positions")

                    # CRITICAL FIX: Update positions even without trader data (cTrader API bug workaround)
                    # Positions are always valid in PT_TRADER_RES, even if trader object is missing
                    self._account_state['open_positions'] = positions
                    for i, pos in enumerate(positions):
                        pos_id = pos.get('positionId', 'unknown')
                        volume = pos.get('tradeData', {}).get('volume', 0)
                        symbol_id = pos.get('tradeData', {}).get('symbolId', 0)
                        logger.info(f"[ACCOUNT_MONITOR] Position {i+1}: ID={pos_id}, symbolId={symbol_id}, volume={volume}")

                    # CRITICAL FIX: Update risk manager with current positions
                    if self.risk_manager:
                        self._sync_positions_to_risk_manager(positions)

                    updated = True
                    logger.info(f"[ACCOUNT_MONITOR] ✅ Positions updated from PT_TRADER_RES ({len(positions)} positions)")

                    # Log warning if trader data is missing (but continue with position update)
                    if not trader_data or not isinstance(trader_data, dict):
                        logger.warning(f"[ACCOUNT_MONITOR] ⚠️ PT_TRADER_RES missing trader balance data (known cTrader API bug), using fallback balance")

                # Handle PT_DEAL_LIST_RES (deals for balance and PnL)
                elif source == "PT_DEAL_LIST_RES":
                    deals = account_data.get('deals', [])
                    logger.info(f"[💰 ACCOUNT_UPDATE] PT_DEAL_LIST_RES: {len(deals)} deals")

                    # CRITICAL FIX: Only process if we have actual deals
                    if deals and len(deals) > 0:
                        # Extract balance from deals
                        balance = self.extract_balance_from_deals(deals)
                        logger.debug(f"[💰 ACCOUNT_UPDATE] Extracted balance: {balance}")
                        # CRITICAL FIX: Update balance even if it's the same (None means not found)
                        if balance is not None:
                            old_balance = self._account_state['balance']
                            self._account_state['balance'] = balance
                            self._account_state['equity'] = balance
                            updated = True
                            if abs(old_balance - balance) > 0.01:  # Changed
                                logger.info(f"[ACCOUNT_MONITOR] 💰 Balance updated: {old_balance:.2f} → {balance:.2f}")
                            else:
                                logger.debug(f"[ACCOUNT_MONITOR] ✅ Balance confirmed: {balance:.2f}")
                        else:
                            logger.warning(f"[ACCOUNT_MONITOR] ⚠️ Could not extract balance from {len(deals)} deals")

                        # Calculate daily realized PnL
                        daily_pnl_data = self.calculate_daily_realized_pnl(deals)
                        logger.debug(f"[💰 ACCOUNT_UPDATE] Daily PnL calculated: {daily_pnl_data}")

                        # CRITICAL FIX: Only update daily PnL if we found closed positions for today
                        # or if it's the first calculation (current value is 0)
                        if daily_pnl_data['closed_positions_today'] > 0 or self._account_state['daily_realized_pnl'] == 0:
                            self._account_state['daily_realized_pnl'] = daily_pnl_data['daily_pnl']
                            self._account_state['closed_positions_today'] = daily_pnl_data['closed_positions_today']
                            logger.info(f"[ACCOUNT_MONITOR] Daily PnL updated: {daily_pnl_data['daily_pnl']:.2f} CZK ({daily_pnl_data['closed_positions_today']} positions)")
                        else:
                            logger.info(f"[ACCOUNT_MONITOR] 💰 Preserving daily PnL: {self._account_state['daily_realized_pnl']:.2f} CZK (no new closed positions found in this update)")

                        updated = True
                    else:
                        # CRITICAL FIX: Don't update if no deals
                        logger.info(f"[ACCOUNT_MONITOR] PT_DEAL_LIST_RES with no deals, skipping update")
                        # DON'T set updated = True here!

                    # CRITICAL FIX: Never reset positions when processing deals
                    current_positions_count = len(self._account_state['open_positions'])
                    logger.info(f"[ACCOUNT_MONITOR] 🔐 Preserving {current_positions_count} positions after PT_DEAL_LIST_RES")

                # Always update timestamp to show we're alive and have current data
                self._account_state['last_update'] = datetime.now(timezone.utc)
                logger.debug(f"[ACCOUNT_UPDATE] Timestamp updated: {self._account_state['last_update']}")

                # Always update HA entities to ensure risk status has current timestamp
                self._update_ha_entities()

                if updated:
                    logger.info(f"[ACCOUNT_MONITOR] HA entities updated with new data")
                else:
                    logger.debug(f"[ACCOUNT_MONITOR] HA entities refreshed (no data changes but timestamp updated)")

        except Exception as e:
            logger.error(f"[ACCOUNT_MONITOR] Error handling account update: {e}")

    def _handle_execution_event(self, execution_data: Dict):
        """Handle execution event - extract data directly from execution event"""
        try:
            # execution_data IS already the payload from cTrader API
            payload = execution_data

            # Log execution type for debugging
            execution_type = payload.get('executionType', 'unknown')
            logger.info(f"[ACCOUNT_MONITOR] 🔥 Execution event type: {execution_type}")

            # Extract position data if available
            position = payload.get('position', {})
            if position:
                position_id = position.get('positionId')
                trade_data = position.get('tradeData', {})
                symbol_id = trade_data.get('symbolId')
                volume = trade_data.get('volume', 0)
                status = position.get('positionStatus', 0)

                logger.info(f"[ACCOUNT_MONITOR] 📍 Position: ID={position_id}, Symbol={symbol_id}, Volume={volume}, Status={status}")

                # Update position data
                with self._lock:
                    # Update open positions based on POSITION STATUS, not execution type
                    # Execution type 2 = order created/updated, doesn't mean position closed!
                    # Execution type 3 = order filled/position opened
                    # Execution type 5 = position closed

                    if status == 1 and volume > 0:  # Position OPEN
                        # Add/update position
                        found = False
                        for i, pos in enumerate(self._account_state['open_positions']):
                            if pos.get('positionId') == position_id:
                                self._account_state['open_positions'][i] = position
                                found = True
                                break
                        if not found:
                            self._account_state['open_positions'].append(position)
                        logger.info(f"[ACCOUNT_MONITOR] ✅ Updated/Added open position {position_id}")
                    elif status in [2, 3] or volume == 0:  # Position CLOSED (status 2 = closed, status 3 = partially closed)
                        # Remove position only if really closed
                        if status == 3 and execution_type == 2:
                            # Status 3 with exec type 2 might be just order creation, not position close
                            logger.debug(f"[ACCOUNT_MONITOR] 📊 Ignoring status 3 with exec type 2 (order creation)")
                        else:
                            self._account_state['open_positions'] = [
                                pos for pos in self._account_state['open_positions']
                                if pos.get('positionId') != position_id
                            ]
                            logger.info(f"[ACCOUNT_MONITOR] ✅ Removed closed position {position_id} (status={status}, volume={volume})")

                        # Extract balance and PnL data from execution event if available
                        self._extract_balance_from_execution_event(payload)

                    # Update timestamp and trigger HA updates
                    self._account_state['last_update'] = datetime.now(timezone.utc)
                    logger.info(f"[ACCOUNT_MONITOR] 📈 Current open positions: {len(self._account_state['open_positions'])}")

                    # Update HA entities with current data
                    self._update_ha_entities()

                    # NEW: Event-driven deals request for important executions
                    if self.update_on_execution_only:
                        self._last_execution_time = datetime.now(timezone.utc)

                        # Trigger deals request for position changes (balance/PnL updates)
                        if status in [1, 2, 3]:  # Position opened (1), SL/TP closed (2), or manually closed (3)
                            logger.info(f"[ACCOUNT_MONITOR] 🎯 EVENT-DRIVEN: Position {position_id} status changed to {status}, requesting deals update")
                            self._request_deals_async("execution_event")

                            # CRITICAL FIX: Update risk manager when positions close
                            # Use status field (2 or 3 = closed) instead of execution_type
                            # Execution type 3 = order filled/position opened, type 5 = position closed
                            # But status field is more reliable: status 2 = closed, status 3 = partially closed
                            if status in [2, 3] and self.risk_manager:  # Position closed
                                self._handle_position_close_for_risk_manager(payload)

                        else:
                            logger.debug(f"[ACCOUNT_MONITOR] 📊 Execution event status {status} - no deals request needed")

        except Exception as e:
            logger.error(f"[ACCOUNT_MONITOR] Error handling execution event: {e}")
            import traceback
            logger.error(f"[ACCOUNT_MONITOR] Traceback: {traceback.format_exc()}")

    def _update_ha_entities_initial_only(self):
        """Update only balance/PnL entities during initialization - DO NOT touch positions"""
        try:
            with self._lock:
                balance = self._account_state['balance']
                daily_pnl = self._account_state['daily_realized_pnl']

                # Calculate daily PnL percentage
                daily_pnl_pct = (daily_pnl / balance * 100) if balance > 0 else 0

                # Only update balance and PnL entities, NOT positions
                self._set_state_safe("sensor.trading_account_balance", round(balance, 2), attributes={
                    "friendly_name": "Trading Account Balance",
                    "unit_of_measurement": "CZK",
                    "equity": round(self._account_state['equity'], 2),
                    "last_update": self._account_state['last_update']
                })
                self._set_state_safe("sensor.trading_daily_pnl", round(daily_pnl, 2), attributes={
                    "friendly_name": "Trading Daily P&L",
                    "unit_of_measurement": "CZK",
                    "pnl_percentage": round(daily_pnl_pct, 2),
                    "closed_positions": self._account_state['closed_positions_today']
                })

                logger.info(f"[ACCOUNT_MONITOR] Initial setup: Balance={balance:.2f}, PnL={daily_pnl:.2f} (positions unchanged)")

                # Also update risk status entity with initial PnL data to prevent "No Data" display
                try:
                    current_risk_entity = self.app.get_state("sensor.trading_risk_status", attribute="all")
                    if isinstance(current_risk_entity, dict):
                        current_attributes = current_risk_entity.get("attributes", {})
                        current_state = current_risk_entity.get("state", "ACTIVE")
                    else:
                        current_attributes = {}
                        current_state = "ACTIVE"

                    # Set initial PnL values in risk status
                    current_time = datetime.now(timezone.utc)
                    filtered_attributes = {
                        k: v for k, v in current_attributes.items()
                        if k not in ['last_changed', 'last_reported', 'last_updated', 'context', 'state']
                    }

                    filtered_attributes.update({
                        "account_monitor_active": True,
                        "daily_pnl_czk": daily_pnl,  # Set initial PnL
                        "daily_pnl_pct": daily_pnl_pct,
                        "daily_realized_pnl": daily_pnl,
                        "daily_unrealized_pnl": 0,
                        "account_monitor_last_update": current_time.isoformat()
                    })

                    self._set_state_safe("sensor.trading_risk_status", current_state, attributes=filtered_attributes)
                    logger.info(f"[ACCOUNT_MONITOR] ✅ Initial risk_status set with PnL={daily_pnl:.2f} CZK")
                except Exception as e:
                    logger.error(f"[ACCOUNT_MONITOR] Failed to set initial risk status: {e}")

        except Exception as e:
            import traceback
            logger.error(f"[ACCOUNT_MONITOR] Error updating initial HA entities: {e}")
            logger.error(f"[ACCOUNT_MONITOR] Traceback: {traceback.format_exc()}")

    def _update_risk_status_timestamp_only(self):
        """Update only the timestamp in risk status to prevent legacy PnL calculation"""
        try:
            # Get current risk status entity
            current_entity = self.app.get_state("sensor.trading_risk_status", attribute="all")
            if not current_entity:
                logger.debug("[ACCOUNT_MONITOR] No trading_risk_status entity to update")
                return

            current_attributes = current_entity.get("attributes", {})
            current_state = current_entity.get("state", "ACTIVE")

            # Only update the timestamp to show we're alive - use CURRENT time!
            current_time = datetime.now(timezone.utc)
            current_attributes["account_monitor_last_update"] = current_time.isoformat()

            # CRITICAL: Also ensure daily_pnl values are present
            with self._lock:
                daily_realized_pnl = self._account_state['daily_realized_pnl']
                balance = self._account_state['balance']
                daily_pnl_pct = (daily_realized_pnl / balance * 100) if balance > 0 else 0

                current_attributes.update({
                    "account_monitor_active": True,
                    "daily_pnl_czk": daily_realized_pnl,
                    "daily_pnl_pct": daily_pnl_pct,
                    "daily_realized_pnl": daily_realized_pnl,
                })

            self._set_state_safe("sensor.trading_risk_status", current_state, attributes=current_attributes)
            logger.debug(f"[ACCOUNT_MONITOR] Updated risk status timestamp and PnL values")

        except Exception as e:
            logger.error(f"[ACCOUNT_MONITOR] Error updating risk status timestamp: {e}")

    def _update_ha_entities(self):
        """Update Home Assistant entities"""
        try:
            with self._lock:
                balance = self._account_state['balance']
                open_positions_count = len(self._account_state['open_positions'])
                daily_realized_pnl = self._account_state['daily_realized_pnl']

                # Calculate unrealized PnL from open positions
                unrealized_pnl = 0
                for pos in self._account_state['open_positions']:
                    pos_pnl = self._calculate_position_pnl(pos)
                    if pos_pnl is not None:
                        unrealized_pnl += pos_pnl

                # Total daily PnL = realized + unrealized
                daily_pnl = daily_realized_pnl + unrealized_pnl

                # SAFETY CHECK: Log warning if positions suddenly disappear
                if hasattr(self, '_last_positions_count'):
                    if self._last_positions_count > 0 and open_positions_count == 0:
                        logger.warning(f"[ACCOUNT_MONITOR] ⚠️ Positions dropped from {self._last_positions_count} to 0!")
                self._last_positions_count = open_positions_count

                # Calculate daily PnL percentage
                daily_pnl_pct = (daily_pnl / balance * 100) if balance > 0 else 0

                logger.debug(f"[ACCOUNT_MONITOR] 🔄 Updating HA entities: Balance={balance:.2f}, Positions={open_positions_count}, PnL={daily_pnl:.2f}")

                # Update trading entities for dashboard
                # CRITICAL FIX: Always create NEW dict for attributes (never reuse existing entity attributes)
                logger.debug("[ACCOUNT_MONITOR] 🔧 Setting trading_account_balance...")
                self._set_state_safe("sensor.trading_account_balance", balance, attributes={
                    "unit_of_measurement": "CZK",
                    "friendly_name": "Trading Account Balance",
                    "equity": self._account_state['equity'],
                    "last_update": self._account_state['last_update']
                })

                logger.debug(f"[ACCOUNT_MONITOR] 🔧 Setting trading_open_positions to {open_positions_count}...")
                self._set_state_safe("sensor.trading_open_positions", open_positions_count, attributes={
                    "friendly_name": "Trading Open Positions",
                    "icon": "mdi:currency-usd"
                })

                # CRITICAL FIX: Update daily PnL in CZK (was missing from regular updates!)
                logger.debug(f"[ACCOUNT_MONITOR] 🔧 Setting trading_daily_pnl to {daily_pnl:.2f} CZK...")
                self._set_state_safe("sensor.trading_daily_pnl", round(daily_pnl, 2), attributes={
                    "friendly_name": "Trading Daily P&L",
                    "unit_of_measurement": "CZK",
                    "pnl_percentage": round(daily_pnl_pct, 2),
                    "closed_positions": self._account_state['closed_positions_today']
                })

                logger.debug("[ACCOUNT_MONITOR] 🔧 Setting trading_daily_pnl_percent...")
                self._set_state_safe("sensor.trading_daily_pnl_percent", daily_pnl_pct, attributes={
                    "friendly_name": "Trading Daily PnL Percent",
                    "daily_pnl_czk": daily_pnl,
                    "closed_positions_today": self._account_state['closed_positions_today']
                })

                # Mark Account Monitor as active in risk status entity
                try:
                    logger.debug("[ACCOUNT_MONITOR] 🔧 Getting trading_risk_status...")
                    current_risk_entity = self.app.get_state("sensor.trading_risk_status", attribute="all")
                    logger.debug(f"[ACCOUNT_MONITOR] 📥 Got trading_risk_status: type={type(current_risk_entity)}")

                    # Ensure we have a valid dict, not an exception object
                    if isinstance(current_risk_entity, dict):
                        current_risk_attributes = current_risk_entity.get("attributes", {})
                        current_state = current_risk_entity.get("state", "ACTIVE")
                    else:
                        logger.warning(f"[ACCOUNT_MONITOR] ⚠️ trading_risk_status returned non-dict: {type(current_risk_entity)}")
                        current_risk_attributes = {}
                        current_state = "ACTIVE"
                except Exception as e:
                    import traceback
                    logger.warning(f"[ACCOUNT_MONITOR] ⚠️ Failed to get trading_risk_status: {e}")
                    logger.warning(f"[ACCOUNT_MONITOR] ⚠️ Traceback: {traceback.format_exc()}")
                    current_risk_attributes = {}
                    current_state = "ACTIVE"

                try:
                    logger.debug("[ACCOUNT_MONITOR] 🔧 Setting trading_risk_status...")
                    # CRITICAL FIX: Create NEW dict instead of updating existing (avoids HA internal attributes)
                    # Only copy custom application attributes, filter out HA internal ones
                    # DOUBLE CHECK: Ensure current_risk_attributes is actually a dict
                    if not isinstance(current_risk_attributes, dict):
                        logger.error(f"[ACCOUNT_MONITOR] ❌ current_risk_attributes is not a dict: {type(current_risk_attributes)}")
                        current_risk_attributes = {}

                    filtered_attributes = {
                        k: v for k, v in current_risk_attributes.items()
                        if k not in ['last_changed', 'last_reported', 'last_updated', 'context', 'state']
                    }

                    # Update with new values - CRITICAL: Always use fresh timestamp
                    current_time = datetime.now(timezone.utc)
                    filtered_attributes.update({
                        "account_monitor_active": True,
                        "open_positions": open_positions_count,  # CRITICAL FIX: Update open_positions from real data
                        "daily_pnl_czk": daily_pnl,
                        "daily_pnl_pct": daily_pnl_pct,
                        "daily_realized_pnl": daily_realized_pnl,
                        "daily_unrealized_pnl": unrealized_pnl,
                        "account_monitor_last_update": current_time.isoformat()  # CRITICAL: Always use current time
                    })

                    self._set_state_safe("sensor.trading_risk_status", current_state, attributes=filtered_attributes)
                    logger.info(f"[ACCOUNT_MONITOR] ✅ risk_status updated: daily_pnl_czk={daily_pnl:.2f}, timestamp={current_time.isoformat()}")
                except Exception as e:
                    logger.error(f"[ACCOUNT_MONITOR] ❌ Failed to update trading_risk_status: {e}")

                # Also update main entities
                logger.debug("[ACCOUNT_MONITOR] 🔧 Setting account_balance...")
                self._set_state_safe("sensor.account_balance", balance, attributes={
                    "unit_of_measurement": "CZK",
                    "friendly_name": "Account Balance",
                    "equity": self._account_state['equity']
                })

                logger.info(f"[ACCOUNT_MONITOR] ✅ HA Entities Updated: Balance={balance:.2f} CZK, Positions={open_positions_count}, Daily PnL={daily_pnl:.2f} CZK ({daily_pnl_pct:.2f}%)")

        except Exception as e:
            logger.error(f"[ACCOUNT_MONITOR] Error updating HA entities: {e}")

    def _sync_positions_to_risk_manager(self, positions: List[Dict]):
        """Sync existing positions to risk manager at startup"""
        try:
            logger.info(f"[ACCOUNT_MONITOR] 🔄 STARTUP: Syncing {len(positions)} positions to risk manager...")

            if not self.risk_manager:
                logger.warning(f"[ACCOUNT_MONITOR] ⚠️ No risk manager available for position sync")
                return

            # Clear existing positions in risk manager (startup clean state)
            self.risk_manager.open_positions.clear()
            logger.info(f"[ACCOUNT_MONITOR] Cleared existing risk manager positions for startup sync")

            # Convert each position to risk manager format and add
            synced_count = 0
            for pos in positions:
                try:
                    # Extract position data
                    pos_id = pos.get('positionId', 0)
                    trade_data = pos.get('tradeData', {})
                    symbol_id = trade_data.get('symbolId', 0)
                    volume = trade_data.get('volume', 0) / 100  # Convert to lots
                    trade_side = trade_data.get('tradeSide', 1)  # 1=BUY, 2=SELL
                    price = pos.get('price', 0)

                    # Map symbol ID to symbol name
                    symbol = 'NASDAQ' if symbol_id == 208 else ('DAX' if symbol_id == 203 else f'SYMBOL_{symbol_id}')

                    # Create minimal position for risk manager
                    if not RISK_MANAGER_AVAILABLE or PositionSize is None:
                        logger.warning(f"[ACCOUNT_MONITOR] ⚠️ Cannot sync position {pos_id} - PositionSize not available")
                        continue

                    # Get point value from symbol specs
                    symbol_specs = self.config.get('symbol_specs', {})
                    symbol_spec = symbol_specs.get(symbol, {})
                    point_value = symbol_spec.get('pip_value_per_lot', 0.2)  # Default to NASDAQ value

                    position_size = PositionSize(
                        symbol=symbol,
                        lots=volume,
                        entry_price=price,
                        stop_loss=price * 0.95 if trade_side == 1 else price * 1.05,  # Estimate
                        take_profit=price * 1.10 if trade_side == 1 else price * 0.90,  # Estimate
                        risk_amount_czk=10000,  # Estimate
                        margin_required_czk=30000,  # Estimate
                        potential_profit_czk=20000,  # Estimate
                        risk_percent=0.5,
                        point_value=point_value  # CRITICAL FIX: Add required point_value parameter
                    )

                    # Add to risk manager
                    self.risk_manager.open_positions.append(position_size)
                    synced_count += 1
                    logger.info(f"[ACCOUNT_MONITOR] ✅ Synced position: {symbol} {volume:.2f} lots @ {price}")

                except Exception as e:
                    logger.error(f"[ACCOUNT_MONITOR] ❌ Error syncing position {pos.get('positionId', 'unknown')}: {e}")

            logger.info(f"[ACCOUNT_MONITOR] 🎯 STARTUP SYNC COMPLETE: {synced_count}/{len(positions)} positions added to risk manager")

            # Force risk manager status update
            risk_status = self.risk_manager.get_risk_status()
            logger.info(f"[ACCOUNT_MONITOR] 📊 Risk manager updated: {len(self.risk_manager.open_positions)} positions, can_trade={risk_status.can_trade}")

        except Exception as e:
            logger.error(f"[ACCOUNT_MONITOR] Error syncing positions to risk manager: {e}")
            import traceback
            logger.error(f"[ACCOUNT_MONITOR] Traceback: {traceback.format_exc()}")

    def _handle_position_close_for_risk_manager(self, payload: Dict):
        """Handle position close for risk manager synchronization"""
        try:
            position_data = payload.get('position', {})
            trade_data = position_data.get('tradeData', {})
            symbol_id = trade_data.get('symbolId', 0)
            position_id = position_data.get('positionId', 0)

            # Map symbol ID to symbol name
            symbol = 'NASDAQ' if symbol_id == 208 else ('DAX' if symbol_id == 203 else f'SYMBOL_{symbol_id}')

            # Calculate PnL from deal details
            deal = payload.get('deal', {})
            close_detail = deal.get('closePositionDetail', {})

            pnl_czk = 0
            if close_detail:
                gross_profit = close_detail.get('grossProfit', 0)
                commission = close_detail.get('commission', 0)
                # Convert from money digits format (usually cents)
                money_digits = deal.get('moneyDigits', 2)
                scaling_factor = 10 ** money_digits
                pnl_czk = (gross_profit + commission) / scaling_factor

            logger.info(f"[ACCOUNT_MONITOR] 🎯 POSITION CLOSED: {symbol} (ID: {position_id}), PnL: {pnl_czk:+.2f} CZK")

            # Remove from risk manager - try to find by symbol first
            removed_count = 0
            original_count = len(self.risk_manager.open_positions)

            # Remove one position of this symbol (preferably matching entry price if possible)
            for i, pos in enumerate(self.risk_manager.open_positions):
                if pos.symbol == symbol:
                    removed_pos = self.risk_manager.open_positions.pop(i)
                    removed_count = 1
                    logger.info(f"[ACCOUNT_MONITOR] ✅ Removed {symbol} position from risk manager: {removed_pos.lots:.2f} lots @ {removed_pos.entry_price}")
                    break

            if removed_count == 0:
                logger.warning(f"[ACCOUNT_MONITOR] ⚠️ Could not find {symbol} position in risk manager to remove")
            else:
                # Update daily PnL
                self.risk_manager.daily_pnl += pnl_czk
                logger.info(f"[ACCOUNT_MONITOR] 📊 Risk manager updated: {original_count} → {len(self.risk_manager.open_positions)} positions")

                # Force risk manager status update
                risk_status = self.risk_manager.get_risk_status()
                logger.info(f"[ACCOUNT_MONITOR] 🎯 Risk status: {len(self.risk_manager.open_positions)} positions, can_trade={risk_status.can_trade}")

        except Exception as e:
            logger.error(f"[ACCOUNT_MONITOR] Error handling position close for risk manager: {e}")
            import traceback
            logger.error(f"[ACCOUNT_MONITOR] Traceback: {traceback.format_exc()}")

    def start_periodic_updates(self):
        """Initialize account monitoring - actual requests triggered by execution events"""

        # Guard against double initialization
        if self._started:
            logger.debug("[ACCOUNT_MONITOR] Already started, skipping duplicate initialization")
            return

        if not self.enabled:
            logger.info("[ACCOUNT_MONITOR] Account monitoring disabled")
            return

        # Mark as started to prevent double init
        self._started = True

        logger.info("[ACCOUNT_MONITOR] 🚀 Account monitoring ready - setting initial balance...")

        # Set initial balance from config to show something immediately
        with self._lock:
            config_balance = self.config.get('account_balance', 2000000)  # CZK
            self._account_state['balance'] = config_balance
            self._account_state['equity'] = config_balance
            self._account_state['last_update'] = datetime.now(timezone.utc)
            logger.info(f"[ACCOUNT_MONITOR] 📊 Initial balance set to {config_balance} CZK")

        # Update HA entities with initial data (but skip position reset)
        self._update_ha_entities_initial_only()
        logger.info("[ACCOUNT_MONITOR] ✅ Initial balance displayed")

        # NEW: Request initial account snapshot for current positions
        if self.client and hasattr(self.client, '_get_account_snapshot'):
            logger.info("[ACCOUNT_MONITOR] 🎯 INITIAL: Requesting account snapshot for current positions...")
            try:
                import asyncio
                import threading

                def request_initial_snapshot():
                    """Request initial account snapshot in background"""
                    try:
                        if self.client and hasattr(self.client, '_loop') and self.client._loop:
                            # Use existing request method instead of _get_account_snapshot to avoid recv collision
                            logger.info("[ACCOUNT_MONITOR] 🎯 INITIAL: Requesting initial deals for account snapshot...")
                            self._request_deals_async("initial_snapshot")
                        else:
                            logger.warning("[ACCOUNT_MONITOR] ⚠️ INITIAL: Cannot request snapshot - WebSocket not ready")
                    except Exception as e:
                        logger.error(f"[ACCOUNT_MONITOR] Error requesting initial snapshot: {e}")

                # Request after short delay to let WebSocket fully connect
                timer = threading.Timer(2.0, request_initial_snapshot)
                timer.daemon = True
                timer.start()
                logger.info("[ACCOUNT_MONITOR] ⏰ Initial snapshot scheduled in 2 seconds")

            except Exception as e:
                logger.error(f"[ACCOUNT_MONITOR] Error scheduling initial snapshot: {e}")

        # CRITICAL FIX: Start periodic/fallback deals requests for real balance and PnL data
        logger.info("[ACCOUNT_MONITOR] 🚀 About to call _start_periodic_deals_requests()...")
        self._start_periodic_deals_requests()
        logger.info("[ACCOUNT_MONITOR] ✅ _start_periodic_deals_requests() returned")

    def get_account_summary_sync(self) -> Dict:
        """Get current account summary (thread-safe, synchronous)"""
        with self._lock:
            return {
                "balance": self._account_state['balance'],
                "equity": self._account_state['equity'],
                "open_positions_count": len(self._account_state['open_positions']),
                "daily_realized_pnl": self._account_state['daily_realized_pnl'],
                "closed_positions_today": self._account_state['closed_positions_today'],
                "last_update": self._account_state['last_update']
            }

    def _request_deals_async(self, reason: str = "manual"):
        """Request deals list asynchronously - extracted from periodic logic for reuse"""
        try:
            logger.info(f"[ACCOUNT_MONITOR] 🔄 Requesting deals (reason: {reason}) - checking WebSocket readiness...")

            if self.client and hasattr(self.client, '_loop') and self.client._loop:
                # Get timestamp range for deals filtering
                # For initial snapshot or fallback: use 30 days back to find latest balance
                # For periodic updates: use today only for daily PnL
                now = datetime.now(timezone.utc)
                to_timestamp = int(now.timestamp() * 1000)

                if reason in ["initial_snapshot", "fallback", "execution_event"]:
                    # Look back 30 days to find latest closed deal with balance and all today's trades
                    from_date = now - timedelta(days=30)
                    from_timestamp = int(from_date.timestamp() * 1000)
                    if reason == "execution_event":
                        logger.debug(f"[ACCOUNT_MONITOR] 📅 EXECUTION_EVENT: Requesting 30 days of deals for complete daily PnL")
                else:
                    # For other reasons: today only
                    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
                    from_timestamp = int(today.timestamp() * 1000)

                logger.info(f"[ACCOUNT_MONITOR] 🎯 {reason.upper()}: Requesting deals list for real balance and PnL... (from: {from_timestamp}, to: {to_timestamp})")

                # Schedule request in WebSocket thread
                import asyncio
                future = asyncio.run_coroutine_threadsafe(
                    self.client.request_deals_list(from_timestamp, to_timestamp, 100),
                    self.client._loop
                )

                logger.info(f"[ACCOUNT_MONITOR] ✅ Deals request scheduled ({reason}), future: {future}")
                return future
            else:
                client_status = f"client={bool(self.client)}, loop={bool(getattr(self.client, '_loop', None))}"
                logger.warning(f"[ACCOUNT_MONITOR] ⚠️ Cannot request deals ({reason}) - WebSocket not ready: {client_status}")
                return None

        except Exception as e:
            logger.error(f"[ACCOUNT_MONITOR] Error requesting deals ({reason}): {e}")
            import traceback
            logger.error(f"[ACCOUNT_MONITOR] Traceback: {traceback.format_exc()}")
            return None

    def _start_periodic_deals_requests(self):
        """Start periodic/fallback deals requests - REFACTORED to event-driven"""
        logger.info(f"[ACCOUNT_MONITOR] 🔍 _start_periodic_deals_requests() called (enabled={self.enabled}, update_on_execution_only={self.update_on_execution_only})")
        try:
            import threading

            def request_deals():
                """Request deals list from cTrader API - with event-driven logic"""
                try:
                    # CRITICAL FIX: Mark timer as not running at start of execution
                    with self._timer_lock:
                        self._timer_running = False

                    current_time = datetime.now(timezone.utc)

                    # NEW: Event-driven mode logic
                    if self.update_on_execution_only:
                        # Check if we had recent execution event
                        if self._last_execution_time:
                            time_since_execution = (current_time - self._last_execution_time).total_seconds()
                            if time_since_execution < self.fallback_update_interval:
                                logger.debug(f"[ACCOUNT_MONITOR] 🎯 FALLBACK SKIPPED: Recent execution event {time_since_execution:.0f}s ago, no fallback needed")
                                schedule_next_check()
                                return

                        logger.info(f"[ACCOUNT_MONITOR] 🔄 FALLBACK: No recent execution events, requesting deals as fallback...")
                        reason = "fallback"
                        interval = self.fallback_update_interval
                    else:
                        logger.info(f"[ACCOUNT_MONITOR] 📍 LEGACY: Periodic timer fired - requesting deals...")
                        reason = "periodic_legacy"
                        interval = self.legacy_periodic_interval

                    # Use the new unified request method
                    future = self._request_deals_async(reason)
                    if future:
                        logger.info(f"[ACCOUNT_MONITOR] ✅ Deals request scheduled via {reason}")

                except Exception as e:
                    logger.error(f"[ACCOUNT_MONITOR] Error in periodic deals request: {e}")
                    import traceback
                    logger.error(f"[ACCOUNT_MONITOR] Traceback: {traceback.format_exc()}")
                finally:
                    schedule_next_check()

            def schedule_next_check():
                """Schedule next timer check - THREAD-SAFE with protection against concurrent timers"""
                # CRITICAL FIX: Check if timer is already running
                with self._timer_lock:
                    if self._timer_running:
                        logger.debug(f"[ACCOUNT_MONITOR] ⏭️  Timer already running, skipping duplicate schedule")
                        return

                    if not self.enabled:
                        logger.info(f"[ACCOUNT_MONITOR] ❌ Not scheduling next request - monitoring disabled")
                        return

                    # Mark timer as running BEFORE starting it
                    self._timer_running = True

                # Use appropriate interval based on mode
                interval = self.fallback_update_interval if self.update_on_execution_only else self.legacy_periodic_interval

                mode_desc = "fallback" if self.update_on_execution_only else "periodic legacy"
                logger.info(f"[ACCOUNT_MONITOR] 📅 Scheduling next {mode_desc} check in {interval} seconds...")

                timer = threading.Timer(interval, request_deals)
                timer.daemon = True  # CRITICAL: Allows clean shutdown
                timer.start()
                logger.debug(f"[ACCOUNT_MONITOR] ⏰ Timer scheduled: {timer}")

            # Start first request after 5 seconds (let WebSocket settle)
            initial_delay = 5.0
            mode_desc = "event-driven with fallback" if self.update_on_execution_only else "legacy periodic"
            logger.info(f"[ACCOUNT_MONITOR] ⏰ Starting first timer in {initial_delay} seconds ({mode_desc} mode)...")

            # CRITICAL FIX: Mark timer as running before starting
            with self._timer_lock:
                self._timer_running = True

            timer = threading.Timer(initial_delay, request_deals)
            timer.daemon = True  # CRITICAL: Allows clean shutdown
            timer.start()

            interval_desc = f"{self.fallback_update_interval}s fallback" if self.update_on_execution_only else f"{self.legacy_periodic_interval}s periodic"
            logger.info(f"[ACCOUNT_MONITOR] 🔄 Deals requests scheduled ({mode_desc}, {interval_desc}), initial timer: {timer}")

        except Exception as e:
            import traceback
            logger.error(f"[ACCOUNT_MONITOR] Error starting periodic/fallback deals requests: {e}")
            logger.error(f"[ACCOUNT_MONITOR] Traceback: {traceback.format_exc()}")

    def _extract_balance_from_execution_event(self, payload: Dict):
        """Extract balance and PnL data directly from execution event payload"""
        try:
            # Extract deal data from execution event
            deal = payload.get('deal', {})
            close_position_detail = deal.get('closePositionDetail', {})

            if close_position_detail:
                # Extract balance (in money digits format, need to convert)
                raw_balance = close_position_detail.get('balance', 0)
                money_digits = close_position_detail.get('moneyDigits', 2)
                balance = raw_balance / (10 ** money_digits)

                # Extract gross profit for PnL calculation
                raw_gross_profit = close_position_detail.get('grossProfit', 0)
                gross_profit = raw_gross_profit / (10 ** money_digits)

                # Extract commission and swap
                raw_commission = close_position_detail.get('commission', 0)
                commission = raw_commission / (10 ** money_digits)

                swap = close_position_detail.get('swap', 0) / (10 ** money_digits)

                # Calculate net profit
                net_profit = gross_profit + commission + swap

                logger.info(f"[ACCOUNT_MONITOR] 💰 EXEC EVENT: Balance={balance:.2f}, GrossProfit={gross_profit:.2f}, Commission={commission:.2f}, Net={net_profit:.2f}")

                # Update balance immediately
                with self._lock:
                    old_balance = self._account_state.get('balance', 0)
                    self._account_state['balance'] = balance
                    self._account_state['equity'] = balance

                    # Update daily realized PnL (add this trade's net profit)
                    current_daily_pnl = self._account_state.get('daily_realized_pnl', 0)
                    self._account_state['daily_realized_pnl'] = current_daily_pnl + net_profit

                    # Increment closed positions today counter
                    self._account_state['closed_positions_today'] = self._account_state.get('closed_positions_today', 0) + 1

                    logger.info(f"[ACCOUNT_MONITOR] ✅ BALANCE UPDATED: {old_balance:.2f} → {balance:.2f} (PnL: +{net_profit:.2f})")
                    logger.info(f"[ACCOUNT_MONITOR] ✅ DAILY PnL: {self._account_state['daily_realized_pnl']:.2f}, Closed positions today: {self._account_state['closed_positions_today']}")

                # CRITICAL: Update BalanceTracker with real balance from execution event
                if self.balance_tracker:
                    # Create a minimal trader-like payload for balance tracker
                    # Balance from closePositionDetail is already in base currency (after moneyDigits conversion)
                    trader_like = {
                        "balance": int(raw_balance),  # Raw balance in cents/hundredths
                        "equity": int(raw_balance),
                        "moneyDigits": money_digits,
                        "depositCurrency": "CZK"
                    }
                    success = self.balance_tracker.update_from_trader_res(trader_like)
                    if success:
                        logger.info(f"[ACCOUNT_MONITOR] ✅ BalanceTracker updated from execution event: {balance:.2f} CZK")
                    else:
                        logger.warning(f"[ACCOUNT_MONITOR] ⚠️ Failed to update BalanceTracker from execution event")

            else:
                logger.debug(f"[ACCOUNT_MONITOR] 📊 No closePositionDetail in execution event")

        except Exception as e:
            logger.error(f"[ACCOUNT_MONITOR] Error extracting balance from execution event: {e}")
            import traceback
            logger.error(f"[ACCOUNT_MONITOR] Traceback: {traceback.format_exc()}")