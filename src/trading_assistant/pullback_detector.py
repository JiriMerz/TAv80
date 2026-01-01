#!/usr/bin/env python3
"""
Pullback Detection for Trending Markets

Detekuje příležitosti k vstupu na pullback proti trendu v silných trendech.
"""

import logging
from typing import List, Dict, Optional, Tuple
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)

class PullbackType(Enum):
    """Typy pullback signálů"""
    RETRACEMENT = "RETRACEMENT"  # Klasický retracement na EMA/podporu
    STRUCTURE = "STRUCTURE"       # Pullback na strukturální level
    FIBO = "FIBO"                # Fibonacci retracement
    VWAP = "VWAP"                # VWAP pullback
    DOUBLE_TOP = "DOUBLE_TOP"    # Double top pattern
    DOUBLE_BOTTOM = "DOUBLE_BOTTOM"  # Double bottom pattern
    HOD = "HOD"                  # Highest of Day
    LOD = "LOD"                  # Lowest of Day

class PullbackQuality(Enum):
    """Kvalita pullback příležitosti"""
    HIGH = "HIGH"      # 80%+ - velmi silný setup
    GOOD = "GOOD"      # 60-79% - dobrý setup
    MEDIUM = "MEDIUM"  # 40-59% - průměrný
    LOW = "LOW"        # <40% - slabý

class PullbackDetector:
    """
    Detects pullback opportunities in trending markets
    """
    
    def __init__(self, config: Dict):
        self.config = config
        
        # Pullback detection parameters
        self.min_trend_strength = config.get('min_trend_strength', 25)  # ADX minimum
        self.max_retracement_pct = config.get('max_retracement_pct', 0.618)  # 61.8% max (Golden Ratio)
        self.min_retracement_pct = config.get('min_retracement_pct', 0.382)  # 38.2% min (standard Fibonacci, best practices for swing trading)
        
        # Structure levels
        self.structure_touch_atr = config.get('structure_touch_atr', 0.5)  # Distance to structure
        self.min_structure_age = config.get('min_structure_age', 5)  # Min bars old
        
        # VWAP parameters  
        self.vwap_touch_distance = config.get('vwap_touch_distance', 0.1)  # % from VWAP
        
        # Quality scoring
        self.confluence_bonus = config.get('confluence_bonus', 15)  # Multi-level confluence
        self.momentum_divergence_bonus = config.get('momentum_divergence_bonus', 20)
        
        # Reversal candlestick pattern detection
        self.reversal_pattern_bonus = config.get('reversal_pattern_bonus', 15)  # Bonus for reversal patterns
        self.pin_bar_ratio = config.get('pin_bar_ratio', 0.3)  # Minimum wick-to-body ratio for pin bars
        self.min_wick_ratio = config.get('min_wick_ratio', 0.6)  # Minimum wick-to-range ratio for hammer/shooting star
        
        self.app = None  # Will be set by caller
        
    def detect_pullback_opportunity(self, 
                                    bars: List[Dict], 
                                    regime_state: Dict,
                                    swing_state: Dict,
                                    pivot_levels: Dict,
                                    microstructure_data: Dict = None) -> Optional[Dict]:
        """
        Hlavní metoda pro detekci pullback příležitostí
        
        Args:
            bars: OHLC data
            regime_state: Market regime info (trend direction, ADX, etc.)
            swing_state: Swing analysis data
            pivot_levels: Support/resistance levels
            microstructure_data: Microstructure analysis
            
        Returns:
            Dict with pullback opportunity or None
        """
        current_price = bars[-1]['close'] if bars else 0
        
        if len(bars) < 20:
            logger.info(f"[PULLBACK] ⛔ Insufficient bars ({len(bars)} < 20)")
            return None
            
        # Check if we're in a strong trend
        trend_strength = regime_state.get('adx', 0)
        trend_direction = regime_state.get('trend_direction')
        
        logger.info(f"[PULLBACK] Checking: price={current_price:.2f}, ADX={trend_strength:.1f}, trend={trend_direction}")
        
        if trend_strength < self.min_trend_strength:
            logger.info(f"[PULLBACK] ⛔ Weak trend (ADX {trend_strength:.1f} < {self.min_trend_strength})")
            return None
            
        if not trend_direction or trend_direction == 'SIDEWAYS':
            logger.info(f"[PULLBACK] ⛔ No trend direction ({trend_direction})")
            return None
            
        # Detect active pullback
        pullback_analysis = self._analyze_pullback_state(bars, trend_direction)
        if not pullback_analysis:
            logger.info(f"[PULLBACK] ⛔ No active pullback detected (price not retracing from swing extreme)")
            return None
        
        logger.info(f"[PULLBACK] ✅ Active pullback: retracement={pullback_analysis['retracement_pct']:.1f}%")
        
        # Check for reversal candlestick pattern (indicates pullback bottom)
        reversal_pattern = self._detect_reversal_candlestick(bars, trend_direction)
        if reversal_pattern:
            logger.info(f"[PULLBACK] ✅ Reversal pattern detected: {reversal_pattern['pattern']} ({reversal_pattern['strength']})")
        else:
            logger.info(f"[PULLBACK] ⚠️ No reversal pattern detected - pullback may not be complete")
            
        # Find entry levels
        entry_levels = self._find_pullback_entry_levels(
            bars, trend_direction, pivot_levels, microstructure_data
        )
        
        if not entry_levels:
            return None
            
        # Calculate quality score
        quality_score = self._calculate_pullback_quality(
            pullback_analysis, entry_levels, bars, trend_direction, 
            regime_state, microstructure_data, reversal_pattern
        )
        
        # Select best entry level
        best_entry = self._select_best_entry_level(entry_levels, current_price, trend_direction)
        
        if quality_score < 40:  # Minimum quality threshold
            return None
            
        return {
            'type': 'PULLBACK',
            'trend_direction': trend_direction,
            'signal_direction': 'SELL' if trend_direction == 'DOWN' else 'BUY',
            'entry_price': best_entry['price'],
            'entry_reason': best_entry['reason'],
            'quality_score': quality_score,
            'pullback_type': best_entry.get('pullback_type', PullbackType.RETRACEMENT),
            'pullback_analysis': pullback_analysis,
            'confluence_levels': len(entry_levels),
            'trend_strength': trend_strength,
            'retracement_pct': pullback_analysis.get('retracement_pct', 0),
            'reversal_pattern': reversal_pattern  # Add reversal pattern info
        }
        
    def _analyze_pullback_state(self, bars: List[Dict], trend_direction: str) -> Optional[Dict]:
        """Analyzuje, zda právě probíhá pullback"""
        if len(bars) < 10:
            return None
            
        current_price = bars[-1]['close']
        
        # Find recent swing extreme (start of pullback)
        swing_extreme = self._find_recent_swing_extreme(bars, trend_direction)
        if not swing_extreme:
            logger.info(f"[PULLBACK_STATE] ⛔ No swing extreme found")
            return None
            
        # Calculate retracement percentage
        if trend_direction == 'DOWN':
            # In downtrend, looking for bounce (pullback up)
            pullback_start = swing_extreme['low']
            current_retracement = (current_price - pullback_start) / pullback_start
            
            logger.info(f"[PULLBACK_STATE] DOWNTREND: swing_low={pullback_start:.2f}, price={current_price:.2f}, retr={current_retracement*100:.1f}%")
            
            # Check if we're actually in a pullback (price moved up from low)
            if current_price <= pullback_start:
                logger.info(f"[PULLBACK_STATE] ⛔ Price {current_price:.2f} <= swing_low {pullback_start:.2f} (no pullback yet)")
                return None
                
        else:  # UP trend
            # In uptrend, looking for dip (pullback down)  
            pullback_start = swing_extreme['high']
            current_retracement = (pullback_start - current_price) / pullback_start
            
            logger.info(f"[PULLBACK_STATE] UPTREND: swing_high={pullback_start:.2f}, price={current_price:.2f}, retr={current_retracement*100:.1f}%")
            
            # Check if we're actually in a pullback (price moved down from high)
            if current_price >= pullback_start:
                logger.info(f"[PULLBACK_STATE] ⛔ Price {current_price:.2f} >= swing_high {pullback_start:.2f} (at/above high, no pullback)")
                return None
        
        # Check retracement is within reasonable bounds
        min_pct = self.min_retracement_pct * 100
        max_pct = self.max_retracement_pct * 100
        retr_pct = current_retracement * 100
        
        if current_retracement < self.min_retracement_pct:
            logger.info(f"[PULLBACK_STATE] ⛔ Retracement too small: {retr_pct:.1f}% < {min_pct:.1f}%")
            return None
            
        if current_retracement > self.max_retracement_pct:
            logger.info(f"[PULLBACK_STATE] ⛔ Retracement too large: {retr_pct:.1f}% > {max_pct:.1f}%")
            return None
        
        logger.info(f"[PULLBACK_STATE] ✅ Valid pullback: {retr_pct:.1f}% (range {min_pct:.1f}%-{max_pct:.1f}%)")
            
        return {
            'pullback_start_price': pullback_start,
            'pullback_start_bar': swing_extreme['bar_index'],
            'current_retracement': current_retracement,
            'retracement_pct': current_retracement * 100,
            'bars_in_pullback': len(bars) - swing_extreme['bar_index'],
            'trend_direction': trend_direction
        }
        
    def _find_recent_swing_extreme(self, bars: List[Dict], trend_direction: str) -> Optional[Dict]:
        """Najde poslední swing high/low (začátek pullback)"""
        lookback = min(20, len(bars) - 5)  # Look back max 20 bars
        
        if trend_direction == 'DOWN':
            # Find recent swing low
            min_low = float('inf')
            min_idx = -1
            
            for i in range(len(bars) - lookback, len(bars) - 2):  # Don't include last 2 bars
                if bars[i]['low'] < min_low:
                    min_low = bars[i]['low']
                    min_idx = i
                    
            if min_idx != -1:
                return {'low': min_low, 'bar_index': min_idx}
                
        else:  # UP trend
            # Find recent swing high
            max_high = 0
            max_idx = -1
            
            for i in range(len(bars) - lookback, len(bars) - 2):
                if bars[i]['high'] > max_high:
                    max_high = bars[i]['high']
                    max_idx = i
                    
            if max_idx != -1:
                return {'high': max_high, 'bar_index': max_idx}
                
        return None
        
    def _find_pullback_entry_levels(self, 
                                    bars: List[Dict], 
                                    trend_direction: str,
                                    pivot_levels: Dict,
                                    microstructure_data: Dict = None) -> List[Dict]:
        """Najde možné vstupní levely pro pullback"""
        entry_levels = []
        current_price = bars[-1]['close']
        
        # 1. Fibonacci retracement levels
        fib_levels = self._calculate_fibonacci_levels(bars, trend_direction)
        for fib in fib_levels:
            entry_levels.append({
                'price': fib['price'],
                'reason': f"Fibonacci {fib['level']}%",
                'pullback_type': PullbackType.FIBO,
                'strength': fib['strength']
            })
            
        # 2. Structural levels (pivot points)
        if pivot_levels:
            for level_name, level_price in pivot_levels.items():
                if self._is_level_relevant_for_pullback(level_price, current_price, trend_direction):
                    entry_levels.append({
                        'price': level_price,
                        'reason': f"Pivot {level_name}",
                        'pullback_type': PullbackType.STRUCTURE,
                        'strength': self._calculate_structure_strength(level_name)
                    })
                    
        # 3. VWAP levels
        if microstructure_data:
            vwap_price = microstructure_data.get('vwap_price')
            if (vwap_price and 
                self._is_level_relevant_for_pullback(vwap_price, current_price, trend_direction)):
                entry_levels.append({
                    'price': vwap_price,
                    'reason': "VWAP retest",
                    'pullback_type': PullbackType.VWAP,
                    'strength': 75  # VWAP is generally strong
                })
                
        # 4. Moving average levels (EMA 21, 50)
        ema_levels = self._calculate_ema_levels(bars, trend_direction)
        for ema in ema_levels:
            entry_levels.append({
                'price': ema['price'],
                'reason': f"EMA {ema['period']}",
                'pullback_type': PullbackType.RETRACEMENT,
                'strength': ema['strength']
            })
        
        # 5. Double Top/Bottom patterns
        double_patterns = self._detect_double_top_bottom(bars, trend_direction)
        for pattern in double_patterns:
            entry_levels.append({
                'price': pattern['price'],
                'reason': f"{pattern['type']} pattern",
                'pullback_type': PullbackType.DOUBLE_TOP if pattern['type'] == 'DOUBLE_TOP' else PullbackType.DOUBLE_BOTTOM,
                'strength': pattern['strength']
            })
        
        # 6. HOD/LOD (Highest/Lowest of Day)
        hod_lod_levels = self._calculate_hod_lod_levels(bars, trend_direction)
        for level in hod_lod_levels:
            entry_levels.append({
                'price': level['price'],
                'reason': f"{level['type']} (intraday)",
                'pullback_type': PullbackType.HOD if level['type'] == 'HOD' else PullbackType.LOD,
                'strength': level['strength']
            })
            
        # Filter levels too close to current price or outside reasonable range
        filtered_levels = []
        atr = self._calculate_atr(bars[-14:])  # 14-period ATR
        
        for level in entry_levels:
            distance = abs(level['price'] - current_price)
            if distance > atr * 0.5:  # At least 0.5 ATR away
                if self._is_price_in_pullback_zone(level['price'], current_price, trend_direction):
                    filtered_levels.append(level)
                    
        return filtered_levels
        
    def _calculate_fibonacci_levels(self, bars: List[Dict], trend_direction: str) -> List[Dict]:
        """Calculate Fibonacci retracement levels"""
        levels = []
        
        if len(bars) < 20:
            return levels
            
        # Find swing high and low for Fibonacci calculation
        lookback = min(50, len(bars))
        recent_bars = bars[-lookback:]
        
        if trend_direction == 'DOWN':
            swing_high = max(bar['high'] for bar in recent_bars)
            swing_low = min(bar['low'] for bar in recent_bars[-10:])  # Recent low
        else:
            swing_low = min(bar['low'] for bar in recent_bars)
            swing_high = max(bar['high'] for bar in recent_bars[-10:])  # Recent high
            
        swing_range = abs(swing_high - swing_low)
        
        # Standard Fibonacci levels
        fib_ratios = [
            (23.6, 0.236, 60),   # (level%, ratio, strength)
            (38.2, 0.382, 75),
            (50.0, 0.500, 70),
            (61.8, 0.618, 85),   # Golden ratio - strongest
            (78.6, 0.786, 65)
        ]
        
        for level_pct, ratio, strength in fib_ratios:
            if trend_direction == 'DOWN':
                fib_price = swing_low + (swing_range * ratio)
            else:
                fib_price = swing_high - (swing_range * ratio)
                
            levels.append({
                'price': fib_price,
                'level': level_pct,
                'strength': strength
            })
            
        return levels
        
    def _calculate_ema_levels(self, bars: List[Dict], trend_direction: str) -> List[Dict]:
        """Calculate EMA support/resistance levels"""
        levels = []
        
        if len(bars) < 50:
            return levels
            
        # Calculate EMAs
        ema21 = self._ema(bars, 21)
        ema50 = self._ema(bars, 50)
        
        current_price = bars[-1]['close']
        
        # Check if EMAs are relevant for pullback
        if trend_direction == 'DOWN':
            # In downtrend, EMAs should be above current price (resistance)
            if ema21 > current_price:
                levels.append({'price': ema21, 'period': 21, 'strength': 70})
            if ema50 > current_price:
                levels.append({'price': ema50, 'period': 50, 'strength': 75})
        else:
            # In uptrend, EMAs should be below current price (support)
            if ema21 < current_price:
                levels.append({'price': ema21, 'period': 21, 'strength': 70})
            if ema50 < current_price:
                levels.append({'price': ema50, 'period': 50, 'strength': 75})
                
        return levels
        
    def _ema(self, bars: List[Dict], period: int) -> float:
        """Calculate Exponential Moving Average"""
        if len(bars) < period:
            return sum(bar['close'] for bar in bars) / len(bars)
            
        multiplier = 2 / (period + 1)
        ema = sum(bar['close'] for bar in bars[:period]) / period
        
        for bar in bars[period:]:
            ema = (bar['close'] * multiplier) + (ema * (1 - multiplier))
            
        return ema
        
    def _calculate_atr(self, bars: List[Dict]) -> float:
        """Calculate Average True Range"""
        if len(bars) < 2:
            return 0
            
        true_ranges = []
        for i in range(1, len(bars)):
            high = bars[i]['high']
            low = bars[i]['low']
            prev_close = bars[i-1]['close']
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)
            
        return sum(true_ranges) / len(true_ranges)
        
    def _is_level_relevant_for_pullback(self, level_price: float, current_price: float, trend_direction: str) -> bool:
        """Check if level is relevant for pullback entry"""
        if trend_direction == 'DOWN':
            # In downtrend pullback, we want resistance levels above current price
            return level_price > current_price
        else:
            # In uptrend pullback, we want support levels below current price
            return level_price < current_price
            
    def _is_price_in_pullback_zone(self, target_price: float, current_price: float, trend_direction: str) -> bool:
        """Check if target price is in reasonable pullback zone"""
        if trend_direction == 'DOWN':
            # Price should be above current but not too far (max 5% pullback)
            return current_price < target_price < current_price * 1.05
        else:
            # Price should be below current but not too far (max 5% pullback)
            return current_price * 0.95 < target_price < current_price
            
    def _calculate_structure_strength(self, level_name: str) -> int:
        """Calculate strength score for structural levels"""
        strength_map = {
            'R2': 60, 'R1': 70, 'PIVOT': 85, 'S1': 70, 'S2': 60,
            'weekly_high': 80, 'weekly_low': 80,
            'daily_high': 75, 'daily_low': 75
        }
        return strength_map.get(level_name, 65)
        
    def _detect_reversal_candlestick(self, bars: List[Dict], trend_direction: str) -> Optional[Dict]:
        """
        Detekuje reversal svíčkové formace indikující dno pullbacku
        
        Pro UPTREND pullback (hledáme dno): bullish reversal patterns
        - Hammer (dlouhý dolní knot, malé tělo)
        - Bullish Engulfing
        - Pin bar s dlouhým dolním knotem
        - Doji (může signalizovat obrat)
        
        Pro DOWNTREND pullback (hledáme vrchol): bearish reversal patterns
        - Shooting Star (dlouhý horní knot, malé tělo)
        - Bearish Engulfing
        - Pin bar s dlouhým horním knotem
        - Doji
        
        Returns:
            Dict s pattern informací nebo None
        """
        if len(bars) < 2:
            return None
        
        current_bar = bars[-1]
        prev_bar = bars[-2] if len(bars) >= 2 else None
        
        # Calculate bar components
        body = abs(current_bar['close'] - current_bar['open'])
        total_range = current_bar['high'] - current_bar['low']
        upper_wick = current_bar['high'] - max(current_bar['close'], current_bar['open'])
        lower_wick = min(current_bar['close'], current_bar['open']) - current_bar['low']
        
        if total_range == 0:
            return None
        
        body_ratio = body / total_range if total_range > 0 else 0
        upper_wick_ratio = upper_wick / total_range if total_range > 0 else 0
        lower_wick_ratio = lower_wick / total_range if total_range > 0 else 0
        
        is_bullish = current_bar['close'] > current_bar['open']
        
        if trend_direction == 'UP':
            # UPTREND pullback: hledáme bullish reversal (dno pullbacku)
            
            # 1. Hammer pattern (dlouhý dolní knot, malé tělo)
            if (lower_wick_ratio >= self.min_wick_ratio and 
                body_ratio < 0.4 and 
                upper_wick_ratio < lower_wick_ratio * 0.5):
                strength = 'HIGH' if lower_wick_ratio >= 0.7 else 'MEDIUM'
                logger.info(f"[REVERSAL] Hammer detected (lower_wick={lower_wick_ratio:.1%}, body={body_ratio:.1%})")
                return {
                    'pattern': 'HAMMER',
                    'direction': 'bullish',
                    'strength': strength,
                    'confidence': 85 if strength == 'HIGH' else 70
                }
            
            # 2. Pin bar s dlouhým dolním knotem
            if (lower_wick >= body * self.pin_bar_ratio and 
                lower_wick > upper_wick * 1.5 and 
                lower_wick_ratio >= 0.5):
                logger.info(f"[REVERSAL] Bullish Pin Bar detected (lower_wick={lower_wick_ratio:.1%})")
                return {
                    'pattern': 'PIN_BAR',
                    'direction': 'bullish',
                    'strength': 'HIGH' if lower_wick_ratio >= 0.7 else 'MEDIUM',
                    'confidence': 80
                }
            
            # 3. Bullish Engulfing
            if prev_bar:
                prev_body = abs(prev_bar['close'] - prev_bar['open'])
                prev_is_bearish = prev_bar['close'] < prev_bar['open']
                
                if (prev_is_bearish and is_bullish and
                    body > prev_body * 0.9 and
                    current_bar['close'] > prev_bar['open'] and
                    current_bar['open'] < prev_bar['close']):
                    logger.info(f"[REVERSAL] Bullish Engulfing detected")
                    return {
                        'pattern': 'ENGULFING',
                        'direction': 'bullish',
                        'strength': 'HIGH',
                        'confidence': 85
                    }
            
            # 4. Doji (možný obrat)
            if body_ratio < 0.1:  # Velmi malé tělo
                logger.info(f"[REVERSAL] Doji detected (possible reversal)")
                return {
                    'pattern': 'DOJI',
                    'direction': 'neutral',
                    'strength': 'LOW',
                    'confidence': 50
                }
                
        else:  # DOWNTREND
            # DOWNTREND pullback: hledáme bearish reversal (vrchol pullbacku)
            
            # 1. Shooting Star (dlouhý horní knot, malé tělo)
            if (upper_wick_ratio >= self.min_wick_ratio and 
                body_ratio < 0.4 and 
                lower_wick_ratio < upper_wick_ratio * 0.5):
                strength = 'HIGH' if upper_wick_ratio >= 0.7 else 'MEDIUM'
                logger.info(f"[REVERSAL] Shooting Star detected (upper_wick={upper_wick_ratio:.1%}, body={body_ratio:.1%})")
                return {
                    'pattern': 'SHOOTING_STAR',
                    'direction': 'bearish',
                    'strength': strength,
                    'confidence': 85 if strength == 'HIGH' else 70
                }
            
            # 2. Pin bar s dlouhým horním knotem
            if (upper_wick >= body * self.pin_bar_ratio and 
                upper_wick > lower_wick * 1.5 and 
                upper_wick_ratio >= 0.5):
                logger.info(f"[REVERSAL] Bearish Pin Bar detected (upper_wick={upper_wick_ratio:.1%})")
                return {
                    'pattern': 'PIN_BAR',
                    'direction': 'bearish',
                    'strength': 'HIGH' if upper_wick_ratio >= 0.7 else 'MEDIUM',
                    'confidence': 80
                }
            
            # 3. Bearish Engulfing
            if prev_bar:
                prev_body = abs(prev_bar['close'] - prev_bar['open'])
                prev_is_bullish = prev_bar['close'] > prev_bar['open']
                
                if (prev_is_bullish and not is_bullish and
                    body > prev_body * 0.9 and
                    current_bar['close'] < prev_bar['open'] and
                    current_bar['open'] > prev_bar['close']):
                    logger.info(f"[REVERSAL] Bearish Engulfing detected")
                    return {
                        'pattern': 'ENGULFING',
                        'direction': 'bearish',
                        'strength': 'HIGH',
                        'confidence': 85
                    }
            
            # 4. Doji (možný obrat)
            if body_ratio < 0.1:  # Velmi malé tělo
                logger.info(f"[REVERSAL] Doji detected (possible reversal)")
                return {
                    'pattern': 'DOJI',
                    'direction': 'neutral',
                    'strength': 'LOW',
                    'confidence': 50
                }
        
        return None
    
    def _calculate_pullback_quality(self, 
                                    pullback_analysis: Dict,
                                    entry_levels: List[Dict],
                                    bars: List[Dict],
                                    trend_direction: str,
                                    regime_state: Dict,
                                    microstructure_data: Dict = None,
                                    reversal_pattern: Optional[Dict] = None) -> int:
        """Calculate overall quality score for pullback opportunity"""
        base_score = 40
        
        # Trend strength bonus
        adx = regime_state.get('adx', 0)
        if adx > 35:
            base_score += 20
        elif adx > 25:
            base_score += 10
            
        # Pullback depth bonus (ideal 38.2-61.8%)
        retracement = pullback_analysis.get('current_retracement', 0)
        if 0.35 < retracement < 0.65:
            base_score += 15
        elif 0.25 < retracement < 0.75:
            base_score += 8
            
        # Multiple confluence levels bonus
        # Pivot pointy mají vyšší váhu v confluence
        pivot_levels_count = sum(1 for level in entry_levels if level.get('pullback_type') == PullbackType.STRUCTURE)
        confluence_count = len(entry_levels)
        confluence_bonus = 0
        
        if confluence_count >= 3:
            confluence_bonus = self.confluence_bonus
        elif confluence_count >= 2:
            confluence_bonus = self.confluence_bonus // 2
        
        # Extra bonus pokud jsou v confluence pivot pointy
        if pivot_levels_count >= 2:
            confluence_bonus += 10  # Extra bonus pro pivot confluence
            if self.app:
                self.app.log(f"[PULLBACK] Pivot confluence detected ({pivot_levels_count} pivots), +10 extra bonus")
        elif pivot_levels_count == 1:
            confluence_bonus += 5  # Menší bonus pro jeden pivot
            if self.app:
                self.app.log(f"[PULLBACK] Single pivot in confluence, +5 extra bonus")
        
        base_score += confluence_bonus
            
        # High-strength levels bonus
        avg_strength = sum(level.get('strength', 50) for level in entry_levels) / max(1, len(entry_levels))
        if avg_strength > 75:
            base_score += 10
        elif avg_strength > 65:
            base_score += 5
            
        # Microstructure bonus
        if microstructure_data:
            liquidity = microstructure_data.get('liquidity_score', 0.5)
            if liquidity > 0.6:
                base_score += 8
                
            quality_time = microstructure_data.get('is_high_quality_time', False)
            if quality_time:
                base_score += 5
                
        # Volume analysis bonus (if available)
        recent_volume = self._analyze_pullback_volume(bars, pullback_analysis)
        if recent_volume == 'decreasing':  # Pullback on decreasing volume is good
            base_score += 8
        
        # Reversal candlestick pattern bonus (indicates pullback bottom)
        if reversal_pattern:
            pattern_strength = reversal_pattern.get('strength', 'LOW')
            confidence = reversal_pattern.get('confidence', 50)
            
            # Strong patterns get higher bonus
            if pattern_strength == 'HIGH':
                base_score += self.reversal_pattern_bonus
                if self.app:
                    self.app.log(f"[PULLBACK] Strong reversal pattern ({reversal_pattern.get('pattern')}) bonus: +{self.reversal_pattern_bonus}")
            elif pattern_strength == 'MEDIUM':
                base_score += self.reversal_pattern_bonus // 2
                if self.app:
                    self.app.log(f"[PULLBACK] Medium reversal pattern ({reversal_pattern.get('pattern')}) bonus: +{self.reversal_pattern_bonus // 2}")
            else:  # LOW (e.g., Doji)
                base_score += 5
                if self.app:
                    self.app.log(f"[PULLBACK] Weak reversal pattern ({reversal_pattern.get('pattern')}) bonus: +5")
        else:
            # No reversal pattern - penalize slightly (pullback may not be complete)
            base_score -= 5
            if self.app:
                self.app.log(f"[PULLBACK] No reversal pattern detected - penalty: -5")
            
        return min(100, max(0, base_score))
        
    def _analyze_pullback_volume(self, bars: List[Dict], pullback_analysis: Dict) -> str:
        """Analyze volume behavior during pullback"""
        pullback_start_idx = pullback_analysis.get('pullback_start_bar', len(bars) - 5)
        
        if pullback_start_idx >= len(bars) - 2:
            return 'unknown'
            
        # Compare recent volume to volume during trend move
        pullback_bars = bars[pullback_start_idx:]
        trend_bars = bars[max(0, pullback_start_idx - 10):pullback_start_idx]
        
        if not pullback_bars or not trend_bars:
            return 'unknown'
            
        avg_pullback_volume = sum(bar.get('volume', 1) for bar in pullback_bars) / len(pullback_bars)
        avg_trend_volume = sum(bar.get('volume', 1) for bar in trend_bars) / len(trend_bars)
        
        if avg_pullback_volume < avg_trend_volume * 0.8:
            return 'decreasing'  # Good for continuation
        elif avg_pullback_volume > avg_trend_volume * 1.2:
            return 'increasing'  # Might signal reversal
        else:
            return 'stable'
            
    def _select_best_entry_level(self, entry_levels: List[Dict], current_price: float, trend_direction: str) -> Dict:
        """Select the best entry level from available options"""
        if not entry_levels:
            return None
            
        # Score each level based on multiple factors
        scored_levels = []
        
        for level in entry_levels:
            score = level.get('strength', 50)
            
            # Distance bonus - closer levels get slight penalty (too close might not trigger)
            distance = abs(level['price'] - current_price)
            distance_ratio = distance / current_price
            
            if 0.005 < distance_ratio < 0.02:  # 0.5% - 2% distance is ideal
                score += 10
            elif distance_ratio < 0.005:  # Too close
                score -= 5
            elif distance_ratio > 0.05:  # Too far
                score -= 10
                
            # Bonus for high-probability setups
            if level['pullback_type'] == PullbackType.FIBO and '61.8' in level['reason']:
                score += 15  # Golden ratio bonus
            elif level['pullback_type'] == PullbackType.VWAP:
                score += 10  # VWAP is dynamic and reliable
            elif level['pullback_type'] in [PullbackType.DOUBLE_TOP, PullbackType.DOUBLE_BOTTOM]:
                score += 12  # Double top/bottom are strong S/R levels
            elif level['pullback_type'] in [PullbackType.HOD, PullbackType.LOD]:
                score += 8  # HOD/LOD are important intraday levels
                
            scored_levels.append((score, level))
            
        # Return highest scoring level
        scored_levels.sort(reverse=True)
        return scored_levels[0][1]
    
    def _detect_double_top_bottom(self, bars: List[Dict], trend_direction: str) -> List[Dict]:
        """
        Detekuje double top/bottom patterny
        
        Double Top: Dva podobné highy s poklesem mezi nimi
        Double Bottom: Dva podobné lowy s růstem mezi nimi
        
        Returns:
            List of pattern dicts with price and strength
        """
        patterns = []
        
        if len(bars) < 30:
            return patterns
        
        atr = self._calculate_atr(bars[-20:])
        tolerance = atr * 0.3  # 30% ATR tolerance pro podobnost
        
        # Look for double top (resistance level)
        if trend_direction == 'UP':
            # V uptrendu hledáme double top jako resistance pro pullback
            highs = []
            for i in range(len(bars) - 30, len(bars) - 5):
                # Check if this is a local high
                is_local_high = True
                for j in range(max(0, i - 5), min(len(bars), i + 5)):
                    if j != i and bars[j]['high'] >= bars[i]['high']:
                        is_local_high = False
                        break
                
                if is_local_high:
                    highs.append({
                        'index': i,
                        'price': bars[i]['high'],
                        'bar': bars[i]
                    })
            
            # Find two similar highs
            for i in range(len(highs) - 1):
                for j in range(i + 1, len(highs)):
                    price_diff = abs(highs[i]['price'] - highs[j]['price'])
                    if price_diff <= tolerance:
                        # Check if there's a pullback between them
                        min_between = min(b['low'] for b in bars[highs[i]['index']:highs[j]['index']])
                        pullback_depth = (highs[i]['price'] - min_between) / highs[i]['price']
                        
                        if pullback_depth > 0.01:  # At least 1% pullback
                            # Double top found
                            avg_price = (highs[i]['price'] + highs[j]['price']) / 2
                            patterns.append({
                                'type': 'DOUBLE_TOP',
                                'price': avg_price,
                                'strength': 80,  # Strong resistance level
                                'first_high': highs[i]['price'],
                                'second_high': highs[j]['price'],
                                'pullback_depth': pullback_depth
                            })
                            break
        
        # Look for double bottom (support level)
        elif trend_direction == 'DOWN':
            # V downtrendu hledáme double bottom jako support pro pullback
            lows = []
            for i in range(len(bars) - 30, len(bars) - 5):
                # Check if this is a local low
                is_local_low = True
                for j in range(max(0, i - 5), min(len(bars), i + 5)):
                    if j != i and bars[j]['low'] <= bars[i]['low']:
                        is_local_low = False
                        break
                
                if is_local_low:
                    lows.append({
                        'index': i,
                        'price': bars[i]['low'],
                        'bar': bars[i]
                    })
            
            # Find two similar lows
            for i in range(len(lows) - 1):
                for j in range(i + 1, len(lows)):
                    price_diff = abs(lows[i]['price'] - lows[j]['price'])
                    if price_diff <= tolerance:
                        # Check if there's a pullback between them
                        max_between = max(b['high'] for b in bars[lows[i]['index']:lows[j]['index']])
                        pullback_depth = (max_between - lows[i]['price']) / lows[i]['price']
                        
                        if pullback_depth > 0.01:  # At least 1% pullback
                            # Double bottom found
                            avg_price = (lows[i]['price'] + lows[j]['price']) / 2
                            patterns.append({
                                'type': 'DOUBLE_BOTTOM',
                                'price': avg_price,
                                'strength': 80,  # Strong support level
                                'first_low': lows[i]['price'],
                                'second_low': lows[j]['price'],
                                'pullback_depth': pullback_depth
                            })
                            break
        
        return patterns
    
    def _calculate_hod_lod_levels(self, bars: List[Dict], trend_direction: str) -> List[Dict]:
        """
        Vypočítá HOD (Highest of Day) a LOD (Lowest of Day) levely
        
        HOD/LOD jsou důležité intraday levely, které mohou sloužit jako support/resistance
        """
        levels = []
        
        if len(bars) < 10:
            return levels
        
        # Find today's bars (assuming bars are sorted by time)
        # For M5 timeframe, look at last ~288 bars (24 hours)
        lookback = min(288, len(bars))
        today_bars = bars[-lookback:]
        
        if not today_bars:
            return levels
        
        # Calculate HOD and LOD
        hod = max(b['high'] for b in today_bars)
        lod = min(b['low'] for b in today_bars)
        
        current_price = bars[-1]['close']
        atr = self._calculate_atr(bars[-14:])
        
        # HOD level (resistance)
        if trend_direction == 'UP':
            # V uptrendu může být HOD relevantní pro pullback (pokud cena je pod HOD)
            if current_price < hod and (hod - current_price) <= atr * 2:
                levels.append({
                    'type': 'HOD',
                    'price': hod,
                    'strength': 75,  # Strong intraday resistance
                    'distance_pct': ((hod - current_price) / current_price) * 100
                })
        
        # LOD level (support)
        if trend_direction == 'DOWN':
            # V downtrendu může být LOD relevantní pro pullback (pokud cena je nad LOD)
            if current_price > lod and (current_price - lod) <= atr * 2:
                levels.append({
                    'type': 'LOD',
                    'price': lod,
                    'strength': 75,  # Strong intraday support
                    'distance_pct': ((current_price - lod) / current_price) * 100
                })
        
        return levels