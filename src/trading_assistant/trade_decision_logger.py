"""
Trade Decision Logger - Production Component
Logs every trade decision with full context for later analysis

Part of TAv70 Trading Assistant
"""
import json
import os
from datetime import datetime
from pathlib import Path
import logging
from enum import Enum

logger = logging.getLogger(__name__)


class TradeDecisionLogger:
    """
    Logs trade decisions to JSONL format for analytics

    Each trade is logged with:
    - Signal quality metrics (quality, confidence, RRR)
    - Market context (regime, ATR, trend strength)
    - Decision reasons (categorized)
    - Microstructure factors (liquidity, volume, VWAP, ORB)
    - Pattern and setup classification
    - Risk metrics
    """

    def __init__(self, log_dir=None):
        """
        Initialize logger

        Args:
            log_dir: Directory for log files
                    - If None, uses /config/analytics/logs (HA production)
                    - Can be overridden for testing
        """
        if log_dir is None:
            # Production: Use HA config directory
            log_dir = "/config/analytics/logs"

        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"[TRADE_LOGGER] Initialized - logging to {self.log_dir}")

    def _get_daily_log_file(self) -> Path:
        """
        Get log file path for current date
        Creates daily log files: trade_decisions_2025-10-08.jsonl
        """
        today = datetime.now().strftime('%Y-%m-%d')
        return self.log_dir / f"trade_decisions_{today}.jsonl"

    def log_trade(self, signal: dict, execution_result: dict, context: dict):
        """
        Log trade decision with full context

        Args:
            signal: Signal dict from EdgeDetector
            execution_result: Result from SimpleOrderExecutor
            context: Market context (regime, ADX, swings, balance)
        """
        try:
            # Get today's log file
            log_file = self._get_daily_log_file()
            position_id = execution_result.get('position_id', 'unknown')

            entry = {
                # Identification & matching fields
                "timestamp": datetime.now().isoformat(),
                "position_id": position_id,
                "symbol": signal.get('symbol'),
                "direction": signal.get('direction'),
                "entry_price": signal.get('entry_price'),

                # cTrader matching fields
                "ctrader_symbol": self._map_to_ctrader_symbol(signal.get('symbol')),
                "open_time": datetime.now().isoformat(),
                "volume_lots": execution_result.get('position_data', {}).get('position_size'),

                # SL/TP
                "sl_price": execution_result.get('position_data', {}).get('sl_price'),
                "tp_price": execution_result.get('position_data', {}).get('tp_price'),

                # Signal quality metrics
                "quality": signal.get('quality', signal.get('signal_quality')),
                "confidence": signal.get('confidence'),
                "rrr": signal.get('risk_reward_ratio'),

                # Market context
                "regime": context.get('regime'),
                "atr": signal.get('atr'),
                "trend_strength": context.get('adx'),

                # Decision reasons (human readable + categorized)
                "reasons": self._extract_reasons(signal, context),
                "reason_categories": self._categorize_reasons(signal, context),

                # Microstructure factors
                "microstructure": {
                    "liquidity": signal.get('liquidity_score'),
                    "volume_zscore": signal.get('volume_zscore'),
                    "vwap_distance": signal.get('vwap_distance_pct'),
                    "orb_triggered": signal.get('orb_triggered', False),
                    "high_quality_time": signal.get('high_quality_time', False)
                },

                # Pattern & Setup
                "pattern": self._to_serializable(signal.get('pattern_type', signal.get('signal_type'))),
                "setup_type": self._classify_setup(signal),

                # Risk metrics
                "risk_amount_czk": execution_result.get('position_data', {}).get('risk_amount'),
                "balance_at_entry": context.get('current_balance'),

                # Swing context
                "swing_context": {
                    "last_swing_high": context.get('last_swing_high'),
                    "last_swing_low": context.get('last_swing_low'),
                    "swing_quality": signal.get('swing_quality_score')
                }
            }

            # Write as single line JSON to daily log file
            with open(log_file, 'a') as f:
                f.write(json.dumps(entry) + '\n')

            logger.info(f"[TRADE_LOGGER] ✅ Logged trade: {position_id} ({signal.get('symbol')} {signal.get('direction')}) → {log_file.name}")

        except Exception as e:
            logger.error(f"[TRADE_LOGGER] ❌ Failed to log trade: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def _map_to_ctrader_symbol(self, symbol):
        """Map internal symbol to cTrader export format"""
        mapping = {
            'DAX': 'GER40',
            'NASDAQ': 'US100',
            'DE40': 'GER40',
            'US100': 'US100',
            'GER40': 'GER40'
        }
        return mapping.get(symbol, symbol)

    def _to_serializable(self, value):
        """
        Convert value to JSON-serializable format
        Handles Enum types (like SignalType) by extracting their value
        """
        if isinstance(value, Enum):
            return value.value
        return value

    def _categorize_reasons(self, signal: dict, context: dict) -> dict:
        """
        Categorize reasons for later statistical analysis

        Returns dict with standardized categories:
        - trend_strength: weak/medium/strong
        - microstructure_quality: none/moderate/good/excellent
        - pattern_type: PULLBACK/PIN_BAR/etc
        - orb_status: yes/no
        - vwap_proximity: very_close/close/near/far
        - liquidity_level: low/medium/high
        """
        categories = {
            'trend_strength': 'none',
            'microstructure_quality': 'none',
            'pattern_type': self._to_serializable(signal.get('pattern_type', 'unknown')),
            'orb_status': 'no',
            'vwap_proximity': 'far',
            'liquidity_level': 'low'
        }

        # Trend strength based on ADX (handle None)
        adx = context.get('adx') or 0
        if adx >= 30:
            categories['trend_strength'] = 'strong'
        elif adx >= 25:
            categories['trend_strength'] = 'medium'
        elif adx >= 20:
            categories['trend_strength'] = 'weak'
        else:
            categories['trend_strength'] = 'none'

        # Liquidity level (handle None)
        liquidity = signal.get('liquidity_score') or 0
        if liquidity >= 0.7:
            categories['liquidity_level'] = 'high'
        elif liquidity >= 0.5:
            categories['liquidity_level'] = 'medium'
        else:
            categories['liquidity_level'] = 'low'

        # Microstructure quality based on volume (handle None)
        volume_z = signal.get('volume_zscore') or 0
        if volume_z >= 2.0:
            categories['microstructure_quality'] = 'excellent'
        elif volume_z >= 1.5:
            categories['microstructure_quality'] = 'good'
        elif volume_z >= 1.0:
            categories['microstructure_quality'] = 'moderate'
        else:
            categories['microstructure_quality'] = 'none'

        # ORB status
        if signal.get('orb_triggered'):
            categories['orb_status'] = 'yes'

        # VWAP proximity (handle None)
        vwap_dist = abs(signal.get('vwap_distance_pct') or 1.0)
        if vwap_dist < 0.001:
            categories['vwap_proximity'] = 'very_close'
        elif vwap_dist < 0.003:
            categories['vwap_proximity'] = 'close'
        elif vwap_dist < 0.01:
            categories['vwap_proximity'] = 'near'
        else:
            categories['vwap_proximity'] = 'far'

        return categories

    def _classify_setup(self, signal: dict) -> str:
        """
        Classify the setup type for analysis

        Returns: PULLBACK, PIN_BAR, ENGULFING, INSIDE_BAR, MOMENTUM, OTHER
        """
        pattern = self._to_serializable(signal.get('pattern_type', signal.get('signal_type', '')))
        pattern_upper = str(pattern).upper()

        if 'PULLBACK' in pattern_upper:
            return 'PULLBACK'
        elif 'PIN' in pattern_upper:
            return 'PIN_BAR'
        elif 'ENGULF' in pattern_upper:
            return 'ENGULFING'
        elif 'INSIDE' in pattern_upper:
            return 'INSIDE_BAR'
        elif 'MOMENTUM' in pattern_upper:
            return 'MOMENTUM'
        else:
            return 'OTHER'

    def _extract_reasons(self, signal: dict, context: dict) -> list:
        """
        Extract human-readable reasons for trade decision

        Returns list of strings like:
        ["Pattern: PULLBACK", "Strong trend (ADX=32)", "High liquidity", ...]
        """
        reasons = []

        # Signal type/pattern
        signal_type = self._to_serializable(signal.get('signal_type', signal.get('pattern_type')))
        if signal_type:
            reasons.append(f"Pattern: {signal_type}")

        # Trend
        regime = context.get('regime')
        if regime == 'TREND':
            adx = context.get('adx', 0)
            reasons.append(f"Trend (ADX={adx:.0f})")
        elif regime == 'RANGE':
            reasons.append("Range market")

        # Microstructure factors (handle None values)
        liquidity = signal.get('liquidity_score') or 0
        if liquidity > 0.7:
            reasons.append("High liquidity")

        volume_z = signal.get('volume_zscore') or 0
        if volume_z > 1.5:
            reasons.append(f"High volume (Z={volume_z:.1f})")

        vwap_dist = abs(signal.get('vwap_distance_pct') or 1.0)
        if vwap_dist < 0.003:
            reasons.append("Near VWAP")

        if signal.get('orb_triggered'):
            reasons.append("ORB breakout")

        if signal.get('high_quality_time'):
            reasons.append("High quality time")

        # Quality metrics (handle None values)
        quality = signal.get('quality') or signal.get('signal_quality') or 0
        if quality >= 80:
            reasons.append(f"High quality ({quality}%)")

        confidence = signal.get('confidence') or 0
        if confidence >= 80:
            reasons.append(f"High confidence ({confidence}%)")

        rrr = signal.get('risk_reward_ratio') or 0
        if rrr and rrr >= 2.0:
            reasons.append(f"Good RRR ({rrr:.1f})")

        return reasons
