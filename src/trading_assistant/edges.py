"""
Edge Detection & Signal Generation Module
Wide Stops Strategy for M5
25-09-03
"""

from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timezone
import logging
from .pullback_detector import PullbackDetector

logger = logging.getLogger(__name__)

@dataclass
class Signal:
    """Trading signal data structure"""
    signal_type: 'SignalType'
    entry: float
    stop_loss: float
    take_profit: float
    signal_quality: float
    confidence: float
    patterns: List[str]
    risk_reward_ratio: float
    atr: float
    timestamp: Any

class SignalType(Enum):
    """Signal direction"""
    BUY = "BUY"
    SELL = "SELL"

class PatternType(Enum):
    """Candlestick patterns"""
    PIN_BAR = "PIN_BAR"
    ENGULFING = "ENGULFING"
    INSIDE_BAR = "INSIDE_BAR"
    MOMENTUM = "MOMENTUM"

@dataclass
class TradingSignal:
    """Complete trading signal with metadata"""
    signal_type: SignalType
    timestamp: str
    price: float
    patterns: List[str]
    structure_break: Optional[str]
    regime_alignment: bool
    entry: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    signal_quality: float
    confidence: float
    atr: float
    regime_state: str
    swing_trend: str
    nearest_pivot_name: Optional[str] = None
    nearest_pivot_value: Optional[float] = None
    # Microstructure data for analytics
    liquidity_score: Optional[float] = None
    volume_zscore: Optional[float] = None
    vwap_distance_pct: Optional[float] = None
    orb_triggered: bool = False
    high_quality_time: bool = False
    # Swing context for analytics
    swing_quality_score: Optional[float] = None
    last_swing_high: Optional[float] = None
    last_swing_low: Optional[float] = None

class EdgeDetector:
    """Edge detection with wide stops strategy for low pip values"""
    
    def __init__(self, config: Dict = None):
        """Initialize edge detector"""
        self.config = config or {}
        self.app = self.config.get('app')
        self.main_config = self.config.get('main_config', {})
        self.timeframe = self.config.get('timeframe', 'M5')
        
        # Get all configuration parameters
        self.min_swing_quality = float(self.config.get('min_swing_quality', 30))
        
        # Pattern detection
        self.pin_bar_ratio = self.config.get('pin_bar_ratio', 0.3)
        self.engulfing_min_size = self.config.get('engulfing_min_size', 0.9)
        self.momentum_threshold_atr = self.config.get('momentum_threshold_atr', 0.8)
        
        # Risk parameters
        self.min_rr_ratio = self.config.get('min_rrr', 1.5)
        self.standard_rrr = self.config.get('standard_rrr', 2.0)
        
        # Wide stops parameters
        self.use_dynamic_stops = self.config.get('use_dynamic_stops', True)
        
        # Initialize pullback detector
        pullback_config = self.config.get('pullback', {})
        pullback_config['app'] = self.app
        self.pullback_detector = PullbackDetector(pullback_config)
        self.pullback_detector.app = self.app
        self.min_rrr_for_wide = self.config.get('min_rrr_for_wide', 1.5)
        self.target_rrr_wide = self.config.get('target_rrr_wide', 2.0)
        
        # ATR factors
        self.atr_factor_sl = self.config.get('atr_factor_sl', 0.3)
        self.atr_factor_tp_min = self.config.get('atr_factor_tp_min', 1.8)
        self.atr_factor_tp_standard = self.config.get('atr_factor_tp_standard', 2.0)
        self.fallback_atr = self.config.get('fallback_atr', 20.0)
        
        # Quality thresholds
        self.min_signal_quality = self.config.get('min_signal_quality', 40)
        self.min_confidence = self.config.get('min_confidence', 50)
        self.default_confidence = self.config.get('default_confidence', 70)
        self.default_signal_quality = self.config.get('default_signal_quality', 75)
        self.require_regime_alignment = self.config.get('require_regime_alignment', False)
        
        # Cooldown
        self.min_bars_between_signals = self.config.get('min_bars_between_signals', 3)
        self._last_signal_bar_index = -999
        
        # Tick size
        self.tick_size = float(self.config.get('tick_size', 0.5))
        
        # Swing parameters
        self.swing_lookback = self.config.get('swing_lookback', 30)
        self.recent_swing_bars = self.config.get('recent_swing_bars', 10)
        self.swing_break_lookback = self.config.get('swing_break_lookback', 10)
        
        # State
        self.last_signal: Optional[TradingSignal] = None
        self.current_atr: float = 0
        self.current_symbol = None
        
    def detect_signals(self, 
                      bars: List[Dict],
                      regime_state: Dict,
                      pivot_levels: Dict,
                      swing_state: Dict,
                      microstructure_data: Optional[Dict] = None) -> List[TradingSignal]:
        """Main signal detection method"""
        
        if len(bars) < 20:
            self._log_rejection("Insufficient bars for analysis", {
                "bars_available": len(bars),
                "minimum_required": 20
            })
            return []
        
        current_bar_index = len(bars) - 1
        
        # Check cooldown
        if current_bar_index - self._last_signal_bar_index < self.min_bars_between_signals:
            bars_since_last = current_bar_index - self._last_signal_bar_index
            self._log_rejection("Signal cooldown active", {
                "bars_since_last_signal": bars_since_last,
                "minimum_required": self.min_bars_between_signals,
                "cooldown_remaining": self.min_bars_between_signals - bars_since_last
            })
            return []
        
        signals = []
        
        # Calculate ATR
        self.current_atr = self._calculate_atr(bars)
        
        # Log what we're checking (periodically, not every bar)
        if self.app and (current_bar_index % 12 == 0):  # Every 12 bars = 1 hour on M5
            self._log_validation_summary(bars, regime_state, swing_state, microstructure_data)
        
        # Check swing quality
        swing_quality = swing_state.get('quality', 0)
        if swing_quality < self.min_swing_quality:
            regime = regime_state.get('state', 'UNKNOWN')
            adx = regime_state.get('adx', 0)
            if not (regime == 'TREND' and adx > 25):
                self._log_rejection("Low swing quality", {
                    "current_swing_quality": f"{swing_quality:.1f}%",
                    "minimum_required": f"{self.min_swing_quality:.1f}%",
                    "regime": regime,
                    "adx": f"{adx:.1f}",
                    "trend_exception": f"Not strong trend (ADX > 25): {adx <= 25}"
                })
                return []
        
        # === PULLBACK DETECTION (Priority 1) ===
        # Check for high-quality pullback opportunities in strong trends
        pullback_opportunity = self.pullback_detector.detect_pullback_opportunity(
            bars, regime_state, swing_state, pivot_levels, microstructure_data
        )
        
        if pullback_opportunity:
            # Convert pullback opportunity to trading signal
            pullback_signal = self._create_pullback_signal(pullback_opportunity, bars, regime_state)
            if pullback_signal:
                if self.app:
                    self.app.log("=" * 60)
                    self.app.log(f"[PULLBACK SIGNAL] {pullback_signal.signal_type.value} detected")
                    self.app.log(f"🎯 Type: {pullback_opportunity['pullback_type'].value}")
                    self.app.log(f"🎯 Entry: {pullback_signal.entry:.1f} ({pullback_opportunity['entry_reason']})")
                    self.app.log(f"🎯 Quality: {pullback_opportunity['quality_score']:.0f}%")
                    self.app.log(f"🎯 Confluence: {pullback_opportunity['confluence_levels']} levels")
                    self.app.log(f"🎯 Retracement: {pullback_opportunity.get('retracement_pct', 0):.1f}%")
                    self.app.log("=" * 60)
                signals.append(pullback_signal)
                self.last_signal = pullback_signal
                self._last_signal_bar_index = current_bar_index
                return signals  # Return immediately for high-quality pullbacks
        
        # === STANDARD PATTERN DETECTION (Priority 2) ===
        # Only if no pullback opportunity found
        patterns = self._detect_patterns(bars, regime_state)
        
        # Check structure breaks
        structure_breaks = self._check_structure_breaks(bars, swing_state, pivot_levels)
        
        # Evaluate confluence
        if patterns or structure_breaks:
            signal = self._evaluate_confluence_wide_stops(
                bars, patterns, structure_breaks,
                regime_state, pivot_levels, swing_state, microstructure_data
            )
            
            if signal:
                if signal.signal_quality >= self.min_signal_quality and \
                   signal.confidence >= self.min_confidence:
                    signals.append(signal)
                    self.last_signal = signal
                    self._last_signal_bar_index = current_bar_index
        
        return signals
    
    def _create_pullback_signal(self, pullback_opportunity: Dict, bars: List[Dict], regime_state: Dict) -> Optional[TradingSignal]:
        """Create trading signal from pullback opportunity"""
        try:
            signal_type = SignalType.BUY if pullback_opportunity['signal_direction'] == 'BUY' else SignalType.SELL
            entry_price = pullback_opportunity['entry_price']
            
            # Calculate stop loss and take profit for pullback
            atr = self.current_atr
            
            # Pullback stops are tighter than standard wide stops
            if signal_type == SignalType.BUY:
                # For pullback BUY in uptrend, SL below recent swing low
                stop_loss = entry_price - (atr * 2.0)  # Tighter stop
                take_profit = entry_price + (atr * 4.0)  # 1:2 RRR minimum
            else:
                # For pullback SELL in downtrend, SL above recent swing high  
                stop_loss = entry_price + (atr * 2.0)
                take_profit = entry_price - (atr * 4.0)
                
            # Calculate risk-reward ratio
            risk_distance = abs(entry_price - stop_loss)
            reward_distance = abs(take_profit - entry_price)
            risk_reward_ratio = reward_distance / risk_distance if risk_distance > 0 else 0

            # Ex-post RRR validation for pullbacks
            min_rrr_required = self.min_rr_ratio
            if risk_reward_ratio < min_rrr_required:
                if self.app:
                    self.app.log(f"[PULLBACK] ❌ RRR validation failed: {risk_reward_ratio:.2f} < {min_rrr_required:.2f}")
                return None

            # Quality and confidence from pullback analysis
            quality_score = pullback_opportunity['quality_score']
            confidence = min(95, quality_score + 10)  # Pullbacks get confidence bonus
            
            # Create pattern list for pullback
            patterns = [
                f"PULLBACK_{pullback_opportunity['pullback_type'].value}",
                pullback_opportunity['entry_reason']
            ]
            
            return TradingSignal(
                signal_type=signal_type,
                entry=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                signal_quality=quality_score,
                confidence=confidence,
                patterns=patterns,
                risk_reward_ratio=risk_reward_ratio,
                atr=atr,
                timestamp=datetime.now(timezone.utc)
            )
            
        except Exception as e:
            if self.app:
                self.app.log(f"[ERROR] Creating pullback signal: {e}")
            return None
    
    def _evaluate_confluence_wide_stops(self, bars: List[Dict], patterns: List[Dict], 
                                   structure_breaks: List[Dict], regime_state: Dict,
                                   pivot_levels: Dict, swing_state: Dict, 
                                   microstructure_data: Optional[Dict] = None) -> Optional[TradingSignal]:
        """Evaluate patterns with SIMPLE WIDE STOPS strategy"""
        
        if not patterns:
            self._log_rejection("No patterns detected", {
                "bars_analyzed": len(bars),
                "current_atr": f"{self.current_atr:.2f}",
                "current_price": f"{bars[-1]['close']:.1f}" if bars else "N/A"
            })
            return None
        
        current_price = bars[-1]['close']
        
        # Determine signal direction
        bullish_count = sum(1 for p in patterns if p.get('direction') == 'bullish')
        bearish_count = sum(1 for p in patterns if p.get('direction') == 'bearish')
        
        if bullish_count == bearish_count:
            self._log_rejection("Equal bullish/bearish signals", {
                "bullish_count": bullish_count,
                "bearish_count": bearish_count,
                "patterns": [f"{p.get('type', 'UNKNOWN')}: {p.get('direction', 'neutral')}" for p in patterns]
            })
            return None
        
        # === MICROSTRUCTURE EARLY FILTERING ===
        if microstructure_data:
            # Liquidity gate - skip low liquidity periods
            liquidity = microstructure_data.get('liquidity_score', 0.5)
            min_liquidity = self.main_config.get('microstructure', {}).get('min_liquidity_score', 0.3)
            if liquidity < min_liquidity:
                self._log_rejection("Low liquidity", {
                    "current_liquidity": f"{liquidity:.3f}",
                    "minimum_required": f"{min_liquidity:.2f}",
                    "microstructure_data": {
                        "vwap_distance": f"{microstructure_data.get('vwap_distance', 0):.2f}%",
                        "volume_zscore": f"{microstructure_data.get('volume_zscore', 0):.2f}",
                        "is_high_quality_time": microstructure_data.get('is_high_quality_time', False)
                    }
                })
                return None
            
            # ATR filtering - avoid extreme volatility
            atr_data = microstructure_data.get('atr_analysis', {})
            if atr_data.get('is_elevated', False) and atr_data.get('ratio', 1.0) > 2.0:
                self._log_rejection("Extreme volatility", {
                    "atr_ratio": f"{atr_data.get('ratio', 0):.2f}",
                    "maximum_allowed": "2.0",
                    "current_atr": f"{atr_data.get('current', 0):.2f}",
                    "expected_atr": f"{atr_data.get('expected', 0):.2f}",
                    "is_elevated": atr_data.get('is_elevated', False)
                })
                return None
        
        # Get configuration
        main_config = self.main_config or self.config.get('main_config', {})
        
        # Detect symbol based on price range
        if current_price > 20000:
            symbol_alias = 'DAX'
            symbol_name = 'DE40'
        else:
            symbol_alias = 'NASDAQ'
            symbol_name = 'US100'
        
        symbol_spec = main_config.get('symbol_specs', {}).get(symbol_alias, {})
        
        # Get parameters
        pip_value = symbol_spec.get('pip_value_per_lot', 0.21)
        target_position = symbol_spec.get('target_position_lots', main_config.get('target_position_lots', 12.0))
        max_risk_czk = main_config.get('account_balance', 2000000) * main_config.get('max_risk_per_trade', 0.005)
        
        # Get configured limits
        min_sl_points = symbol_spec.get('min_sl_points', 150.0)
        max_sl_points = symbol_spec.get('max_sl_points', 400.0)
        
        # Calculate ATR
        atr = self.current_atr if self.current_atr > 0 else self._calculate_atr(bars)
        if atr <= 0:
            atr = 50  # Fallback value
        
        # === SIMPLE SL CALCULATION ===
        
        # 1. Base SL according to volatility
        if atr < 30:
            base_sl = 150  # Low volatility
        elif atr < 50:
            base_sl = 200  # Medium volatility
        elif atr < 80:
            base_sl = 250  # Higher volatility
        else:
            base_sl = 300  # High volatility
        
        # 2. Adjust for market regime
        regime = regime_state.get('state', 'UNKNOWN')
        if regime == 'TREND':
            sl_distance = base_sl * 1.2  # Wider stops in trend
        elif regime == 'RANGE':
            sl_distance = base_sl * 0.8  # Tighter stops in range
        else:
            sl_distance = base_sl
        
        # 3. Adjust for symbol characteristics
        if symbol_alias == 'DAX':
            sl_distance = sl_distance * 0.9  # DAX moves less than NASDAQ
        
        # 4. Consider swing quality
        swing_quality = swing_state.get('quality', 50)
        if swing_quality > 70:
            sl_distance = sl_distance * 0.9  # Tighter with high quality
        elif swing_quality < 30:
            sl_distance = sl_distance * 1.1  # Wider with low quality
        
        # 5. Apply configured limits
        sl_distance = max(min_sl_points, min(sl_distance, max_sl_points))
        
        # 5.5 MICROSTRUCTURE SL ADJUSTMENTS
        if microstructure_data:
            atr_data = microstructure_data.get('atr_analysis', {})
            
            # Widen stops during elevated volatility
            if atr_data.get('is_elevated', False):
                sl_adjustment = 1.2
                sl_distance = sl_distance * sl_adjustment
                if self.app:
                    self.app.log(f"[MICRO] Elevated ATR detected, widening SL by {(sl_adjustment-1)*100:.0f}%")
            
            # Tighten stops during low volatility (remove dependency on micro_bonus_conf)
            elif atr_data.get('ratio', 1.0) < 0.8:
                # Check if we have high liquidity as a proxy for high confidence
                liquidity = microstructure_data.get('liquidity_score', 0.5)
                if liquidity > 0.7:
                    sl_adjustment = 0.9
                    sl_distance = sl_distance * sl_adjustment
                    if self.app:
                        self.app.log(f"[MICRO] Low volatility + high liquidity, tightening SL by {(1-sl_adjustment)*100:.0f}%")
        
        # 6. Optional: Check nearest swing for adjustment
        if len(bars) >= 10:
            recent_bars = bars[-10:]
            if bullish_count > bearish_count:  # BUY
                recent_lows = [b['low'] for b in recent_bars]
                nearest_swing = max(recent_lows) if recent_lows else current_price - sl_distance
                natural_sl = current_price - nearest_swing
                
                # Use swing only if it's reasonable
                if natural_sl > sl_distance * 0.5 and natural_sl < sl_distance * 1.5:
                    sl_distance = natural_sl
            else:  # SELL
                recent_highs = [b['high'] for b in recent_bars]
                nearest_swing = min(recent_highs) if recent_highs else current_price + sl_distance
                natural_sl = nearest_swing - current_price
                
                if natural_sl > sl_distance * 0.5 and natural_sl < sl_distance * 1.5:
                    sl_distance = natural_sl
        
        # === SIMPLE TP CALCULATION ===
        
        # Base RRR
        base_rrr = 2.0
        
        # Adjust RRR based on confidence
        pattern_count = len(patterns)
        structure_count = len(structure_breaks)
        total_signals = pattern_count + structure_count
        
        if total_signals >= 3:
            target_rrr = base_rrr * 1.2  # Strong confluence
        elif total_signals >= 2:
            target_rrr = base_rrr
        else:
            target_rrr = base_rrr * 0.9  # Weaker signal
        
        # Ensure minimum RRR
        target_rrr = max(1.5, target_rrr)
        
        tp_distance = sl_distance * target_rrr
        
        # === TREND DIRECTION FILTER ===
        # STRICT: Only allow signals WITH the trend direction (no counter-trend entries)
        # Allow pullback entries in trend direction only
        
        # Get trend direction from regime
        trend_direction = regime_state.get('trend_direction')
        regime_type = regime_state.get('state', 'UNKNOWN')
        adx_value = regime_state.get('adx', 0)
        
        # Determine signal direction based on pattern count
        signal_wants_buy = bullish_count > bearish_count
        signal_wants_sell = bullish_count <= bearish_count
        
        # STRICT TREND FILTERING: Block counter-trend signals when trend direction is clear
        # Only allow signals in the direction of the trend (including pullbacks)
        if trend_direction and trend_direction in ['UP', 'DOWN']:
            # We have a clear trend direction - block counter-trend signals
            if signal_wants_buy and trend_direction != 'UP':
                # Want to go long but trend is down - REJECT (counter-trend)
                self._log_rejection("Trend filter: BUY signal against trend (counter-trend blocked)", {
                    "signal_direction": "BUY",
                    "trend_direction": trend_direction,
                    "regime_type": regime_type,
                    "adx": adx_value,
                    "bullish_count": bullish_count,
                    "bearish_count": bearish_count,
                    "reason": "Only trend-following entries allowed (no counter-trend)"
                })
                return None
            elif signal_wants_sell and trend_direction != 'DOWN':
                # Want to go short but trend is up - REJECT (counter-trend)
                self._log_rejection("Trend filter: SELL signal against trend (counter-trend blocked)", {
                    "signal_direction": "SELL", 
                    "trend_direction": trend_direction,
                    "regime_type": regime_type,
                    "adx": adx_value,
                    "bullish_count": bullish_count,
                    "bearish_count": bearish_count,
                    "reason": "Only trend-following entries allowed (no counter-trend)"
                })
                return None
            # If we get here, signal is in trend direction - ALLOW (including pullbacks)
        
        # If trend_direction is SIDEWAYS or None, allow both directions (range trading)
        
        # === SET FINAL LEVELS ===
        
        if bullish_count > bearish_count:  # BUY SIGNAL
            signal_type = SignalType.BUY
            entry = current_price
            stop_loss = entry - sl_distance
            take_profit = entry + tp_distance
            
            # Optional: Adjust TP to pivot level if close
            if pivot_levels:
                r1 = pivot_levels.get('r1', 0)
                if r1 and r1 > entry:
                    distance_to_r1 = r1 - entry
                    if distance_to_r1 > sl_distance * 1.5 and distance_to_r1 < tp_distance:
                        take_profit = r1 - (atr * 0.1)  # Just before R1
                        tp_distance = take_profit - entry
                        
        else:  # SELL SIGNAL
            signal_type = SignalType.SELL
            entry = current_price
            stop_loss = entry + sl_distance
            take_profit = entry - tp_distance
            
            # Optional: Adjust TP to pivot level if close
            if pivot_levels:
                s1 = pivot_levels.get('s1', 0)
                if s1 and s1 < entry:
                    distance_to_s1 = entry - s1
                    if distance_to_s1 > sl_distance * 1.5 and distance_to_s1 < tp_distance:
                        take_profit = s1 + (atr * 0.1)  # Just after S1
                        tp_distance = entry - take_profit

        # === CALCULATE INITIAL QUALITY SCORE ===
        signal_quality = 60  # Base quality
        swing_quality_score = swing_state.get('quality', 50)
        if swing_quality_score > 60:
            signal_quality += 15

        # === CALCULATE METRICS ===

        sl_pips = sl_distance * 100  # FIXED: 1 point = 100 pips for DAX/NASDAQ
        tp_pips = tp_distance * 100  # FIXED: 1 point = 100 pips for DAX/NASDAQ
        rrr = tp_distance / sl_distance if sl_distance > 0 else 0

        # Validate minimum RRR (initial check)
        if rrr < 1.5:
            self._log_rejection("Risk/Reward ratio too low", {
                "calculated_rrr": f"{rrr:.2f}",
                "minimum_required": "1.50",
                "sl_distance": f"{sl_distance:.1f}",
                "tp_distance": f"{tp_distance:.1f}",
                "entry_price": f"{entry:.1f}",
                "stop_loss": f"{stop_loss:.1f}",
                "take_profit": f"{take_profit:.1f}"
            })
            return None
        
        # === CALCULATE EXPECTED POSITION SIZE ===
        
        # Position size preview (actual sizing done in risk manager)
        # For fixed position sizing strategy, show target position
        expected_lots = target_position
        
        # === EX-POST RRR VALIDATION (after all TP adjustments) ===

        # Recalculate final RRR after all pivot/clamping adjustments
        final_sl_distance = abs(entry - stop_loss)
        final_tp_distance = abs(take_profit - entry)
        final_rrr = final_tp_distance / final_sl_distance if final_sl_distance > 0 else 0

        # Validate final RRR meets minimum requirements
        min_rrr_required = self.min_rr_ratio  # From config (usually 1.5)
        if final_rrr < min_rrr_required:
            self._log_rejection("Ex-post RRR validation failed", {
                "initial_rrr": f"{rrr:.2f}",
                "final_rrr_after_adjustments": f"{final_rrr:.2f}",
                "minimum_required": f"{min_rrr_required:.2f}",
                "final_entry": f"{entry:.1f}",
                "final_stop_loss": f"{stop_loss:.1f}",
                "final_take_profit": f"{take_profit:.1f}",
                "final_sl_distance": f"{final_sl_distance:.1f}",
                "final_tp_distance": f"{final_tp_distance:.1f}",
                "reason": "TP clamping or pivot adjustments reduced RRR below minimum"
            })
            return None

        # Update metrics with final values
        rrr = final_rrr
        sl_distance = final_sl_distance
        tp_distance = final_tp_distance
        sl_pips = sl_distance * 100
        tp_pips = tp_distance * 100

        # Log signal details
        if self.app:
            self.app.log(f"[EDGE] Wide stops signal: {signal_type.value}")
            self.app.log(f"  Entry: {entry:.1f}")
            self.app.log(f"  SL: {stop_loss:.1f} ({sl_pips:.0f} pips)")
            self.app.log(f"  TP: {take_profit:.1f} ({tp_pips:.0f} pips)")
            self.app.log(f"  Final RRR: 1:{rrr:.1f} ✅ (passed ex-post validation)")
            self.app.log(f"  Expected position: ~{expected_lots:.1f} lots")
            self.app.log(f"  ATR: {atr:.1f}, Regime: {regime}, Quality: {swing_quality}")

        # === CREATE SIGNAL ===
        
        # Calculate confidence based on confluence
        confidence = 60  # Base
        if pattern_count >= 2:
            confidence += 10
        if structure_count > 0:
            confidence += 10
        if regime == 'TREND' and signal_type.value.lower() == swing_state.get('trend', '').lower():
            confidence += 10

        # Update signal quality
        # Add RRR bonus
        if rrr >= 2.0:
            signal_quality += 10
        
        # === MICROSTRUCTURE ENHANCEMENTS ===
        micro_bonus_conf = 0
        micro_bonus_qual = 0
        
        if microstructure_data:
            liquidity = microstructure_data.get('liquidity_score', 0.5)
            
            # Volume confirmation for breakouts
            volume_zscore = microstructure_data.get('volume_zscore', 0)
            if volume_zscore > 1.5:
                micro_bonus_conf += 10
                if self.app:
                    self.app.log(f"[MICRO] High volume Z-score {volume_zscore:.2f}, +10% confidence")
            
            # VWAP confluence
            vwap_distance = abs(microstructure_data.get('vwap_distance', 999))
            if vwap_distance < 0.3:  # Within 0.3% of VWAP
                micro_bonus_qual += 10
                if self.app:
                    self.app.log(f"[MICRO] Near VWAP ({vwap_distance:.2f}%), +10% quality")
            
            # ORB alignment bonus
            or_data = microstructure_data.get('opening_range', {})
            if or_data.get('orb_triggered'):
                orb_direction = or_data.get('orb_direction')
                if (orb_direction == 'LONG' and signal_type == SignalType.BUY) or \
                   (orb_direction == 'SHORT' and signal_type == SignalType.SELL):
                    micro_bonus_conf += 15
                    micro_bonus_qual += 10
                    if self.app:
                        self.app.log(f"[MICRO] ORB alignment {orb_direction}, +15% conf, +10% qual")
            
            # High liquidity bonus
            if liquidity > 0.7:
                micro_bonus_qual += 5
                if self.app:
                    self.app.log(f"[MICRO] High liquidity {liquidity:.2f}, +5% quality")
            
            # Time-based quality
            if microstructure_data.get('is_high_quality_time', False):
                micro_bonus_conf += 5
                if self.app:
                    self.app.log(f"[MICRO] High quality time window, +5% confidence")
        
        confidence = min(90, confidence + micro_bonus_conf)
        signal_quality = min(95, signal_quality + micro_bonus_qual)
        
        # === COMPREHENSIVE SIGNAL DIAGNOSTICS ===
        if self.app:
            self.app.log("=" * 60)
            self.app.log(f"[SIGNAL DIAGNOSTICS] {signal_type.value} Signal Generated")
            self.app.log("=" * 60)
            
            # Core conditions
            self.app.log(f"📊 CORE CONDITIONS:")
            self.app.log(f"   • Bullish Count: {bullish_count}")
            self.app.log(f"   • Bearish Count: {bearish_count}")
            self.app.log(f"   • Direction: {'LONG' if bullish_count > bearish_count else 'SHORT'}")
            
            # Trend alignment
            self.app.log(f"📈 TREND ALIGNMENT:")
            self.app.log(f"   • Regime: {regime} ({regime_state.get('state', 'UNKNOWN')})")
            self.app.log(f"   • Trend Direction: {trend_direction}")
            self.app.log(f"   • Trend Filter: {'✅ PASSED' if regime_type != 'TREND' or not trend_direction or (signal_type.value == 'BUY' and trend_direction == 'UP') or (signal_type.value == 'SELL' and trend_direction == 'DOWN') else '❌ FAILED'}")
            
            # Pattern analysis
            self.app.log(f"🔍 PATTERNS DETECTED:")
            if patterns:
                for p in patterns:
                    self.app.log(f"   • {p.get('type', 'UNKNOWN')}: {p.get('direction', 'neutral')} (conf: {p.get('confidence', 0):.1f}%)")
            else:
                self.app.log(f"   • No patterns detected")
            
            # Structure breaks
            self.app.log(f"🏗️ STRUCTURE ANALYSIS:")
            if structure_breaks:
                for sb in structure_breaks:
                    self.app.log(f"   • {sb.get('type', 'UNKNOWN')}: {sb.get('direction', 'neutral')} (conf: {sb.get('confidence', 0):.1f}%)")
            else:
                self.app.log(f"   • No structure breaks")
            
            # Microstructure bonuses
            self.app.log(f"🔬 MICROSTRUCTURE BONUSES:")
            self.app.log(f"   • Confidence Bonus: +{micro_bonus_conf}%")
            self.app.log(f"   • Quality Bonus: +{micro_bonus_qual}%")
            if microstructure_data:
                self.app.log(f"   • Liquidity: {microstructure_data.get('liquidity_score', 0):.2f}")
                self.app.log(f"   • VWAP Distance: {microstructure_data.get('vwap_distance', 999):.2f}%")
                self.app.log(f"   • High Quality Time: {microstructure_data.get('is_high_quality_time', False)}")
            
            # Final metrics
            self.app.log(f"📋 FINAL METRICS:")
            self.app.log(f"   • Entry: {entry:.1f}")
            self.app.log(f"   • Stop Loss: {stop_loss:.1f} ({sl_distance:.1f} points)")
            self.app.log(f"   • Take Profit: {take_profit:.1f} ({tp_distance:.1f} points)")
            self.app.log(f"   • Risk/Reward: {rrr:.2f}:1")
            self.app.log(f"   • Quality Score: {signal_quality:.1f}%")
            self.app.log(f"   • Confidence: {confidence:.1f}%")
            self.app.log(f"   • ATR: {atr:.1f}")
            self.app.log("=" * 60)
        
        # Create final signal with microstructure and swing context
        signal = TradingSignal(
            signal_type=signal_type,
            entry=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            confidence=confidence,
            signal_quality=signal_quality,
            patterns=[f"{p.get('type', 'UNKNOWN')}_{p.get('direction', 'neutral').upper()}"
                    for p in patterns],
            timestamp=datetime.now(timezone.utc),
            price=current_price,
            structure_break=structure_breaks[0]['type'] if structure_breaks else None,
            regime_alignment=(regime == 'TREND'),
            risk_reward=rrr,
            atr=atr,
            regime_state=regime,
            swing_trend=swing_state.get('trend', 'NEUTRAL'),
            # Add microstructure data for analytics
            liquidity_score=microstructure_data.get('liquidity') if microstructure_data else None,
            volume_zscore=microstructure_data.get('volume_zscore') if microstructure_data else None,
            vwap_distance_pct=microstructure_data.get('vwap_distance_pct') if microstructure_data else None,
            orb_triggered=microstructure_data.get('orb_triggered', False) if microstructure_data else False,
            high_quality_time=microstructure_data.get('is_high_quality_time', False) if microstructure_data else False,
            # Add swing context for analytics
            swing_quality_score=swing_state.get('quality_score'),
            last_swing_high=swing_state.get('last_swing_high'),
            last_swing_low=swing_state.get('last_swing_low')
        )

        return signal
    
    def _log_rejection(self, reason: str, details: Dict = None):
        """Log why a signal was rejected with comprehensive diagnostics"""
        if not self.app:
            return
            
        self.app.log("─" * 60)
        self.app.log(f"❌ [SIGNAL REJECTED] {reason}")
        self.app.log("─" * 60)
        
        if details:
            for key, value in details.items():
                if isinstance(value, dict):
                    self.app.log(f"📊 {key.upper()}:")
                    for subkey, subvalue in value.items():
                        self.app.log(f"   • {subkey}: {subvalue}")
                else:
                    self.app.log(f"📊 {key}: {value}")
        
        self.app.log("─" * 60)
    
    def _log_validation_summary(self, bars: List[Dict], regime_state: Dict, 
                               swing_state: Dict, microstructure_data: Dict = None):
        """Log comprehensive validation summary - what was checked"""
        if not self.app:
            return
            
        self.app.log("🔍" * 20 + " VALIDATION SUMMARY " + "🔍" * 20)
        self.app.log(f"📊 BASIC CHECKS:")
        self.app.log(f"   ✅ Bars available: {len(bars)} (min: 20)")
        self.app.log(f"   ✅ ATR calculated: {self.current_atr:.2f}")
        self.app.log(f"   ✅ Cooldown check: {self._last_signal_bar_index} bars ago (min: {self.min_bars_between_signals})")
        
        self.app.log(f"📈 MARKET CONDITIONS:")
        regime = regime_state.get('state', 'UNKNOWN')
        adx = regime_state.get('adx', 0)
        trend_dir = regime_state.get('trend_direction')
        self.app.log(f"   • Regime: {regime} (ADX: {adx:.1f})")
        self.app.log(f"   • Trend Direction: {trend_dir}")
        
        swing_quality = swing_state.get('quality', 0)
        self.app.log(f"   • Swing Quality: {swing_quality:.1f}% (min: {self.min_swing_quality})")
        
        if microstructure_data:
            liquidity = microstructure_data.get('liquidity_score', 0)
            vwap_dist = microstructure_data.get('vwap_distance', 0)
            quality_time = microstructure_data.get('is_high_quality_time', False)
            atr_data = microstructure_data.get('atr_analysis', {})

            # Get min_liquidity from config
            min_liquidity = self.main_config.get('microstructure', {}).get('min_liquidity_score', 0.3)

            self.app.log(f"🔬 MICROSTRUCTURE:")
            self.app.log(f"   • Liquidity: {liquidity:.3f} (min: {min_liquidity:.2f})")
            self.app.log(f"   • VWAP Distance: {vwap_dist:.2f}%")
            self.app.log(f"   • Quality Time: {quality_time}")
            if atr_data:
                self.app.log(f"   • ATR Ratio: {atr_data.get('ratio', 1):.2f} (max: 2.0)")
                self.app.log(f"   • ATR Elevated: {atr_data.get('is_elevated', False)}")
        
        self.app.log("🔍" * 60)
    
    def _detect_patterns(self, bars: List[Dict], regime_state: Dict = None) -> List[Dict]:
        """Detect candlestick patterns"""
        patterns = []
        
        if len(bars) >= 3 and self.current_atr > 0:
            last_bar = bars[-1]
            prev_bar = bars[-2]
            prev_prev_bar = bars[-3]
            
            # Momentum detection
            move = last_bar['close'] - prev_prev_bar['close']
            move_atr = abs(move) / self.current_atr if self.current_atr > 0 else 0
            
            if move_atr > self.momentum_threshold_atr:
                direction = 'bullish' if move > 0 else 'bearish'
                patterns.append({
                    'type': 'MOMENTUM',
                    'direction': direction,
                    'bar_index': -1,
                    'price': last_bar['close'],
                    'strength': move_atr
                })
        
        # Check classic patterns
        for i in range(-3, 0):
            if abs(i) > len(bars):
                continue
            
            bar = bars[i]
            prev_bar = bars[i-1] if i-1 >= -len(bars) else None
            
            # Pin Bar
            pin = self._is_pin_bar(bar)
            if pin:
                patterns.append({
                    'type': PatternType.PIN_BAR,
                    'direction': pin,
                    'bar_index': i,
                    'price': bar['high'] if pin == 'bearish' else bar['low']
                })
            
            # Engulfing
            if prev_bar:
                eng = self._is_engulfing(prev_bar, bar)
                if eng:
                    patterns.append({
                        'type': PatternType.ENGULFING,
                        'direction': eng,
                        'bar_index': i,
                        'price': bar['close']
                    })
            
            # Inside Bar
            if prev_bar and self._is_inside_bar(prev_bar, bar):
                patterns.append({
                    'type': PatternType.INSIDE_BAR,
                    'direction': 'neutral',
                    'bar_index': i,
                    'price': bar['close']
                })
        
        return patterns
    
    def _is_pin_bar(self, bar: Dict) -> Optional[str]:
        """Detect pin bar pattern"""
        body = abs(bar['close'] - bar['open'])
        upper_wick = bar['high'] - max(bar['close'], bar['open'])
        lower_wick = min(bar['close'], bar['open']) - bar['low']
        total_range = bar['high'] - bar['low']
        
        if total_range == 0:
            return None
        
        if lower_wick > body * self.pin_bar_ratio and lower_wick > upper_wick * 1.5:
            if lower_wick / total_range > 0.5:
                return 'bullish'
        
        if upper_wick > body * self.pin_bar_ratio and upper_wick > lower_wick * 1.5:
            if upper_wick / total_range > 0.5:
                return 'bearish'
        
        return None
    
    def _is_engulfing(self, prev_bar: Dict, bar: Dict) -> Optional[str]:
        """Detect engulfing pattern"""
        prev_body = abs(prev_bar['close'] - prev_bar['open'])
        curr_body = abs(bar['close'] - bar['open'])
        
        if prev_body == 0:
            return None
        
        if curr_body < prev_body * self.engulfing_min_size:
            return None
        
        # Bullish engulfing
        if (prev_bar['close'] < prev_bar['open'] and
            bar['close'] > bar['open'] and
            bar['close'] > prev_bar['open']):
            return 'bullish'
        
        # Bearish engulfing
        if (prev_bar['close'] > prev_bar['open'] and
            bar['close'] < bar['open'] and
            bar['close'] < prev_bar['open']):
            return 'bearish'
        
        return None
    
    def _is_inside_bar(self, prev_bar: Dict, bar: Dict) -> bool:
        """Detect inside bar pattern"""
        return (bar['high'] <= prev_bar['high'] and 
                bar['low'] >= prev_bar['low'])
    
    def _check_structure_breaks(self, bars: List[Dict], 
                                swing_state: Dict, 
                                pivot_levels: Dict) -> List[Dict]:
        """Check for structure breaks"""
        breaks = []
        current_price = bars[-1]['close']
        
        lookback = self.swing_break_lookback
        last_high = swing_state.get('last_high')
        last_low = swing_state.get('last_low')
        
        if last_high is None and len(bars) >= lookback:
            last_high = max(b['high'] for b in bars[-lookback:])
        if last_low is None and len(bars) >= lookback:
            last_low = min(b['low'] for b in bars[-lookback:])
        
        # Swing breaks
        if last_high and current_price > last_high:
            breaks.append({
                'type': 'SWING_HIGH_BREAK',
                'level': last_high,
                'direction': 'bullish'
            })
        
        if last_low and current_price < last_low:
            breaks.append({
                'type': 'SWING_LOW_BREAK',
                'level': last_low,
                'direction': 'bearish'
            })
        
        # Pivot tests
        tolerance = self.current_atr * 0.3
        
        for level_name, level_value in (pivot_levels or {}).items():
            if isinstance(level_value, (int, float)) and abs(current_price - level_value) <= tolerance:
                breaks.append({
                    'type': f'PIVOT_{level_name}_TEST',
                    'level': level_value,
                    'direction': 'neutral'
                })
        
        return breaks
    
    def _calculate_atr(self, bars: List[Dict], period: int = 14) -> float:
        """Calculate ATR - handles data where bars contain full prices"""
        if len(bars) < period + 1:
            return 0.0
        
        # Detekce, jestli pracujeme s M5 bary pro indexy (DAX/NASDAQ)
        # Tyto trhy se obvykle pohybují 20-100 bodů za M5 bar
        
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
        
        if len(tr_values) >= period:
            raw_atr = sum(tr_values[-period:]) / float(period)
        else:
            raw_atr = sum(tr_values) / float(len(tr_values)) if tr_values else 0.0
        
        # Detekce cenového rozsahu pro určení správného ATR
        if len(bars) > 0:
            current_price = bars[-1]['close']
            
            # Pro indexy (DAX ~26000, NASDAQ ~26000)
            if current_price > 20000:
                # ATR je v bodech, ale data přišla jako celkový pohyb
                # Typické M5 ATR pro indexy je 20-50 bodů
                
                # Pokud raw_atr vypadá jako celý rozsah (> 1000), 
                # pravděpodobně máme špatná data
                if raw_atr > 500:
                    # Pro M5 timeframe použít realistické hodnoty
                    if current_price > 25000:  # DAX
                        return 30.0  # Typické ATR pro DAX M5
                    else:
                        return 40.0  # Typické ATR pro NASDAQ M5
                
                # Jinak ATR vypadá rozumně
                return raw_atr
            
            # Pro jiné instrumenty
            else:
                # Zde by měla být jiná logika podle typu instrumentu
                return min(raw_atr, 100.0)  # Cap na rozumnou hodnotu
        
        # Fallback
        return min(raw_atr, 50.0)
    
    def is_quality_trading_time(self, symbol: str, micro_data: Dict) -> bool:
        """
        Check if current time is optimal for trading
        
        Returns:
            True if time is good for trading, False otherwise
        """
        # Check liquidity score - read from config
        min_liquidity = self.main_config.get('microstructure', {}).get('min_liquidity_score', 0.1)
        if micro_data.get('liquidity_score', 0) < min_liquidity:
            return False
        
        # Check if it's high quality time
        if not micro_data.get('is_high_quality_time', False):
            return False
        
        # Symbol-specific time windows
        from datetime import datetime
        now = datetime.now()
        hour = now.hour
        
        if 'DAX' in symbol.upper() or 'DE40' in symbol.upper():
            # DAX quality hours: 9:00-14:30 CET
            return (9 <= hour < 14) or (hour == 14 and now.minute <= 30)
        elif 'NASDAQ' in symbol.upper() or 'US100' in symbol.upper():
            # NASDAQ quality hours: 14:30-22:00 CET
            return (hour == 14 and now.minute >= 30) or (15 <= hour <= 22)
        
        return True
    
    def calculate_microstructure_score(self, micro_data: Dict) -> float:
        """
        Calculate additional signal score based on microstructure
        
        Returns:
            Score 0-100 based on microstructure conditions
        """
        if not micro_data:
            return 0
            
        score = 0
        
        # Liquidity component (0-30)
        liquidity = micro_data.get('liquidity_score', 0.5)
        score += liquidity * 30
        
        # Volume component (0-20)
        vol_z = abs(micro_data.get('volume_zscore', 0))
        if vol_z > 2:
            score += 20
        elif vol_z > 1:
            score += 10
        
        # VWAP component (0-20)
        vwap_dist = abs(micro_data.get('vwap_distance', 5))
        if vwap_dist < 0.2:
            score += 20
        elif vwap_dist < 0.5:
            score += 10
        
        # ORB component (0-30)
        or_data = micro_data.get('opening_range', {})
        if or_data.get('orb_triggered'):
            score += 30
        elif or_data.get('or_high') and or_data.get('or_low'):
            # Inside OR range
            score += 15
        
        return min(score, 100)
    
    def check_orb_setup(self, bars: List[Dict], micro_data: Dict) -> Optional[Dict]:
        """
        Check for Opening Range Breakout setup
        
        Returns:
            ORB signal dict or None
        """
        if not micro_data:
            return None
            
        or_data = micro_data.get('opening_range', {})
        
        if not or_data.get('orb_triggered'):
            return None
        
        current_price = bars[-1]['close']
        orb_direction = or_data.get('orb_direction')
        
        if orb_direction == 'LONG':
            return {
                'type': 'BUY',
                'pattern': 'ORB_LONG',
                'entry': or_data['or_high'],
                'stop': or_data['or_low'],
                'confidence_boost': 20
            }
        elif orb_direction == 'SHORT':
            return {
                'type': 'SELL',
                'pattern': 'ORB_SHORT',
                'entry': or_data['or_low'],
                'stop': or_data['or_high'],
                'confidence_boost': 20
            }
        
        return None


    def log(self, message: str):
        """Helper for logging"""
        if self.app:
            self.app.log(f"[EDGE] {message}")