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
from .logging_config import LoggingConfig, LogLevel

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
        
        # Initialize logging config
        logging_config = self.main_config.get('logging', {})
        self.logging = LoggingConfig(logging_config)
        
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
        # STRICT regime filter - lze vypnout pro backtesting
        self.strict_regime_filter = self.config.get('strict_regime_filter', True)  # Default: True (produkce)
        
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
        
        current_bar_index = len(bars) - 1
        current_price = bars[-1]['close'] if bars else 0
        regime_type = regime_state.get('state', 'UNKNOWN')
        
        # Always log signal detection attempt
        if self.app:
            self.app.log(f"🔍 [SIGNAL_DETECT] Starting signal detection - bars={len(bars)}, price={current_price:.2f}, regime={regime_type}")
        
        if len(bars) < 20:
            self._log_rejection("Insufficient bars for analysis", {
                "bars_available": len(bars),
                "minimum_required": 20
            })
            return []
        
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
        
        if self.app:
            self.app.log(f"📊 [SIGNAL_DETECT] ATR={self.current_atr:.2f}, Cooldown OK, Bars OK")
        
        # === STRICT REGIME FILTER: REGIME MUSÍ BÝT TREND A EMA34 TAKÉ ===
        # Oba musí souhlasit - regime TREND a EMA34 trend ve stejném směru
        # Lze vypnout přes config: strict_regime_filter: false (pro backtesting)
        if self.strict_regime_filter:
            regime_type = regime_state.get('state', 'UNKNOWN')
            regime_regime = regime_state.get('regime', regime_type)  # Fallback na 'state'
            trend_direction = regime_state.get('trend_direction')
            
            # Kontrola EMA34 trendu
            ema34_trend = self._get_ema34_trend(bars)
            
            # STRICT: Regime MUSÍ být TREND_UP nebo TREND_DOWN
            regime_is_trend = (
                regime_type.upper() in ['TREND_UP', 'TREND_DOWN'] or 
                regime_regime.upper() in ['TREND_UP', 'TREND_DOWN']
            )
            
            # STRICT: EMA34 MUSÍ ukazovat trend (UP nebo DOWN)
            ema34_has_trend = ema34_trend and ema34_trend.upper() in ['UP', 'DOWN']
            
            # STRICT: Oba musí souhlasit ve směru
            directions_match = False
            if regime_is_trend and ema34_has_trend:
                # Zkontrolovat, zda směry souhlasí
                regime_direction = None
                if regime_type.upper() == 'TREND_UP' or regime_regime.upper() == 'TREND_UP':
                    regime_direction = 'UP'
                elif regime_type.upper() == 'TREND_DOWN' or regime_regime.upper() == 'TREND_DOWN':
                    regime_direction = 'DOWN'
                elif trend_direction and trend_direction.upper() in ['UP', 'DOWN']:
                    regime_direction = trend_direction.upper()
                
                if regime_direction and ema34_trend.upper() == regime_direction:
                    directions_match = True
            
            # Povolit signály jen pokud OBA podmínky jsou splněny
            rejection_reason = []  # Inicializovat před použitím
            if not (regime_is_trend and ema34_has_trend and directions_match):
                # Blokovat všechny signály
                if not regime_is_trend:
                    rejection_reason.append(f"Regime is not TREND (current: {regime_type}/{regime_regime})")
                if not ema34_has_trend:
                    rejection_reason.append(f"EMA34 does not show trend (current: {ema34_trend})")
                if regime_is_trend and ema34_has_trend and not directions_match:
                    rejection_reason.append(f"Directions don't match (regime: {trend_direction}, EMA34: {ema34_trend})")
                
                # Always log strict filter rejection (removed throttling for visibility)
                if self.app:
                    self.app.log(f"🚫 [STRICT_FILTER] BLOCKED: regime={regime_type}, EMA34={ema34_trend}, reasons={', '.join(rejection_reason)}")
                
                self._log_rejection("STRICT Regime filter: Both regime and EMA34 must be in TREND", {
                    "regime_type": regime_type,
                    "regime_regime": regime_regime,
                    "trend_direction": trend_direction,
                    "ema34_trend": ema34_trend,
                    "regime_is_trend": regime_is_trend,
                    "ema34_has_trend": ema34_has_trend,
                    "directions_match": directions_match,
                    "reasons": rejection_reason,
                    "rule": "Signals only generated when BOTH regime=TREND AND EMA34=trend (same direction)"
                })
                return []
            else:
                # Strict filter prošel - logovat vždy
                if self.app:
                    self.app.log(f"✅ [STRICT_FILTER] PASSED: regime={regime_type}, EMA34={ema34_trend}, directions_match=True")
        
        # Log what we're checking (periodically, not every bar)
        if self.app and (current_bar_index % 12 == 0):  # Every 12 bars = 1 hour on M5
            self._log_validation_summary(bars, regime_state, swing_state, microstructure_data)
        
        # Check swing quality
        swing_quality = swing_state.get('quality', 0)
        if swing_quality < self.min_swing_quality:
            regime = regime_state.get('state', 'UNKNOWN')
            adx = regime_state.get('adx', 0)
            if not (regime == 'TREND' and adx > 25):
                if self.app:
                    self.app.log(f"🚫 [SWING_QUALITY] BLOCKED: {swing_quality:.1f}% < {self.min_swing_quality:.1f}%, regime={regime}, ADX={adx:.1f}")
                self._log_rejection("Low swing quality", {
                    "current_swing_quality": f"{swing_quality:.1f}%",
                    "minimum_required": f"{self.min_swing_quality:.1f}%",
                    "regime": regime,
                    "adx": f"{adx:.1f}",
                    "trend_exception": f"Not strong trend (ADX > 25): {adx <= 25}"
                })
                return []
        else:
            # Swing quality OK - logovat vždy
            if self.app:
                self.app.log(f"✅ [SWING_QUALITY] PASSED: {swing_quality:.1f}% >= {self.min_swing_quality:.1f}%")
        
        # === PULLBACK DETECTION (Priority 1) ===
        # Check for high-quality pullback opportunities in strong trends
        if self.app:
            self.app.log(f"🔍 [PULLBACK_CHECK] Checking for pullback opportunities...")
        
        pullback_opportunity = self.pullback_detector.detect_pullback_opportunity(
            bars, regime_state, swing_state, pivot_levels, microstructure_data
        )
        
        if pullback_opportunity:
            if self.app:
                self.app.log(f"✅ [PULLBACK] Opportunity found: {pullback_opportunity.get('pullback_type', 'UNKNOWN')}, quality={pullback_opportunity.get('quality_score', 0):.0f}%")
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
        # V trendech: provést standardní detekci jen pokud jsme v pullback zóně
        # V RANGE: také kontrolovat swing extrémy
        
        # === EMA(34) TREND CHECK - PŘED KONTROLOU PULLBACK ZÓNY ===
        # Pokud regime říká RANGE, ale EMA34 ukazuje trend, použijeme EMA trend
        trend_direction = regime_state.get('trend_direction')
        ema34_trend = self._get_ema34_trend(bars)
        if ema34_trend:
            # Pokud regime říká RANGE/SIDEWAYS, ale EMA34 ukazuje trend → použijeme EMA trend
            if not trend_direction or trend_direction.upper() in ['SIDEWAYS', 'RANGE']:
                trend_direction = ema34_trend
                if self.app:
                    self.app.log(f"[TREND] Regime={regime_state.get('trend_direction', 'UNKNOWN')} but EMA34={ema34_trend} → Using EMA34 for pullback check")
        
        # Pokud jsme v trendu a nejsme v pullback zóně, přeskočit standardní detekci
        if trend_direction and trend_direction.upper() in ['UP', 'DOWN']:
            if not self._is_in_pullback_zone(bars, swing_state, trend_direction):
                if self.app:
                    self.app.log(f"⏭️ [PATTERN_DETECT] Skipping - not in pullback zone (trend: {trend_direction})")
                return signals  # Vrátit prázdný seznam - žádné signály mimo pullback v trendu
        
        # V RANGE režimu kontroly swing extrémů proběhnou v _evaluate_confluence_wide_stops()
        if self.app:
            self.app.log(f"🔍 [PATTERN_DETECT] Checking for patterns and structure breaks...")
        
        patterns = self._detect_patterns(bars, regime_state)
        
        # Check structure breaks
        structure_breaks = self._check_structure_breaks(bars, swing_state, pivot_levels)
        
        if self.app:
            pattern_count = len(patterns) if patterns else 0
            break_count = len(structure_breaks) if structure_breaks else 0
            self.app.log(f"📊 [PATTERN_DETECT] Found {pattern_count} pattern(s), {break_count} structure break(s)")
        
        # Evaluate confluence
        if patterns or structure_breaks:
            signal = self._evaluate_confluence_wide_stops(
                bars, patterns, structure_breaks,
                regime_state, pivot_levels, swing_state, microstructure_data
            )
            
            if signal:
                # Always log signal quality check
                if self.app:
                    self.app.log(f"🔍 [SIGNAL_QUALITY] Signal generated: quality={signal.signal_quality:.1f}% (min: {self.min_signal_quality}%), confidence={signal.confidence:.1f}% (min: {self.min_confidence}%)")
                
                if signal.signal_quality >= self.min_signal_quality and \
                   signal.confidence >= self.min_confidence:
                    if self.app:
                        self.app.log(f"✅ [SIGNAL_GENERATED] Signal passed quality check: {signal.signal_type.value if hasattr(signal.signal_type, 'value') else str(signal.signal_type)} @ {signal.entry:.2f}")
                    signals.append(signal)
                    self.last_signal = signal
                    self._last_signal_bar_index = current_bar_index
                else:
                    # Logovat, proč byl signál odmítnut kvůli kvalitě
                    reasons = []
                    if signal.signal_quality < self.min_signal_quality:
                        reasons.append(f"Quality {signal.signal_quality:.1f}% < {self.min_signal_quality}%")
                    if signal.confidence < self.min_confidence:
                        reasons.append(f"Confidence {signal.confidence:.1f}% < {self.min_confidence}%")
                    if self.app:
                        self.app.log(f"🚫 [SIGNAL_QUALITY] BLOCKED: {', '.join(reasons)}")
                    if reasons:
                        self._log_rejection("Signal quality/confidence below threshold", {
                            "signal_quality": f"{signal.signal_quality:.1f}%",
                            "min_signal_quality": f"{self.min_signal_quality}%",
                            "signal_confidence": f"{signal.confidence:.1f}%",
                            "min_confidence": f"{self.min_confidence}%",
                            "reasons": ", ".join(reasons),
                            "signal_type": signal.signal_type.value if hasattr(signal.signal_type, 'value') else str(signal.signal_type)
                        })
            else:
                if self.app:
                    self.app.log(f"🚫 [SIGNAL_GENERATED] No signal from confluence evaluation (patterns/structure breaks found but no valid signal)")
        
        # Summary log
        if self.app:
            if signals:
                self.app.log(f"✅ [SIGNAL_DETECT] SUCCESS: {len(signals)} signal(s) generated")
            else:
                self.app.log(f"⏸️ [SIGNAL_DETECT] No signals generated (all filters passed but no valid signals)")
        
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
        
        # === FALSE BREAKOUT FILTER ===
        # Pro samotné breakouts (ne retest) vyžadovat volume confirmation
        # Retest je silnější, takže může projít i bez volume
        validated_breaks = []
        for sb in structure_breaks:
            if 'RETEST' in sb.get('type', ''):
                # Retest může projít i bez volume (je silnější)
                validated_breaks.append(sb)
            elif sb.get('validated', False):
                # Samotný breakout musí mít volume confirmation
                if microstructure_data:
                    volume_zscore = microstructure_data.get('volume_zscore', 0)
                    if volume_zscore >= 1.0:
                        validated_breaks.append(sb)
                        if self.app and self.logging.should_log('breakout', f"validated:{sb.get('type')}"):
                            self.app.log(f"[BREAKOUT_VALIDATION] ✅ Breakout validated: {sb.get('type')} with volume zscore {volume_zscore:.2f}")
                    else:
                        if self.app and self.logging.should_log('breakout', f"low_volume:{sb.get('type')}"):
                            self.app.log(f"[FALSE_BREAKOUT] ❌ Blocking breakout {sb.get('type')}: Low volume (zscore: {volume_zscore:.2f} < 1.0)")
                else:
                    # Bez microstructure data - blokovat (nebezpečné)
                    if self.app and self.logging.should_log('breakout', f"no_microdata:{sb.get('type')}"):
                        self.app.log(f"[FALSE_BREAKOUT] ❌ Blocking breakout {sb.get('type')}: No microstructure data for volume validation")
            else:
                # Nevalidovaný breakout - přidat (pro zpětnou kompatibilitu, ale s nižší confidence)
                validated_breaks.append(sb)
        
        # Použít pouze validované breakouts
        structure_breaks = validated_breaks
        structure_count = len(structure_breaks)
        
        # === BREAKOUT RETEST BONUS ===
        # Retest po breakoutu je silnější signál - přidat bonus
        retest_bonus = 0
        for sb in structure_breaks:
            if 'RETEST' in sb.get('type', ''):
                retest_bonus += 15  # Retest je silnější než samotný breakout
                if self.app and self.logging.should_log('breakout', f"retest:{sb.get('type')}"):
                    self.app.log(f"[BREAKOUT_RETEST] ✅ Retest detected: {sb.get('type')} at {sb.get('level', 0):.1f}")
        
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
        
        # === EMA(34) TREND CHECK - PRIORITA PRO RANGE REŽIM ===
        # Pokud regime detekuje RANGE, ale EMA34 ukazuje jasný trend, použijeme EMA trend
        # EMA34 je spolehlivější pro detekci aktuálního trendu než regime detector
        ema34_trend = self._get_ema34_trend(bars)
        if ema34_trend:
            # Pokud regime říká RANGE/SIDEWAYS, ale EMA34 ukazuje trend → použijeme EMA trend
            # To je důležité, protože regime detector může být příliš konzervativní
            if not trend_direction or trend_direction.upper() in ['SIDEWAYS', 'RANGE']:
                # Regime říká RANGE/SIDEWAYS, ale EMA34 ukazuje jasný trend → použijeme EMA trend
                trend_direction = ema34_trend
                if self.app:
                    self.app.log(f"[TREND] Regime={regime_state.get('trend_direction', 'UNKNOWN')} but EMA34={ema34_trend} → Using EMA34 trend as primary")
            elif trend_direction and trend_direction.upper() in ['UP', 'DOWN'] and trend_direction.upper() != ema34_trend:
                # Konflikt mezi regime trendem (UP/DOWN) a EMA trendem
                # Preferujeme EMA trend jako primární (je aktuálnější a spolehlivější)
                if self.app:
                    self.app.log(f"[TREND] ⚠️ Trend conflict: Regime={trend_direction}, EMA34={ema34_trend} - using EMA34 as primary")
                trend_direction = ema34_trend
        
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
            
            # === BLOCK SIGNALS AT SWING EXTREMES IN TRENDS ===
            # V trendech generujeme signály jen na pullbacku, ne na vrcholu swingu
            if self._is_at_swing_extreme(bars, swing_state, trend_direction):
                self._log_rejection("Trend filter: Signal at swing extreme (pullback required)", {
                    "signal_direction": "BUY" if signal_wants_buy else "SELL",
                    "trend_direction": trend_direction,
                    "regime_type": regime_type,
                    "adx": adx_value,
                    "reason": "In trends, signals only allowed on pullbacks, not at swing extremes",
                    "swing_state": {
                        "last_high": swing_state.get('last_high'),
                        "last_low": swing_state.get('last_low')
                    }
                })
                return None
            
            # === REQUIRE PULLBACK ZONE FOR TREND SIGNALS ===
            # Zkontrolujeme, zda je cena v pullback zóně (ne na vrcholu)
            if not self._is_in_pullback_zone(bars, swing_state, trend_direction):
                self._log_rejection("Trend filter: Signal not in pullback zone", {
                    "signal_direction": "BUY" if signal_wants_buy else "SELL",
                    "trend_direction": trend_direction,
                    "regime_type": regime_type,
                    "current_price": current_price,
                    "reason": "In trends, signals only allowed in pullback zones",
                    "swing_state": {
                        "last_high": swing_state.get('last_high'),
                        "last_low": swing_state.get('last_low')
                    }
                })
                return None
            
            # If we get here, signal is in trend direction and in pullback zone - ALLOW
        else:
            # === RANGE/SIDEWAYS: Still block signals at swing extremes ===
            # I v RANGE režimu nechceme vstupovat na swing extrémech
            # Pro BUY: blokovat pokud je na swing high
            # Pro SELL: blokovat pokud je na swing low
            if signal_wants_buy:
                # BUY signál v RANGE - blokovat pokud je na swing high
                if self._is_at_swing_extreme_for_range(bars, swing_state, 'BUY'):
                    self._log_rejection("Range filter: BUY signal at swing high (extreme blocked)", {
                        "signal_direction": "BUY",
                        "regime_type": regime_type,
                        "adx": adx_value,
                        "current_price": current_price,
                        "reason": "In range markets, BUY signals blocked at swing highs",
                        "swing_state": {
                            "last_high": swing_state.get('last_high'),
                            "last_low": swing_state.get('last_low')
                        }
                    })
                    return None
            elif signal_wants_sell:
                # SELL signál v RANGE - blokovat pokud je na swing low
                if self._is_at_swing_extreme_for_range(bars, swing_state, 'SELL'):
                    self._log_rejection("Range filter: SELL signal at swing low (extreme blocked)", {
                        "signal_direction": "SELL",
                        "regime_type": regime_type,
                        "adx": adx_value,
                        "current_price": current_price,
                        "reason": "In range markets, SELL signals blocked at swing lows",
                        "swing_state": {
                            "last_high": swing_state.get('last_high'),
                            "last_low": swing_state.get('last_low')
                        }
                    })
                    return None
        
        # === SET FINAL LEVELS ===
        
        if bullish_count > bearish_count:  # BUY SIGNAL
            signal_type = SignalType.BUY
            entry = current_price
            stop_loss = entry - sl_distance
            take_profit = entry + tp_distance
            
            # Optional: Adjust TP to pivot level if close (prioritize R2, then R1)
            if pivot_levels:
                # Try R2 first (stronger level)
                r2 = pivot_levels.get('r2', 0)
                r1 = pivot_levels.get('r1', 0)
                
                # Check R2 first
                if r2 and r2 > entry:
                    distance_to_r2 = r2 - entry
                    if distance_to_r2 > sl_distance * 1.5 and distance_to_r2 < tp_distance * 1.5:
                        take_profit = r2 - (atr * 0.1)  # Just before R2
                        tp_distance = take_profit - entry
                        if self.app:
                            self.app.log(f"[PIVOT_TP] Adjusted TP to R2: {take_profit:.2f} (distance: {distance_to_r2:.2f})")
                # Fallback to R1 if R2 is too far or not available
                elif r1 and r1 > entry:
                    distance_to_r1 = r1 - entry
                    if distance_to_r1 > sl_distance * 1.5 and distance_to_r1 < tp_distance * 1.5:
                        take_profit = r1 - (atr * 0.1)  # Just before R1
                        tp_distance = take_profit - entry
                        if self.app:
                            self.app.log(f"[PIVOT_TP] Adjusted TP to R1: {take_profit:.2f} (distance: {distance_to_r1:.2f})")
                        
        else:  # SELL SIGNAL
            signal_type = SignalType.SELL
            entry = current_price
            stop_loss = entry + sl_distance
            take_profit = entry - tp_distance
            
            # Optional: Adjust TP to pivot level if close (prioritize S2, then S1)
            if pivot_levels:
                # Try S2 first (stronger level)
                s2 = pivot_levels.get('s2', 0)
                s1 = pivot_levels.get('s1', 0)
                
                # Check S2 first
                if s2 and s2 < entry:
                    distance_to_s2 = entry - s2
                    if distance_to_s2 > sl_distance * 1.5 and distance_to_s2 < tp_distance * 1.5:
                        take_profit = s2 + (atr * 0.1)  # Just after S2
                        tp_distance = entry - take_profit
                        if self.app:
                            self.app.log(f"[PIVOT_TP] Adjusted TP to S2: {take_profit:.2f} (distance: {distance_to_s2:.2f})")
                # Fallback to S1 if S2 is too far or not available
                elif s1 and s1 < entry:
                    distance_to_s1 = entry - s1
                    if distance_to_s1 > sl_distance * 1.5 and distance_to_s1 < tp_distance * 1.5:
                        take_profit = s1 + (atr * 0.1)  # Just after S1
                        tp_distance = entry - take_profit
                        if self.app:
                            self.app.log(f"[PIVOT_TP] Adjusted TP to S1: {take_profit:.2f} (distance: {distance_to_s1:.2f})")

        # === CALCULATE INITIAL QUALITY SCORE ===
        signal_quality = 60  # Base quality
        swing_quality_score = swing_state.get('quality', 50)
        if swing_quality_score > 60:
            signal_quality += 15
        
        # === PIVOT CONFLUENCE BONUS ===
        # Pivot pointy jsou velmi významné úrovně - přidat bonus pokud je cena blízko
        if pivot_levels:
            pivot_confluence_bonus = 0
            current_price = bars[-1]['close']
            tolerance = atr * 0.3  # 0.3 ATR tolerance pro pivot confluence
            
            # Zkontrolovat, zda je cena blízko nějakého pivot pointu
            for level_name, level_price in pivot_levels.items():
                if isinstance(level_price, (int, float)) and level_price > 0:
                    distance = abs(current_price - level_price)
                    if distance <= tolerance:
                        # Pivot pointy mají různou váhu podle významnosti
                        if level_name.upper() == 'PIVOT':
                            pivot_confluence_bonus += 20  # Pivot je nejvýznamnější
                        elif level_name.upper() in ['R1', 'S1']:
                            pivot_confluence_bonus += 15  # R1/S1 jsou silné
                        elif level_name.upper() in ['R2', 'S2']:
                            pivot_confluence_bonus += 10  # R2/S2 jsou střední
                        else:
                            pivot_confluence_bonus += 8  # Ostatní pivoty
            
            if pivot_confluence_bonus > 0:
                signal_quality += pivot_confluence_bonus
                if self.app:
                    self.app.log(f"[PIVOT_CONFLUENCE] ✅ Price near pivot level, +{pivot_confluence_bonus} quality bonus")

        # === CALCULATE METRICS ===

        sl_pips = sl_distance * 100  # FIXED: 1 point = 100 pips for DAX/NASDAQ
        tp_pips = tp_distance * 100  # FIXED: 1 point = 100 pips for DAX/NASDAQ
        rrr = tp_distance / sl_distance if sl_distance > 0 else 0

        # Validate minimum RRR (initial check) - PHASE 1: Use config value
        min_rrr_required = self.min_rr_ratio  # From config (2.0 after PHASE 1)
        if rrr < min_rrr_required:
            self._log_rejection("Risk/Reward ratio too low", {
                "calculated_rrr": f"{rrr:.2f}",
                "minimum_required": f"{min_rrr_required:.2f}",
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
        
        # Add retest bonus (if applicable)
        signal_quality += retest_bonus
        
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
            
            # Pivot levels
            self.app.log(f"📊 PIVOT LEVELS:")
            if pivot_levels:
                current_price = bars[-1]['close']
                atr = self.current_atr
                tolerance = atr * 0.3
                for level_name, level_price in pivot_levels.items():
                    if isinstance(level_price, (int, float)) and level_price > 0:
                        distance = abs(current_price - level_price)
                        distance_atr = distance / atr if atr > 0 else 999
                        status = "✅ NEAR" if distance <= tolerance else "   "
                        self.app.log(f"   {status} {level_name}: {level_price:.2f} (distance: {distance:.2f} = {distance_atr:.2f} ATR)")
            else:
                self.app.log(f"   • No pivot levels available")
            
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
        
        # Check if should log based on log level and throttling
        message_key = f"{reason}:{str(details.get('regime_type', ''))}:{str(details.get('signal_direction', ''))}"
        
        # === BYPASS THROTTLING FOR STRICT REGIME FILTER ===
        # Always log strict regime filter rejections (critical for debugging)
        if "STRICT Regime filter" in reason:
            # Always log - bypass throttling
            pass  # Continue to log
        elif not self.logging.should_log('rejection', message_key):
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
    
    def _get_ema34_trend(self, bars: List[Dict]) -> Optional[str]:
        """
        Získá trend směr pomocí EMA(34)
        
        Args:
            bars: OHLC data
            
        Returns:
            'UP' pokud cena > EMA(34), 'DOWN' pokud cena < EMA(34), None pokud nedostatek dat
        """
        if len(bars) < 34:
            if self.app and hasattr(self, '_ema34_debug_count'):
                self._ema34_debug_count = getattr(self, '_ema34_debug_count', 0) + 1
                if self._ema34_debug_count % 100 == 0:
                    self.app.log(f"[EMA34] Insufficient bars: {len(bars)} < 34")
            return None
            
        try:
            # Vypočítat EMA(34)
            ema34 = self._calculate_ema(bars, 34)
            if ema34 == 0 or ema34 is None:
                if self.app and hasattr(self, '_ema34_zero_count'):
                    self._ema34_zero_count = getattr(self, '_ema34_zero_count', 0) + 1
                    if self._ema34_zero_count % 100 == 0:
                        self.app.log(f"[EMA34] EMA34 calculation returned 0 or None (bars: {len(bars)})")
                return None
                
            current_price = bars[-1].get('close', 0)
            if current_price == 0:
                return None
            
            # Tolerance: 0.1% od EMA pro "exactly at EMA" situaci
            tolerance = ema34 * 0.001
            
            # Debug: logovat občas pro diagnostiku
            if self.app and hasattr(self, '_ema34_debug_logged'):
                debug_count = getattr(self, '_ema34_debug_logged', 0)
                if debug_count % 200 == 0:  # Každých 200 barů
                    self.app.log(f"[EMA34 DEBUG] Price: {current_price:.2f}, EMA34: {ema34:.2f}, Diff: {abs(current_price - ema34):.2f}, Tolerance: {tolerance:.2f}")
                self._ema34_debug_logged = debug_count + 1
            else:
                if self.app:
                    self._ema34_debug_logged = 1
            
            if current_price > ema34 + tolerance:
                result = 'UP'
            elif current_price < ema34 - tolerance:
                result = 'DOWN'
            else:
                # Cena je velmi blízko EMA34 - použít menší toleranci nebo rozhodnout podle momentum
                # Pokud je cena přesně na EMA, použít momentum z posledních 2-3 barů
                if len(bars) >= 3:
                    recent_momentum = bars[-1]['close'] - bars[-3]['close']
                    if recent_momentum > tolerance:
                        result = 'UP'
                    elif recent_momentum < -tolerance:
                        result = 'DOWN'
                    else:
                        result = None  # Cena je na EMA a momentum je neutrální
                else:
                    result = None  # Cena je na EMA - trend nejasný
            
            return result
                
        except Exception as e:
            if self.app:
                self.app.log(f"[TREND] Error calculating EMA34 trend: {e}")
                import traceback
                self.app.log(traceback.format_exc())
            return None
    
    def _calculate_ema(self, bars: List[Dict], period: int) -> float:
        """
        Vypočítá Exponential Moving Average
        
        Args:
            bars: OHLC data
            period: EMA period (např. 34)
            
        Returns:
            EMA hodnota
        """
        if len(bars) < period:
            return 0.0
        
        # Ověřit, že máme validní close hodnoty
        closes = [bar.get('close', 0) for bar in bars[:period]]
        if not closes or all(c == 0 for c in closes):
            return 0.0
            
        # Multiplier pro EMA
        multiplier = 2.0 / (period + 1.0)
        
        # Začneme s SMA (průměr z prvních 'period' barů)
        sma_sum = sum(closes)
        if sma_sum == 0:
            return 0.0
        ema = sma_sum / period
        
        # Aplikujeme EMA na zbývající bary
        for bar in bars[period:]:
            close = bar.get('close', 0)
            if close > 0:
                ema = (close * multiplier) + (ema * (1.0 - multiplier))
            # Pokud close == 0, použijeme předchozí EMA (není ideální, ale lepší než 0)
                
        return ema
    
    def _calculate_rsi(self, bars: List[Dict], period: int = 14) -> float:
        """
        Vypočítá Relative Strength Index (RSI)
        
        Args:
            bars: OHLC data
            period: RSI period (default 14)
            
        Returns:
            RSI hodnota (0-100)
        """
        if len(bars) < period + 1:
            return 50.0  # Neutral RSI pokud nedostatek dat
        
        gains = []
        losses = []
        
        # Vypočítat změny
        for i in range(1, len(bars)):
            change = bars[i].get('close', 0) - bars[i-1].get('close', 0)
            if change > 0:
                gains.append(change)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(change))
        
        if len(gains) < period:
            return 50.0
        
        # Průměrný zisk a ztráta (Wilder's smoothing)
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100.0  # Perfect uptrend
        
        # RSI calculation
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def _check_rsi_pullback_confirmation(self, bars: List[Dict], trend_direction: str) -> Tuple[bool, str]:
        """
        Zkontroluje, zda RSI potvrzuje pullback vstup
        
        Args:
            bars: OHLC data
            trend_direction: 'UP', 'DOWN', nebo 'SIDEWAYS'
            
        Returns:
            Tuple (is_confirmed, reason)
        """
        rsi = self._calculate_rsi(bars, 14)
        
        if trend_direction == 'UP':
            # V uptrendu: RSI by měl být 40-60 (zdravý pullback, ne oversold)
            # Oversold (<30) může signalizovat slabost trendu
            if rsi < 30:
                return False, f"RSI too oversold ({rsi:.1f}) - possible weak trend"
            if rsi > 70:
                return False, f"RSI overbought ({rsi:.1f}) - not a pullback"
            if 40 <= rsi <= 60:
                return True, f"RSI in ideal pullback zone ({rsi:.1f})"
            # RSI 30-40 nebo 60-70 je OK, ale ne ideální
            return True, f"RSI acceptable ({rsi:.1f})"
            
        elif trend_direction == 'DOWN':
            # V downtrendu: RSI by měl být 40-60 (zdravý pullback, ne overbought)
            if rsi > 70:
                return False, f"RSI too overbought ({rsi:.1f}) - possible weak trend"
            if rsi < 30:
                return False, f"RSI oversold ({rsi:.1f}) - not a pullback"
            if 40 <= rsi <= 60:
                return True, f"RSI in ideal pullback zone ({rsi:.1f})"
            # RSI 30-40 nebo 60-70 je OK, ale ne ideální
            return True, f"RSI acceptable ({rsi:.1f})"
        
        # SIDEWAYS - povolit
        return True, f"RSI neutral ({rsi:.1f}) - sideways market"
    
    def _is_at_swing_extreme_for_range(self, bars: List[Dict], swing_state: Dict, signal_direction: str) -> bool:
        """
        Kontrola swing extrému pro RANGE režim
        
        Pro BUY: blokovat pokud je na swing high
        Pro SELL: blokovat pokud je na swing low
        
        Args:
            bars: OHLC data
            swing_state: Swing state
            signal_direction: 'BUY' nebo 'SELL'
            
        Returns:
            True pokud je signál na swing extrému (měl by být blokován)
        """
        if len(bars) < 5:
            return False
            
        current_price = bars[-1]['close']
        current_high = bars[-1]['high']
        current_low = bars[-1]['low']
        
        # Tolerance: 0.3 ATR od swing extreme
        tolerance = self.current_atr * 0.3
        
        # Získáme swing high/low
        last_high = swing_state.get('last_high')
        last_low = swing_state.get('last_low')
        
        if last_high is None or last_low is None:
            lookback = min(20, len(bars) - 2)
            if lookback > 0:
                recent_bars = bars[-lookback:-1]
                if not last_high:
                    last_high = max(b['high'] for b in recent_bars) if recent_bars else None
                if not last_low:
                    last_low = min(b['low'] for b in recent_bars) if recent_bars else None
        
        # Zpracování swing high/low
        if isinstance(last_high, dict):
            last_high_price = last_high.get('price')
        else:
            last_high_price = last_high
            
        if isinstance(last_low, dict):
            last_low_price = last_low.get('price')
        else:
            last_low_price = last_low
        
        if signal_direction == 'BUY':
            # BUY signál: blokovat pokud je na swing high
            if last_high_price:
                if current_high >= (last_high_price - tolerance):
                    # Zkontrolujeme momentum
                    if len(bars) >= 2:
                        price_change = bars[-1]['close'] - bars[-2]['close']
                        if price_change > 0:  # Cena roste
                            if self.app:
                                self.app.log(f"[RANGE_EXTREME] Blocking BUY: Price at/near swing high {last_high_price:.1f}")
                            return True
                            
        elif signal_direction == 'SELL':
            # SELL signál: blokovat pokud je na swing low
            if last_low_price:
                if current_low <= (last_low_price + tolerance):
                    # Zkontrolujeme momentum
                    if len(bars) >= 2:
                        price_change = bars[-1]['close'] - bars[-2]['close']
                        if price_change < 0:  # Cena klesá
                            if self.app:
                                self.app.log(f"[RANGE_EXTREME] Blocking SELL: Price at/near swing low {last_low_price:.1f}")
                            return True
        
        return False
    
    def _is_at_swing_extreme(self, bars: List[Dict], swing_state: Dict, trend_direction: str) -> bool:
        """
        Zkontroluje, zda je aktuální cena na vrcholu swingu (blízko swing high/low)
        
        V trendech chceme generovat signály jen na pullbacku, ne na vrcholu swingu.
        Kontroluje také EMA(34) trend pro dodatečnou validaci.
        
        Args:
            bars: OHLC data
            swing_state: Swing state s last_high a last_low
            trend_direction: 'UP', 'DOWN', nebo 'SIDEWAYS'
            
        Returns:
            True pokud je cena na vrcholu swingu (v rámci tolerance)
        """
        if not trend_direction or trend_direction.upper() in ['SIDEWAYS', 'RANGE']:
            return False  # V range markets neblokujeme (ale měli bychom použít EMA34 trend)
        
        # DODATEČNÁ KONTROLA: EMA(34) trend
        ema34_trend = self._get_ema34_trend(bars)
        if ema34_trend and ema34_trend != trend_direction:
            # EMA trend se liší od regime trendu - být přísnější
            if self.app:
                self.app.log(f"[SWING_EXTREME] EMA34 trend ({ema34_trend}) differs from regime trend ({trend_direction}) - using EMA")
            trend_direction = ema34_trend  # Použijeme EMA trend
            
        if len(bars) < 5:
            return False
            
        current_price = bars[-1]['close']
        current_high = bars[-1]['high']
        current_low = bars[-1]['low']
        
        # Tolerance: 0.3 ATR od swing extreme (přísnější)
        tolerance = self.current_atr * 0.3
        
        # Získáme swing high/low z swing_state
        last_high = swing_state.get('last_high')
        last_low = swing_state.get('last_low')
        
        # Pokud nemáme swing data ze swing_state, zkusíme je najít z bars
        if last_high is None or last_low is None:
            lookback = min(20, len(bars) - 2)
            if lookback > 0:
                recent_bars = bars[-lookback:-1]  # Nezahrnujeme poslední bar
                if not last_high:
                    last_high = max(b['high'] for b in recent_bars) if recent_bars else None
                if not last_low:
                    last_low = min(b['low'] for b in recent_bars) if recent_bars else None
        
        # Zpracování swing high/low - mohou být dict nebo float
        if isinstance(last_high, dict):
            last_high_price = last_high.get('price')
        else:
            last_high_price = last_high
            
        if isinstance(last_low, dict):
            last_low_price = last_low.get('price')
        else:
            last_low_price = last_low
        
        # KONTROLA 1: Zda cena právě vytváří nový swing high/low
        # V uptrendu: pokud current_high je blízko nebo nad last_high → blokovat
        if trend_direction == 'UP':
            if last_high_price:
                # Kontrola 1a: Current high je blízko nebo nad last high
                if current_high >= (last_high_price - tolerance):
                    # Kontrola 1b: Zkontrolujeme, zda poslední 2-3 bary ukazují růst (ne pullback)
                    if len(bars) >= 3:
                        recent_highs = [b['high'] for b in bars[-3:]]
                        if all(h >= recent_highs[0] * 0.999 for h in recent_highs):  # Všechny bary jsou blízko high
                            if self.app:
                                self.app.log(f"[SWING_EXTREME] Blocking: Current high {current_high:.1f} near/above last high {last_high_price:.1f} (uptrend)")
                            return True
                    
        # V downtrendu: pokud current_low je blízko nebo pod last_low → blokovat
        elif trend_direction == 'DOWN':
            if last_low_price:
                # Kontrola 1a: Current low je blízko nebo pod last low
                if current_low <= (last_low_price + tolerance):
                    # Kontrola 1b: Zkontrolujeme, zda poslední 2-3 bary ukazují pokles (ne pullback)
                    if len(bars) >= 3:
                        recent_lows = [b['low'] for b in bars[-3:]]
                        if all(l <= recent_lows[0] * 1.001 for l in recent_lows):  # Všechny bary jsou blízko low
                            if self.app:
                                self.app.log(f"[SWING_EXTREME] Blocking: Current low {current_low:.1f} near/below last low {last_low_price:.1f} (downtrend)")
                            return True
        
        # KONTROLA 2: Zda cena je blízko swing extrému a pohybuje se směrem k němu (ne od něj)
        if trend_direction == 'UP' and last_high_price:
            distance_from_high = abs(current_price - last_high_price)
            if distance_from_high <= tolerance:
                # Zkontrolujeme momentum: pokud poslední 2 bary rostou → blokovat
                if len(bars) >= 2:
                    price_change = bars[-1]['close'] - bars[-2]['close']
                    if price_change > 0:  # Cena roste směrem k high
                        if self.app:
                            self.app.log(f"[SWING_EXTREME] Blocking: Price rising toward swing high (uptrend)")
                        return True
                        
        elif trend_direction == 'DOWN' and last_low_price:
            distance_from_low = abs(current_price - last_low_price)
            if distance_from_low <= tolerance:
                # Zkontrolujeme momentum: pokud poslední 2 bary klesají → blokovat
                if len(bars) >= 2:
                    price_change = bars[-1]['close'] - bars[-2]['close']
                    if price_change < 0:  # Cena klesá směrem k low
                        if self.app:
                            self.app.log(f"[SWING_EXTREME] Blocking: Price falling toward swing low (downtrend)")
                        return True
        
        return False
    
    def _is_in_pullback_zone(self, bars: List[Dict], swing_state: Dict, trend_direction: str) -> bool:
        """
        Zkontroluje, zda je cena v pullback zóně (ne na vrcholu swingu)
        
        Pullback zóna = cena se vzdaluje od swing extrému (klesá z high v uptrendu, roste z low v downtrendu)
        Kontroluje také EMA(34) trend pro dodatečnou validaci.
        
        Args:
            bars: OHLC data
            swing_state: Swing state
            trend_direction: 'UP', 'DOWN', nebo 'SIDEWAYS'
            
        Returns:
            True pokud je cena v pullback zóně
        """
        if not trend_direction or trend_direction.upper() in ['SIDEWAYS', 'RANGE']:
            # V range markets bychom měli použít EMA34 trend pokud je dostupný
            # Pokud nemáme trend, vrátíme True (ale mělo by se to řešit výše pomocí EMA34)
            return True  # V range markets bez EMA34 trendu je vše "pullback zone"
            
        if len(bars) < 5:
            return False  # Potřebujeme alespoň 5 barů pro analýzu
        
        # DODATEČNÁ KONTROLA: EMA(34) trend
        ema34_trend = self._get_ema34_trend(bars)
        if ema34_trend and ema34_trend != trend_direction:
            # EMA trend se liší od regime trendu - být přísnější
            if self.app:
                self.app.log(f"[PULLBACK] EMA34 trend ({ema34_trend}) differs from regime trend ({trend_direction}) - using EMA")
            trend_direction = ema34_trend  # Použijeme EMA trend
            
        current_price = bars[-1]['close']
        pullback_tolerance = self.current_atr * 0.2  # Přísnější tolerance: 0.2 ATR
        
        # DODATEČNÁ KONTROLA: EMA(34) pozice
        if len(bars) >= 34:
            ema34 = self._calculate_ema(bars, 34)
            if ema34 > 0:
                if trend_direction == 'UP':
                    # V uptrendu: pullback zóna je když cena je pod nebo blízko EMA(34)
                    # Pokud je cena výrazně nad EMA(34), není to pullback
                    if current_price > ema34 * 1.002:  # Více než 0.2% nad EMA
                        if self.app:
                            self.app.log(f"[PULLBACK] Rejecting: Price {current_price:.1f} too far above EMA34 {ema34:.1f} (uptrend)")
                        return False
                elif trend_direction == 'DOWN':
                    # V downtrendu: pullback zóna je když cena je nad nebo blízko EMA(34)
                    # Pokud je cena výrazně pod EMA(34), není to pullback
                    if current_price < ema34 * 0.998:  # Více než 0.2% pod EMA
                        if self.app:
                            self.app.log(f"[PULLBACK] Rejecting: Price {current_price:.1f} too far below EMA34 {ema34:.1f} (downtrend)")
                        return False
        
        # Získáme swing high/low
        last_high = swing_state.get('last_high')
        last_low = swing_state.get('last_low')
        
        if last_high is None or last_low is None:
            lookback = min(20, len(bars) - 2)
            if lookback > 0:
                recent_bars = bars[-lookback:-1]
                if not last_high:
                    last_high = max(b['high'] for b in recent_bars) if recent_bars else None
                if not last_low:
                    last_low = min(b['low'] for b in recent_bars) if recent_bars else None
        
        # Zpracování swing high/low
        if isinstance(last_high, dict):
            last_high_price = last_high.get('price')
        else:
            last_high_price = last_high
            
        if isinstance(last_low, dict):
            last_low_price = last_low.get('price')
        else:
            last_low_price = last_low
        
        if trend_direction == 'UP':
            # V uptrendu: pullback zóna je když cena klesla pod recent high A pohybuje se dolů
            if last_high_price:
                # KONTROLA 1: Cena musí být pod swing high (s tolerancí)
                if current_price >= (last_high_price - pullback_tolerance):
                    if self.app:
                        self.app.log(f"[PULLBACK] Rejecting: Price {current_price:.1f} too close to swing high {last_high_price:.1f} (uptrend)")
                    return False
                
                # KONTROLA 2: Cena se musí vzdalovat od high (pullback pattern)
                # Zkontrolujeme poslední 3 bary - měly by ukazovat pokles
                if len(bars) >= 3:
                    recent_closes = [b['close'] for b in bars[-3:]]
                    # Pokud poslední 2 bary rostou → není to pullback
                    if recent_closes[-1] > recent_closes[-2]:
                        if self.app:
                            self.app.log(f"[PULLBACK] Rejecting: Price rising (not pulling back) in uptrend")
                        return False
                    
                    # Pokud cena je stále velmi blízko high → není to pullback
                    max_recent_high = max(b['high'] for b in bars[-3:])
                    if max_recent_high >= (last_high_price - pullback_tolerance * 2):
                        if self.app:
                            self.app.log(f"[PULLBACK] Rejecting: Recent high {max_recent_high:.1f} too close to swing high {last_high_price:.1f}")
                        return False
                
                # KONTROLA 3: RSI Confirmation
                rsi_confirmed, rsi_reason = self._check_rsi_pullback_confirmation(bars, trend_direction)
                if not rsi_confirmed:
                    if self.app:
                        self.app.log(f"[PULLBACK] Rejecting: {rsi_reason}")
                    return False
                
                # Pokud jsme tady, cena je v pullback zóně
                if self.app:
                    self.app.log(f"[PULLBACK] ✅ Price {current_price:.1f} in pullback zone (below swing high {last_high_price:.1f})")
                    self.app.log(f"[PULLBACK] ✅ RSI confirmation: {rsi_reason}")
                return True
                
            # Pokud nemáme swing high, použijeme recent high z bars
            if len(bars) >= 5:
                recent_high = max(b['high'] for b in bars[-5:-1])
                if current_price < (recent_high - pullback_tolerance):
                    # Zkontrolujeme momentum
                    if len(bars) >= 2:
                        if bars[-1]['close'] <= bars[-2]['close']:  # Cena klesá
                            return True
                return False
                
        elif trend_direction == 'DOWN':
            # V downtrendu: pullback zóna je když cena stoupla nad recent low A pohybuje se nahoru
            if last_low_price:
                # KONTROLA 1: Cena musí být nad swing low (s tolerancí)
                if current_price <= (last_low_price + pullback_tolerance):
                    if self.app:
                        self.app.log(f"[PULLBACK] Rejecting: Price {current_price:.1f} too close to swing low {last_low_price:.1f} (downtrend)")
                    return False
                
                # KONTROLA 2: Cena se musí vzdalovat od low (pullback pattern)
                # Zkontrolujeme poslední 3 bary - měly by ukazovat růst
                if len(bars) >= 3:
                    recent_closes = [b['close'] for b in bars[-3:]]
                    # Pokud poslední 2 bary klesají → není to pullback
                    if recent_closes[-1] < recent_closes[-2]:
                        if self.app:
                            self.app.log(f"[PULLBACK] Rejecting: Price falling (not pulling back) in downtrend")
                        return False
                    
                    # Pokud cena je stále velmi blízko low → není to pullback
                    min_recent_low = min(b['low'] for b in bars[-3:])
                    if min_recent_low <= (last_low_price + pullback_tolerance * 2):
                        if self.app:
                            self.app.log(f"[PULLBACK] Rejecting: Recent low {min_recent_low:.1f} too close to swing low {last_low_price:.1f}")
                        return False
                
                # KONTROLA 3: RSI Confirmation
                rsi_confirmed, rsi_reason = self._check_rsi_pullback_confirmation(bars, trend_direction)
                if not rsi_confirmed:
                    if self.app:
                        self.app.log(f"[PULLBACK] Rejecting: {rsi_reason}")
                    return False
                
                # Pokud jsme tady, cena je v pullback zóně
                if self.app:
                    self.app.log(f"[PULLBACK] ✅ Price {current_price:.1f} in pullback zone (above swing low {last_low_price:.1f})")
                    self.app.log(f"[PULLBACK] ✅ RSI confirmation: {rsi_reason}")
                return True
                
            # Pokud nemáme swing low, použijeme recent low z bars
            if len(bars) >= 5:
                recent_low = min(b['low'] for b in bars[-5:-1])
                if current_price > (recent_low + pullback_tolerance):
                    # Zkontrolujeme momentum
                    if len(bars) >= 2:
                        if bars[-1]['close'] >= bars[-2]['close']:  # Cena roste
                            return True
                return False
        
        return False  # Default: nepovolit (přísnější)
    
    def _check_structure_breaks(self, bars: List[Dict], 
                                swing_state: Dict, 
                                pivot_levels: Dict) -> List[Dict]:
        """
        Check for structure breaks and breakout retests
        
        Breakout Retest Strategy:
        - Po breakoutu čekáme na retest breakout levelu
        - Retest potvrzuje breakout a poskytuje lepší entry
        - Méně false breakouts, lepší R:R
        """
        breaks = []
        current_price = bars[-1]['close']
        
        lookback = self.swing_break_lookback
        last_high = swing_state.get('last_high')
        last_low = swing_state.get('last_low')
        
        if last_high is None and len(bars) >= lookback:
            last_high = max(b['high'] for b in bars[-lookback:])
        if last_low is None and len(bars) >= lookback:
            last_low = min(b['low'] for b in bars[-lookback:])
        
        tolerance = self.current_atr * 0.3
        
        # === BREAKOUT RETEST DETECTION ===
        # Detekce, zda cena testuje nedávný breakout level
        # To je důležité - retest po breakoutu je silnější signál než samotný breakout
        
        # Check for swing high breakout retest
        if last_high:
            # Zkontroluj, zda byl nedávný breakout nad last_high
            recent_breakout = False
            breakout_bar_idx = None
            
            # Hledej breakout v posledních 20 barech
            for i in range(max(0, len(bars) - 20), len(bars) - 1):
                if bars[i]['close'] > last_high:
                    recent_breakout = True
                    breakout_bar_idx = i
                    break
            
            if recent_breakout and breakout_bar_idx is not None:
                # Po breakoutu hledej retest - cena se vrátila k levelu
                # Retest = cena je blízko breakout levelu a začíná se odrážet
                distance_from_level = abs(current_price - last_high)
                
                if distance_from_level <= tolerance:
                    # Zkontroluj, zda cena se odráží (ne proráží zpět)
                    # V uptrendu: cena by měla být nad nebo blízko levelu a začínat růst
                    if current_price >= last_high * 0.999:  # Nad nebo velmi blízko levelu
                        # Zkontroluj momentum - poslední 2-3 bary by měly být bullish
                        if len(bars) >= 3:
                            recent_closes = [b['close'] for b in bars[-3:]]
                            if recent_closes[-1] >= recent_closes[-2]:  # Roste nebo drží
                                breaks.append({
                                    'type': 'SWING_HIGH_BREAK_RETEST',
                                    'level': last_high,
                                    'direction': 'bullish',
                                    'confidence': 85,  # Retest je silnější než samotný breakout
                                    'breakout_bar': breakout_bar_idx
                                })
        
        # Check for swing low breakout retest
        if last_low:
            # Zkontroluj, zda byl nedávný breakout pod last_low
            recent_breakout = False
            breakout_bar_idx = None
            
            for i in range(max(0, len(bars) - 20), len(bars) - 1):
                if bars[i]['close'] < last_low:
                    recent_breakout = True
                    breakout_bar_idx = i
                    break
            
            if recent_breakout and breakout_bar_idx is not None:
                distance_from_level = abs(current_price - last_low)
                
                if distance_from_level <= tolerance:
                    # V downtrendu: cena by měla být pod nebo blízko levelu a začínat klesat
                    if current_price <= last_low * 1.001:  # Pod nebo velmi blízko levelu
                        if len(bars) >= 3:
                            recent_closes = [b['close'] for b in bars[-3:]]
                            if recent_closes[-1] <= recent_closes[-2]:  # Klesá nebo drží
                                breaks.append({
                                    'type': 'SWING_LOW_BREAK_RETEST',
                                    'level': last_low,
                                    'direction': 'bearish',
                                    'confidence': 85,
                                    'breakout_bar': breakout_bar_idx
                                })
        
        # === ORIGINAL BREAKOUT DETECTION (s přísnou validací proti false breakouts) ===
        # Swing breaks (pouze pokud NENÍ retest)
        has_retest = any('RETEST' in b.get('type', '') for b in breaks)
        
        if not has_retest:
            # === PŘÍSNÁ VALIDACE BREAKOUTU ===
            # False breakout = cena prorazí level, ale uzavře zpět nebo se vrátí
            
            # Swing high breakout
            if last_high and current_price > last_high:
                # VALIDACE 1: Close confirmation - bar musí uzavřít nad levelem
                if bars[-1]['close'] <= last_high:
                    # Breakout nepotvrzen close → pravděpodobně false breakout
                        if self.app and self.logging.should_log('breakout', f"false_breakout_close:{last_high:.1f}"):
                            self.app.log(f"[FALSE_BREAKOUT] Blocking: Price broke {last_high:.1f} but closed at {bars[-1]['close']:.1f} (below level)")
                    # NEPŘIDÁVAT - false breakout
                else:
                    # VALIDACE 2: Multiple bar confirmation - min 2 bary nad levelem
                    bars_above = 0
                    for i in range(-1, -min(3, len(bars)), -1):
                        if bars[i]['close'] > last_high:
                            bars_above += 1
                    
                    if bars_above >= 2:
                        # VALIDACE 3: Momentum check - cena by měla růst
                        if len(bars) >= 2 and bars[-1]['close'] >= bars[-2]['close']:
                            breaks.append({
                                'type': 'SWING_HIGH_BREAK',
                                'level': last_high,
                                'direction': 'bullish',
                                'confidence': 70,
                                'validated': True  # Prošlo validací
                            })
                        else:
                            if self.app and self.logging.should_log('breakout', f"false_breakout_momentum:{last_high:.1f}"):
                                self.app.log(f"[FALSE_BREAKOUT] Blocking: Breakout above {last_high:.1f} but momentum not confirming")
                    else:
                        if self.app and self.logging.should_log('breakout', f"false_breakout_bars:{last_high:.1f}"):
                            self.app.log(f"[FALSE_BREAKOUT] Blocking: Breakout above {last_high:.1f} but only {bars_above} bars confirmed (need 2+)")
            
            # Swing low breakout
            if last_low and current_price < last_low:
                # VALIDACE 1: Close confirmation
                if bars[-1]['close'] >= last_low:
                    if self.app and self.logging.should_log('breakout', f"false_breakout_close:{last_low:.1f}"):
                        self.app.log(f"[FALSE_BREAKOUT] Blocking: Price broke {last_low:.1f} but closed at {bars[-1]['close']:.1f} (above level)")
                else:
                    # VALIDACE 2: Multiple bar confirmation
                    bars_below = 0
                    for i in range(-1, -min(3, len(bars)), -1):
                        if bars[i]['close'] < last_low:
                            bars_below += 1
                    
                    if bars_below >= 2:
                        # VALIDACE 3: Momentum check
                        if len(bars) >= 2 and bars[-1]['close'] <= bars[-2]['close']:
                            breaks.append({
                                'type': 'SWING_LOW_BREAK',
                                'level': last_low,
                                'direction': 'bearish',
                                'confidence': 70,
                                'validated': True
                            })
                        else:
                            if self.app and self.logging.should_log('breakout', f"false_breakout_momentum:{last_low:.1f}"):
                                self.app.log(f"[FALSE_BREAKOUT] Blocking: Breakout below {last_low:.1f} but momentum not confirming")
                    else:
                        if self.app and self.logging.should_log('breakout', f"false_breakout_bars:{last_low:.1f}"):
                            self.app.log(f"[FALSE_BREAKOUT] Blocking: Breakout below {last_low:.1f} but only {bars_below} bars confirmed (need 2+)")
        
        # Pivot tests
        for level_name, level_value in (pivot_levels or {}).items():
            if isinstance(level_value, (int, float)) and abs(current_price - level_value) <= tolerance:
                breaks.append({
                    'type': f'PIVOT_{level_name}_TEST',
                    'level': level_value,
                    'direction': 'neutral',
                    'confidence': 60
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
            # DAX quality hours: 9:00-15:30 CET
            return (9 <= hour < 15) or (hour == 15 and now.minute <= 30)
        elif 'NASDAQ' in symbol.upper() or 'US100' in symbol.upper():
            # NASDAQ quality hours: 15:30-22:00 CET
            return (hour == 15 and now.minute >= 30) or (16 <= hour < 22)
        
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