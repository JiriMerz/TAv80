"""
Position Closer Module
Handles closing positions via cTrader API

Part of TAv70 Trading Assistant - Close & Reverse Feature
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime
import time

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

    def __init__(self, ctrader_client, create_task_fn=None):
        """
        Initialize position closer

        Args:
            ctrader_client: CTraderClient instance
            create_task_fn: AppDaemon's create_task function for async execution
        """
        self.ctrader_client = ctrader_client
        self.create_task_fn = create_task_fn

        logger.info("[POSITION_CLOSER] Initialized")

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

        for pos in positions:
            result = self.close_position(pos)
            results.append(result)

            if result.get('success'):
                closed_count += 1
            else:
                failed_count += 1

            # Small delay between closes to avoid overwhelming cTrader
            time.sleep(0.1)

        logger.info(f"[POSITION_CLOSER] Closed {closed_count}/{len(positions)} positions")

        return {
            'total': len(positions),
            'closed': closed_count,
            'failed': failed_count,
            'results': results
        }
