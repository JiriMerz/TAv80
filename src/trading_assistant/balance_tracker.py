#!/usr/bin/env python3
"""
Balance Tracker for MVP Auto-Trading
Tracks real-time account balance from cTrader API

MVP Implementation - Sprint 3
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class BalanceTracker:
    """
    Tracks real-time account balance and related metrics from cTrader API
    
    Updates balance from:
    - RECONCILE_REQ responses (periodic updates)
    - EXECUTION_EVENT messages (after each trade)
    """
    
    def __init__(self, initial_balance: float = 0):
        # Balance tracking
        self.balance: float = initial_balance
        self.free_margin: float = 0
        self.margin_used: float = 0
        self.unrealized_pnl: float = 0
        
        # Update tracking
        self.last_update: Optional[datetime] = None
        self.update_count: int = 0
        self.data_source: str = "none"  # reconcile, execution, initial
        
        # Balance history for debugging
        self.balance_history: list = []
        self.max_history_length: int = 100
        
        logger.info(f"[BALANCE] Initialized with balance: {initial_balance:,.2f}")
    
    def update_from_trader_res(self, trader_data: Dict[str, Any]) -> bool:
        """
        Update balance from PT_TRADER_RES (PROTO_OA_TRADER) response

        Args:
            trader_data: Trader payload from PT_TRADER_RES with moneyDigits scaling

        Returns:
            True if balance was updated
        """
        try:
            # Extract money scaling factor
            money_digits = trader_data.get('moneyDigits', 2)
            scaling_factor = 10 ** money_digits

            # Extract raw balance data
            balance_raw = trader_data.get('balance', 0)
            equity_raw = trader_data.get('equity', 0)
            margin_raw = trader_data.get('margin', 0)
            free_margin_raw = trader_data.get('freeMargin', 0)

            # Validate raw data
            if balance_raw <= 0:
                # Known issue: Demo API doesn't return balance in PT_TRADER_RES
                logger.debug(f"[BALANCE] PT_TRADER_RES missing balance (known demo API limitation), using PT_DEAL_LIST_RES instead")
                return False

            # Scale all monetary values
            new_balance = balance_raw / scaling_factor
            new_equity = equity_raw / scaling_factor
            new_margin_used = margin_raw / scaling_factor
            new_free_margin = free_margin_raw / scaling_factor

            # Calculate unrealized PnL from equity and balance
            new_unrealized_pnl = new_equity - new_balance if new_equity > 0 else 0

            # Store previous values
            old_balance = self.balance

            # Update values
            self.balance = new_balance
            self.free_margin = new_free_margin
            self.margin_used = new_margin_used
            self.unrealized_pnl = new_unrealized_pnl
            self.last_update = datetime.now()
            self.update_count += 1
            self.data_source = "trader_res"

            # Add to history
            self._add_to_history("trader_res", old_balance, new_balance)

            # Log update
            balance_change = new_balance - old_balance
            if abs(balance_change) > 1.0:  # Log changes > 1 CZK
                logger.info(f"[BALANCE] Updated from PT_TRADER_RES: {old_balance:,.2f} → {new_balance:,.2f} "
                           f"(Δ {balance_change:+,.2f}, equity={new_equity:,.2f})")
            else:
                logger.info(f"[BALANCE] PT_TRADER_RES update: balance={new_balance:,.2f}, equity={new_equity:,.2f}")

            return True

        except Exception as e:
            logger.error(f"[BALANCE] Error updating from PT_TRADER_RES: {e}")
            return False

    def update_from_reconcile(self, reconcile_data: Dict[str, Any]) -> bool:
        """
        Update balance from RECONCILE_REQ response (legacy support)

        Args:
            reconcile_data: Response payload from RECONCILE_REQ

        Returns:
            True if balance was updated
        """
        try:
            # Extract balance data
            new_balance = reconcile_data.get('balance', 0)
            new_free_margin = reconcile_data.get('freeMargin', 0)
            new_margin_used = reconcile_data.get('marginUsed', 0)
            new_unrealized_pnl = reconcile_data.get('unrealizedGrossProfit', 0)

            # Validate data
            if new_balance <= 0:
                logger.warning(f"[BALANCE] Invalid balance from reconcile: {new_balance}")
                return False

            # Store previous values
            old_balance = self.balance

            # Update values
            self.balance = new_balance
            self.free_margin = new_free_margin
            self.margin_used = new_margin_used
            self.unrealized_pnl = new_unrealized_pnl
            self.last_update = datetime.now()
            self.update_count += 1
            self.data_source = "reconcile"

            # Add to history
            self._add_to_history("reconcile", old_balance, new_balance)

            # Log significant changes
            balance_change = new_balance - old_balance
            if abs(balance_change) > 1.0:  # Log changes > 1 CZK
                logger.info(f"[BALANCE] Updated from reconcile: {old_balance:,.2f} → {new_balance:,.2f} "
                           f"(Δ {balance_change:+,.2f})")
            else:
                logger.debug(f"[BALANCE] Reconcile update: {new_balance:,.2f}")

            return True

        except Exception as e:
            logger.error(f"[BALANCE] Error updating from reconcile: {e}")
            return False
    
    def update_from_execution(self, execution_data: Dict[str, Any]) -> bool:
        """
        Update balance from EXECUTION_EVENT message
        
        Args:
            execution_data: Payload from EXECUTION_EVENT
            
        Returns:
            True if balance was updated
        """
        try:
            # Check if balance is in execution data
            if 'balance' not in execution_data:
                logger.debug("[BALANCE] No balance in execution event")
                return False
            
            new_balance = execution_data.get('balance', 0)
            
            # Validate data
            if new_balance <= 0:
                logger.warning(f"[BALANCE] Invalid balance from execution: {new_balance}")
                return False
            
            # Store previous values
            old_balance = self.balance
            
            # Update balance
            self.balance = new_balance
            self.last_update = datetime.now()
            self.update_count += 1
            self.data_source = "execution"
            
            # Add to history
            self._add_to_history("execution", old_balance, new_balance)
            
            # Get execution type for logging
            exec_type = execution_data.get('executionType', 'unknown')
            balance_change = new_balance - old_balance
            
            logger.info(f"[BALANCE] Updated from execution ({exec_type}): {old_balance:,.2f} → {new_balance:,.2f} "
                       f"(Δ {balance_change:+,.2f})")
            
            return True
            
        except Exception as e:
            logger.error(f"[BALANCE] Error updating from execution: {e}")
            return False
    
    def _add_to_history(self, source: str, old_balance: float, new_balance: float):
        """Add balance update to history"""
        self.balance_history.append({
            'timestamp': datetime.now(),
            'source': source,
            'old_balance': old_balance,
            'new_balance': new_balance,
            'change': new_balance - old_balance
        })
        
        # Limit history length
        if len(self.balance_history) > self.max_history_length:
            self.balance_history = self.balance_history[-self.max_history_length:]
    
    def get_current_balance(self) -> float:
        """Get current account balance"""
        return self.balance
    
    def is_stale(self, max_age_minutes: int = 5) -> bool:
        """
        Check if balance data is too old
        
        Args:
            max_age_minutes: Maximum age in minutes before data is considered stale
            
        Returns:
            True if balance data is stale
        """
        if self.last_update is None:
            return True
            
        age = datetime.now() - self.last_update
        return age > timedelta(minutes=max_age_minutes)
    
    def get_age_minutes(self) -> float:
        """Get age of current balance data in minutes"""
        if self.last_update is None:
            return float('inf')
            
        age = datetime.now() - self.last_update
        return age.total_seconds() / 60.0
    
    def calculate_risk_amount(self, risk_percentage: float) -> float:
        """
        Calculate risk amount in account currency
        
        Args:
            risk_percentage: Risk as decimal (0.005 for 0.5%)
            
        Returns:
            Risk amount in account currency (CZK)
        """
        if self.balance <= 0:
            logger.warning("[BALANCE] Cannot calculate risk - invalid balance")
            return 0
            
        risk_amount = self.balance * risk_percentage
        
        logger.debug(f"[BALANCE] Risk calculation: {self.balance:,.2f} × {risk_percentage:.1%} = {risk_amount:,.2f}")
        
        return risk_amount
    
    def get_balance_info(self) -> Dict[str, Any]:
        """
        Get comprehensive balance information
        
        Returns:
            Dict with all balance-related data
        """
        return {
            'balance': self.balance,
            'free_margin': self.free_margin,
            'margin_used': self.margin_used,
            'unrealized_pnl': self.unrealized_pnl,
            'last_update': self.last_update.isoformat() if self.last_update else None,
            'age_minutes': self.get_age_minutes(),
            'is_stale': self.is_stale(),
            'update_count': self.update_count,
            'data_source': self.data_source
        }
    
    def get_balance_summary(self) -> str:
        """Get human-readable balance summary"""
        age = self.get_age_minutes()
        age_str = f"{age:.1f}min" if age != float('inf') else "never"
        
        stale_indicator = "⚠️" if self.is_stale() else "✅"
        
        return f"{stale_indicator} Balance: {self.balance:,.2f} CZK (updated {age_str} ago)"
    
    def get_recent_history(self, limit: int = 10) -> list:
        """
        Get recent balance change history
        
        Args:
            limit: Maximum number of history entries
            
        Returns:
            List of recent balance changes
        """
        return self.balance_history[-limit:] if self.balance_history else []
    
    def validate_balance(self, min_balance: float = 1000) -> Dict[str, Any]:
        """
        Validate current balance for trading
        
        Args:
            min_balance: Minimum required balance
            
        Returns:
            Dict with validation results
        """
        issues = []
        
        # Check minimum balance
        if self.balance < min_balance:
            issues.append(f"Balance too low: {self.balance:,.2f} < {min_balance:,.2f}")
        
        # Check if data is stale
        if self.is_stale():
            issues.append(f"Balance data is stale (age: {self.get_age_minutes():.1f} minutes)")
        
        # Check if balance is valid
        if self.balance <= 0:
            issues.append("Invalid balance: must be positive")
        
        # Check margin usage if available
        if self.margin_used > 0 and self.free_margin > 0:
            total_margin = self.margin_used + self.free_margin
            margin_usage = self.margin_used / total_margin if total_margin > 0 else 0
            
            if margin_usage > 0.8:  # 80% margin usage
                issues.append(f"High margin usage: {margin_usage:.1%}")
        
        return {
            'valid': len(issues) == 0,
            'issues': issues,
            'balance': self.balance,
            'age_minutes': self.get_age_minutes()
        }
    
    def reset(self, new_balance: float = 0):
        """
        Reset balance tracker (for testing)
        
        Args:
            new_balance: New balance to set
        """
        self.balance = new_balance
        self.free_margin = 0
        self.margin_used = 0
        self.unrealized_pnl = 0
        self.last_update = None
        self.update_count = 0
        self.data_source = "reset"
        self.balance_history.clear()
        
        logger.info(f"[BALANCE] Reset to: {new_balance:,.2f}")