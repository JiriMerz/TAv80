"""
Logging Configuration for Trading Assistant
Controls what and how much is logged for fine-tuning and debugging
"""
from enum import Enum
from typing import Dict, Optional
import time
from collections import defaultdict

class LogLevel(Enum):
    """Logging verbosity levels"""
    MINIMAL = "minimal"      # Only critical events (position opened/closed, errors)
    NORMAL = "normal"        # Important events + position details (default)
    VERBOSE = "verbose"      # Everything including rejections and validations
    DEBUG = "debug"          # Maximum verbosity for debugging

class LoggingConfig:
    """
    Centralized logging configuration with throttling
    """
    
    def __init__(self, config: Dict = None):
        self.config = config or {}
        
        # Log level
        level_str = self.config.get('log_level', 'normal').lower()
        try:
            self.log_level = LogLevel(level_str)
        except ValueError:
            self.log_level = LogLevel.NORMAL
        
        # Throttling for repeated messages
        self.throttle_enabled = self.config.get('throttle_repeated_logs', True)
        self.throttle_window = self.config.get('throttle_window_seconds', 300)  # 5 minutes
        self._throttle_cache = defaultdict(lambda: {'count': 0, 'last_log': 0})
        
        # What to log
        self.log_rejections = self.log_level in [LogLevel.VERBOSE, LogLevel.DEBUG]
        self.log_validations = self.log_level == LogLevel.DEBUG
        self.log_breakout_details = self.log_level in [LogLevel.NORMAL, LogLevel.VERBOSE, LogLevel.DEBUG]
        self.log_position_details = True  # Always log position details
        
    def should_log(self, category: str, message: str = None) -> bool:
        """
        Check if message should be logged based on category and throttling
        
        Args:
            category: Log category ('rejection', 'validation', 'breakout', 'position', etc.)
            message: Optional message for throttling (same message = throttled)
            
        Returns:
            True if should log, False otherwise
        """
        # Always log positions and errors
        if category in ['position', 'error', 'critical']:
            return True
        
        # Check log level
        if category == 'rejection' and not self.log_rejections:
            return False
        if category == 'validation' and not self.log_validations:
            return False
        if category == 'breakout' and not self.log_breakout_details:
            return False
        
        # Throttling for repeated messages
        if self.throttle_enabled and message:
            cache_key = f"{category}:{message}"
            now = time.time()
            cached = self._throttle_cache[cache_key]
            
            # Reset if window expired
            if now - cached['last_log'] > self.throttle_window:
                cached['count'] = 0
                cached['last_log'] = now
                return True
            
            # Throttle if too frequent
            if cached['count'] > 0:
                cached['count'] += 1
                return False
            
            cached['count'] = 1
            cached['last_log'] = now
            return True
        
        return True
    
    def format_position_log(self, signal: Dict, execution_result: Dict, context: Dict) -> str:
        """
        Format detailed position log for fine-tuning
        
        Returns:
            Formatted string with all relevant information
        """
        lines = []
        lines.append("=" * 60)
        lines.append("📊 POSITION OPENED")
        lines.append("=" * 60)
        
        # Basic info
        lines.append(f"Symbol: {signal.get('symbol', 'UNKNOWN')}")
        lines.append(f"Direction: {signal.get('direction', 'UNKNOWN')}")
        lines.append(f"Entry: {signal.get('entry_price', 0):.2f}")
        lines.append(f"SL: {execution_result.get('position_data', {}).get('sl_price', 0):.2f}")
        lines.append(f"TP: {execution_result.get('position_data', {}).get('tp_price', 0):.2f}")
        lines.append(f"Size: {execution_result.get('position_data', {}).get('position_size', 0):.2f} lots")
        lines.append(f"Risk: {execution_result.get('risk_amount', 0):,.0f} CZK")
        
        # Signal quality
        lines.append("")
        lines.append("Signal Quality:")
        lines.append(f"  Quality: {signal.get('quality', signal.get('signal_quality', 0)):.1f}")
        lines.append(f"  Confidence: {signal.get('confidence', 0):.1f}%")
        lines.append(f"  R:R Ratio: {signal.get('risk_reward_ratio', 0):.2f}")
        
        # Market context
        lines.append("")
        lines.append("Market Context:")
        lines.append(f"  Regime: {context.get('regime', 'UNKNOWN')}")
        lines.append(f"  Trend Direction: {context.get('trend_direction', 'UNKNOWN')}")
        lines.append(f"  ADX: {context.get('adx', 0):.1f}")
        lines.append(f"  ATR: {signal.get('atr', 0):.2f}")
        
        # Patterns
        patterns = signal.get('patterns', [])
        if patterns:
            lines.append("")
            lines.append("Patterns:")
            for pattern in patterns:
                lines.append(f"  - {pattern}")
        
        # Structure breaks
        structure_break = signal.get('structure_break')
        if structure_break:
            lines.append("")
            lines.append(f"Structure Break: {structure_break}")
        
        # Microstructure
        lines.append("")
        lines.append("Microstructure:")
        lines.append(f"  Liquidity: {signal.get('liquidity_score', 0):.2f}")
        lines.append(f"  Volume Z-score: {signal.get('volume_zscore', 0):.2f}")
        lines.append(f"  VWAP Distance: {signal.get('vwap_distance_pct', 0):.2f}%")
        lines.append(f"  ORB Triggered: {signal.get('orb_triggered', False)}")
        
        # Swings
        lines.append("")
        lines.append("Swing Context:")
        lines.append(f"  Last High: {signal.get('last_swing_high', 0):.2f}")
        lines.append(f"  Last Low: {signal.get('last_swing_low', 0):.2f}")
        lines.append(f"  Swing Quality: {signal.get('swing_quality_score', 0):.1f}")
        
        # Decision reasons
        reasons = signal.get('reasons', [])
        if reasons:
            lines.append("")
            lines.append("Decision Reasons:")
            for reason in reasons:
                lines.append(f"  - {reason}")
        
        lines.append("=" * 60)
        
        return "\n".join(lines)

