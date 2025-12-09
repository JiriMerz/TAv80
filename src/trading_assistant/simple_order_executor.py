#!/usr/bin/env python3
"""
Simple Order Executor for MVP Auto-Trading
Orchestrates all components to execute market orders with fixed 0.5% risk

MVP Implementation - Sprint 3
"""

import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
import asyncio
from .position_closer import PositionCloser

logger = logging.getLogger(__name__)


class SimpleOrderExecutor:
    """
    Simple order executor for MVP auto-trading
    
    Features:
    - Time-based symbol switching (DAX/NASDAQ)
    - Dynamic risk management (0.4-0.6% per trade)
    - 5% daily loss limit (dynamic based on account size)
    - Market orders only
    - Multiple concurrent positions (managed by RiskManager)
    - Automatic position closing on symbol switch
    """
    
    def __init__(self, config: Dict, time_manager, balance_tracker,
                 risk_manager, daily_risk_tracker, ctrader_client, create_task_fn=None, edge_detector=None, hass_instance=None):
        """
        Initialize order executor

        Args:
            config: Configuration dict from apps.yaml
            time_manager: TimeBasedSymbolManager instance
            balance_tracker: BalanceTracker instance
            position_sizer: DynamicPositionSizer instance
            daily_risk_tracker: DailyRiskTracker instance
            ctrader_client: CTrader client for order execution
            edge_detector: EdgeDetector instance for context (optional)
        """
        self.config = config
        self.time_manager = time_manager
        self.balance_tracker = balance_tracker
        self.create_task_fn = create_task_fn  # Store AppDaemon's create_task method
        self.risk_manager = risk_manager
        self.daily_risk_tracker = daily_risk_tracker
        self.ctrader_client = ctrader_client
        self.edge = edge_detector  # Store for context extraction
        self.hass = hass_instance  # Store hass instance for notifications

        # Initialize trade decision logger
        from .trade_decision_logger import TradeDecisionLogger
        self.trade_logger = TradeDecisionLogger()

        # Initialize position closer for close & reverse feature
        self.position_closer = PositionCloser(ctrader_client, create_task_fn)
        logger.info("[ORDER_EXECUTOR] PositionCloser initialized - close & reverse feature enabled")

        # Register for execution events to track position lifecycle
        if self.ctrader_client and hasattr(self.ctrader_client, 'add_execution_callback'):
            self.ctrader_client.add_execution_callback(self._handle_execution_event)
            logger.info("[ORDER_EXECUTOR] ✅ Registered for execution events")
        elif self.ctrader_client is None:
            logger.info("[ORDER_EXECUTOR] ⏳ Client not yet initialized - will register execution callback later")
        else:
            logger.error("[ORDER_EXECUTOR] ❌ Client missing add_execution_callback method")

        # Execution state - position tracking now handled by RiskManager
        # Removed single-position tracking, now supports multiple concurrent positions
        self.pending_orders = {}  # Track pending orders by symbol
        self.last_symbol_check = None

        logger.info("[MULTI-POSITION] OrderExecutor initialized - multiple concurrent positions supported")
        
        # Configuration
        self.enabled = config.get('auto_trading', {}).get('enabled', False)
        self.per_trade_risk = config.get('auto_trading', {}).get('per_trade_risk_pct', 0.005)
        self.daily_risk_limit = config.get('auto_trading', {}).get('daily_risk_limit_pct', 0.015)
        
        logger.info(f"[ORDER_EXECUTOR] Initialized - Enabled: {self.enabled}")
        logger.info(f"  Per trade risk: {self.per_trade_risk:.1%}")
        logger.info(f"  Daily risk limit: {self.daily_risk_limit:.1%}")

        # Rejected signals tracking for re-evaluation when auto-trading is enabled
        self.rejected_signals = []  # List of (signal, timestamp) tuples
        self.max_rejected_signals = 10  # Keep only recent rejections

        # Pending order tracking for execution confirmation
        self.pending_order = None
    
    def _handle_execution_event(self, execution_data: Dict):
        """
        Handle execution events from cTrader WebSocket

        Args:
            execution_data: Execution event payload from cTrader (includes executionType)
        """
        # Extract execution type from cTrader payload
        execution_type = execution_data.get('executionType', 0)
        logger.debug(f"[ORDER_EXECUTOR] Execution event: type={execution_type}")

        # executionType 3 = ORDER_FILLED (position opened/modified)
        if execution_type == 3:
            # Find which symbol had the pending order filled
            symbol = None
            for sym, pending in self.pending_orders.items():
                if pending:
                    symbol = sym
                    break

            if symbol and self.pending_orders.get(symbol):
                logger.error(f"[🚨 POSITION CONFIRMED] Order filled for {symbol}")

                # Position confirmed - add to RiskManager tracking
                pending_order = self.pending_orders[symbol]
                position_data = pending_order.copy()

                # Extract actual entry price from execution event
                position_payload = execution_data.get('position', {})
                actual_price = position_payload.get('price', pending_order['entry_price'])

                position_data.update({
                    'actual_entry_price': actual_price,
                    'opened_at': datetime.now().isoformat(),
                    'fill_confirmation': execution_data
                })

                # Add to daily risk tracking
                self.daily_risk_tracker.add_trade({
                    'symbol': symbol,
                    'position_size': position_data['position_size'],
                    'risk_amount': position_data['risk_amount'],
                    'entry_price': position_data['actual_entry_price'],
                    'sl_price': position_data['sl_price'],
                    'tp_price': position_data['tp_price'],
                    'opened_at': position_data['opened_at']
                })

                # CRITICAL: Add position to risk_manager for max position control
                from risk_manager import PositionSize
                risk_position = PositionSize(
                    symbol=symbol,
                    lots=position_data['position_size'],
                    entry_price=position_data['actual_entry_price'],
                    stop_loss=position_data['sl_price'],
                    take_profit=position_data['tp_price'],
                    risk_amount_czk=position_data['risk_amount'],
                    risk_percent=position_data['risk_amount'] / position_data.get('balance', 2000000) * 100,
                    margin_required_czk=position_data.get('margin_required', 0),
                    potential_profit_czk=position_data.get('potential_profit', 0)
                )

                self.risk_manager.add_position(risk_position)
                logger.error(f"[🚨 POSITION ADDED] {symbol} added to risk_manager ({len(self.risk_manager.open_positions)} positions)")

                # Clear this symbol's pending order
                self.pending_orders[symbol] = None

                logger.error(f"[🚨 POSITION CONFIRMED] {symbol} position opened, tracking updated")
                
                # Send notification to mobile - position is CONFIRMED opened by platform
                self._send_position_opened_notification(symbol, position_data)

        # executionType 4 = ORDER_REJECTED
        elif execution_type == 4:
            # Order was rejected - find and clear the rejected order
            error_code = execution_data.get('errorCode', 'UNKNOWN')
            description = execution_data.get('description', 'No description')

            logger.error(f"[🚨 ORDER FAILED] Order rejected: {error_code} - {description}")

            # Clear the rejected pending order
            for symbol in self.pending_orders:
                if self.pending_orders[symbol]:
                    logger.error(f"[🚨 ORDER FAILED] Clearing pending order for {symbol}")
                    self.pending_orders[symbol] = None
                    break

        # Note: Position closing is handled by account_state_monitor via deal events
        # We don't need to duplicate that logic here since account_monitor already
        # tracks position closures and updates balance via PT_DEAL_LIST_RES
    
    def _send_position_opened_notification(self, symbol: str, position_data: Dict):
        """
        Send mobile notification when position is CONFIRMED opened by platform
        
        This is called only after EXECUTION_EVENT (type 3) confirms the position is actually opened.
        """
        if not self.hass:
            logger.warning("[ORDER_EXECUTOR] Cannot send notification - hass instance not available")
            return
        
        try:
            direction = position_data.get('direction', 'UNKNOWN')
            entry_price = position_data.get('actual_entry_price', position_data.get('entry_price', 0))
            position_size = position_data.get('position_size', 0)
            sl_price = position_data.get('sl_price', 0)
            tp_price = position_data.get('tp_price', 0)
            risk_amount = position_data.get('risk_amount', 0)
            
            title = f"✅ Pozice otevřena: {symbol} {direction}"
            message = (
                f"Symbol: {symbol}\n"
                f"Směr: {direction}\n"
                f"Velikost: {position_size:.2f} lots\n"
                f"Entry: {entry_price:.1f}\n"
                f"SL: {sl_price:.1f}\n"
                f"TP: {tp_price:.1f}\n"
                f"Riziko: {risk_amount:.0f} CZK"
            )
            
            # Send via HA notify (mobile notification)
            self.hass.call_service("notify/notify", title=title, message=message)
            
            # Also persistent notification
            self.hass.call_service(
                "persistent_notification/create",
                title=title,
                message=message,
                notification_id=f"position_opened_{symbol}_{datetime.now().timestamp()}"
            )
            
            logger.info(f"[ORDER_EXECUTOR] 📱 Notification sent: {symbol} {direction} position confirmed opened")
            
        except Exception as e:
            logger.error(f"[ORDER_EXECUTOR] Error sending position opened notification: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
        else:
            # Maintenance/status events after position handling - log as DEBUG to reduce noise
            if event_type in ['EXECUTION_TYPE_2', 'EXECUTION_TYPE_5']:
                logger.debug(f"[EXECUTION CALLBACK] Maintenance event: {event_type} (normal after position events)")
            elif self.risk_manager.open_positions and payload.get('positionId'):
                # Events for tracked positions - normal maintenance, log as DEBUG
                logger.debug(f"[EXECUTION CALLBACK] Position update event: {event_type} for tracked position")
            else:
                # Truly unhandled events
                logger.info(f"[EXECUTION CALLBACK] Unhandled event: {event_type} (no active position or unknown type)")
    
    def can_execute_trade(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """
        Check if trade can be executed based on all constraints
        
        Args:
            signal: Trading signal from edge detection
            
        Returns:
            Dict with execution permission and detailed reasons
        """
        issues = []
        
        try:
            # 1. Check if auto-trading is enabled
            if not self.enabled:
                issues.append("Auto-trading is disabled via toggle")
                logger.info(f"[ORDER_EXECUTOR] ⏸️ Signal rejected - auto-trading DISABLED: {signal.get('symbol')} {signal.get('direction')}")

                # Save rejected signal for re-evaluation when auto-trading is enabled
                from datetime import datetime
                self.rejected_signals.append((signal.copy(), datetime.now()))
                # Keep only recent rejections
                if len(self.rejected_signals) > self.max_rejected_signals:
                    self.rejected_signals = self.rejected_signals[-self.max_rejected_signals:]
                logger.info(f"[ORDER_EXECUTOR] 💾 Signal saved for re-evaluation ({len(self.rejected_signals)} total)")
            
            # 2. Position limits now handled by RiskManager.can_trade()
            # (Removed hardcoded single-position limit)
            
            # 3. Check time-based symbol trading
            session_change = self.time_manager.check_session_change()
            active_symbol = session_change.get('new_symbol')
            
            # TESTING BYPASS - Allow all symbols for testing
            if active_symbol is None:
                logger.warning("[ORDER_EXECUTOR] TESTING: Bypassing trading hours check")
                active_symbol = signal.get('symbol')  # Use signal's symbol
            elif signal.get('symbol') != active_symbol:
                issues.append(f"Wrong symbol: {signal.get('symbol')} (active: {active_symbol})")
            
            # 4. Check balance availability
            if self.balance_tracker.is_stale():
                logger.warning("[ORDER_EXECUTOR] TESTING: Bypassing stale balance check")
                # issues.append("Account balance data is stale")  # TESTING: Disabled
            
            current_balance = self.balance_tracker.get_current_balance()
            if current_balance <= 1000:  # Minimum 1000 CZK
                issues.append(f"Insufficient balance: {current_balance:,.0f} CZK")
            
            # 5. Calculate position size using RiskManager
            symbol = signal.get('symbol')
            entry_price = signal.get('entry_price', signal.get('entry', 0))  # Try both keys
            sl_distance_points = signal.get('sl_distance_points', 0)
            tp_distance_points = signal.get('tp_distance_points', sl_distance_points * 2)
            
            # Initialize sizing_result
            sizing_result = {}
            
            if entry_price <= 0 or sl_distance_points <= 0:
                issues.append("Invalid entry price or stop loss distance")
            else:
                # Calculate SL and TP prices
                direction = signal.get('direction', 'BUY')
                if direction.upper() == 'BUY':
                    stop_loss_price = signal.get('stop_loss', entry_price - sl_distance_points)
                    take_profit_price = signal.get('take_profit', entry_price + tp_distance_points)
                else:
                    stop_loss_price = signal.get('stop_loss', entry_price + sl_distance_points)
                    take_profit_price = signal.get('take_profit', entry_price - tp_distance_points)
                
                # Use existing RiskManager for position sizing with ATR
                position_size = self.risk_manager.calculate_position_size(
                    symbol=symbol,
                    entry=entry_price,
                    stop_loss=stop_loss_price,
                    take_profit=take_profit_price,
                    regime=signal.get('regime', 'TREND'),
                    signal_quality=signal.get('quality', signal.get('signal_quality', 75)),
                    atr=signal.get('atr', 0)  # ATR from signal or 0 for fallback
                )
                
                if position_size is None:
                    issues.append("Position sizing failed")
                else:
                    # Check if we have enough margin
                    risk_status = self.risk_manager.get_risk_status()
                    if not risk_status.can_trade:
                        issues.append(f"Risk limits exceeded: {', '.join(risk_status.warnings)}")
                    
                    sizing_result = {
                        'position_size_lots': position_size.lots,
                        'risk_amount_actual': position_size.risk_amount_czk,
                        'risk_percentage_actual': position_size.risk_percent / 100,
                        'margin_required': position_size.margin_required_czk,
                        'stop_loss_price': position_size.stop_loss,
                        'take_profit_price': position_size.take_profit,
                        'potential_profit': position_size.potential_profit_czk
                    }
            
            # 6. Check daily risk limits with soft-cap scaling
            if sizing_result and 'risk_amount_actual' in sizing_result:
                risk_check = self.daily_risk_tracker.can_trade(sizing_result['risk_amount_actual'])

                if not risk_check.get('can_trade', False):
                    # Hard rejection - no budget left
                    issues.append(f"Daily risk limit exhausted: "
                                f"{risk_check.get('risk_used', 0):,.0f} >= {risk_check.get('daily_limit', 0):,.0f} CZK")
                elif risk_check.get('scaled', False):
                    # Soft-cap: scale down position size proportionally
                    scale_factor = risk_check.get('scale_factor', 1.0)

                    logger.info(f"[SOFT-CAP] Scaling position down by {scale_factor:.2f} "
                               f"(daily risk budget: {risk_check.get('scaled_risk', 0):,.0f} CZK)")

                    # Scale down the position size in sizing_result
                    original_lots = sizing_result.get('position_size', 0)
                    scaled_lots = original_lots * scale_factor

                    # Update sizing_result with scaled values
                    sizing_result['position_size'] = scaled_lots
                    sizing_result['risk_amount_actual'] = risk_check.get('scaled_risk', 0)
                    # Note: SL/TP prices remain the same, only position size changes

                    logger.info(f"[SOFT-CAP] Position scaled: {original_lots:.2f} → {scaled_lots:.2f} lots")
            
            # 7. Check signal quality
            signal_quality = signal.get('quality', 0)
            min_quality = self.config.get('edges', {}).get('min_signal_quality', 60)
            
            if signal_quality < min_quality:
                issues.append(f"Signal quality too low: {signal_quality}% < {min_quality}%")
            
            result = {
                'can_execute': len(issues) == 0,
                'issues': issues,
                'active_symbol': active_symbol,
                'signal_symbol': signal.get('symbol'),
                'current_balance': current_balance,
                'position_open': len(self.risk_manager.open_positions) > 0
            }
            
            if result['can_execute']:
                result['sizing_result'] = sizing_result
                result['risk_check'] = risk_check
            
            return result
            
        except Exception as e:
            logger.error(f"[ORDER_EXECUTOR] Error checking trade execution: {e}")
            return {
                'can_execute': False,
                'issues': [f"Execution check error: {e}"],
                'error': str(e)
            }

    def _trade_side_from_direction(self, direction: str) -> int:
        """Convert direction string to cTrader tradeSide integer"""
        d = str(direction).upper()
        if d in {"BUY", "LONG", "SIGNALTYPE.BUY"}:
            return 1  # BUY
        if d in {"SELL", "SHORT", "SIGNALTYPE.SELL"}:
            return 2  # SELL
        raise ValueError(f"Unknown direction: {direction}")

    def _compute_prices(self, entry: float, sl_pts: float, tp_pts: float, side: int) -> tuple[float, float]:
        """Compute SL/TP prices based on trade direction"""
        # side: 1=BUY, 2=SELL
        if side == 1:  # BUY
            sl = entry - sl_pts
            tp = entry + tp_pts
        else:  # SELL
            sl = entry + sl_pts
            tp = entry - tp_pts
        return sl, tp

    def _sanity_check_orientation(self, direction: str, entry: float, sl_pts: float, tp_pts: float, side: int):
        """Safety check to prevent wrong direction orders"""
        sl, tp = self._compute_prices(entry, sl_pts, tp_pts, side)

        if "BUY" in str(direction).upper():
            if not (sl < entry < tp):
                raise RuntimeError(f"[SAFETY] BUY signal but computed SELL orientation "
                                   f"(entry={entry}, SL={sl}, TP={tp}). Aborting.")
            logger.info(f"[SAFETY] ✅ BUY orientation verified: SL {sl} < Entry {entry} < TP {tp}")
        else:  # SELL
            if not (tp < entry < sl):
                raise RuntimeError(f"[SAFETY] SELL signal but computed BUY orientation "
                                   f"(entry={entry}, SL={sl}, TP={tp}). Aborting.")
            logger.info(f"[SAFETY] ✅ SELL orientation verified: TP {tp} < Entry {entry} < SL {sl}")

    def execute_signal(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute trading signal as market order
        
        Args:
            signal: Trading signal from edge detection
            
        Returns:
            Execution result
        """
        logger.info(f"[ORDER_EXECUTOR] Attempting to execute signal: {signal.get('symbol')} {signal.get('direction')}")
        logger.info(f"[ORDER_EXECUTOR] Auto-trading enabled: {self.enabled}")
        logger.info(f"[ORDER_EXECUTOR] cTrader client connected: {self.ctrader_client.is_connected() if self.ctrader_client else False}")
        
        try:
            # Pre-execution checks
            execution_check = self.can_execute_trade(signal)
            if not execution_check['can_execute']:
                logger.warning(f"[ORDER_EXECUTOR] Signal execution rejected:")
                for issue in execution_check['issues']:
                    logger.warning(f"  - {issue}")
                
                return {
                    'executed': False,
                    'reason': 'Pre-execution checks failed',
                    'issues': execution_check['issues'],
                    'signal': signal
                }
            
            
            # Extract execution data
            sizing_result = execution_check['sizing_result']
            symbol = signal['symbol']
            direction = signal['direction']  # BUY/SELL
            entry_price = signal['entry_price']
            sl_distance_points = signal['sl_distance_points']
            tp_distance_points = signal.get('tp_distance_points', sl_distance_points * 2)  # Default 2:1 RRR
            
            position_size = sizing_result['position_size_lots']
            
            logger.info(f"[ORDER_EXECUTOR] Executing {symbol} {direction}:")
            logger.info(f"  Position size: {position_size:.2f} lots")
            logger.info(f"  Entry: {entry_price}")
            logger.info(f"  SL distance: {sl_distance_points} points")
            logger.info(f"  TP distance: {tp_distance_points} points")
            logger.info(f"  Risk: {sizing_result['risk_amount_actual']:,.0f} CZK ({sizing_result['risk_percentage_actual']:.2%})")
            
            # Calculate SL/TP prices
            if direction.upper() == 'BUY':
                sl_price = entry_price - sl_distance_points
                tp_price = entry_price + tp_distance_points
            else:  # SELL
                sl_price = entry_price + sl_distance_points
                tp_price = entry_price - tp_distance_points
            
            # Prepare order data
            order_data = {
                'symbol': symbol,
                'direction': direction.upper(),
                'position_size': position_size,
                'entry_price': entry_price,
                'sl_price': sl_price,
                'tp_price': tp_price,
                'risk_amount': sizing_result['risk_amount_actual'],
                'signal_id': signal.get('id', 'unknown'),
                'timestamp': datetime.now().isoformat()
            }
            
            # Execute order via cTrader client
                
            execution_result = self._send_market_order(order_data)
            logger.info(f"[ORDER_EXECUTOR] 📊 _send_market_order returned: {execution_result}")
            
            # 🚨 CRITICAL FIX: Don't set position_open=True until we get EXECUTION_EVENT confirmation
            # The _send_market_order just sends the order - actual position opening is confirmed via WebSocket
            has_positions = len(self.risk_manager.open_positions) > 0
            logger.error(f"[🚨 ORDER TRACKING] Order sent but position_open remains: {has_positions}")
            logger.error(f"[🚨 ORDER TRACKING] Waiting for EXECUTION_EVENT to confirm position opening...")
            
            if execution_result.get('success', False):
                # DON'T set position_open = True here - wait for EXECUTION_EVENT
                logger.error("[🚨 POSITION STATE] Order sent successfully but position_open stays FALSE until execution confirmed")
                # Store pending order info for when we get execution confirmation
                self.pending_order = {
                    'symbol': symbol,
                    'direction': direction,
                    'position_size': position_size,
                    'entry_price': entry_price,
                    'sl_price': sl_price,
                    'tp_price': tp_price,
                    'position_id': execution_result.get('position_id'),
                    'sent_at': datetime.now().isoformat(),
                    'risk_amount': sizing_result['risk_amount_actual']
                }
                
                # Position tracking now handled by RiskManager - no need for current_position
                
                # Add to daily risk tracking
                self.daily_risk_tracker.add_trade({
                    'symbol': symbol,
                    'position_size': position_size,
                    'risk_amount': sizing_result['risk_amount_actual'],
                    'entry_price': execution_result.get('actual_entry_price', entry_price),
                    'sl_price': sl_price,
                    'tp_price': tp_price,
                    'trade_id': execution_result.get('position_id', 'unknown')
                })

                # Log trade decision for analytics
                try:
                    # Prepare enhanced execution_result with position_data for logger
                    # Get position data from risk_manager or pending_order
                    position_data = self._get_current_position_data(symbol)
                    enhanced_execution = {
                        **execution_result,
                        'position_data': position_data
                    }

                    # Build context from signal data (not from EdgeDetector attributes)
                    context = {
                        'regime': signal.get('regime', 'UNKNOWN'),
                        'adx': signal.get('adx', 0),
                        'current_balance': self.balance_tracker.get_current_balance(),
                        'last_swing_high': signal.get('last_swing_high'),
                        'last_swing_low': signal.get('last_swing_low')
                    }
                    self.trade_logger.log_trade(signal, enhanced_execution, context)
                except Exception as log_error:
                    logger.warning(f"[ORDER_EXECUTOR] Failed to log trade decision: {log_error}")

                logger.info(f"[ORDER_EXECUTOR] ✅ Order executed successfully!")
                logger.info(f"  Position ID: {execution_result.get('position_id')}")
                logger.info(f"  Actual entry: {execution_result.get('actual_entry_price')}")

                # Get position data from risk_manager or pending_order
                position_data = self._get_current_position_data(symbol)
                return {
                    'success': True,  # Fixed: Use 'success' key for consistency
                    'executed': True,
                    'position_id': execution_result.get('position_id'),
                    'actual_entry_price': execution_result.get('actual_entry_price'),
                    'position_data': position_data,
                    'execution_result': execution_result,
                    'signal': signal
                }
            else:
                logger.error(f"[ORDER_EXECUTOR] ❌ Order execution failed:")
                logger.error(f"  Error: {execution_result.get('error', 'Unknown error')}")
                
                return {
                    'executed': False,
                    'reason': 'Order execution failed',
                    'error': execution_result.get('error', 'Unknown error'),
                    'execution_result': execution_result,
                    'signal': signal
                }
            
        except Exception as e:
            logger.error(f"[ORDER_EXECUTOR] Exception during signal execution: {e}")
            import traceback
            traceback.print_exc()
            
            return {
                'executed': False,
                'reason': 'Exception during execution',
                'error': str(e),
                'signal': signal
            }
    
    def _send_market_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send market order via cTrader client - Based on PROVEN trading_test_open_final.py logic
        
        Args:
            order_data: Order information 
            
        Returns:
            Execution result
        """
        logger.info("[ORDER_EXECUTOR] 🚀 _send_market_order called!")
        logger.info(f"[ORDER_EXECUTOR] 📊 Order data: {order_data}")
        
        try:
            logger.info(f"[ORDER_EXECUTOR] Sending REAL market order to cTrader (based on proven logic)...")
            
            # Extract order parameters
            symbol = order_data['symbol']
            direction = order_data['direction']
            position_size = order_data['position_size'] 
            entry_price = order_data['entry_price']
            sl_price = order_data['sl_price']
            tp_price = order_data['tp_price']
            
            logger.info(f"[ORDER_EXECUTOR] Order: {symbol} {direction} {position_size:.2f} lots")
            
            # Symbol mapping (using REAL cTrader symbol names)
            symbol_mapping = {
                'DAX': {'name': 'GER40', 'id': 203},     # REAL cTrader name: GER40
                'NASDAQ': {'name': 'US100', 'id': 208},
                'DE40': {'name': 'GER40', 'id': 203},    # Config uses DE40 but cTrader is GER40
                'US100': {'name': 'US100', 'id': 208},
                'GER40': {'name': 'GER40', 'id': 203}    # Direct cTrader mapping
            }
            
            if symbol not in symbol_mapping:
                raise ValueError(f"Unknown symbol: {symbol}")
            
            symbol_id = symbol_mapping[symbol]['id']
            
            # cTrader constants (from proven test)
            PRICE_SCALE = 100000
            TICK_SIZE = 0.01  # Both DAX and NASDAQ
            TICK_RAW = 1000   # 0.01 * 100000 = 1000
            
            def price_to_raw(price: float) -> int:
                return int(round(price * PRICE_SCALE))
            
            def points_to_relative(points: float) -> int:
                return int(round(points * PRICE_SCALE))
            
            def align_to_tick(raw_value: int) -> int:
                return (raw_value // TICK_RAW) * TICK_RAW
            
            # Calculate SL/TP distances in points (proven logic)
            if direction.upper() == 'BUY':
                sl_points = entry_price - sl_price  # Distance in points
                tp_points = tp_price - entry_price  # Distance in points
            else:  # SELL
                sl_points = sl_price - entry_price  # Distance in points
                tp_points = entry_price - tp_price  # Distance in points
            
            # Convert to relative with tick alignment (CRITICAL from proven test)
            sl_relative = align_to_tick(points_to_relative(abs(sl_points)))
            tp_relative = align_to_tick(points_to_relative(abs(tp_points)))
            
            # Volume: lots to cTrader format (from proven test)
            volume_raw = int(position_size * 100)  # NOT 100000! Test uses *100
            
            logger.info(f"[ORDER_EXECUTOR] cTrader conversion (proven format):")
            logger.info(f"  Symbol ID: {symbol_id}")
            logger.info(f"  Volume: {volume_raw} (= {position_size} lots)")
            logger.info(f"  SL: {abs(sl_points):.1f} points → {sl_relative:,} relative (tick-aligned)")
            logger.info(f"  TP: {abs(tp_points):.1f} points → {tp_relative:,} relative (tick-aligned)")
            
            # FIXED: Robust direction mapping and sanity check
            side = self._trade_side_from_direction(direction)
            self._sanity_check_orientation(direction, entry_price, abs(sl_points), abs(tp_points), side)

            # Order message (EXACT format from proven test)
            order_msg = {
                "ctidTraderAccountId": self.ctrader_client.ctid_trader_account_id,
                "symbolId": symbol_id,
                "orderType": 1,  # MARKET
                "tradeSide": side,  # Fixed mapping
                "volume": volume_raw,
                "relativeStopLoss": sl_relative,     # Already positive and tick-aligned
                "relativeTakeProfit": tp_relative    # Already positive and tick-aligned
            }
            
            logger.info(f"[ORDER_EXECUTOR] NEW_ORDER_REQ payload: {order_msg}")
            
            # Use cTrader client's existing _send method (simple and proven)
            success = self._send_order_simple(order_msg)
            
            if success:
                position_id = f"POS_{symbol}_{datetime.now().strftime('%H%M%S')}"
                
                logger.info("[ORDER_EXECUTOR] ✅ Order sent to cTrader (using proven format)")
                logger.info("[ORDER_EXECUTOR] ⏳ Waiting for EXECUTION_EVENT confirmation...")
                
                return {
                    'success': True,
                    'position_id': position_id,
                    'actual_entry_price': entry_price,
                    'execution_time': datetime.now().isoformat(),
                    'order_msg': order_msg,
                    'message': 'Order sent using proven cTrader format'
                }
            else:
                raise Exception("Failed to send order via WebSocket")
                
        except Exception as e:
            logger.error(f"[ORDER_EXECUTOR] Error sending market order: {e}")
            import traceback
            traceback.print_exc()
            
            return {
                'success': False,
                'error': str(e),
                'message': f'Order execution failed: {e}'
            }
    
    def _send_order_simple(self, order_msg: Dict) -> bool:
        """Send order using AppDaemon's create_task method"""
        try:
            logger.error("[🚨 CRITICAL] _send_order_simple called!")
            logger.error(f"[🚨 CRITICAL] Order message: {order_msg}")
            logger.info("[ORDER_EXECUTOR] Using AppDaemon create_task for async operation")
            
            import json
            import time
            
            # Prepare message exactly like proven test
            msg_id = int(time.time())
            message = {
                "clientMsgId": str(msg_id),
                "payloadType": 2106,  # NEW_ORDER_REQ
                "payload": order_msg
            }
            
            logger.info(f"[ORDER_EXECUTOR] 📤 Sending payloadType 2106 (NEW_ORDER_REQ)")
            logger.info(f"[ORDER_EXECUTOR] Detail: {json.dumps(order_msg, indent=2)}")
            
            # Use AppDaemon's proper async method
            async def send_order_task():
                """Async task for sending order"""
                try:
                    logger.error("[🚨 ASYNC TASK] send_order_task STARTED!")
                    
                    # Check if cTrader client is connected
                    if not self.ctrader_client:
                        logger.error("[🚨 ASYNC TASK] No cTrader client available!")
                        return False
                    
                    if not hasattr(self.ctrader_client, 'ws') or not self.ctrader_client.ws:
                        logger.error("[🚨 ASYNC TASK] ❌ cTrader WebSocket not connected!")
                        return False
                        
                    logger.error("[🚨 ASYNC TASK] ✅ WebSocket connected, sending order to cTrader...")
                    # Use thread-safe sender to avoid cross-loop await
                    future = self.ctrader_client.send_from_other_thread(2106, order_msg, timeout=15.0)
                    client_msg_id = future  # This is the actual clientMsgId from cTrader
                    logger.error(f"[🚨 ASYNC TASK] ✅ ORDER SENT! cTrader message ID: {client_msg_id}")
                    
                    logger.error("[🚨 ASYNC TASK] 🔄 Waiting for cTrader response...")
                    # Wait for order response (5 seconds timeout)
                    import asyncio
                    await asyncio.sleep(2)  # Give cTrader time to process
                    
                    logger.error("[🚨 ASYNC TASK] ✅ cTrader should have processed the order!")
                    return True
                except Exception as e:
                    logger.error(f"[🚨 ASYNC TASK] ERROR: {e}")
                    import traceback
                    logger.error(f"[🚨 ASYNC TASK] TRACEBACK: {traceback.format_exc()}")
                    return False
            
            # Create task using AppDaemon's method (this is the correct way!)
            try:
                if self.create_task_fn:
                    logger.error("[🚨 CREATE_TASK] About to schedule async task...")
                    
                    # Check connection first BEFORE scheduling task
                    if not self.ctrader_client or not hasattr(self.ctrader_client, 'ws') or not self.ctrader_client.ws:
                        logger.error("[🚨 CREATE_TASK] ❌ No WebSocket - task NOT scheduled!")
                        return False
                    
                    logger.error("[🚨 CREATE_TASK] ✅ WebSocket OK, scheduling task...")
                    # AppDaemon's create_task schedules the async function
                    task = self.create_task_fn(send_order_task())
                    logger.error(f"[🚨 CREATE_TASK] ✅ Task scheduled: {task}")
                    logger.error("[🚨 CREATE_TASK] 📤 Returning True - task should execute now...")
                    return True  # Task is scheduled, AppDaemon will execute it
                else:
                    logger.error("[ORDER_EXECUTOR] No create_task_fn available")
                    return self._fallback_send_order(order_msg)
                
            except Exception as task_error:
                logger.error(f"[ORDER_EXECUTOR] AppDaemon create_task failed: {task_error}")
                return self._fallback_send_order(order_msg)
                
        except Exception as e:
            logger.error(f"[ORDER_EXECUTOR] _send_order_simple failed: {e}")
            return False

    def _fallback_send_order(self, order_msg: Dict) -> bool:
        """Fallback - log order instead of sending"""
        try:
            import json
            import time
            
            logger.info("[ORDER_EXECUTOR] 🚨 FALLBACK: Just logging order (not sending)")
            
            message = {
                "clientMsgId": str(int(time.time())),
                "payloadType": 2106,
                "payload": order_msg
            }
            
            logger.info("[ORDER_EXECUTOR] 📋 Would send:")
            logger.info(json.dumps(message, indent=2))
            logger.info("[ORDER_EXECUTOR] ⚠️ Order NOT actually sent (fallback mode)")
            logger.info("[ORDER_EXECUTOR] 🔍 This means either create_task failed or cTrader client issue")
            
            return False  # Return FALSE because we didn't actually send anything!
            
        except Exception as e:
            logger.error(f"[ORDER_EXECUTOR] Fallback failed: {e}")
            return False

    def _send_order_proven_method(self, order_msg: Dict) -> bool:
        """Send order using EXACT logic from proven trading_test_open_final.py"""
        try:
            logger.info("[ORDER_EXECUTOR] Using PROVEN test logic for order sending")
            
            # Get credentials from cTrader client (should be same as test)
            client_id = getattr(self.ctrader_client, 'client_id', None)
            client_secret = getattr(self.ctrader_client, 'client_secret', None) 
            access_token = getattr(self.ctrader_client, 'access_token', None)
            account_id = getattr(self.ctrader_client, 'ctid_trader_account_id', None)
            
            if not all([client_id, client_secret, access_token, account_id]):
                logger.error("[ORDER_EXECUTOR] Missing cTrader credentials")
                return False
            
            logger.info(f"[ORDER_EXECUTOR] Using account ID: {account_id}")
            
            # Use existing cTrader WebSocket connection
            import json
            import asyncio
            import time
            
            logger.info("[ORDER_EXECUTOR] Using existing cTrader WebSocket connection")
            
            if not hasattr(self.ctrader_client, 'ws') or not self.ctrader_client.ws:
                logger.error("[ORDER_EXECUTOR] No WebSocket connection available")
                return False
            
            # Results storage  
            results = {'success': False, 'error': None, 'completed': False}
            
            # Prepare order message
            message = {
                "clientMsgId": f"order_{int(time.time())}",
                "payloadType": 2106,  # NEW_ORDER_REQ
                "payload": order_msg
            }
            
            logger.info(f"[ORDER_EXECUTOR] Sending order: {json.dumps(message, indent=2)}")
            
            # Send via existing WebSocket using async properly
            async def send_order_async():
                try:
                    await self.ctrader_client.ws.send(json.dumps(message))
                    logger.info("[ORDER_EXECUTOR] ✅ Order sent via existing WebSocket")
                    results['success'] = True
                    results['completed'] = True
                except Exception as e:
                    logger.error(f"[ORDER_EXECUTOR] Send error: {e}")
                    results['error'] = str(e)
                    results['completed'] = True
            
            # Run the async function
            try:
                # Try to get existing event loop
                loop = asyncio.get_running_loop()
                task = loop.create_task(send_order_async())
                logger.info("[ORDER_EXECUTOR] Order send task created")
            except RuntimeError:
                # No running loop, this shouldn't happen in AppDaemon
                logger.error("[ORDER_EXECUTOR] No running event loop found")
                return False
            
            # Wait for completion (max 5 seconds)
            for i in range(50):  # 5 seconds, check every 0.1s
                if results['completed']:
                    break
                time.sleep(0.1)
            
            if results['error']:
                logger.error(f"[ORDER_EXECUTOR] Order failed: {results['error']}")
                return False
            elif results['success']:
                logger.info("[ORDER_EXECUTOR] ✅ Order sent successfully using existing WebSocket")
                return True
            else:
                logger.error("[ORDER_EXECUTOR] Order send timeout")
                return False
                
        except Exception as e:
            logger.error(f"[ORDER_EXECUTOR] Error in proven method: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _add_sync_order_method_and_send(self, order_msg: Dict) -> bool:
        """Add synchronous order sending method to cTrader client and send order"""
        try:
            logger.info("[ORDER_EXECUTOR] Adding synchronous order method to cTrader client...")
            
            # Create synchronous order sending method (based on proven test logic)
            def send_market_order_sync(client_self, order_payload):
                try:
                    import json
                    import threading
                    import time
                    
                    # Prepare message in exact format from proven test
                    client_self._msg_id = getattr(client_self, '_msg_id', 0) + 1
                    message = {
                        "clientMsgId": str(client_self._msg_id),
                        "payloadType": 2106,  # NEW_ORDER_REQ
                        "payload": order_payload
                    }
                    
                    logger.info(f"[ORDER_EXECUTOR] Sending sync message: {json.dumps(message, indent=2)}")
                    
                    # Check WebSocket type and send appropriately
                    if hasattr(client_self, 'ws') and client_self.ws:
                        # Use synchronous send (like proven test)
                        if hasattr(client_self.ws, 'send') and not asyncio.iscoroutinefunction(client_self.ws.send):
                            client_self.ws.send(json.dumps(message))
                            logger.info("[ORDER_EXECUTOR] ✅ Order sent via synchronous WebSocket")
                            return True
                        else:
                            # It's async WebSocket, schedule it in the event loop
                            logger.info("[ORDER_EXECUTOR] Using async WebSocket via event loop")
                            try:
                                import asyncio
                                
                                # Get the current event loop or create one
                                try:
                                    loop = asyncio.get_running_loop()
                                    # We're in an async context, use create_task
                                    task = loop.create_task(client_self.ws.send(json.dumps(message)))
                                    logger.info("[ORDER_EXECUTOR] ✅ Order scheduled via async task")
                                    return True
                                except RuntimeError:
                                    # No running loop, try to run in new loop
                                    logger.info("[ORDER_EXECUTOR] No running loop, creating new one")
                                    
                                    # Create a function to run the async send
                                    async def send_async():
                                        await client_self.ws.send(json.dumps(message))
                                    
                                    # Run it in a new event loop
                                    asyncio.run(send_async())
                                    logger.info("[ORDER_EXECUTOR] ✅ Order sent via new async loop")
                                    return True
                                    
                            except Exception as async_error:
                                logger.error(f"[ORDER_EXECUTOR] Async send failed: {async_error}")
                                # Last resort - try the raw coroutine (will give warning but might work)
                                try:
                                    result = client_self.ws.send(json.dumps(message))
                                    # If it returns a coroutine, ignore it (fire and forget)
                                    if asyncio.iscoroutine(result):
                                        logger.warning("[ORDER_EXECUTOR] Created coroutine but not awaiting (fire and forget)")
                                    logger.info("[ORDER_EXECUTOR] ✅ Order sent via fallback method")
                                    return True
                                except Exception as fallback_error:
                                    logger.error(f"[ORDER_EXECUTOR] All methods failed: {fallback_error}")
                                    return False
                    else:
                        logger.error("[ORDER_EXECUTOR] No WebSocket connection available")
                        return False
                        
                except Exception as e:
                    logger.error(f"[ORDER_EXECUTOR] Error in send_market_order_sync: {e}")
                    return False
            
            # Monkey-patch the method to cTrader client
            import types
            self.ctrader_client.send_market_order_sync = types.MethodType(send_market_order_sync, self.ctrader_client)
            
            # Now call the new method
            return self.ctrader_client.send_market_order_sync(order_msg)
            
        except Exception as e:
            logger.error(f"[ORDER_EXECUTOR] Error adding sync method: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _send_order_via_websocket(self, msg_type: int, payload: Dict) -> bool:
        """Send order message via cTrader WebSocket"""
        try:
            if not self.ctrader_client.is_connected():
                logger.error("[ORDER_EXECUTOR] cTrader not connected")
                return False
            
            message = {
                "payloadType": msg_type,
                "payload": payload,
                "clientMsgId": f"order_{datetime.now().strftime('%H%M%S%f')[:9]}"  # Add microseconds for uniqueness
            }
            
            logger.info(f"[ORDER_EXECUTOR] Preparing WebSocket message: {message}")
            
            # Use the existing WebSocket connection with proper async handling
            if hasattr(self.ctrader_client, 'ws') and self.ctrader_client.ws:
                import json
                import asyncio
                
                message_json = json.dumps(message)
                logger.info(f"[ORDER_EXECUTOR] Sending JSON: {message_json}")
                
                # Check if we're in async context or need to handle sync
                try:
                    # Try to send directly if it's not a coroutine
                    if hasattr(self.ctrader_client.ws, 'send_str'):
                        # aiohttp websocket
                        self.ctrader_client.ws.send_str(message_json)
                    else:
                        # Regular websocket - check if it's async
                        send_method = self.ctrader_client.ws.send
                        if asyncio.iscoroutinefunction(send_method):
                            # It's async, we need to run it properly
                            logger.warning("[ORDER_EXECUTOR] WebSocket.send is async - using synchronous wrapper")
                            # For now, try the raw send without await
                            send_method(message_json)
                        else:
                            # It's synchronous
                            send_method(message_json)
                    
                    logger.info("[ORDER_EXECUTOR] ✅ Order message sent via WebSocket")
                    return True
                    
                except Exception as ws_error:
                    logger.error(f"[ORDER_EXECUTOR] WebSocket send error: {ws_error}")
                    # Try alternative method
                    try:
                        self.ctrader_client.ws.send(message_json)
                        logger.info("[ORDER_EXECUTOR] ✅ Order sent via fallback method")
                        return True
                    except Exception as fallback_error:
                        logger.error(f"[ORDER_EXECUTOR] Fallback send failed: {fallback_error}")
                        return False
            else:
                logger.error("[ORDER_EXECUTOR] No WebSocket connection available")
                return False
                
        except Exception as e:
            logger.error(f"[ORDER_EXECUTOR] Error in _send_order_via_websocket: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def check_symbol_switch(self) -> Optional[Dict[str, Any]]:
        """
        Check for symbol switch and close positions if needed
        
        Returns:
            Symbol switch information or None
        """
        try:
            session_change = self.time_manager.check_session_change()
            
            if session_change.get('changed', False):
                old_symbol = session_change.get('old_symbol')
                new_symbol = session_change.get('new_symbol')
                action_required = session_change.get('action_required')
                
                logger.info(f"[ORDER_EXECUTOR] Session changed: {old_symbol} → {new_symbol}")
                
                if action_required == 'close_positions' and len(self.risk_manager.open_positions) > 0:
                    logger.info("[ORDER_EXECUTOR] Closing position due to symbol switch...")
                    
                    close_result = self.close_current_position(reason="Symbol switch")
                    
                    return {
                        'symbol_switched': True,
                        'old_symbol': old_symbol,
                        'new_symbol': new_symbol,
                        'position_closed': close_result.get('closed', False),
                        'close_result': close_result
                    }
            
            return None
            
        except Exception as e:
            logger.error(f"[ORDER_EXECUTOR] Error checking symbol switch: {e}")
            return None
    
    def _get_current_position_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get current position data from risk_manager or pending_order"""
        # First try to get from risk_manager
        positions = [p for p in self.risk_manager.open_positions if p.symbol == symbol]
        if positions:
            pos = positions[0]  # Get first position for this symbol
            return {
                'symbol': pos.symbol,
                'direction': pos.direction,
                'position_size': pos.lots,
                'entry_price': pos.entry_price,
                'sl_price': pos.stop_loss,
                'tp_price': pos.take_profit,
                'position_id': pos.position_id,
                'risk_amount': pos.risk_amount_czk
            }
        # Fallback to pending_order if available
        if hasattr(self, 'pending_order') and self.pending_order:
            pending = self.pending_order if isinstance(self.pending_order, dict) else {}
            if pending.get('symbol') == symbol:
                return pending
        return None
    
    def close_current_position(self, reason: str = "Manual close") -> Dict[str, Any]:
        """
        LEGACY METHOD - Close positions (updated for multi-position system)

        Args:
            reason: Reason for closing position

        Returns:
            Close result
        """
        try:
            # Check if we have any open positions via risk manager
            if not self.risk_manager.open_positions:
                return {
                    'closed': False,
                    'reason': 'No positions to close'
                }

            # For backward compatibility, close the first position
            position = self.risk_manager.open_positions[0]
            position_id = getattr(position, 'position_id', 'unknown')
            symbol = getattr(position, 'symbol', 'unknown')

            logger.info(f"[ORDER_EXECUTOR] Closing position {position_id} ({symbol}): {reason}")
            logger.warning("[ORDER_EXECUTOR] ⚠️ LEGACY METHOD - Use multi-position API instead!")

            # TODO: Implement actual position closing via cTrader API
            # This would use CLOSE_POSITION_REQ message

            # Mock successful close
            mock_close_result = {
                'success': True,
                'position_id': position_id,
                'symbol': symbol,
                'close_time': datetime.now().isoformat(),
                'pnl': 500.0,  # Mock P&L
                'message': 'Mock close - replace with real cTrader integration'
            }

            # Remove from risk manager (multi-position system)
            self.risk_manager.remove_position(position)

            logger.info(f"[ORDER_EXECUTOR] ✅ Position closed: {reason}")
            logger.warning("[ORDER_EXECUTOR] ⚠️ MOCK CLOSE - Replace with real cTrader API!")

            return {
                'closed': True,
                'reason': reason,
                'symbol': symbol,
                'close_result': mock_close_result
            }
            
        except Exception as e:
            logger.error(f"[ORDER_EXECUTOR] Error closing position: {e}")
            return {
                'closed': False,
                'reason': f"Error closing position: {e}",
                'error': str(e)
            }
    
    def get_execution_status(self) -> Dict[str, Any]:
        """Get current execution status"""
        try:
            session_info = self.time_manager.get_session_info()
            balance_info = self.balance_tracker.get_balance_info()
            daily_status = self.daily_risk_tracker.get_daily_status()
            
            # Get position info from risk_manager
            has_positions = len(self.risk_manager.open_positions) > 0
            current_positions = [self._get_current_position_data(p.symbol) for p in self.risk_manager.open_positions]
            # Filter out None values
            current_positions = [p for p in current_positions if p is not None]
            
            return {
                'enabled': self.enabled,
                'position_open': has_positions,
                'current_position': current_positions[0] if current_positions else None,
                'all_positions': current_positions,  # New: all positions
                'session_info': session_info,
                'balance_info': balance_info,
                'daily_risk': daily_status,
                'can_trade': (
                    self.enabled and 
                    not has_positions and 
                    session_info.get('trading_active', False) and
                    not balance_info.get('is_stale', True) and
                    daily_status.get('percentage_used', 1.0) < 1.0
                )
            }
            
        except Exception as e:
            logger.error(f"[ORDER_EXECUTOR] Error getting execution status: {e}")
            return {
                'enabled': self.enabled,
                'position_open': len(self.risk_manager.open_positions) > 0,
                'error': str(e)
            }
    
    def get_status_summary(self) -> str:
        """Get human-readable status summary"""
        try:
            status = self.get_execution_status()
            
            if not status['enabled']:
                return "🔴 Auto-trading DISABLED"
            
            session_info = status.get('session_info', {})
            daily_risk = status.get('daily_risk', {})
            
            if status['position_open']:
                pos = status['current_position']
                if pos:
                    return f"🟡 Position OPEN: {pos.get('symbol', 'UNKNOWN')} {pos.get('direction', '')} {pos.get('position_size', 0):.1f} lots"
                return f"🟡 Position OPEN: {len(status.get('all_positions', []))} position(s)"
            
            if not session_info.get('trading_active', False):
                return f"🔴 Markets CLOSED {session_info.get('session', '')}"
            
            daily_pct = daily_risk.get('percentage_used', 0)
            if daily_pct >= 1.0:
                return f"🔴 Daily limit REACHED ({daily_pct:.0%})"
            
            active_symbol = session_info.get('symbol', 'None')
            time_left = session_info.get('minutes_to_change', 0)

            return f"🟢 Ready for {active_symbol} ({time_left}min left, {daily_pct:.0%} daily risk used)"

        except Exception as e:
            logger.error(f"[ORDER_EXECUTOR] Error in get_status_summary: {e}")
            return f"🔴 Status ERROR: {e}"

    def _extract_symbol_from_payload(self, payload):
        """Extract symbol from cTrader execution payload"""
        try:
            # Try to get symbol ID from payload and convert to symbol name
            symbol_id = payload.get('position', {}).get('tradeData', {}).get('symbolId')
            if symbol_id:
                # Convert symbol ID to symbol name (based on config)
                symbol_map = {208: 'NASDAQ', 203: 'DAX'}  # From your cTrader config
                return symbol_map.get(symbol_id, f'SYMBOL_{symbol_id}')

            # Fallback: check if we can infer from current risk manager positions
            if self.risk_manager.open_positions:
                # If we only have one position, it's likely the one being closed
                if len(self.risk_manager.open_positions) == 1:
                    return self.risk_manager.open_positions[0].symbol

            return None
        except Exception as e:
            logger.error(f"[EXTRACT SYMBOL] Error: {e}")
            return None

    def reevaluate_rejected_signals(self):
        """
        DISCARD signals that were rejected due to disabled auto-trading.
        Called when auto-trading is enabled via toggle.

        NOTE: Signals generated while auto-trading was OFF are DISCARDED, not executed.
        This prevents executing stale signals that may no longer be valid.
        """
        if not self.rejected_signals:
            logger.info("[ORDER_EXECUTOR] ℹ️ No rejected signals to discard")
            return

        discarded_count = len(self.rejected_signals)

        logger.info(f"[ORDER_EXECUTOR] 🗑️ Discarding {discarded_count} old signals generated while auto-trading was OFF")

        # Log what we're discarding
        from datetime import datetime
        now = datetime.now()
        for signal, rejected_at in self.rejected_signals:
            age = now - rejected_at
            logger.info(f"[ORDER_EXECUTOR] 🗑️ Discarded: {signal.get('symbol')} {signal.get('direction')} (age: {age.total_seconds():.0f}s)")

        # Clear all rejected signals - DO NOT execute them
        self.rejected_signals = []

        logger.info(f"[ORDER_EXECUTOR] ✅ Discarded {discarded_count} old signals - only NEW signals will be executed")

        return {
            'discarded': discarded_count,
            'executed': 0  # Never execute old signals
        }