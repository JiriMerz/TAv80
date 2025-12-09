#!/usr/bin/env python3
"""
Daily Risk Tracker for MVP Auto-Trading
Tracks daily risk consumption against 1.5% daily limit

MVP Implementation - Sprint 3
"""

import logging
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional
import json
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


class DailyRiskTracker:
    """
    Tracks daily risk consumption to enforce 1.5% daily limit
    
    Features:
    - Tracks risk used per trading day
    - Resets at midnight
    - Prevents exceeding daily limits
    - Stores trade history for analysis
    """
    
    def __init__(self, daily_limit_percentage: float = 0.015, balance_tracker=None):
        """
        Initialize daily risk tracker
        
        Args:
            daily_limit_percentage: Daily risk limit as decimal (0.015 = 1.5%)
            balance_tracker: BalanceTracker instance for current balance
        """
        self.daily_limit_percentage = daily_limit_percentage
        self.balance_tracker = balance_tracker
        
        # Daily tracking
        self.current_date: Optional[date] = None
        self.daily_risk_used: float = 0.0  # CZK amount used today
        self.daily_trades: List[Dict] = []
        
        # Historical data
        self.daily_history: Dict[str, Dict] = {}  # date_str -> daily_data
        self.max_history_days = 30
        
        logger.info(f"[DAILY_RISK] Initialized with {daily_limit_percentage:.1%} daily limit")
    
    def _ensure_current_date(self):
        """Ensure we're tracking the current date, reset if new day"""
        today = datetime.now(ZoneInfo("Europe/Prague")).date()
        
        if self.current_date != today:
            # New day - save previous day and reset
            if self.current_date is not None:
                self._save_daily_data()
            
            self._reset_daily_tracking(today)
    
    def _reset_daily_tracking(self, new_date: date):
        """Reset daily tracking for new date"""
        self.current_date = new_date
        self.daily_risk_used = 0.0
        self.daily_trades = []
        
        logger.info(f"[DAILY_RISK] Reset for new trading day: {new_date}")
    
    def _save_daily_data(self):
        """Save current daily data to history"""
        if self.current_date is None:
            return
            
        date_str = self.current_date.isoformat()
        
        self.daily_history[date_str] = {
            'date': date_str,
            'risk_used': self.daily_risk_used,
            'risk_limit': self._get_daily_limit(),
            'risk_percentage_used': self.daily_risk_used / self._get_daily_limit() if self._get_daily_limit() > 0 else 0,
            'trades_count': len(self.daily_trades),
            'trades': self.daily_trades.copy()
        }
        
        # Limit history size
        if len(self.daily_history) > self.max_history_days:
            # Keep only recent days
            sorted_dates = sorted(self.daily_history.keys())
            for old_date in sorted_dates[:-self.max_history_days]:
                del self.daily_history[old_date]
        
        logger.info(f"[DAILY_RISK] Saved daily data for {date_str}: "
                   f"{self.daily_risk_used:,.0f} CZK, {len(self.daily_trades)} trades")
    
    def _get_daily_limit(self) -> float:
        """Get daily risk limit in CZK"""
        if self.balance_tracker is None:
            return 0
            
        current_balance = self.balance_tracker.get_current_balance()
        return current_balance * self.daily_limit_percentage
    
    def can_trade(self, proposed_risk: float) -> Dict[str, Any]:
        """
        Check if proposed trade would exceed daily risk limit
        
        Args:
            proposed_risk: Risk amount in CZK for proposed trade
            
        Returns:
            Dict with trade permission and details
        """
        self._ensure_current_date()
        
        daily_limit = self._get_daily_limit()
        risk_after_trade = self.daily_risk_used + proposed_risk
        would_exceed = risk_after_trade > daily_limit
        
        remaining_risk = max(0, daily_limit - self.daily_risk_used)
        risk_percentage_used = self.daily_risk_used / daily_limit if daily_limit > 0 else 0
        risk_percentage_after = risk_after_trade / daily_limit if daily_limit > 0 else 0
        
        # Soft-cap scaling: if would exceed, suggest scaled down risk
        scaled_risk = proposed_risk
        scale_factor = 1.0

        if would_exceed and remaining_risk > 0:
            # Scale down to fit remaining budget
            scale_factor = remaining_risk / proposed_risk
            scaled_risk = remaining_risk

            logger.info(f"[DAILY_RISK] Soft-cap scaling: {proposed_risk:,.0f} → {scaled_risk:,.0f} CZK "
                       f"(scale factor: {scale_factor:.2f})")

        result = {
            'can_trade': True,  # Always allow trading with soft-cap
            'proposed_risk': proposed_risk,
            'scaled_risk': scaled_risk,
            'scale_factor': scale_factor,
            'daily_limit': daily_limit,
            'risk_used': self.daily_risk_used,
            'risk_remaining': remaining_risk,
            'risk_after_trade': self.daily_risk_used + scaled_risk,
            'percentage_used': risk_percentage_used,
            'percentage_after': (self.daily_risk_used + scaled_risk) / daily_limit if daily_limit > 0 else 0,
            'trades_count': len(self.daily_trades),
            'would_exceed': would_exceed,
            'scaled': scale_factor < 1.0
        }

        if would_exceed and remaining_risk > 0:
            logger.info(f"[DAILY_RISK] Trade scaled down to fit daily limit: "
                       f"{scaled_risk:,.0f} CZK ({remaining_risk:,.0f} remaining)")
        elif would_exceed and remaining_risk <= 0:
            result['can_trade'] = False
            logger.warning(f"[DAILY_RISK] Trade rejected - daily limit exhausted: "
                          f"{self.daily_risk_used:,.0f} >= {daily_limit:,.0f} CZK")
        else:
            logger.debug(f"[DAILY_RISK] Trade allowed: {proposed_risk:,.0f} CZK "
                        f"({remaining_risk:,.0f} remaining)")
        
        return result
    
    def add_trade(self, trade_data: Dict[str, Any]) -> bool:
        """
        Add completed trade to daily tracking
        
        Args:
            trade_data: Trade information dict
            
        Returns:
            True if trade was added successfully
        """
        try:
            self._ensure_current_date()
            
            # Extract trade information
            symbol = trade_data.get('symbol', 'UNKNOWN')
            position_size = trade_data.get('position_size', 0)
            risk_amount = trade_data.get('risk_amount', 0)
            entry_price = trade_data.get('entry_price', 0)
            sl_price = trade_data.get('sl_price', 0)
            tp_price = trade_data.get('tp_price', 0)
            
            # Create trade record
            trade_record = {
                'timestamp': datetime.now().isoformat(),
                'symbol': symbol,
                'position_size': position_size,
                'entry_price': entry_price,
                'sl_price': sl_price,
                'tp_price': tp_price,
                'risk_amount': risk_amount,
                'trade_id': trade_data.get('trade_id', f"trade_{len(self.daily_trades) + 1}")
            }
            
            # Add to daily tracking
            self.daily_trades.append(trade_record)
            self.daily_risk_used += risk_amount
            
            logger.info(f"[DAILY_RISK] Trade added: {symbol} {position_size} lots, "
                       f"Risk: {risk_amount:,.0f} CZK, Daily total: {self.daily_risk_used:,.0f} CZK")
            
            return True
            
        except Exception as e:
            logger.error(f"[DAILY_RISK] Error adding trade: {e}")
            return False
    
    def get_daily_status(self) -> Dict[str, Any]:
        """Get current daily risk status"""
        self._ensure_current_date()
        
        daily_limit = self._get_daily_limit()
        remaining_risk = max(0, daily_limit - self.daily_risk_used)
        percentage_used = self.daily_risk_used / daily_limit if daily_limit > 0 else 0
        
        # Calculate max trades remaining (assuming 0.5% per trade)
        per_trade_risk = daily_limit / 3  # 1.5% / 3 = 0.5% per trade
        max_trades_remaining = int(remaining_risk / per_trade_risk) if per_trade_risk > 0 else 0
        
        return {
            'date': self.current_date.isoformat() if self.current_date else None,
            'daily_limit': daily_limit,
            'risk_used': self.daily_risk_used,
            'risk_remaining': remaining_risk,
            'percentage_used': percentage_used,
            'trades_count': len(self.daily_trades),
            'max_trades_remaining': max_trades_remaining,
            'limit_percentage': self.daily_limit_percentage
        }
    
    def get_daily_summary(self) -> str:
        """Get human-readable daily summary"""
        status = self.get_daily_status()
        
        if status['daily_limit'] == 0:
            return "❌ Daily risk tracking unavailable (no balance)"
        
        percentage = status['percentage_used']
        risk_used = status['risk_used']
        risk_limit = status['daily_limit']
        trades_count = status['trades_count']
        
        if percentage < 0.5:  # Less than 50%
            indicator = "🟢"
        elif percentage < 0.8:  # 50-80%
            indicator = "🟡"
        else:  # 80%+
            indicator = "🔴"
        
        return (f"{indicator} Daily risk: {risk_used:,.0f}/{risk_limit:,.0f} CZK "
               f"({percentage:.1%}) | {trades_count} trades")
    
    def get_risk_breakdown(self) -> Dict[str, Any]:
        """Get detailed risk breakdown for today"""
        self._ensure_current_date()
        
        # Group trades by symbol
        symbol_breakdown = {}
        for trade in self.daily_trades:
            symbol = trade['symbol']
            if symbol not in symbol_breakdown:
                symbol_breakdown[symbol] = {
                    'trades_count': 0,
                    'total_risk': 0.0,
                    'total_volume': 0.0,
                    'trades': []
                }
            
            symbol_breakdown[symbol]['trades_count'] += 1
            symbol_breakdown[symbol]['total_risk'] += trade['risk_amount']
            symbol_breakdown[symbol]['total_volume'] += trade['position_size']
            symbol_breakdown[symbol]['trades'].append(trade)
        
        return {
            'total_risk': self.daily_risk_used,
            'total_trades': len(self.daily_trades),
            'symbol_breakdown': symbol_breakdown,
            'daily_limit': self._get_daily_limit()
        }
    
    def get_recent_history(self, days: int = 7) -> List[Dict]:
        """Get recent daily history"""
        # Get recent dates
        end_date = datetime.now(ZoneInfo("Europe/Prague")).date()
        dates = []
        
        for i in range(days):
            check_date = end_date - timedelta(days=i)
            date_str = check_date.isoformat()
            
            if date_str in self.daily_history:
                dates.append(self.daily_history[date_str])
            else:
                # Add empty day
                dates.append({
                    'date': date_str,
                    'risk_used': 0.0,
                    'risk_limit': 0.0,
                    'risk_percentage_used': 0.0,
                    'trades_count': 0,
                    'trades': []
                })
        
        return sorted(dates, key=lambda x: x['date'], reverse=True)
    
    def reset_daily_risk(self, new_date: date = None):
        """
        Manually reset daily risk tracking (for testing)
        
        Args:
            new_date: Date to reset to (default: today)
        """
        if new_date is None:
            new_date = datetime.now(ZoneInfo("Europe/Prague")).date()
            
        if self.current_date is not None:
            self._save_daily_data()
            
        self._reset_daily_tracking(new_date)
        logger.info(f"[DAILY_RISK] Manually reset to {new_date}")
    
    def validate_daily_limits(self) -> Dict[str, Any]:
        """Validate current daily risk status"""
        self._ensure_current_date()
        
        status = self.get_daily_status()
        issues = []
        
        # Check if limit exceeded
        if status['percentage_used'] > 1.0:
            issues.append(f"Daily limit exceeded: {status['percentage_used']:.1%}")
        
        # Check if close to limit
        elif status['percentage_used'] > 0.9:
            issues.append(f"Close to daily limit: {status['percentage_used']:.1%}")
        
        # Check balance availability
        if status['daily_limit'] <= 0:
            issues.append("No balance available for risk calculation")
        
        return {
            'valid': len(issues) == 0,
            'issues': issues,
            'status': status
        }