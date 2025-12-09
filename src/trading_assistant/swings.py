"""
Swings Detection Engine Module - NO NUMPY VERSION
Sprint 1: ZigZag with ATR-adaptive thresholds and quality metrics
Fixed version without NumPy dependency
25-08-28 19:05
"""

from typing import List, Dict, Optional
from dataclasses import dataclass
from enum import Enum
import logging
import math

logger = logging.getLogger(__name__)


class SwingType(Enum):
    """Types of swing points"""
    HIGH = "HIGH"
    LOW = "LOW"


class TrendDirection(Enum):
    """Trend direction based on swing sequence"""
    UP = "UP"  # HH-HL pattern
    DOWN = "DOWN"  # LL-LH pattern
    SIDEWAYS = "SIDEWAYS"  # Mixed pattern


@dataclass
class SwingPoint:
    """Individual swing point with metadata"""
    index: int  # Bar index
    price: float
    type: SwingType
    timestamp: str
    amplitude: float  # Distance from previous swing
    amplitude_atr: float  # Amplitude in ATR units
    bars_from_prev: int  # Bars since previous swing
    # NEW: Pivot and round number confluence data
    pivot_confluence: Optional[Dict] = None
    round_confluence: Optional[Dict] = None
    

@dataclass
class SwingState:
    """Current state of swing structure"""
    swings: List[SwingPoint]
    last_high: Optional[SwingPoint]
    last_low: Optional[SwingPoint]
    trend: TrendDirection
    swing_quality: float  # 0-100 quality score
    last_impulse_atr: float  # Last impulse move in ATR
    rotation_count: int  # Number of alternating swings
    cleanliness: float  # How clean the swings are (0-100)


class SwingEngine:
    """
    ZigZag-based swing detection with ATR adaptation
    Calculates swing quality metrics for trade filtering
    """
    
    def __init__(self, config: Dict = None, pivot_calculator=None):
        """
        Initialize swing engine s upravenými defaulty
        
        Args:
            config: Swing configuration
            pivot_calculator: Optional PivotCalculator for enhanced validation
        """
        self.config = config or {}
        self.pivot_calculator = pivot_calculator
        
        # ZigZag parameters - upravené pro lepší detekci
        self.atr_multiplier_m1 = self.config.get('atr_multiplier_m1', 0.5)  # Sníženo z 0.8
        self.atr_multiplier_m5 = self.config.get('atr_multiplier_m5', 0.8)  # Sníženo z 1.0
        self.min_bars_between = self.config.get('min_bars_between', 3)  # Sníženo z 8
        self.min_swing_quality = self.config.get('min_swing_quality', 20)  # Sníženo z 60
        
        # ATR calculation period
        self.atr_period = self.config.get('atr_period', 10)
        
        # Timeframe-specific configs
        self.timeframe_config = {
            'M1': {
                'min_swings_for_trend': 2,
                'min_swings_for_quality': 2,
                'default_quality': 30
            },
            'M5': {
                'min_swings_for_trend': 3,
                'min_swings_for_quality': 3,
                'default_quality': 25
            },
            'M15': {
                'min_swings_for_trend': 4,
                'min_swings_for_quality': 4,
                'default_quality': 20
            }
        }
    
        # Pivot-enhanced swing detection parameters
        self.pivot_confluence_atr = self.config.get('pivot_confluence_atr', 0.3)  # ATR distance for pivot confluence
        self.pivot_validation_weight = self.config.get('pivot_validation_weight', 1.2)  # Quality boost multiplier
        self.use_pivot_validation = self.config.get('use_pivot_validation', True)
        
        # State storage
        self.current_state: Optional[SwingState] = None
        self.current_atr: float = 0
        
    def detect_swings(self, bars: List[Dict], timeframe: str = "M1") -> SwingState:
        """
        Main swing detection method - upravená pro flexibilnější detekci
        """
        logger.info(f"[SWING] Starting swing detection with {len(bars)} bars, timeframe: {timeframe}")
        
        # Získat konfiguraci pro timeframe
        tf_config = self.timeframe_config.get(timeframe, self.timeframe_config['M5'])
        
        # Minimální počet barů podle timeframu
        min_bars = 5 if timeframe == "M1" else max(10, self.atr_period)
        
        if len(bars) < min_bars:
            logger.warning(f"[SWING] Insufficient bars for swing detection. Have {len(bars)}, need at least {min_bars}")
            return SwingState(
                swings=[],
                last_high=None,
                last_low=None,
                trend=TrendDirection.SIDEWAYS,
                swing_quality=tf_config['default_quality'],  # Použít default místo 0
                last_impulse_atr=0,
                rotation_count=0,
                cleanliness=0
            )
        
        # Calculate ATR
        self.current_atr = self._calculate_atr(bars)
        logger.info(f"[SWING] Current ATR: {self.current_atr:.5f}")
        
        # Pokud je ATR příliš malé, použít fixní threshold
        if self.current_atr < 0.0001:
            # Pro nízkou volatilitu použít % z ceny
            avg_price = sum(b['close'] for b in bars[-20:]) / min(20, len(bars))
            threshold = avg_price * 0.001  # 0.1% ceny
            logger.info(f"[SWING] ATR too small, using price-based threshold: {threshold:.5f}")
        else:
            # Get appropriate ATR multiplier
            atr_mult = self.atr_multiplier_m1 if timeframe == "M1" else self.atr_multiplier_m5
            threshold = self.current_atr * atr_mult
            logger.info(f"[SWING] Using ATR threshold: {threshold:.5f} (ATR {self.current_atr:.5f} * multiplier {atr_mult})")
        
        # Detect swing points using ZigZag
        swings = self._zigzag_detection(bars, threshold)
        logger.info(f"[SWING] ZigZag detected {len(swings)} swing points")
        
        # Enhance swings with pivot validation if available
        if self.use_pivot_validation and self.pivot_calculator:
            swings = self._enhance_swings_with_pivots(swings)
            logger.info(f"[SWING] Enhanced {len(swings)} swings with pivot validation")
        
        # Calculate swing metrics s flexibilnějšími požadavky
        min_swings_quality = tf_config['min_swings_for_quality']
        min_swings_trend = tf_config['min_swings_for_trend']
        
        # Určit trend
        if len(swings) >= min_swings_trend:
            trend = self._determine_trend(swings)
        else:
            trend = TrendDirection.SIDEWAYS
            logger.debug(f"[SWING] Not enough swings for trend: {len(swings)} < {min_swings_trend}")
        
        # Vypočítat kvalitu
        if len(swings) >= min_swings_quality:
            quality = self._calculate_swing_quality(swings)
        else:
            # Použít částečnou kvalitu místo 0
            quality = tf_config['default_quality']
            if len(swings) > 0:
                # Přidat bonus za detekované swingy
                quality += len(swings) * 5
            logger.info(f"[SWING] Using default quality {quality:.1f} (only {len(swings)} swings)")
        
        # Ostatní metriky
        last_impulse = self._get_last_impulse(swings) if len(swings) >= 2 else 0
        rotation = self._count_rotations(swings) if len(swings) >= 2 else 0
        cleanliness = self._calculate_cleanliness(swings, bars) if len(swings) >= 2 else 50
        
        logger.info(f"[SWING] Trend: {trend.value}, Quality: {quality:.1f} (min required: {self.min_swing_quality})")
        
        # Get last high and low
        last_high = None
        last_low = None
        for swing in reversed(swings):
            if swing.type == SwingType.HIGH and not last_high:
                last_high = swing
            elif swing.type == SwingType.LOW and not last_low:
                last_low = swing
            if last_high and last_low:
                break
        
        # Create state
        state = SwingState(
            swings=swings,
            last_high=last_high,
            last_low=last_low,
            trend=trend,
            swing_quality=quality,
            last_impulse_atr=last_impulse,
            rotation_count=rotation,
            cleanliness=cleanliness
        )
        
        self.current_state = state
        logger.info(f"[SWING] Detection complete: {len(swings)} swings, trend={trend.value}, quality={quality:.1f}")
        
        return state

    def _calculate_atr(self, bars: List[Dict]) -> float:
        """Calculate Average True Range without NumPy"""
        if len(bars) < self.atr_period + 1:
            return 0
        
        tr_values = []
        
        for i in range(1, len(bars)):
            high = bars[i]['high']
            low = bars[i]['low']
            prev_close = bars[i-1]['close']
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            tr_values.append(tr)
        
        # EMA of TR for ATR
        if len(tr_values) >= self.atr_period:
            atr_values = self._ema(tr_values, self.atr_period)
            atr = atr_values[-1] if atr_values else 0
        else:
            atr = sum(tr_values) / len(tr_values) if tr_values else 0
        
        return atr
    
    def _zigzag_detection(self, bars: List[Dict], threshold: float) -> List[SwingPoint]:
        """
        ZigZag algorithm - upravený pro citlivější detekci
        """
        if len(bars) < 3:
            logger.debug(f"[SWING] ZigZag needs at least 3 bars, have {len(bars)}")
            return []
        
        logger.debug(f"[SWING] Starting ZigZag with {len(bars)} bars, threshold={threshold:.5f}")
        
        swings = []
        current_trend = None
        last_swing_idx = 0
        last_swing_price = bars[0]['close']
        
        highs = [b['high'] for b in bars]
        lows = [b['low'] for b in bars]
        timestamps = [b.get('timestamp', str(i)) for i, b in enumerate(bars)]
        
        # Flexibilnější min_bars pro začátek
        min_bars_first = max(2, self.min_bars_between // 2)
        
        for i in range(1, len(bars)):
            # Pro první swing použít menší minimum
            if len(swings) == 0:
                min_bars_current = min_bars_first
            else:
                min_bars_current = self.min_bars_between
                
            if i - last_swing_idx < min_bars_current:
                continue
            
            if current_trend is None:
                # Initialize trend - použít menší threshold pro první detekci
                init_threshold = threshold * 0.7
                if highs[i] - last_swing_price > init_threshold:
                    current_trend = 'up'
                    logger.debug(f"[SWING] Initial trend set to UP at index {i}")
                elif last_swing_price - lows[i] > init_threshold:
                    current_trend = 'down'
                    logger.debug(f"[SWING] Initial trend set to DOWN at index {i}")
                continue
            
            if current_trend == 'up':
                # Look for swing high
                if last_swing_price - lows[i] > threshold:
                    # Found swing high
                    high_idx = last_swing_idx
                    max_high = highs[last_swing_idx]
                    for j in range(last_swing_idx + 1, i):
                        if highs[j] > max_high:
                            max_high = highs[j]
                            high_idx = j
                    
                    amplitude = abs(max_high - last_swing_price)
                    
                    swing = SwingPoint(
                        index=high_idx,
                        price=max_high,
                        type=SwingType.HIGH,
                        timestamp=timestamps[high_idx],
                        amplitude=amplitude,
                        amplitude_atr=amplitude / self.current_atr if self.current_atr > 0 else 1,
                        bars_from_prev=high_idx - last_swing_idx
                    )
                    swings.append(swing)
                    
                    current_trend = 'down'
                    last_swing_idx = high_idx
                    last_swing_price = max_high
                    
            else:  # current_trend == 'down'
                # Look for swing low
                if highs[i] - last_swing_price > threshold:
                    # Found swing low
                    low_idx = last_swing_idx
                    min_low = lows[last_swing_idx]
                    for j in range(last_swing_idx + 1, i):
                        if lows[j] < min_low:
                            min_low = lows[j]
                            low_idx = j
                    
                    amplitude = abs(last_swing_price - min_low)
                    
                    swing = SwingPoint(
                        index=low_idx,
                        price=min_low,
                        type=SwingType.LOW,
                        timestamp=timestamps[low_idx],
                        amplitude=amplitude,
                        amplitude_atr=amplitude / self.current_atr if self.current_atr > 0 else 1,
                        bars_from_prev=low_idx - last_swing_idx
                    )
                    swings.append(swing)
                    
                    current_trend = 'up'
                    last_swing_idx = low_idx
                    last_swing_price = min_low
        
        logger.debug(f"[SWING] ZigZag complete: {len(swings)} swings detected")
        return swings
        
    def _determine_trend(self, swings: List[SwingPoint]) -> TrendDirection:
        """
        Determine trend based on swing sequence
        HH-HL = Uptrend
        LL-LH = Downtrend
        Mixed = Sideways
        """
        if len(swings) < 4:
            return TrendDirection.SIDEWAYS
        
        # Get last 4 swings for pattern analysis
        recent_swings = swings[-4:]
        
        # Separate highs and lows
        recent_highs = [s for s in recent_swings if s.type == SwingType.HIGH]
        recent_lows = [s for s in recent_swings if s.type == SwingType.LOW]
        
        if len(recent_highs) >= 2 and len(recent_lows) >= 2:
            # Check for higher highs and higher lows (uptrend)
            hh = recent_highs[-1].price > recent_highs[-2].price
            hl = recent_lows[-1].price > recent_lows[-2].price
            
            # Check for lower lows and lower highs (downtrend)
            ll = recent_lows[-1].price < recent_lows[-2].price
            lh = recent_highs[-1].price < recent_highs[-2].price
            
            if hh and hl:
                return TrendDirection.UP
            elif ll and lh:
                return TrendDirection.DOWN
        
        return TrendDirection.SIDEWAYS
    
    def _calculate_swing_quality(self, swings: List[SwingPoint]) -> float:
        """
        Calculate overall swing quality - upravená pro méně swingů
        Enhanced with pivot confluence if available
        """
        if len(swings) < 2:
            return 20  # Základní kvalita místo 0
        
        # Use pivot-enhanced quality if available
        if (self.use_pivot_validation and 
            self.pivot_calculator and 
            swings and 
            hasattr(swings[0], 'pivot_confluence')):
            return self._calculate_pivot_enhanced_quality(swings)
        
        return self._calculate_base_swing_quality(swings)
    
    def _calculate_base_swing_quality(self, swings: List[SwingPoint]) -> float:
        """
        Calculate base swing quality without pivot enhancements
        """
        quality_scores = []
        
        # 1. Amplitude consistency (30% weight)
        amplitudes = [s.amplitude_atr for s in swings if s.amplitude_atr > 0]
        if len(amplitudes) >= 2:
            mean = sum(amplitudes) / len(amplitudes)
            variance = sum((x - mean) ** 2 for x in amplitudes) / len(amplitudes)
            std = math.sqrt(variance)
            
            # Méně přísné hodnocení
            amp_consistency = max(20, 100 - (std / max(mean, 0.1)) * 50)
            quality_scores.append(amp_consistency * 0.3)
        else:
            quality_scores.append(30 * 0.3)  # Default 30%
        
        # 2. Time consistency (30% weight)
        time_gaps = [s.bars_from_prev for s in swings[1:] if s.bars_from_prev > 0]
        if len(time_gaps) >= 2:
            mean = sum(time_gaps) / len(time_gaps)
            variance = sum((x - mean) ** 2 for x in time_gaps) / len(time_gaps)
            std = math.sqrt(variance)
            
            time_consistency = max(20, 100 - (std / max(mean, 1)) * 30)
            quality_scores.append(time_consistency * 0.3)
        else:
            quality_scores.append(30 * 0.3)  # Default 30%
        
        # 3. Trend clarity (40% weight) - upravené hodnocení
        if len(swings) >= 4:
            trend = self._determine_trend(swings)
            if trend == TrendDirection.UP or trend == TrendDirection.DOWN:
                trend_clarity = 80
            else:
                trend_clarity = 50
        else:
            # Pro méně swingů použít počet jako indikátor
            trend_clarity = 30 + (len(swings) * 10)
        quality_scores.append(trend_clarity * 0.4)
        
        # 4. Bonus za počet swingů
        swing_bonus = min(20, len(swings) * 2)
        
        total_quality = sum(quality_scores) + swing_bonus
        return min(100, max(20, total_quality))  # Minimum 20, maximum 100
        
    def _get_last_impulse(self, swings: List[SwingPoint]) -> float:
        """Get the last impulse move in ATR units"""
        if len(swings) < 2:
            return 0
        
        return swings[-1].amplitude_atr
    
    def _count_rotations(self, swings: List[SwingPoint]) -> int:
        """Count number of alternating high-low rotations"""
        if len(swings) < 2:
            return 0
        
        rotations = 0
        for i in range(1, len(swings)):
            if swings[i].type != swings[i-1].type:
                rotations += 1
        
        return rotations
    
    def _calculate_cleanliness(self, swings: List[SwingPoint], bars: List[Dict]) -> float:
        """
        Calculate how clean the swings are (minimal noise between swings)
        Returns 0-100 score
        """
        if len(swings) < 2 or len(bars) < 10:
            return 50
        
        cleanliness_scores = []
        
        for i in range(1, len(swings)):
            prev_swing = swings[i-1]
            curr_swing = swings[i]
            
            # Get bars between swings
            start_idx = prev_swing.index
            end_idx = curr_swing.index
            
            if end_idx <= start_idx or end_idx >= len(bars):
                continue
            
            segment_bars = bars[start_idx:end_idx+1]
            
            # Calculate directional consistency
            if curr_swing.type == SwingType.HIGH:
                # Should be mostly up moves
                up_bars = sum(1 for b in segment_bars[1:] 
                            if b['close'] > b['open'])
                consistency = (up_bars / len(segment_bars[1:])) * 100 if len(segment_bars) > 1 else 50
            else:
                # Should be mostly down moves
                down_bars = sum(1 for b in segment_bars[1:] 
                              if b['close'] < b['open'])
                consistency = (down_bars / len(segment_bars[1:])) * 100 if len(segment_bars) > 1 else 50
            
            cleanliness_scores.append(consistency)
        
        # Calculate average
        if cleanliness_scores:
            return sum(cleanliness_scores) / len(cleanliness_scores)
        else:
            return 50
    
    def _ema(self, values: List[float], period: int) -> List[float]:
        """Calculate Exponential Moving Average"""
        if not values:
            return []
        
        alpha = 2 / (period + 1)
        ema = [values[0]]
        
        for i in range(1, len(values)):
            ema.append(alpha * values[i] + (1 - alpha) * ema[-1])
        
        return ema
    
    def get_swing_summary(self) -> Dict:
        """Get summary of swing state for UI/logging"""
        if not self.current_state:
            return {
                "trend": "UNKNOWN",
                "swing_quality": 0,
                "last_high": None,
                "last_low": None,
                "swing_count": 0
            }
        
        state = self.current_state
        return {
            "trend": state.trend.value,
            "swing_quality": round(state.swing_quality, 1),
            "last_high": state.last_high.price if state.last_high else None,
            "last_low": state.last_low.price if state.last_low else None,
            "swing_count": len(state.swings),
            "last_impulse_atr": round(state.last_impulse_atr, 2),
            "rotation_count": state.rotation_count,
            "cleanliness": round(state.cleanliness, 1)
        }
    
    def check_swing_breakout(self, current_price: float) -> Optional[str]:
        """
        Check if price breaks recent swing levels
        
        Returns:
            "HIGH_BREAK", "LOW_BREAK", or None
        """
        if not self.current_state:
            return None
        
        if self.current_state.last_high and current_price > self.current_state.last_high.price:
            return "HIGH_BREAK"
        
        if self.current_state.last_low and current_price < self.current_state.last_low.price:
            return "LOW_BREAK"
        
        return None
    
    def get_swing_targets(self, direction: str) -> Optional[Dict]:
        """
        Get potential targets based on swing structure
        
        Args:
            direction: "long" or "short"
            
        Returns:
            Dictionary with entry, stop, and target levels
        """
        if not self.current_state or len(self.current_state.swings) < 4:
            return None
        
        swings = self.current_state.swings
        
        if direction == "long":
            # Entry above last high
            entry = self.current_state.last_high.price if self.current_state.last_high else None
            
            # Stop below last low
            stop = self.current_state.last_low.price if self.current_state.last_low else None
            
            # Target at previous high or projection
            highs = [s.price for s in swings if s.type == SwingType.HIGH]
            target = max(highs) if highs else None
            
        else:  # short
            # Entry below last low
            entry = self.current_state.last_low.price if self.current_state.last_low else None
            
            # Stop above last high
            stop = self.current_state.last_high.price if self.current_state.last_high else None
            
            # Target at previous low or projection
            lows = [s.price for s in swings if s.type == SwingType.LOW]
            target = min(lows) if lows else None
        
        if entry and stop and target:
            return {
                "entry": round(entry, 5),
                "stop": round(stop, 5),
                "target": round(target, 5),
                "risk": round(abs(entry - stop), 5),
                "reward": round(abs(target - entry), 5),
                "rr_ratio": round(abs(target - entry) / abs(entry - stop), 2)
            }
        
        return None
    
    def _enhance_swings_with_pivots(self, swings: List[SwingPoint]) -> List[SwingPoint]:
        """
        Enhance swing quality scores based on pivot confluence
        
        Swings that occur near pivot levels get quality boosts as they are more likely
        to be significant support/resistance points based on floor trader pivots.
        
        Args:
            swings: List of detected swing points
            
        Returns:
            Enhanced swing points with pivot-adjusted quality
        """
        if not self.pivot_calculator or not swings:
            return swings
        
        enhanced_swings = []
        pivot_enhancements = 0
        
        logger.debug(f"[SWING] Analyzing {len(swings)} swings for pivot confluence")
        
        for swing in swings:
            # Find pivot confluence near this swing
            nearby_pivots = self.pivot_calculator.find_pivot_confluence(
                swing.price, 
                self.pivot_confluence_atr
            )
            
            # Add pivot enhancement if pivots found nearby
            if nearby_pivots:
                pivot_enhancements += 1
                
                # Calculate pivot strength bonus
                pivot_strength_bonus = sum(pivot.strength for pivot in nearby_pivots)
                
                # Log the enhancement
                pivot_names = ', '.join([f"{p.name}({p.value:.2f})" for p in nearby_pivots[:2]])
                logger.info(f"[SWING] Pivot confluence at {swing.type.value} swing {swing.price:.2f}: "
                          f"{len(nearby_pivots)} pivots [{pivot_names}], strength bonus: {pivot_strength_bonus}")
                
                # Store pivot information in the swing object
                swing.pivot_confluence = {
                    'count': len(nearby_pivots),
                    'strength_bonus': pivot_strength_bonus,
                    'pivots': [{'name': p.name, 'value': p.value, 'type': p.type} for p in nearby_pivots]
                }
            else:
                swing.pivot_confluence = {'count': 0, 'strength_bonus': 0, 'pivots': []}
            
            # Also check for round number confluence
            round_confluence = self.check_swing_at_round_number(
                swing.price, 
                swing.type.value.lower()
            )
            
            if round_confluence:
                logger.info(f"[SWING] Round number confluence at {swing.type.value} swing {swing.price:.2f}: "
                          f"{round_confluence['round_confluence_count']} levels, "
                          f"closest: {round_confluence['closest_round']['value']:.0f}")
                swing.round_confluence = round_confluence
            else:
                swing.round_confluence = {'round_confluence_count': 0, 'total_strength': 0, 'round_numbers': []}
            
            enhanced_swings.append(swing)
        
        logger.info(f"[SWING] Pivot enhancement complete: {pivot_enhancements}/{len(swings)} swings enhanced with pivot confluence")
        
        return enhanced_swings
    
    def _calculate_pivot_enhanced_quality(self, swings: List[SwingPoint]) -> float:
        """
        Calculate swing quality with pivot confluence bonuses
        
        Args:
            swings: List of swing points with pivot confluence data
            
        Returns:
            Quality score (0-100) enhanced by pivot confluence
        """
        base_quality = self._calculate_base_swing_quality(swings)
        
        if not self.use_pivot_validation or not hasattr(swings[0], 'pivot_confluence'):
            return base_quality
        
        # Calculate pivot enhancement bonus
        pivot_bonus = 0
        total_pivot_strength = 0
        enhanced_swings_count = 0
        
        # Calculate round number enhancement bonus
        round_bonus = 0
        total_round_strength = 0
        round_enhanced_count = 0
        
        for swing in swings:
            # Count pivot confluence
            if hasattr(swing, 'pivot_confluence') and swing.pivot_confluence['count'] > 0:
                enhanced_swings_count += 1
                total_pivot_strength += swing.pivot_confluence['strength_bonus']
            
            # Count round number confluence
            if hasattr(swing, 'round_confluence') and swing.round_confluence['round_confluence_count'] > 0:
                round_enhanced_count += 1
                total_round_strength += swing.round_confluence['total_strength']
        
        # Calculate pivot bonus
        if enhanced_swings_count > 0:
            # Bonus based on percentage of swings with pivot confluence
            confluence_percentage = enhanced_swings_count / len(swings)
            
            # Bonus based on average pivot strength
            avg_pivot_strength = total_pivot_strength / enhanced_swings_count
            
            # Calculate composite bonus
            pivot_bonus = (confluence_percentage * 15) + (avg_pivot_strength * 3)  # Max ~30 points
            
            logger.info(f"[SWING] Pivot quality bonus: {pivot_bonus:.1f} points "
                      f"({enhanced_swings_count}/{len(swings)} swings with confluence, "
                      f"avg strength: {avg_pivot_strength:.1f})")
        
        # Calculate round number bonus
        if round_enhanced_count > 0:
            round_confluence_percentage = round_enhanced_count / len(swings)
            avg_round_strength = total_round_strength / round_enhanced_count
            
            # Round numbers get smaller bonus than pivots (they're less reliable)
            round_bonus = (round_confluence_percentage * 8) + (avg_round_strength * 1.5)  # Max ~15 points
            
            logger.info(f"[SWING] Round number quality bonus: {round_bonus:.1f} points "
                      f"({round_enhanced_count}/{len(swings)} swings with round confluence, "
                      f"avg strength: {avg_round_strength:.1f})")
        
        # Combined enhancement
        total_bonus = pivot_bonus + round_bonus
        enhanced_quality = min(100, base_quality + total_bonus)
        
        if total_bonus > 0:
            bonus_breakdown = []
            if pivot_bonus > 0:
                bonus_breakdown.append(f"+{pivot_bonus:.1f} pivots")
            if round_bonus > 0:
                bonus_breakdown.append(f"+{round_bonus:.1f} rounds")
            
            logger.info(f"[SWING] Quality enhanced: {base_quality:.1f} → {enhanced_quality:.1f} "
                      f"({', '.join(bonus_breakdown)})")
        
        return enhanced_quality
    
    def check_swing_at_pivot(self, price: float, swing_type: str) -> Optional[Dict]:
        """
        Check if a potential swing point is near significant pivot levels
        
        This can be used for real-time swing validation during bar processing.
        
        Args:
            price: Price level to check
            swing_type: "high" or "low"
            
        Returns:
            Dictionary with pivot confluence information or None
        """
        if not self.pivot_calculator:
            return None
        
        nearby_pivots = self.pivot_calculator.find_pivot_confluence(
            price, 
            self.pivot_confluence_atr
        )
        
        if not nearby_pivots:
            return None
        
        # Filter pivots by type relevance
        relevant_pivots = []
        for pivot in nearby_pivots:
            if swing_type == "high" and pivot.type in ["resistance", "pivot"]:
                relevant_pivots.append(pivot)
            elif swing_type == "low" and pivot.type in ["support", "pivot"]:
                relevant_pivots.append(pivot)
        
        if relevant_pivots:
            return {
                'confluence_count': len(relevant_pivots),
                'total_strength': sum(p.strength for p in relevant_pivots),
                'closest_pivot': {
                    'name': relevant_pivots[0].name,
                    'value': relevant_pivots[0].value,
                    'distance_atr': abs(price - relevant_pivots[0].value) / self.current_atr if self.current_atr > 0 else 0
                },
                'pivots': [{'name': p.name, 'value': p.value, 'type': p.type, 'strength': p.strength} for p in relevant_pivots]
            }
        
        return None
    
    def find_round_numbers(self, price: float, max_distance_atr: float = 0.2) -> List[Dict]:
        """
        Find round numbers/psychological levels near price
        
        These are whole numbers that often act as psychological support/resistance:
        - For indices like DAX (18000+): multiples of 100, 50, 25
        - Major levels: multiples of 500, 1000
        
        Args:
            price: Current price to check
            max_distance_atr: Maximum distance in ATR units
            
        Returns:
            List of round number levels with metadata
        """
        if self.current_atr <= 0:
            return []
        
        max_distance = self.current_atr * max_distance_atr
        round_levels = []
        
        # Determine appropriate round number intervals based on price level
        if price >= 10000:  # High value indices (DAX, NASDAQ)
            intervals = [1000, 500, 250, 100, 50, 25]  # Major to minor levels
        elif price >= 1000:
            intervals = [100, 50, 25, 10, 5]  # Mid-range instruments
        else:
            intervals = [10, 5, 2, 1, 0.5]  # Lower value instruments
        
        logger.debug(f"[SWING] Searching round numbers near {price:.2f} with intervals: {intervals}")
        
        for interval in intervals:
            # Find nearest round number for this interval
            nearest_round = round(price / interval) * interval
            
            # Check both the nearest and adjacent round numbers
            candidates = [
                nearest_round - interval,
                nearest_round,
                nearest_round + interval
            ]
            
            for candidate in candidates:
                distance = abs(price - candidate)
                if distance <= max_distance and candidate > 0:
                    # Determine strength based on interval size
                    if interval >= 1000:
                        strength = 3  # Major psychological level
                    elif interval >= 100:
                        strength = 2  # Strong psychological level
                    else:
                        strength = 1  # Minor psychological level
                    
                    round_levels.append({
                        'value': candidate,
                        'interval': interval,
                        'strength': strength,
                        'distance': distance,
                        'distance_atr': distance / self.current_atr,
                        'type': 'psychological'
                    })
        
        # Remove duplicates and sort by distance
        seen = set()
        unique_levels = []
        for level in round_levels:
            value_key = round(level['value'], 2)
            if value_key not in seen:
                seen.add(value_key)
                unique_levels.append(level)
        
        # Sort by distance from price
        unique_levels.sort(key=lambda x: x['distance'])
        
        if unique_levels:
            levels_str = ', '.join([f"{l['value']:.0f}({l['strength']})" for l in unique_levels[:3]])
            logger.info(f"[SWING] Found {len(unique_levels)} round numbers near {price:.2f}: {levels_str}")
        
        return unique_levels
    
    def check_swing_at_round_number(self, price: float, swing_type: str) -> Optional[Dict]:
        """
        Check if a swing point occurs near psychological round numbers
        
        Args:
            price: Price to check
            swing_type: "high" or "low"
            
        Returns:
            Dictionary with round number confluence or None
        """
        round_numbers = self.find_round_numbers(price, 0.2)
        
        if not round_numbers:
            return None
        
        # Calculate total strength of nearby round numbers
        total_strength = sum(rn['strength'] for rn in round_numbers)
        
        return {
            'round_confluence_count': len(round_numbers),
            'total_strength': total_strength,
            'closest_round': {
                'value': round_numbers[0]['value'],
                'interval': round_numbers[0]['interval'],
                'strength': round_numbers[0]['strength'],
                'distance_atr': round_numbers[0]['distance_atr']
            },
            'round_numbers': round_numbers
        }