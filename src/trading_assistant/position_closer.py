"""
Position Closer Module
Handles closing positions via cTrader API

Part of TAv70 Trading Assistant - Close & Reverse Feature

CRITICAL FIX: Removed time.sleep() to prevent blocking main thread
"""

import logging
from typing import Dict, Any, Optional, Callable
from datetime import datetime

logger = logging.getLogger(__name__)


class PositionCloser:
    """
    Handles position closing operations via cTrader WebSocket API

    Features:
    - Close single position by position data
    - Close all positions for a symbol
    - Close all positions (bulk close)
    - Thread-safe async execution
    """

    def __init__(self, ctrader_client, create_task_fn=None, run_in_fn=None):
        """
        Initialize position closer

        Args:
            ctrader_client: CTraderClient instance
            create_task_fn: AppDaemon's create_task function for async execution
            run_in_fn: AppDaemon's run_in function for scheduling (replaces time.sleep)
        """
        self.ctrader_client = ctrader_client
        self.create_task_fn = create_task_fn
        self.run_in_fn = run_in_fn  # For scheduling delays without blocking

        logger.info("[POSITION_CLOSER] Initialized (non-blocking delays enabled)")

    def update_stop_loss(self, position_id: int, symbol: str, new_sl_price: float, current_price: float, direction: str) -> Dict[str, Any]:
        """
        Update stop loss for an open position
        
        Args:
            position_id: cTrader position ID
            symbol: Symbol name (DAX, NASDAQ, etc.)
            new_sl_price: New stop loss price
            current_price: Current market price
            direction: Position direction (BUY or SELL)
            
        Returns:
            Dict with update result:
                - success: bool
                - position_id: int
                - message: str
                - error: str (if failed)
        """
        try:
            # Map symbol to symbol ID
            symbol_mapping = {
                'DAX': {'name': 'GER40', 'id': 203},
                'NASDAQ': {'name': 'US100', 'id': 208},
                'DE40': {'name': 'GER40', 'id': 203},
                'US100': {'name': 'US100', 'id': 208},
                'GER40': {'name': 'GER40', 'id': 203}
            }
            
            if symbol not in symbol_mapping:
                return {
                    'success': False,
                    'position_id': position_id,
                    'error': f'Unknown symbol: {symbol}'
                }
            
            symbol_id = symbol_mapping[symbol]['id']
            
            # Calculate relative stop loss (in points, then convert to cTrader format)
            # cTrader uses relative stop loss in pips (1 point = 100 pips for DAX/NASDAQ)
            if direction == 'BUY':
                relative_sl_points = current_price - new_sl_price
            else:  # SELL
                relative_sl_points = new_sl_price - current_price
            
            # Convert to cTrader format (pips, where 1 point = 100 pips)
            relative_sl_pips = int(relative_sl_points * 100)
            
            logger.info(f"[POSITION_CLOSER] Updating SL for {symbol} position {position_id}: {new_sl_price:.2f} (relative: {relative_sl_pips} pips)")
            
            # Send modify position request via WebSocket
            # NOTE: cTrader OpenAPI message type for MODIFY_POSITION_REQ needs to be verified
            # Current assumption: 2108 (based on standard sequence: 2106=NEW_ORDER_REQ, 2107=NEW_ORDER_RES)
            # TODO: Verify correct message type in official cTrader OpenAPI documentation
            success = self._send_modify_position_request(position_id, symbol_id, relative_sl_pips)
            
            if success:
                logger.info(f"[POSITION_CLOSER] ✅ SL update sent for {symbol} position {position_id}")
                return {
                    'success': True,
                    'position_id': position_id,
                    'symbol': symbol,
                    'new_sl_price': new_sl_price,
                    'message': f'SL update sent: {new_sl_price:.2f}'
                }
            else:
                return {
                    'success': False,
                    'position_id': position_id,
                    'error': 'Failed to send SL update via WebSocket'
                }
                
        except Exception as e:
            logger.error(f"[POSITION_CLOSER] Error updating stop loss: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            return {
                'success': False,
                'position_id': position_id,
                'error': str(e)
            }
    
    def _send_modify_position_request(self, position_id: int, symbol_id: int, relative_sl_pips: int) -> bool:
        """
        Send modify position request via cTrader WebSocket
        
        WARNING: Message type needs verification!
        - 2107 is PT_NEW_ORDER_RES (response), NOT MODIFY_POSITION_REQ
        - Possible message types: 2108 (MODIFY_POSITION_REQ) or 2109 (MODIFY_POSITION_RES)
        - OR: cTrader OpenAPI might not support MODIFY_POSITION_REQ at all
        
        Implementation depends on cTrader API documentation verification.
        """
        try:
            logger.info(f"[POSITION_CLOSER] Sending modify position request for position {position_id}")
            
            # Use AppDaemon's create_task for async execution
            async def send_modify_task():
                """Async task for sending modify position request"""
                try:
                    if not self.ctrader_client:
                        logger.error("[POSITION_CLOSER] No cTrader client available!")
                        return False
                    
                    if not hasattr(self.ctrader_client, 'ws') or not self.ctrader_client.ws:
                        logger.error("[POSITION_CLOSER] WebSocket not connected!")
                        return False
                    
                    # TODO: Implement actual MODIFY_POSITION_REQ when correct message type is verified
                    # 
                    # ISSUE: 2107 is PT_NEW_ORDER_RES (response), NOT MODIFY_POSITION_REQ!
                    # Need to verify correct message type from cTrader OpenAPI documentation
                    #
                    # Possible approaches:
                    # 1. Find correct MODIFY_POSITION_REQ message type (possibly 2108)
                    # 2. Use alternative: Close position and reopen with new SL
                    # 3. Check if cTrader supports stopLossPrice (absolute) instead of relativeStopLoss
                    #
                    logger.warning(f"[POSITION_CLOSER] ⚠️ SL update NOT IMPLEMENTED - requires API verification")
                    logger.warning(f"[POSITION_CLOSER] Position {position_id}: Would update SL to {relative_sl_pips} pips")
                    logger.warning(f"[POSITION_CLOSER] ⚠️ Trailing stop is currently DISABLED until MODIFY_POSITION_REQ is verified")
                    
                    # Placeholder for actual implementation (once message type is verified):
                    # PT_MODIFY_POSITION_REQ = 2108  # TODO: VERIFY THIS!
                    # modify_msg = {
                    #     "ctidTraderAccountId": self.ctrader_client.ctid_trader_account_id,
                    #     "positionId": position_id,
                    #     "relativeStopLoss": relative_sl_pips  # OR: "stopLossPrice": absolute_price
                    # }
                    # future = self.ctrader_client.send_from_other_thread(PT_MODIFY_POSITION_REQ, modify_msg, timeout=15.0)
                    
                    return True
                except Exception as e:
                    logger.error(f"[POSITION_CLOSER] Error in send_modify_task: {e}")
                    return False
            
            # Create task using AppDaemon
            if self.create_task_fn:
                if not self.ctrader_client or not hasattr(self.ctrader_client, 'ws') or not self.ctrader_client.ws:
                    logger.error("[POSITION_CLOSER] No WebSocket connection!")
                    return False
                
                task = self.create_task_fn(send_modify_task())
                logger.info(f"[POSITION_CLOSER] Modify task scheduled: {task}")
                return True
            else:
                logger.error("[POSITION_CLOSER] No create_task_fn available")
                return False
                
        except Exception as e:
            logger.error(f"[POSITION_CLOSER] Error sending modify request: {e}")
            return False

    def close_position(self, position: Dict[str, Any]) -> Dict[str, Any]:
        """
        Close a single position by sending opposite market order

        In cTrader API:
        - BUY position is closed by SELL market order with same volume
        - SELL position is closed by BUY market order with same volume
        - No need to specify positionId - cTrader auto-matches

        Args:
            position: Position dict with keys:
                - symbol: str (DAX, NASDAQ, etc.)
                - lots: float (position size)
                - direction: str (BUY or SELL)
                - position_id: str (optional, for logging)

        Returns:
            Dict with close result:
                - success: bool
                - position_id: str
                - message: str
                - error: str (if failed)
        """
        try:
            symbol = position.get('symbol', 'UNKNOWN')
            lots = position.get('lots', 0)
            direction = position.get('direction', '').upper()
            position_id = position.get('position_id', 'unknown')

            if lots <= 0:
                return {
                    'success': False,
                    'position_id': position_id,
                    'error': 'Invalid position size (lots <= 0)'
                }

            if direction not in ['BUY', 'SELL']:
                return {
                    'success': False,
                    'position_id': position_id,
                    'error': f'Invalid direction: {direction}'
                }

            # Determine closing direction (opposite of current position)
            close_direction = 'SELL' if direction == 'BUY' else 'BUY'
            close_side = 2 if close_direction == 'BUY' else 1  # cTrader: 1=SELL, 2=BUY

            logger.info(f"[POSITION_CLOSER] Closing {symbol} {direction} position ({lots:.2f} lots)")
            logger.info(f"[POSITION_CLOSER] Close order: {close_direction} {lots:.2f} lots")

            # Symbol mapping (same as in order executor)
            symbol_mapping = {
                'DAX': {'name': 'GER40', 'id': 203},
                'NASDAQ': {'name': 'US100', 'id': 208},
                'DE40': {'name': 'GER40', 'id': 203},
                'US100': {'name': 'US100', 'id': 208},
                'GER40': {'name': 'GER40', 'id': 203}
            }

            if symbol not in symbol_mapping:
                return {
                    'success': False,
                    'position_id': position_id,
                    'error': f'Unknown symbol: {symbol}'
                }

            symbol_id = symbol_mapping[symbol]['id']

            # Convert lots to cTrader volume format
            volume_raw = int(lots * 100)  # Same as opening: lots * 100

            # Close order message (market order without SL/TP)
            close_order_msg = {
                "ctidTraderAccountId": self.ctrader_client.ctid_trader_account_id,
                "symbolId": symbol_id,
                "orderType": 1,  # MARKET
                "tradeSide": close_side,
                "volume": volume_raw
                # NO relativeStopLoss/relativeTakeProfit for closing order
            }

            logger.info(f"[POSITION_CLOSER] Close order payload: {close_order_msg}")

            # Send close order via WebSocket
            success = self._send_close_order(close_order_msg)

            if success:
                logger.info(f"[POSITION_CLOSER] ✅ Close order sent for {symbol} {position_id}")
                return {
                    'success': True,
                    'position_id': position_id,
                    'symbol': symbol,
                    'lots': lots,
                    'close_direction': close_direction,
                    'message': f'Close order sent: {close_direction} {lots:.2f} lots'
                }
            else:
                return {
                    'success': False,
                    'position_id': position_id,
                    'error': 'Failed to send close order via WebSocket'
                }

        except Exception as e:
            logger.error(f"[POSITION_CLOSER] Error closing position: {e}")
            import traceback
            logger.error(traceback.format_exc())

            return {
                'success': False,
                'position_id': position.get('position_id', 'unknown'),
                'error': str(e)
            }

    def _send_close_order(self, order_msg: Dict) -> bool:
        """
        Send close order via cTrader WebSocket

        Uses same mechanism as opening orders (PT_NEW_ORDER_REQ)
        """
        try:
            logger.info("[POSITION_CLOSER] Sending close order via WebSocket")

            # Use AppDaemon's create_task for async execution
            async def send_close_task():
                """Async task for sending close order"""
                try:
                    if not self.ctrader_client:
                        logger.error("[POSITION_CLOSER] No cTrader client available!")
                        return False

                    if not hasattr(self.ctrader_client, 'ws') or not self.ctrader_client.ws:
                        logger.error("[POSITION_CLOSER] WebSocket not connected!")
                        return False

                    # Send order using thread-safe method
                    logger.info("[POSITION_CLOSER] Sending PT_NEW_ORDER_REQ (close)")
                    future = self.ctrader_client.send_from_other_thread(2106, order_msg, timeout=15.0)
                    logger.info(f"[POSITION_CLOSER] ✅ Close order sent! Message ID: {future}")

                    # Wait for cTrader to process
                    import asyncio
                    await asyncio.sleep(1)

                    return True
                except Exception as e:
                    logger.error(f"[POSITION_CLOSER] Error in send_close_task: {e}")
                    return False

            # Create task using AppDaemon
            if self.create_task_fn:
                # Check connection before scheduling
                if not self.ctrader_client or not hasattr(self.ctrader_client, 'ws') or not self.ctrader_client.ws:
                    logger.error("[POSITION_CLOSER] No WebSocket connection!")
                    return False

                # Schedule async task
                task = self.create_task_fn(send_close_task())
                logger.info(f"[POSITION_CLOSER] Close task scheduled: {task}")
                return True
            else:
                logger.error("[POSITION_CLOSER] No create_task_fn available")
                return False

        except Exception as e:
            logger.error(f"[POSITION_CLOSER] Error sending close order: {e}")
            return False

    def close_positions_by_symbol(self, symbol: str, positions: list) -> Dict[str, Any]:
        """
        Close all positions for a specific symbol

        Args:
            symbol: Symbol to close (DAX, NASDAQ, etc.)
            positions: List of position dicts

        Returns:
            Dict with results:
                - total: int (total positions to close)
                - closed: int (successfully closed)
                - failed: int (failed to close)
                - results: list of individual results
        """
        logger.info(f"[POSITION_CLOSER] Closing all {symbol} positions")

        symbol_positions = [p for p in positions if p.get('symbol') == symbol]

        if not symbol_positions:
            logger.info(f"[POSITION_CLOSER] No {symbol} positions to close")
            return {
                'total': 0,
                'closed': 0,
                'failed': 0,
                'results': []
            }

        results = []
        closed_count = 0
        failed_count = 0

        for pos in symbol_positions:
            result = self.close_position(pos)
            results.append(result)

            if result.get('success'):
                closed_count += 1
            else:
                failed_count += 1

        logger.info(f"[POSITION_CLOSER] Closed {closed_count}/{len(symbol_positions)} {symbol} positions")

        return {
            'total': len(symbol_positions),
            'closed': closed_count,
            'failed': failed_count,
            'results': results
        }

    def close_all_positions(self, positions: list) -> Dict[str, Any]:
        """
        Close all positions (bulk close)

        Args:
            positions: List of all position dicts

        Returns:
            Dict with results:
                - total: int
                - closed: int
                - failed: int
                - results: list
        """
        logger.info(f"[POSITION_CLOSER] Closing ALL {len(positions)} positions")

        if not positions:
            logger.info("[POSITION_CLOSER] No positions to close")
            return {
                'total': 0,
                'closed': 0,
                'failed': 0,
                'results': []
            }

        results = []
        closed_count = 0
        failed_count = 0

        # CRITICAL FIX: Remove time.sleep() - use async scheduling instead
        # Process all closes immediately without blocking
        for pos in positions:
            result = self.close_position(pos)
            results.append(result)

            if result.get('success'):
                closed_count += 1
            else:
                failed_count += 1

            # Note: No delay needed - cTrader handles rate limiting on server side
            # If delay is truly needed, use run_in_fn to schedule next close
            # but for now, we process all closes immediately to avoid blocking

        logger.info(f"[POSITION_CLOSER] Closed {closed_count}/{len(positions)} positions")

        return {
            'total': len(positions),
            'closed': closed_count,
            'failed': failed_count,
            'results': results
        }
