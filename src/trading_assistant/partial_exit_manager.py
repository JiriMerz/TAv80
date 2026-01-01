"""
Partial Exit Manager Module
Manages partial position exits at predefined profit levels

Part of TAv80 Trading Assistant - Success Improvement Plan
"""

import logging
import threading
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class PartialExitManager:
    """
    Manages partial exits for open positions
    
    Features:
    - Multiple exit levels (50% TP, 100% TP, 150% TP)
    - Configurable exit percentages
    - Prevents re-execution of exit levels
    - Tracks remaining position size
    """
    
    def __init__(self, config: Dict = None, position_closer=None):
        """
        Initialize partial exit manager
        
        Args:
            config: Configuration dict
            position_closer: PositionCloser instance for closing partial positions
        """
        self.config = config or {}
        self.position_closer = position_closer
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Configuration
        exit_config = self.config.get('partial_exits', {})
        self.enabled = exit_config.get('enabled', True)
        
        # Exit levels: [profit_pct, exit_pct, executed]
        self.exit_levels = exit_config.get('exit_levels', [
            {'profit_pct': 0.5, 'exit_pct': 0.5},   # 50% position at 50% TP
            {'profit_pct': 1.0, 'exit_pct': 0.3},   # 30% position at 100% TP
            {'profit_pct': 1.5, 'exit_pct': 0.2}   # 20% position at 150% TP
        ])
        
        # Track positions being managed
        self.managed_positions: Dict[str, Dict] = {}  # position_id -> position data
        
        logger.info(f"[PARTIAL_EXIT] Initialized - Enabled: {self.enabled}")
        logger.info(f"[PARTIAL_EXIT] Exit levels: {len(self.exit_levels)} configured")
    
    def add_position(self, position_id: str, position_data: Dict):
        """
        Add position to partial exit management
        
        Args:
            position_id: cTrader position ID
            position_data: Position dict with:
                - symbol: str
                - direction: str (BUY/SELL)
                - entry_price: float
                - stop_loss: float
                - take_profit: float
                - lots: float
        """
        if not self.enabled:
            return
        
        with self._lock:
            # Initialize exit tracking for this position
            exit_tracking = []
            for level in self.exit_levels:
                exit_tracking.append({
                    'profit_pct': level['profit_pct'],
                    'exit_pct': level['exit_pct'],
                    'executed': False
                })
            
            self.managed_positions[position_id] = {
                **position_data,
                'original_lots': position_data.get('lots', 0),
                'remaining_lots': position_data.get('lots', 0),
                'exit_levels': exit_tracking,
                'last_check': datetime.now(timezone.utc)
            }
            
            logger.info(f"[PARTIAL_EXIT] ✅ Added position {position_id} ({position_data.get('symbol')}) - {position_data.get('lots'):.2f} lots")
    
    def remove_position(self, position_id: str):
        """Remove position from partial exit management"""
        with self._lock:
            if position_id in self.managed_positions:
                removed = self.managed_positions.pop(position_id)
                logger.info(f"[PARTIAL_EXIT] Removed position {position_id} ({removed.get('symbol')}) from management")
    
    def check_and_execute_exits(self, positions: List[Dict], current_prices: Dict[str, float]):
        """
        Check all positions and execute partial exits if needed
        
        Args:
            positions: List of open positions from account
            current_prices: Dict mapping symbol to current price
        """
        if not self.enabled:
            return
        
        with self._lock:
            for position in positions:
                position_id = str(position.get('positionId', ''))
                if position_id not in self.managed_positions:
                    continue
                
                managed_pos = self.managed_positions[position_id]
                symbol = managed_pos.get('symbol', '')
                current_price = current_prices.get(symbol, 0)
                
                if current_price <= 0:
                    continue
                
                # Check and execute partial exits
                self._check_exit_levels(position_id, managed_pos, current_price, position)
    
    def _check_exit_levels(self, position_id: str, position: Dict, current_price: float, account_position: Dict):
        """
        Check exit levels and execute partial exits if conditions are met
        
        Args:
            position_id: Position ID
            position: Managed position dict
            current_price: Current market price
            account_position: Position dict from account (for closing)
        """
        try:
            entry_price = position.get('entry_price', 0)
            take_profit = position.get('take_profit', 0)
            stop_loss = position.get('stop_loss', 0)
            direction = position.get('direction', 'BUY')
            remaining_lots = position.get('remaining_lots', 0)
            
            if entry_price <= 0 or take_profit <= 0 or stop_loss <= 0:
                return
            
            # Calculate risk distance for R:R calculation
            if direction == 'BUY':
                profit_distance = current_price - entry_price
                risk_distance = entry_price - stop_loss  # SL distance
            else:  # SELL
                profit_distance = entry_price - current_price
                risk_distance = stop_loss - entry_price  # SL distance
            
            if risk_distance <= 0:
                return
            
            # Calculate R:R ratio (profit / risk)
            # profit_pct in exit_levels now means R:R ratio (1.5 = 1.5× risk, 2.5 = 2.5× risk)
            current_rr = profit_distance / risk_distance
            
            # Check each exit level (now based on R:R ratio instead of TP percentage)
            for exit_level in position.get('exit_levels', []):
                if exit_level['executed']:
                    continue
                
                target_rr = exit_level['profit_pct']  # Now means R:R ratio (1.5, 2.5, etc.)
                
                if current_rr >= target_rr:
                    # Execute partial exit
                    exit_lots = remaining_lots * exit_level['exit_pct']
                    
                    if exit_lots > 0.01:  # Minimum 0.01 lots
                        success = self._execute_partial_exit(
                            position_id,
                            position,
                            account_position,
                            exit_lots,
                            exit_level,
                            current_rr
                        )
                        
                        if success:
                            exit_level['executed'] = True
                            position['remaining_lots'] -= exit_lots
                            position['last_check'] = datetime.now(timezone.utc)
                            
                            logger.info(f"[PARTIAL_EXIT] ✅ Partial exit executed: {position.get('symbol')} "
                                      f"{exit_lots:.2f} lots at R:R {current_rr:.2f}:1 (target: {target_rr:.2f}:1)")
                        else:
                            logger.warning(f"[PARTIAL_EXIT] ⚠️ Failed to execute partial exit for {position.get('symbol')}")
        
        except Exception as e:
            logger.error(f"[PARTIAL_EXIT] ❌ Error checking exit levels: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def _execute_partial_exit(self, position_id: str, position: Dict, account_position: Dict, exit_lots: float, exit_level: Dict, current_rr: float) -> bool:
        """
        Execute partial exit by closing portion of position
        
        Args:
            position_id: Position ID
            position: Managed position dict
            account_position: Position dict from account
            exit_lots: Lots to close
            exit_level: Exit level configuration
            
        Returns:
            True if exit was successful
        """
        try:
            if not self.position_closer:
                logger.warning(f"[PARTIAL_EXIT] ⚠️ Cannot execute partial exit - no PositionCloser available")
                return False
            
            symbol = position.get('symbol', '')
            direction = position.get('direction', 'BUY')
            
            # Create partial position dict for closing
            partial_position = {
                'symbol': symbol,
                'lots': exit_lots,
                'direction': direction,
                'position_id': position_id
            }
            
            # Close partial position
            result = self.position_closer.close_position(partial_position)
            
            if result.get('success'):
                logger.info(f"[PARTIAL_EXIT] ✅ Closed {exit_lots:.2f} lots of {symbol} position {position_id} "
                          f"({exit_level['exit_pct']*100:.0f}% at R:R {current_rr:.2f}:1, target was {exit_level['profit_pct']:.2f}:1)")
                return True
            else:
                error = result.get('error', 'Unknown error')
                logger.warning(f"[PARTIAL_EXIT] ⚠️ Failed to close partial position: {error}")
                return False
                
        except Exception as e:
            logger.error(f"[PARTIAL_EXIT] ❌ Error executing partial exit: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False



