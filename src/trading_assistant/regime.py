"""
Regime Detection Module - NO NUMPY VERSION
Sprint 1: Trend vs Range detection using ensemble voting
Fixed version without NumPy dependency
28-08-28 08:00
"""

from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum
import logging
import math

logger = logging.getLogger(__name__)


class RegimeType(Enum):
    """Market regime types"""
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    RANGE = "RANGE"
    UNKNOWN = "UNKNOWN"


@dataclass
class RegimeState:
    """Complete regime state with diagnostics"""
    regime: RegimeType
    confidence: float  # 0-100
    adx_value: float
    adx_vote: str  # TREND/RANGE
    regression_slope: float  # β
    regression_r2: float  # R²
    regression_vote: str  # TREND_UP/TREND_DOWN/RANGE
    trend_direction: Optional[str] = None  # UP/DOWN/SIDEWAYS
    hurst_exponent: Optional[float] = None
    hurst_vote: Optional[str] = None
    votes: Dict[str, str] = field(default_factory=dict)
    timestamp: str = ""
    # Multi-timeframe support (using string values to avoid forward reference issues)
    primary_regime: Optional[str] = None  # Recentní trend (100 barů) - stored as value string
    secondary_regime: Optional[str] = None  # Celkový kontext (180 barů) - stored as value string
    trend_change: Optional[str] = None  # REVERSAL_UP, REVERSAL_DOWN, None
    ema34_trend: Optional[str] = None  # UP, DOWN, SIDEWAYS, None
    used_timeframe: str = "combined"  # "primary", "secondary", "combined"


class RegimeDetector:
    """
    Ensemble regime detection using 2 out of 3 voting:
    1. ADX (Average Directional Index)
    2. Linear Regression (slope β and R²)
    3. Hurst Exponent (optional)
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize regime detector with configuration
        
        Args:
            config: Configuration dictionary with parameters
        """
        self.config = config or {}
        
        # ADX parameters
        self.adx_period = self.config.get('adx_period', 14)
        self.adx_threshold = self.config.get('adx_threshold', 25)
        
        # Linear regression parameters
        self.regression_period = self.config.get('regression_period', 20)
        self.r2_threshold = self.config.get('regression_r2_threshold', 0.6)
        self.slope_threshold = self.config.get('slope_threshold', 0.0001)
        
        # Hurst parameters
        self.use_hurst = self.config.get('use_hurst', self.config.get('enable_hurst', False))
        self.hurst_threshold = self.config.get('hurst_threshold', 0.5)
        
        # Multi-timeframe parameters
        self.use_multi_timeframe = self.config.get('use_multi_timeframe', True)
        self.primary_window = self.config.get('primary_window', 100)  # Recentní trend (8 hodin)
        self.secondary_window = self.config.get('secondary_window', 180)  # Celkový kontext (15 hodin)
        
        # Trend change detection
        self.use_trend_change_detection = self.config.get('use_trend_change_detection', True)
        self.short_trend_window = self.config.get('short_trend_window', 30)  # 2.5 hodiny
        self.medium_trend_window = self.config.get('medium_trend_window', 60)  # 5 hodin
        
        # EMA34 integration
        self.use_ema34_primary = self.config.get('use_ema34_primary', True)
        
        # Exponential weighted regression
        self.use_weighted_regression = self.config.get('use_weighted_regression', False)
        self.weight_decay = self.config.get('weight_decay', 0.95)  # Alpha factor
        
        # State storage
        self.last_state: Optional[RegimeState] = None
        self.last_ema34_trend: Optional[str] = None
        
    def detect(self, bars: List[Dict]) -> RegimeState:
        """
        Main detection method - multi-timeframe ensemble voting with EMA34 support
        
        Args:
            bars: List of bar dictionaries with OHLC data
            
        Returns:
            RegimeState with regime type and diagnostics
        """
        
        logger.info(f"[REGIME] Starting detection with {len(bars)} bars")
        
        if len(bars) < max(self.adx_period * 2, self.regression_period):
            logger.warning(f"Insufficient bars for regime detection. Need at least {max(self.adx_period * 2, self.regression_period)}")
            return RegimeState(
                regime=RegimeType.UNKNOWN,
                confidence=0,
                adx_value=0,
                adx_vote="UNKNOWN",
                regression_slope=0,
                regression_r2=0,
                regression_vote="UNKNOWN"
            )
        
        # Extract price series
        closes = [b['close'] for b in bars]
        highs = [b['high'] for b in bars]
        lows = [b['low'] for b in bars]
        
        # === MULTI-TIMEFRAME DETECTION ===
        primary_state = None
        secondary_state = None
        used_timeframe = "combined"
        
        if self.use_multi_timeframe and len(bars) >= self.primary_window:
            # Primary: Recentní trend (pro trading rozhodnutí)
            primary_bars = bars[-self.primary_window:]
            primary_state = self._detect_single_timeframe(primary_bars, "PRIMARY")
            logger.info(f"[REGIME] PRIMARY ({self.primary_window} bars): {primary_state.regime.value}, Confidence: {primary_state.confidence:.1f}%")
            
            # Secondary: Celkový kontext (pokud máme dostatek dat)
            if len(bars) >= self.secondary_window:
                secondary_bars = bars[-self.secondary_window:]
                secondary_state = self._detect_single_timeframe(secondary_bars, "SECONDARY")
                logger.info(f"[REGIME] SECONDARY ({self.secondary_window} bars): {secondary_state.regime.value}, Confidence: {secondary_state.confidence:.1f}%")
            
            # Rozhodnout, který timeframe použít
            if primary_state.confidence >= 70:
                # Primary má vysokou confidence → použít primary
                used_timeframe = "primary"
                logger.info(f"[REGIME] Using PRIMARY timeframe (confidence {primary_state.confidence:.1f}% >= 70%)")
            elif secondary_state and secondary_state.confidence >= 70:
                # Secondary má vysokou confidence → použít secondary
                used_timeframe = "secondary"
                logger.info(f"[REGIME] Using SECONDARY timeframe (confidence {secondary_state.confidence:.1f}% >= 70%)")
            else:
                # Obě nízké confidence → použít primary (recentní trend je důležitější)
                used_timeframe = "primary"
                logger.info(f"[REGIME] Using PRIMARY timeframe (fallback - both have low confidence)")
        
        # Pokud multi-timeframe není aktivní, použít standardní detekci
        if primary_state is None:
            primary_state = self._detect_single_timeframe(bars, "STANDARD")
            used_timeframe = "combined"
        
        # === TREND CHANGE DETECTION ===
        trend_change = None
        if self.use_trend_change_detection and len(bars) >= self.medium_trend_window:
            trend_change = self._detect_trend_change(bars)
            if trend_change:
                logger.info(f"[REGIME] TREND CHANGE detected: {trend_change}")
        
        # === EMA34 TREND INTEGRATION ===
        ema34_trend = None
        if self.use_ema34_primary:
            ema34_trend = self._get_ema34_trend(bars)
            if ema34_trend:
                logger.info(f"[REGIME] EMA34 trend: {ema34_trend}")
                
                # Pokud EMA34 ukazuje trend a primary regime je RANGE, upravit
                if primary_state.regime == RegimeType.RANGE and ema34_trend in ["UP", "DOWN"]:
                    # EMA34 má prioritu pro recentní trend
                    if ema34_trend == "UP":
                        primary_state.regime = RegimeType.TREND_UP
                        primary_state.confidence = min(primary_state.confidence + 20, 100)
                        logger.info(f"[REGIME] EMA34 priority: Changed RANGE → TREND_UP (EMA34={ema34_trend})")
                    elif ema34_trend == "DOWN":
                        primary_state.regime = RegimeType.TREND_DOWN
                        primary_state.confidence = min(primary_state.confidence + 20, 100)
                        logger.info(f"[REGIME] EMA34 priority: Changed RANGE → TREND_DOWN (EMA34={ema34_trend})")
        
        # Final state (použít primary_state jako base)
        final_state = RegimeState(
            regime=primary_state.regime,
            confidence=primary_state.confidence,
            adx_value=primary_state.adx_value,
            adx_vote=primary_state.adx_vote,
            regression_slope=primary_state.regression_slope,
            regression_r2=primary_state.regression_r2,
            regression_vote=primary_state.regression_vote,
            trend_direction=primary_state.trend_direction,
            hurst_exponent=primary_state.hurst_exponent,
            hurst_vote=primary_state.hurst_vote,
            votes=primary_state.votes or {},
            primary_regime=primary_state.regime.value if primary_state else None,
            secondary_regime=secondary_state.regime.value if secondary_state else None,
            trend_change=trend_change,
            ema34_trend=ema34_trend,
            used_timeframe=used_timeframe
        )
        
        # === DETAILNÍ LOGOVÁNÍ PRO OVĚŘENÍ ===
        logger.info(f"[REGIME] ===== FINAL REGIME STATE =====")
        logger.info(f"[REGIME] Regime: {final_state.regime.value}")
        logger.info(f"[REGIME] Confidence: {final_state.confidence:.1f}%")
        logger.info(f"[REGIME] Used Timeframe: {used_timeframe}")
        if primary_state:
            logger.info(f"[REGIME] Primary ({self.primary_window} bars): {primary_state.regime.value} ({primary_state.confidence:.1f}%)")
        if secondary_state:
            logger.info(f"[REGIME] Secondary ({self.secondary_window} bars): {secondary_state.regime.value} ({secondary_state.confidence:.1f}%)")
        logger.info(f"[REGIME] ADX: {final_state.adx_value:.2f}, Vote: {final_state.adx_vote}")
        logger.info(f"[REGIME] Regression: Slope={final_state.regression_slope:.6f}, R²={final_state.regression_r2:.3f}, Vote: {final_state.regression_vote}")
        logger.info(f"[REGIME] Trend Direction: {final_state.trend_direction}")
        if ema34_trend:
            logger.info(f"[REGIME] EMA34 Trend: {ema34_trend}")
        if trend_change:
            logger.info(f"[REGIME] Trend Change: {trend_change}")
        logger.info(f"[REGIME] =============================")
        
        self.last_state = final_state
        self.last_ema34_trend = ema34_trend
        return final_state
    
    def _detect_single_timeframe(self, bars: List[Dict], timeframe_name: str = "STANDARD") -> RegimeState:
        """
        Detect regime for a single timeframe window
        
        Args:
            bars: List of bar dictionaries with OHLC data
            timeframe_name: Name of the timeframe (for logging)
            
        Returns:
            RegimeState for this timeframe
        """
        closes = [b['close'] for b in bars]
        highs = [b['high'] for b in bars]
        lows = [b['low'] for b in bars]
        
        # 1. Calculate ADX
        adx_value, adx_vote, di_plus, di_minus = self._calculate_adx(highs, lows, closes)
        
        # 2. Calculate Linear Regression (with optional weighted regression)
        if self.use_weighted_regression:
            slope, r2, regression_vote = self._calculate_weighted_regression(closes)
        else:
            slope, r2, regression_vote = self._calculate_regression(closes)
        
        # 3. Calculate Hurst (optional)
        hurst_value = None
        hurst_vote = None
        if self.use_hurst:
            hurst_value, hurst_vote = self._calculate_hurst(closes)
        
        # 4. Ensemble voting
        regime, confidence, votes, trend_direction = self._ensemble_vote(
            adx_vote, regression_vote, hurst_vote, di_plus, di_minus
        )
        
        # Create state object
        state = RegimeState(
            regime=regime,
            confidence=confidence,
            adx_value=adx_value,
            adx_vote=adx_vote,
            regression_slope=slope,
            regression_r2=r2,
            regression_vote=regression_vote,
            trend_direction=self._map_trend_direction(trend_direction),
            hurst_exponent=hurst_value,
            hurst_vote=hurst_vote,
            votes=votes
        )
        
        return state
    
    def _detect_trend_change(self, bars: List[Dict]) -> Optional[str]:
        """
        Detekovat změnu trendu porovnáním krátkodobého a střednědobého trendu
        
        Args:
            bars: OHLC data
            
        Returns:
            "REVERSAL_UP", "REVERSAL_DOWN", nebo None
        """
        if len(bars) < self.medium_trend_window:
            logger.debug(f"[REGIME] Trend Change: Insufficient bars ({len(bars)} < {self.medium_trend_window})")
            return None
        
        closes = [b['close'] for b in bars]
        
        # Krátkodobý trend (30 barů = 2.5 hodiny)
        short_bars = bars[-self.short_trend_window:]
        short_closes = [b['close'] for b in short_bars]
        short_slope, short_r2, short_vote = self._calculate_regression(short_closes)
        
        # Střednědobý trend (60 barů = 5 hodin)
        medium_bars = bars[-self.medium_trend_window:]
        medium_closes = [b['close'] for b in medium_bars]
        medium_slope, medium_r2, medium_vote = self._calculate_regression(medium_closes)
        
        logger.info(f"[REGIME] Trend Change: Short ({self.short_trend_window} bars) = {short_vote} (slope={short_slope:.6f}, R²={short_r2:.3f})")
        logger.info(f"[REGIME] Trend Change: Medium ({self.medium_trend_window} bars) = {medium_vote} (slope={medium_slope:.6f}, R²={medium_r2:.3f})")
        
        # Detekovat reversal
        if short_vote == "TREND_UP" and medium_vote == "TREND_DOWN":
            logger.info(f"[REGIME] Trend Change: REVERSAL_UP detected (short=UP, medium=DOWN)")
            return "REVERSAL_UP"  # Downtrend se mění na uptrend
        elif short_vote == "TREND_DOWN" and medium_vote == "TREND_UP":
            logger.info(f"[REGIME] Trend Change: REVERSAL_DOWN detected (short=DOWN, medium=UP)")
            return "REVERSAL_DOWN"  # Uptrend se mění na downtrend
        
        logger.debug(f"[REGIME] Trend Change: No reversal (short={short_vote}, medium={medium_vote})")
        return None
    
    def _get_ema34_trend(self, bars: List[Dict]) -> Optional[str]:
        """
        Získá trend směr pomocí EMA(34) - stejná logika jako v EdgeDetector
        
        Args:
            bars: OHLC data
            
        Returns:
            'UP' pokud cena > EMA(34), 'DOWN' pokud cena < EMA(34), None pokud nedostatek dat
        """
        if len(bars) < 34:
            logger.debug(f"[REGIME] EMA34: Insufficient bars ({len(bars)} < 34)")
            return None
        
        try:
            # Vypočítat EMA(34)
            ema34 = self._calculate_ema_value(bars, 34)
            if ema34 == 0 or ema34 is None:
                logger.debug(f"[REGIME] EMA34: Calculation returned 0 or None (bars: {len(bars)})")
                return None
                
            current_price = bars[-1].get('close', 0)
            if current_price == 0:
                logger.debug(f"[REGIME] EMA34: Current price is 0")
                return None
            
            # Tolerance: 0.05% od EMA (sníženo z 0.1% pro lepší citlivost)
            tolerance = ema34 * 0.0005
            price_diff = current_price - ema34
            price_diff_pct = (price_diff / ema34) * 100 if ema34 > 0 else 0
            
            # Zkontrolovat slope EMA34 (pokud je EMA34 stoupající, ale cena je dočasně pod, může jít o pullback v uptrendu)
            ema34_slope = None
            if len(bars) >= 10:
                # Porovnat EMA34 z před 10 bary s aktuální EMA34
                ema34_10_bars_ago = self._calculate_ema_value(bars[:-10], 34)
                if ema34_10_bars_ago > 0:
                    ema34_slope_pct = ((ema34 - ema34_10_bars_ago) / ema34_10_bars_ago) * 100 if ema34_10_bars_ago > 0 else 0
                    if ema34_slope_pct > 0.02:  # EMA34 stoupá o více než 0.02%
                        ema34_slope = 'UP'
                    elif ema34_slope_pct < -0.02:  # EMA34 klesá o více než 0.02%
                        ema34_slope = 'DOWN'
            
            logger.info(f"[REGIME] EMA34: Price={current_price:.2f}, EMA34={ema34:.2f}, Diff={price_diff:.2f} ({price_diff_pct:.3f}%), Tolerance={tolerance:.2f}, Slope={ema34_slope}")
            
            # Pokud je cena výrazně nad EMA34, jasný uptrend
            if current_price > ema34 + tolerance:
                logger.info(f"[REGIME] EMA34: Trend=UP (Price {current_price:.2f} > EMA34 {ema34:.2f} + tolerance {tolerance:.2f})")
                return 'UP'
            # Pokud je cena výrazně pod EMA34
            elif current_price < ema34 - tolerance:
                # Pokud EMA34 stoupá (slope=UP), ale cena je pod EMA, může jít o pullback v uptrendu
                # Použít větší toleranci (0.1% místo 0.05%) pro detekci DOWN
                if ema34_slope == 'UP':
                    larger_tolerance = ema34 * 0.001  # 0.1%
                    if current_price < ema34 - larger_tolerance:
                        logger.info(f"[REGIME] EMA34: Trend=DOWN (Price {current_price:.2f} < EMA34 {ema34:.2f} - larger_tolerance {larger_tolerance:.2f}, EMA34 slope=UP but significant pullback)")
                        return 'DOWN'
                    else:
                        # Pullback v uptrendu - nejasný trend
                        logger.info(f"[REGIME] EMA34: Trend=None (Price {current_price:.2f} < EMA34 {ema34:.2f} but EMA34 slope=UP, possible pullback in uptrend)")
                        return None
                else:
                    logger.info(f"[REGIME] EMA34: Trend=DOWN (Price {current_price:.2f} < EMA34 {ema34:.2f} - tolerance {tolerance:.2f})")
                    return 'DOWN'
            else:
                # Cena je blízko EMA34 - použít diff jako primary, momentum jako tiebreaker
                logger.info(f"[REGIME] EMA34: Price close to EMA34 (diff={price_diff:.2f} < tolerance={tolerance:.2f}), using diff with momentum tiebreaker")
                
                # Zmenšená tolerance pro diff-based rozhodování (50% původní tolerance)
                diff_threshold = tolerance * 0.5
                
                # Primary: použít diff pokud je významný (alespoň 50% tolerance)
                if price_diff > diff_threshold:
                    logger.info(f"[REGIME] EMA34: Trend=UP (diff-based, diff={price_diff:.2f} > threshold={diff_threshold:.2f})")
                    return 'UP'
                elif price_diff < -diff_threshold:
                    logger.info(f"[REGIME] EMA34: Trend=DOWN (diff-based, diff={price_diff:.2f} < -threshold={diff_threshold:.2f})")
                    return 'DOWN'
                else:
                    # Diff je velmi malý - použít momentum jako tiebreaker POUZE pokud diff není extrémně malý
                    very_small_diff_threshold = tolerance * 0.1  # < 10% tolerance = velmi malý diff
                    
                    # Pokud je diff extrémně malý, použít None (nejasný trend) - nevěřit momentum
                    if abs(price_diff) < very_small_diff_threshold:
                        logger.info(f"[REGIME] EMA34: Diff extremely small (abs={abs(price_diff):.2f} < {very_small_diff_threshold:.2f}), using None (trend unclear)")
                        return None
                    
                    # Diff je malý, ale ne extrémně malý - použít momentum jako tiebreaker
                    if len(bars) >= 3:
                        recent_momentum = bars[-1]['close'] - bars[-3]['close']
                        momentum_threshold = tolerance * 0.5  # Stejný threshold jako pro diff
                        logger.info(f"[REGIME] EMA34: Diff small (abs={abs(price_diff):.2f} < {diff_threshold:.2f} but >= {very_small_diff_threshold:.2f}), checking momentum (3 bars) = {recent_momentum:.2f}")
                        
                        if recent_momentum > momentum_threshold:
                            logger.info(f"[REGIME] EMA34: Trend=UP (momentum-tiebreaker, momentum={recent_momentum:.2f})")
                            return 'UP'
                        elif recent_momentum < -momentum_threshold:
                            logger.info(f"[REGIME] EMA34: Trend=DOWN (momentum-tiebreaker, momentum={recent_momentum:.2f})")
                            return 'DOWN'
                        else:
                            # Momentum není jasný - použít diff jako fallback (diff je malý, ale ne extrémně malý)
                            if price_diff > 0:
                                logger.info(f"[REGIME] EMA34: Trend=UP (diff-fallback, diff={price_diff:.2f}, momentum unclear)")
                                return 'UP'
                            else:  # price_diff < 0
                                logger.info(f"[REGIME] EMA34: Trend=DOWN (diff-fallback, diff={price_diff:.2f}, momentum unclear)")
                                return 'DOWN'
                    else:
                        # Fallback: použít diff pokud není dostatek barů pro momentum
                        # Ale pouze pokud diff je významný
                        if abs(price_diff) < tolerance * 0.1:  # Velmi malý diff
                            logger.info(f"[REGIME] EMA34: Trend=None (insufficient bars, diff={price_diff:.2f} very small)")
                            return None
                        elif price_diff > 0:
                            logger.info(f"[REGIME] EMA34: Trend=UP (diff-fallback, insufficient bars for momentum, diff={price_diff:.2f})")
                            return 'UP'
                        else:  # price_diff < 0
                            logger.info(f"[REGIME] EMA34: Trend=DOWN (diff-fallback, insufficient bars for momentum, diff={price_diff:.2f})")
                            return 'DOWN'
                    
        except Exception as e:
            logger.warning(f"[REGIME] Error calculating EMA34 trend: {e}")
            import traceback
            logger.debug(f"[REGIME] EMA34 error traceback: {traceback.format_exc()}")
            return None
    
    def _calculate_ema_value(self, bars: List[Dict], period: int) -> float:
        """
        Vypočítá EMA hodnotu (poslední hodnota)
        
        Args:
            bars: OHLC data
            period: EMA period
            
        Returns:
            EMA hodnota (float)
        """
        if len(bars) < period:
            return 0.0
        
        closes = [bar.get('close', 0) for bar in bars]
        if not closes or all(c == 0 for c in closes):
            return 0.0
        
        # Multiplier pro EMA
        multiplier = 2.0 / (period + 1.0)
        
        # Začneme s SMA (průměr z prvních 'period' barů)
        sma_sum = sum(closes[:period])
        if sma_sum == 0:
            return 0.0
        ema = sma_sum / period
        
        # Aplikujeme EMA na zbývající bary
        for close in closes[period:]:
            if close > 0:
                ema = (close * multiplier) + (ema * (1.0 - multiplier))
        
        return ema
    
    def _calculate_weighted_regression(self, closes: List[float]) -> Tuple[float, float, str]:
        """
        Calculate exponential weighted linear regression - recentní bary mají větší váhu
        
        Args:
            closes: Price series
            
        Returns:
            (slope, r_squared, vote) where vote is TREND_UP/TREND_DOWN/RANGE
        """
        y = closes[-self.regression_period:] if len(closes) >= self.regression_period else closes
        n = len(y)
        x = list(range(n))
        
        # Exponenciální váhy (recentní bary mají větší váhu)
        # Nejnovější bar má váhu 1.0, nejstarší má váhu alpha^(n-1)
        weights = [self.weight_decay ** (n - 1 - i) for i in range(n)]
        total_weight = sum(weights)
        
        # Weighted means
        x_mean = sum(x[i] * weights[i] for i in range(n)) / total_weight
        y_mean = sum(y[i] * weights[i] for i in range(n)) / total_weight
        
        # Weighted slope (β)
        numerator = sum(weights[i] * (x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
        denominator = sum(weights[i] * (x[i] - x_mean) ** 2 for i in range(n))
        
        if denominator == 0:
            slope = 0
        else:
            slope = numerator / denominator
        
        # Intercept
        intercept = y_mean - slope * x_mean
        
        # Weighted R² calculation
        y_pred = [slope * x[i] + intercept for i in range(n)]
        ss_res = sum(weights[i] * (y[i] - y_pred[i]) ** 2 for i in range(n))
        ss_tot = sum(weights[i] * (y[i] - y_mean) ** 2 for i in range(n))
        
        if ss_tot == 0:
            r_squared = 0
        else:
            r_squared = 1 - (ss_res / ss_tot)
        
        # Normalize slope to price percentage
        slope_pct = (slope / y_mean) * 100 if y_mean != 0 else 0
        
        # Determine vote (stejná logika jako standardní regression)
        significant_slope = abs(slope_pct) > self.slope_threshold * 2
        
        if r_squared >= self.r2_threshold:
            if slope_pct > self.slope_threshold:
                vote = "TREND_UP"
            elif slope_pct < -self.slope_threshold:
                vote = "TREND_DOWN"
            else:
                vote = "RANGE"
        elif significant_slope and r_squared > 0.01:
            if slope_pct > self.slope_threshold:
                vote = "TREND_UP"
            elif slope_pct < -self.slope_threshold:
                vote = "TREND_DOWN"
            else:
                vote = "RANGE"
        else:
            vote = "RANGE"
        
        logger.info(f"[REGIME] Weighted Regression - Slope: {slope_pct:.4f}%, R²: {r_squared:.3f}, Vote: {vote}")
        
        return slope, r_squared, vote
    
    def _map_trend_direction(self, trend_direction: Optional[str]) -> Optional[str]:
        """Map regression trend direction to simple UP/DOWN/SIDEWAYS"""
        if trend_direction == "TREND_UP":
            return "UP"
        elif trend_direction == "TREND_DOWN":
            return "DOWN"
        else:
            return "SIDEWAYS"
    
    def _calculate_adx(self, highs: List[float], lows: List[float], closes: List[float]) -> Tuple[float, str, float, float]:
        """
        Calculate Average Directional Index (ADX) without NumPy
        
        Returns:
            (adx_value, vote, di_plus, di_minus) where vote is TREND or RANGE
            di_plus and di_minus are the directional indicators for trend direction
        """
        period = self.adx_period
        
        # Calculate True Range (TR) and Directional Movement
        tr_values = []
        plus_dm = []
        minus_dm = []
        
        for i in range(1, len(highs)):
            # True Range
            high_low = highs[i] - lows[i]
            high_close = abs(highs[i] - closes[i-1])
            low_close = abs(lows[i] - closes[i-1])
            tr = max(high_low, high_close, low_close)
            tr_values.append(tr)
            
            # Directional Movement
            up_move = highs[i] - highs[i-1]
            down_move = lows[i-1] - lows[i]
            
            if up_move > down_move and up_move > 0:
                plus_dm.append(up_move)
            else:
                plus_dm.append(0)
                
            if down_move > up_move and down_move > 0:
                minus_dm.append(down_move)
            else:
                minus_dm.append(0)
        
        # Smooth with EMA
        atr = self._ema(tr_values, period)
        plus_di_raw = self._ema(plus_dm, period)
        minus_di_raw = self._ema(minus_dm, period)
        
        # Calculate DI values
        dx_values = []
        di_plus_values = []
        di_minus_values = []
        for i in range(len(atr)):
            if atr[i] != 0:
                plus_di = 100 * plus_di_raw[i] / atr[i]
                minus_di = 100 * minus_di_raw[i] / atr[i]
                
                # Store DI values
                di_plus_values.append(plus_di)
                di_minus_values.append(minus_di)
                
                # Calculate DX
                di_sum = plus_di + minus_di
                if di_sum != 0:
                    dx = 100 * abs(plus_di - minus_di) / di_sum
                else:
                    dx = 0
                dx_values.append(dx)
            else:
                di_plus_values.append(0)
                di_minus_values.append(0)
                dx_values.append(0)
        
        # Calculate ADX
        if len(dx_values) >= period:
            adx_values = self._ema(dx_values, period)
            current_adx = adx_values[-1] if adx_values else 0
        else:
            current_adx = sum(dx_values) / len(dx_values) if dx_values else 0
        
        # Ensure valid range
        current_adx = max(0.0, min(100.0, current_adx))
        
        # Get final DI+ and DI- values for trend direction
        final_di_plus = di_plus_values[-1] if di_plus_values else 0
        final_di_minus = di_minus_values[-1] if di_minus_values else 0
        
        # Ensure valid range for DI values
        final_di_plus = max(0.0, min(100.0, final_di_plus))
        final_di_minus = max(0.0, min(100.0, final_di_minus))
        
        # Determine vote
        vote = "TREND" if current_adx > self.adx_threshold else "RANGE"
        
        logger.info(f"[REGIME] ADX: {current_adx:.2f}, DI+: {final_di_plus:.2f}, DI-: {final_di_minus:.2f}, Vote: {vote}")
        return current_adx, vote, final_di_plus, final_di_minus
    
    def _calculate_regression(self, closes: List[float]) -> Tuple[float, float, str]:
        """
        Calculate linear regression slope (β) and R² without NumPy
        
        Returns:
            (slope, r_squared, vote) where vote is TREND_UP/TREND_DOWN/RANGE
        """
        # Use last N periods
        y = closes[-self.regression_period:] if len(closes) >= self.regression_period else closes
        n = len(y)
        x = list(range(n))
        
        # Calculate means
        x_mean = sum(x) / n
        y_mean = sum(y) / n
        
        # Calculate slope (β)
        numerator = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n))
        
        if denominator == 0:
            slope = 0
        else:
            slope = numerator / denominator
        
        # Intercept
        intercept = y_mean - slope * x_mean
        
        # R² calculation
        y_pred = [slope * x[i] + intercept for i in range(n)]
        ss_res = sum((y[i] - y_pred[i]) ** 2 for i in range(n))
        ss_tot = sum((y[i] - y_mean) ** 2 for i in range(n))
        
        if ss_tot == 0:
            r_squared = 0
        else:
            r_squared = 1 - (ss_res / ss_tot)
        
        # Normalize slope to price percentage
        slope_pct = (slope / y_mean) * 100 if y_mean != 0 else 0
        
        # Determine vote
        # VYLEPŠENÁ LOGIKA: Pokud je slope významný, použijeme ho i při nižším R²
        # Nízké R² může být způsobeno pullbacky v rámci trendu, ne absencí trendu
        significant_slope = abs(slope_pct) > self.slope_threshold * 2  # 2x threshold = významný slope
        
        if r_squared >= self.r2_threshold:
            # Vysoké R² - jasný lineární trend
            if slope_pct > self.slope_threshold:
                vote = "TREND_UP"
            elif slope_pct < -self.slope_threshold:
                vote = "TREND_DOWN"
            else:
                vote = "RANGE"
        elif significant_slope and r_squared > 0.01:
            # Nízké R², ale významný slope - může to být trend s pullbacky
            # Použijeme slope pro určení směru, ale s nižší confidence
            if slope_pct > self.slope_threshold:
                vote = "TREND_UP"
            elif slope_pct < -self.slope_threshold:
                vote = "TREND_DOWN"
            else:
                vote = "RANGE"
        else:
            # Nízké R² a nevýznamný slope - RANGE
            vote = "RANGE"
        
        logger.info(f"[REGIME] Regression - Slope: {slope_pct:.4f}%, R²: {r_squared:.3f}, Vote: {vote}")
    
        return slope, r_squared, vote
    
    def _calculate_hurst(self, closes: List[float]) -> Tuple[float, str]:
        """
        Calculate Hurst Exponent for trend persistence without NumPy
        H > 0.5: Trending
        H = 0.5: Random walk
        H < 0.5: Mean reverting (Range)
        
        Returns:
            (hurst_value, vote) where vote is TREND or RANGE
        """
        # Simple R/S analysis
        lags = list(range(2, min(20, len(closes) // 2)))
        tau = []
        
        for lag in lags:
            # Calculate returns
            returns = [closes[i] - closes[i-1] for i in range(1, lag)]
            if len(returns) == 0:
                continue
                
            # Calculate mean and std
            mean = sum(returns) / len(returns)
            variance = sum((r - mean) ** 2 for r in returns) / len(returns)
            std = math.sqrt(variance) if variance > 0 else 0
            
            if std == 0:
                continue
            
            # Calculate cumulative deviations
            cumsum = []
            cumulative = 0
            for r in returns:
                cumulative += (r - mean)
                cumsum.append(cumulative)
            
            # Calculate R/S
            if cumsum:
                R = max(cumsum) - min(cumsum)
                S = std
                
                if S != 0:
                    tau.append(R / S)
        
        if len(tau) > 2:
            # Fit log-log regression
            log_lags = [math.log(lag) for lag in lags[:len(tau)]]
            log_tau = [math.log(t) for t in tau]
            
            # Calculate Hurst exponent (slope of log-log plot)
            n = len(log_lags)
            x_mean = sum(log_lags) / n
            y_mean = sum(log_tau) / n
            
            numerator = sum((log_lags[i] - x_mean) * (log_tau[i] - y_mean) for i in range(n))
            denominator = sum((log_lags[i] - x_mean) ** 2 for i in range(n))
            
            if denominator != 0:
                hurst = numerator / denominator
            else:
                hurst = 0.5
        else:
            hurst = 0.5  # Default to random walk
        
        # Determine vote
        vote = "TREND" if hurst > self.hurst_threshold else "RANGE"
        
        logger.info(f"[REGIME] Hurst: {hurst:.3f}, Vote: {vote}")
        return hurst, vote
    
    def _ensemble_vote(self, adx_vote: str, regression_vote: str, 
                       hurst_vote: Optional[str], di_plus: float = 0, di_minus: float = 0) -> Tuple[RegimeType, float, Dict, str]:
        """
        Ensemble voting: 2 out of 3 agreement
        
        Returns:
            (regime_type, confidence, votes_dict, trend_direction)
        """
        votes = {
            'adx': adx_vote,
            'regression': regression_vote
        }
        
        if hurst_vote:
            votes['hurst'] = hurst_vote
        
        # Count votes
        trend_votes = 0
        range_votes = 0
        trend_direction = None  # Will be set based on final regime
        
        # ADX vote
        if adx_vote == "TREND":
            trend_votes += 1
        else:
            range_votes += 1
        
        # Regression vote
        if regression_vote in ["TREND_UP", "TREND_DOWN"]:
            trend_votes += 1
            trend_direction = regression_vote  # Set from regression if it's trending
        else:
            range_votes += 1
        
        # Hurst vote (if enabled)
        if hurst_vote:
            if hurst_vote == "TREND":
                trend_votes += 1
            else:
                range_votes += 1
        
        # Determine regime
        total_votes = trend_votes + range_votes
        
        # === VYLEPŠENÁ LOGIKA: ADX má větší váhu ===
        # Pokud ADX říká TREND a je nad threshold, měl by mít prioritu
        # Regression může být nejasný kvůli pullbackům nebo nelinearitě
        
        if trend_votes >= 2:
            # Trend regime - 2 z 3 souhlasí
            if trend_direction == "TREND_UP":
                regime = RegimeType.TREND_UP
            elif trend_direction == "TREND_DOWN":
                regime = RegimeType.TREND_DOWN
            else:
                # ADX and Hurst say trend but regression is unclear
                # Použijeme trend směr z ADX DI
                if adx_vote == "TREND":
                    if di_plus > di_minus:
                        regime = RegimeType.TREND_UP
                        trend_direction = "TREND_UP"
                    elif di_minus > di_plus:
                        regime = RegimeType.TREND_DOWN
                        trend_direction = "TREND_DOWN"
                    else:
                        # Default to UP trend
                        regime = RegimeType.TREND_UP
                        trend_direction = "TREND_UP"
                else:
                    # Default to UP trend
                    regime = RegimeType.TREND_UP
                    trend_direction = "TREND_UP"
            
            confidence = (trend_votes / total_votes) * 100
        elif adx_vote == "TREND" and trend_votes == 1:
            # === NOVÁ LOGIKA: ADX TREND má prioritu ===
            # Pokud ADX říká TREND (i když regression říká RANGE), použijeme ADX trend
            # To je důležité, protože ADX je spolehlivější pro detekci trendu
            # Regression může být nejasný kvůli pullbackům v rámci trendu
            if di_plus > di_minus:
                regime = RegimeType.TREND_UP
                trend_direction = "TREND_UP"
            elif di_minus > di_plus:
                regime = RegimeType.TREND_DOWN
                trend_direction = "TREND_DOWN"
            else:
                # Není jasný směr z DI, použijeme regression pokud je dostupný
                if regression_vote in ["TREND_UP", "TREND_DOWN"]:
                    regime = RegimeType.TREND_UP if regression_vote == "TREND_UP" else RegimeType.TREND_DOWN
                    trend_direction = regression_vote
                else:
                    # Default to UP trend
                    regime = RegimeType.TREND_UP
                    trend_direction = "TREND_UP"
            
            confidence = 60.0  # Střední confidence - ADX říká trend, ale regression ne
            logger.info(f"[REGIME] ADX priority: Using ADX trend despite regression=RANGE")
        else:
            # Range regime - žádný trend vote nebo ADX také říká RANGE
            regime = RegimeType.RANGE
            # Pokud ADX říká TREND, použijeme trend směr z ADX DI (pro fallback)
            if adx_vote == "TREND":
                # ADX říká trend, použijeme DI+ a DI- pro určení směru
                if di_plus > di_minus:
                    trend_direction = "TREND_UP"  # Pozitivní trend podle DI+
                elif di_minus > di_plus:
                    trend_direction = "TREND_DOWN"  # Negativní trend podle DI-
                else:
                    trend_direction = "RANGE"  # Není jasný směr
            else:
                trend_direction = "RANGE"
            confidence = (range_votes / total_votes) * 100
        
        logger.info(f"[REGIME] Final result: {regime.value}, Confidence: {confidence:.1f}%, "
               f"Votes: ADX={adx_vote}, REG={regression_vote}"
               f"{f', HURST={hurst_vote}' if hurst_vote else ''}")
        
        return regime, confidence, votes, trend_direction
    
    def _ema(self, values: List[float], period: int) -> List[float]:
        """
        Exponential Moving Average calculation
        """
        if not values:
            return []
            
        alpha = 2 / (period + 1)
        ema = [values[0]]
        
        for i in range(1, len(values)):
            ema.append(alpha * values[i] + (1 - alpha) * ema[-1])
        
        return ema
    
    def get_state_summary(self) -> Dict:
        """
        Get summary of current regime state for UI/logging
        """
        if not self.last_state:
            return {
                "regime": "UNKNOWN",
                "state": "UNKNOWN",
                "confidence": 0,
                "adx": 0,
                "slope": 0,
                "r2": 0,
                "trend_direction": None,
                "votes": {}
            }
        
        result = {
            "regime": self.last_state.regime.value,
            "state": self.last_state.regime.value,  # For compatibility
            "confidence": self.last_state.confidence,
            "adx": round(self.last_state.adx_value, 2),
            "slope": round(self.last_state.regression_slope, 6),
            "r2": round(self.last_state.regression_r2, 3),
            "trend_direction": self.last_state.trend_direction,
            "votes": self.last_state.votes or {}
        }
        
        # Add new multi-timeframe fields
        if self.last_state.primary_regime:
            result["primary_regime"] = self.last_state.primary_regime
        if self.last_state.secondary_regime:
            result["secondary_regime"] = self.last_state.secondary_regime
        if self.last_state.trend_change:
            result["trend_change"] = self.last_state.trend_change
        if self.last_state.ema34_trend:
            result["ema34_trend"] = self.last_state.ema34_trend
        result["used_timeframe"] = self.last_state.used_timeframe
        
        return result