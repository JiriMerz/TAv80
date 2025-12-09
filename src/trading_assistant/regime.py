"""
Regime Detection Module - NO NUMPY VERSION
Sprint 1: Trend vs Range detection using ensemble voting
Fixed version without NumPy dependency
28-08-28 08:00
"""

from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
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
    votes: Dict[str, str] = None
    timestamp: str = ""


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
        self.use_hurst = self.config.get('use_hurst', False)
        self.hurst_threshold = self.config.get('hurst_threshold', 0.5)
        
        # State storage
        self.last_state: Optional[RegimeState] = None
        
    def detect(self, bars: List[Dict]) -> RegimeState:
        """
        Main detection method - ensemble voting
        
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
        
        # 1. Calculate ADX
        adx_value, adx_vote = self._calculate_adx(highs, lows, closes)
        
        # 2. Calculate Linear Regression
        slope, r2, regression_vote = self._calculate_regression(closes)
        
        # 3. Calculate Hurst (optional)
        hurst_value = None
        hurst_vote = None
        if self.use_hurst:
            hurst_value, hurst_vote = self._calculate_hurst(closes)
        
        # 4. Ensemble voting
        regime, confidence, votes, trend_direction = self._ensemble_vote(
            adx_vote, regression_vote, hurst_vote
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
        
        self.last_state = state
        return state
    
    def _map_trend_direction(self, trend_direction: Optional[str]) -> Optional[str]:
        """Map regression trend direction to simple UP/DOWN/SIDEWAYS"""
        if trend_direction == "TREND_UP":
            return "UP"
        elif trend_direction == "TREND_DOWN":
            return "DOWN"
        else:
            return "SIDEWAYS"
    
    def _calculate_adx(self, highs: List[float], lows: List[float], closes: List[float]) -> Tuple[float, str]:
        """
        Calculate Average Directional Index (ADX) without NumPy
        
        Returns:
            (adx_value, vote) where vote is TREND or RANGE
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
        for i in range(len(atr)):
            if atr[i] != 0:
                plus_di = 100 * plus_di_raw[i] / atr[i]
                minus_di = 100 * minus_di_raw[i] / atr[i]
                
                # Calculate DX
                di_sum = plus_di + minus_di
                if di_sum != 0:
                    dx = 100 * abs(plus_di - minus_di) / di_sum
                else:
                    dx = 0
                dx_values.append(dx)
            else:
                dx_values.append(0)
        
        # Calculate ADX
        if len(dx_values) >= period:
            adx_values = self._ema(dx_values, period)
            current_adx = adx_values[-1] if adx_values else 0
        else:
            current_adx = sum(dx_values) / len(dx_values) if dx_values else 0
        
        # Ensure valid range
        current_adx = max(0.0, min(100.0, current_adx))
        
        # Determine vote
        vote = "TREND" if current_adx > self.adx_threshold else "RANGE"
        
        logger.info(f"[REGIME] ADX: {current_adx:.2f}, Vote: {vote}")
        return current_adx, vote
    
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
        if r_squared >= self.r2_threshold:
            if slope_pct > self.slope_threshold:
                vote = "TREND_UP"
            elif slope_pct < -self.slope_threshold:
                vote = "TREND_DOWN"
            else:
                vote = "RANGE"
        else:
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
                       hurst_vote: Optional[str]) -> Tuple[RegimeType, float, Dict, str]:
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
        
        if trend_votes >= 2:
            # Trend regime
            if trend_direction == "TREND_UP":
                regime = RegimeType.TREND_UP
            elif trend_direction == "TREND_DOWN":
                regime = RegimeType.TREND_DOWN
            else:
                # ADX and Hurst say trend but regression is unclear
                # Default to UP trend (can be improved later with additional logic)
                regime = RegimeType.TREND_UP
                trend_direction = "TREND_UP"
            
            confidence = (trend_votes / total_votes) * 100
        else:
            # Range regime
            regime = RegimeType.RANGE
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
            return {"regime": "UNKNOWN", "confidence": 0}
        
        return {
            "regime": self.last_state.regime.value,
            "state": self.last_state.regime.value,  # For compatibility
            "confidence": self.last_state.confidence,
            "adx": round(self.last_state.adx_value, 2),
            "slope": round(self.last_state.regression_slope, 6),
            "r2": round(self.last_state.regression_r2, 3),
            "trend_direction": self.last_state.trend_direction,
            "votes": self.last_state.votes
        }