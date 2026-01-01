#!/usr/bin/env python3
"""
Time-Based Symbol Manager for MVP Auto-Trading
    Handles DAX (09:00-15:30) and NASDAQ (15:30-22:00) switching

MVP Implementation - Sprint 3
"""

import logging
from datetime import datetime, time, timezone
import pytz
from typing import Optional, Dict, Any
from enum import Enum

logger = logging.getLogger(__name__)


class TradingSession(Enum):
    """Trading session types"""
    DAX = "DAX"
    NASDAQ = "NASDAQ" 
    CLOSED = "CLOSED"


class TimeBasedSymbolManager:
    """
    Manages active trading symbol based on Prague timezone
    
    Schedule:
    - 09:00-15:30: DAX only
    - 15:30-22:00: NASDAQ only  
    - 22:00-09:00: No trading (CLOSED)
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        
        # Trading schedule (Prague time)
        self.dax_start = time(9, 0)      # 09:00
        self.dax_end = time(15, 30)      # 15:30 (DAX ends when NASDAQ starts)
        self.nasdaq_start = time(15, 30)  # 15:30 (Prague time)
        self.nasdaq_end = time(22, 0)    # 22:00
        
        # State tracking
        self.current_session: Optional[TradingSession] = None
        self.last_check_time: Optional[datetime] = None
        self.session_switched: bool = False
        
        # CRITICAL FIX: Store last broker timestamp
        self.last_broker_timestamp: Optional[datetime] = None
        self.broker_time_offset: Optional[float] = None  # Offset between broker time and local time
        
        logger.info(f"[TIME_MANAGER] Initialized with schedule:")
        logger.info(f"  DAX: {self.dax_start.strftime('%H:%M')}-{self.dax_end.strftime('%H:%M')}")
        logger.info(f"  NASDAQ: {self.nasdaq_start.strftime('%H:%M')}-{self.nasdaq_end.strftime('%H:%M')}")
        logger.info(f"  Broker time sync: Enabled")
    
    def update_broker_timestamp(self, broker_timestamp: datetime):
        """
        CRITICAL FIX: Update broker timestamp for time-based decisions
        
        Args:
            broker_timestamp: Timestamp from broker (SPOT_EVENT or BAR_DATA)
        """
        if broker_timestamp:
            self.last_broker_timestamp = broker_timestamp
            # Calculate offset between broker time and local time
            # Ensure both are timezone-aware
            if broker_timestamp.tzinfo is None:
                # If broker timestamp is naive, assume UTC
                broker_timestamp = broker_timestamp.replace(tzinfo=timezone.utc)
            local_time = datetime.now(timezone.utc)
            self.broker_time_offset = (broker_timestamp - local_time).total_seconds()
            if hasattr(self, 'logger'):
                self.logger.debug(f"[TIME_MANAGER] Broker timestamp updated: {broker_timestamp}, offset: {self.broker_time_offset:.1f}s")
    
    def get_active_session(self, current_time: datetime = None) -> TradingSession:
        """
        Determine which trading session is currently active
        
        CRITICAL FIX: Uses broker timestamp if available, otherwise local time
        
        Args:
            current_time: Time to check (default: broker time or now)
            
        Returns:
            TradingSession enum (DAX/NASDAQ/CLOSED)
        """
        # CRITICAL FIX: Use broker timestamp if available
        if current_time is None:
            if self.last_broker_timestamp:
                current_time = self.last_broker_timestamp
                # Convert to Prague timezone if needed
                if current_time.tzinfo:
                    prague_tz = pytz.timezone('Europe/Prague')
                    current_time = current_time.astimezone(prague_tz)
                logger.debug(f"[TIME_MANAGER] Using broker timestamp: {current_time}")
            else:
                # Use current time in Prague timezone
                prague_tz = pytz.timezone('Europe/Prague')
                current_time = datetime.now(prague_tz)
                logger.debug(f"[TIME_MANAGER] Using Prague time: {current_time}")
        else:
            # Ensure timezone-aware and in Prague timezone
            if current_time.tzinfo is None:
                # Assume it's already in Prague timezone (naive)
                prague_tz = pytz.timezone('Europe/Prague')
                current_time = prague_tz.localize(current_time)
            elif str(current_time.tzinfo) != 'Europe/Prague':
                # Convert to Prague timezone
                prague_tz = pytz.timezone('Europe/Prague')
                current_time = current_time.astimezone(prague_tz)
            
        current_time_only = current_time.time()
        
        # DAX session: 09:00 - 15:30
        if self.dax_start <= current_time_only < self.dax_end:
            return TradingSession.DAX
            
        # NASDAQ session: 15:30 - 22:00
        elif self.nasdaq_start <= current_time_only < self.nasdaq_end:
            return TradingSession.NASDAQ
            
        # Outside trading hours
        else:
            return TradingSession.CLOSED
    
    def get_active_symbol(self, current_time: datetime = None) -> Optional[str]:
        """
        Get the symbol that should be traded at given time
        
        CRITICAL FIX: Uses broker timestamp if available
        
        Args:
            current_time: Time to check (default: broker time or now)
            
        Returns:
            Symbol name (DAX/NASDAQ) or None if closed
        """
        # CRITICAL FIX: Use broker timestamp if available
        if current_time is None:
            if self.last_broker_timestamp:
                current_time = self.last_broker_timestamp
            else:
                current_time = datetime.now()
        
        session = self.get_active_session(current_time)
        
        if session == TradingSession.DAX:
            return "DAX"
        elif session == TradingSession.NASDAQ:
            return "NASDAQ"
        else:
            return None
    
    def check_session_change(self, current_time: datetime = None) -> Dict[str, Any]:
        """
        Check if trading session has changed since last check
        
        CRITICAL FIX: Uses broker timestamp if available
        
        Args:
            current_time: Time to check (default: broker time or now)
            
        Returns:
            Dict with session change info:
            {
                'changed': bool,
                'old_session': TradingSession,
                'new_session': TradingSession,
                'old_symbol': str or None,
                'new_symbol': str or None,
                'action_required': str  # 'close_positions' or 'continue'
            }
        """
        # CRITICAL FIX: Use broker timestamp if available
        if current_time is None:
            if self.last_broker_timestamp:
                current_time = self.last_broker_timestamp
            else:
                current_time = datetime.now()
            
        new_session = self.get_active_session(current_time)
        old_session = self.current_session
        
        # First run - no change
        if old_session is None:
            self.current_session = new_session
            self.last_check_time = current_time
            
            return {
                'changed': False,
                'old_session': None,
                'new_session': new_session,
                'old_symbol': None,
                'new_symbol': self.get_active_symbol(current_time),
                'action_required': 'continue'
            }
        
        # Check for change
        session_changed = (old_session != new_session)
        
        if session_changed:
            old_symbol = self._session_to_symbol(old_session)
            new_symbol = self._session_to_symbol(new_session)
            
            # Determine required action
            if old_session != TradingSession.CLOSED and new_session != old_session:
                action_required = 'close_positions'
            else:
                action_required = 'continue'
            
            # Update state
            self.current_session = new_session
            self.last_check_time = current_time
            
            logger.info(f"[TIME_MANAGER] Session changed: {old_session.value if old_session else 'None'} → {new_session.value}")
            logger.info(f"[TIME_MANAGER] Symbol changed: {old_symbol} → {new_symbol}")
            logger.info(f"[TIME_MANAGER] Action required: {action_required}")
            
            return {
                'changed': True,
                'old_session': old_session,
                'new_session': new_session,
                'old_symbol': old_symbol,
                'new_symbol': new_symbol,
                'action_required': action_required
            }
        else:
            # No change
            self.last_check_time = current_time
            return {
                'changed': False,
                'old_session': old_session,
                'new_session': new_session,
                'old_symbol': self._session_to_symbol(old_session),
                'new_symbol': self._session_to_symbol(new_session),
                'action_required': 'continue'
            }
    
    def _session_to_symbol(self, session: Optional[TradingSession]) -> Optional[str]:
        """Convert TradingSession to symbol name"""
        if session == TradingSession.DAX:
            return "DAX"
        elif session == TradingSession.NASDAQ:
            return "NASDAQ"
        else:
            return None
    
    def should_close_positions(self, old_session: Optional[TradingSession], 
                             new_session: TradingSession) -> bool:
        """
        Determine if positions should be closed due to session change
        
        Args:
            old_session: Previous trading session
            new_session: Current trading session
            
        Returns:
            True if positions should be closed
        """
        # Close positions when:
        # 1. Switching from one symbol to another (DAX → NASDAQ or vice versa)
        # 2. Entering CLOSED session (end of trading day)
        
        if old_session is None:
            return False
            
        # Going to CLOSED session - always close
        if new_session == TradingSession.CLOSED:
            return True
            
        # Switching between DAX and NASDAQ - close positions
        if (old_session in [TradingSession.DAX, TradingSession.NASDAQ] and 
            new_session in [TradingSession.DAX, TradingSession.NASDAQ] and 
            old_session != new_session):
            return True
            
        return False
    
    def get_session_info(self, current_time: datetime = None) -> Dict[str, Any]:
        """
        Get comprehensive info about current session
        
        Args:
            current_time: Time to check in Prague timezone (default: now in Prague)
            
        Returns:
            Dict with session information
        """
        if current_time is None:
            prague_tz = pytz.timezone('Europe/Prague')
            current_time = datetime.now(prague_tz)
        else:
            # Ensure timezone-aware and in Prague timezone
            if current_time.tzinfo is None:
                prague_tz = pytz.timezone('Europe/Prague')
                current_time = prague_tz.localize(current_time)
            elif str(current_time.tzinfo) != 'Europe/Prague':
                prague_tz = pytz.timezone('Europe/Prague')
                current_time = current_time.astimezone(prague_tz)
            
        session = self.get_active_session(current_time)
        symbol = self.get_active_symbol(current_time)
        
        # Calculate time to next session change
        next_change_time = self._get_next_session_change(current_time)
        
        return {
            'current_time': current_time.strftime('%H:%M:%S'),
            'session': session.value,
            'symbol': symbol,
            'trading_active': symbol is not None,
            'next_change': next_change_time.strftime('%H:%M') if next_change_time else None,
            'minutes_to_change': self._minutes_until(current_time, next_change_time) if next_change_time else None
        }
    
    def _get_next_session_change(self, current_time: datetime) -> Optional[time]:
        """Get the time of next session change"""
        current_time_only = current_time.time()
        
        if current_time_only < self.dax_start:
            return self.dax_start
        elif current_time_only < self.dax_end:
            return self.dax_end
        elif current_time_only < self.nasdaq_end:
            return self.nasdaq_end
        else:
            return self.dax_start  # Next day
    
    def _minutes_until(self, current_time: datetime, target_time: time) -> int:
        """Calculate minutes until target time"""
        current_time_only = current_time.time()
        
        # Convert to minutes since midnight
        current_minutes = current_time_only.hour * 60 + current_time_only.minute
        target_minutes = target_time.hour * 60 + target_time.minute
        
        # Handle next day case
        if target_minutes <= current_minutes:
            target_minutes += 24 * 60
            
        return target_minutes - current_minutes
    
    def is_trading_active(self, current_time: datetime = None) -> bool:
        """
        Check if trading is currently active
        
        Args:
            current_time: Time to check (default: now)
            
        Returns:
            True if trading session is active
        """
        return self.get_active_symbol(current_time) is not None
    
    def get_status_summary(self) -> str:
        """Get human-readable status summary"""
        info = self.get_session_info()
        
        if info['trading_active']:
            return f"🟢 {info['symbol']} active ({info['minutes_to_change']}min left)"
        else:
            if info['next_change']:
                return f"🔴 Markets closed (opens {info['next_change']})"
            else:
                return f"🔴 Markets closed"