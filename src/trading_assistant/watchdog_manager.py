"""
Watchdog Manager - Dead Man's Switch

CRITICAL SAFETY FEATURE: Monitors if trading bot is alive and responsive.
If bot stops updating watchdog, Home Assistant triggers alert and optionally
activates kill switch to close all positions.

Implementation:
- Bot updates input_boolean.trading_watchdog every 60 seconds
- HA automation monitors: if watchdog unchanged for 3 minutes → ALERT
- Optional: Kill switch to close all positions via broker API
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Callable

logger = logging.getLogger(__name__)


class WatchdogManager:
    """
    Manages Dead Man's Switch for trading bot
    
    Features:
    - Updates HA entity every 60 seconds to signal "alive"
    - Tracks last update timestamp
    - Provides kill switch functionality
    """
    
    def __init__(self, hass_app, config: Dict = None):
        """
        Initialize watchdog manager
        
        Args:
            hass_app: AppDaemon Hass instance
            config: Configuration dict with:
                - watchdog_entity: Entity ID for watchdog (default: input_boolean.trading_watchdog)
                - update_interval: Seconds between updates (default: 60)
                - alert_threshold: Seconds before alert (default: 180 = 3 minutes)
                - kill_switch_enabled: Enable kill switch on timeout (default: False)
                - kill_switch_entity: Entity ID for kill switch (default: input_boolean.trading_kill_switch)
        """
        self.hass = hass_app
        self.config = config or {}
        
        self.watchdog_entity = self.config.get('watchdog_entity', 'input_boolean.trading_watchdog')
        self.update_interval = self.config.get('update_interval', 60)  # 60 seconds
        self.alert_threshold = self.config.get('alert_threshold', 180)  # 3 minutes
        self.kill_switch_enabled = self.config.get('kill_switch_enabled', False)
        self.kill_switch_entity = self.config.get('kill_switch_entity', 'input_boolean.trading_kill_switch')
        
        self.last_update = None
        self.update_count = 0
        
        # Initialize watchdog entity if it doesn't exist
        self._initialize_watchdog_entity()
        
        logger.info(f"[WATCHDOG] Initialized:")
        logger.info(f"  - Entity: {self.watchdog_entity}")
        logger.info(f"  - Update interval: {self.update_interval}s")
        logger.info(f"  - Alert threshold: {self.alert_threshold}s")
        logger.info(f"  - Kill switch: {'ENABLED' if self.kill_switch_enabled else 'DISABLED'}")
    
    def _initialize_watchdog_entity(self):
        """Initialize watchdog entity in HA if it doesn't exist"""
        try:
            current_state = self.hass.get_state(self.watchdog_entity)
            if current_state is None:
                # Entity doesn't exist, create it
                self.hass.set_state(
                    self.watchdog_entity,
                    state='off',
                    attributes={
                        'friendly_name': 'Trading Bot Watchdog',
                        'last_update': None,
                        'update_count': 0
                    }
                )
                logger.info(f"[WATCHDOG] Created watchdog entity: {self.watchdog_entity}")
        except Exception as e:
            logger.warning(f"[WATCHDOG] Could not initialize entity: {e}")
    
    def update(self, kwargs=None):
        """
        Update watchdog to signal bot is alive
        
        This should be called periodically (every 60 seconds) by run_every()
        
        Args:
            kwargs: Optional kwargs from AppDaemon scheduler (ignored)
        """
        try:
            current_time = datetime.now(timezone.utc)
            self.last_update = current_time
            self.update_count += 1
            
            # Toggle watchdog state (off -> on -> off) to trigger state change
            current_state = self.hass.get_state(self.watchdog_entity)
            new_state = 'on' if current_state == 'off' else 'off'
            
            self.hass.set_state(
                self.watchdog_entity,
                state=new_state,
                attributes={
                    'friendly_name': 'Trading Bot Watchdog',
                    'last_update': current_time.isoformat(),
                    'update_count': self.update_count,
                    'update_interval': self.update_interval,
                    'alert_threshold': self.alert_threshold
                }
            )
            
            logger.info(f"[WATCHDOG] ✅ Updated (count: {self.update_count}, state: {new_state})")
            
        except Exception as e:
            logger.error(f"[WATCHDOG] ❌ Failed to update watchdog: {e}")
    
    def get_status(self) -> Dict:
        """Get current watchdog status"""
        try:
            current_state = self.hass.get_state(self.watchdog_entity)
            last_update_attr = self.hass.get_state(self.watchdog_entity, attribute='last_update')
            
            if last_update_attr:
                last_update = datetime.fromisoformat(last_update_attr.replace('Z', '+00:00'))
                time_since_update = (datetime.now(timezone.utc) - last_update).total_seconds()
                is_alive = time_since_update < self.alert_threshold
            else:
                time_since_update = None
                is_alive = False
            
            return {
                'entity': self.watchdog_entity,
                'current_state': current_state,
                'last_update': last_update_attr,
                'time_since_update': time_since_update,
                'is_alive': is_alive,
                'update_count': self.update_count,
                'alert_threshold': self.alert_threshold
            }
        except Exception as e:
            logger.error(f"[WATCHDOG] Error getting status: {e}")
            return {
                'entity': self.watchdog_entity,
                'error': str(e)
            }
    
    def activate_kill_switch(self, reason: str = "Watchdog timeout"):
        """
        Activate kill switch to close all positions
        
        This should be called by HA automation when watchdog times out
        
        Args:
            reason: Reason for kill switch activation
        """
        if not self.kill_switch_enabled:
            logger.warning(f"[WATCHDOG] Kill switch disabled, not activating")
            return
        
        try:
            logger.critical(f"[WATCHDOG] 🚨 KILL SWITCH ACTIVATED: {reason}")
            
            # Set kill switch entity
            self.hass.set_state(
                self.kill_switch_entity,
                state='on',
                attributes={
                    'friendly_name': 'Trading Kill Switch',
                    'activated_at': datetime.now(timezone.utc).isoformat(),
                    'reason': reason
                }
            )
            
            # Trigger notification
            self.hass.call_service(
                'notify.mobile_app',
                title='🚨 TRADING BOT KILL SWITCH',
                message=f'Kill switch activated: {reason}'
            )
            
            # Note: Actual position closing should be handled by separate automation
            # that listens to kill_switch_entity state change
            
        except Exception as e:
            logger.error(f"[WATCHDOG] ❌ Failed to activate kill switch: {e}")

