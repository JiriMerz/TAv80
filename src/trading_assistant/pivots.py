"""
Pivot Levels Calculator Module - NO NUMPY VERSION
Sprint 1: Daily and Weekly Floor Pivots with ATR-based tolerance
Fixed version without NumPy dependency
25-08-28 08:00
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class PivotLevel:
    """Single pivot level with metadata"""
    name: str  # e.g., "R2", "S1", "P"
    value: float
    type: str  # "resistance", "support", "pivot"
    timeframe: str  # "daily", "weekly"
    strength: int  # 1-3 (3 being strongest)


@dataclass
class PivotSet:
    """Complete set of pivot levels"""
    pivot: float  # Central pivot point
    r1: float  # Resistance 1
    r2: float  # Resistance 2
    r3: Optional[float] = None  # Resistance 3
    s1: float = 0  # Support 1
    s2: float = 0  # Support 2
    s3: Optional[float] = None  # Support 3
    timeframe: str = "daily"
    calculated_at: str = ""
    levels: List[PivotLevel] = field(default_factory=list)
    
    def __post_init__(self):
        """Create PivotLevel objects after initialization"""
        if not self.levels:
            self.levels = [
                PivotLevel("P", self.pivot, "pivot", self.timeframe, 2),
                PivotLevel("R1", self.r1, "resistance", self.timeframe, 1),
                PivotLevel("R2", self.r2, "resistance", self.timeframe, 2),
                PivotLevel("S1", self.s1, "support", self.timeframe, 1),
                PivotLevel("S2", self.s2, "support", self.timeframe, 2),
            ]
            
            if self.r3:
                self.levels.append(PivotLevel("R3", self.r3, "resistance", self.timeframe, 3))
            if self.s3:
                self.levels.append(PivotLevel("S3", self.s3, "support", self.timeframe, 3))


class PivotCalculator:
    """
    Calculate Floor Trader Pivots for daily and weekly timeframes
    Includes ATR-based tolerance for touch/retest detection
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize pivot calculator
        
        Args:
            config: Configuration with ATR tolerance settings
        """
        self.config = config or {}
        
        # ATR tolerance for pivot touch detection (multiplier)
        self.atr_tolerance = self.config.get('pivot_tolerance_atr', 0.20)
        
        # Whether to calculate weekly pivots
        self.use_weekly = self.config.get('use_weekly_pivots', False)
        
        # Store last calculated pivots
        self.daily_pivots: Optional[PivotSet] = None
        self.weekly_pivots: Optional[PivotSet] = None
        self.current_atr: float = 0
        
    def calculate_pivots(self, bars: List[Dict], timeframe: str = "M1") -> Dict[str, PivotSet]:
        """
        Calculate pivot levels from bars
        
        Args:
            bars: List of OHLC bars
            timeframe: Current timeframe of bars
            
        Returns:
            Dictionary with 'daily' and optionally 'weekly' PivotSets
        """
        # NOVÝ LOG
        logger.info(f"[PIVOT] Starting pivot calculation with {len(bars)} bars, timeframe: {timeframe}")
        
        if len(bars) < 20:
            # ROZŠÍŘENÝ LOG
            logger.warning(f"[PIVOT] Insufficient bars for pivot calculation: {len(bars)} < 20")
            return {}
        
        results = {}
        
        # Calculate daily pivots
        daily = self._calculate_daily_pivots(bars, timeframe)
        if daily:
            self.daily_pivots = daily
            results['daily'] = daily
            # NOVÝ LOG
            logger.info(f"[PIVOT] Daily pivots calculated: P={daily.pivot:.2f}, "
                    f"R1={daily.r1:.2f}, R2={daily.r2:.2f}, R3={(daily.r3 if daily.r3 else 0):.2f},"
                    f"S1={daily.s1:.2f}, S2={daily.s2:.2f}, S3={(daily.s3 if daily.s3 else 0):.2f}")
        else:
            # NOVÝ LOG
            logger.warning("[PIVOT] Failed to calculate daily pivots")
        
        # Calculate weekly pivots if enabled
        if self.use_weekly:
            weekly = self._calculate_weekly_pivots(bars, timeframe)
            if weekly:
                self.weekly_pivots = weekly
                results['weekly'] = weekly
                # NOVÝ LOG
                logger.info(f"[PIVOT] Weekly pivots calculated: P={weekly.pivot:.2f}, "
                        f"R1={weekly.r1:.2f}, R2={weekly.r2:.2f}, "
                        f"S1={weekly.s1:.2f}, S2={weekly.s2:.2f}")
            else:
                # NOVÝ LOG
                logger.debug("[PIVOT] Weekly pivots not calculated or disabled")
        
        # Calculate current ATR for tolerance
        self.current_atr = self._calculate_atr(bars)
        # NOVÝ LOG
        logger.debug(f"[PIVOT] Current ATR for tolerance: {self.current_atr:.5f}, "
                    f"tolerance multiplier: {self.atr_tolerance}")
        
        # NOVÝ LOG - shrnutí
        logger.info(f"[PIVOT] Calculation complete: {len(results)} pivot sets created")
        
        return results
    
    def _calculate_daily_pivots(self, bars: List[Dict], timeframe: str) -> Optional[PivotSet]:
        """
        Calculate daily floor pivots using previous day's HLC
        
        Formula:
        P = (H + L + C) / 3
        R1 = 2*P - L
        R2 = P + (H - L)
        R3 = H + 2*(P - L)
        S1 = 2*P - H
        S2 = P - (H - L)
        S3 = L - 2*(H - P)
        """
        # NOVÝ LOG
        logger.debug(f"[PIVOT] Calculating daily pivots from {len(bars)} bars")
        
        # Get previous day's data
        prev_day_data = self._get_previous_period_hlc(bars, "daily", timeframe)
        
        if not prev_day_data:
            # ROZŠÍŘENÝ LOG
            logger.warning("[PIVOT] Cannot determine previous day's HLC - insufficient data or invalid bars")
            return None
        
        h, l, c = prev_day_data
        
        # NOVÝ LOG
        logger.debug(f"[PIVOT] Previous day data: H={h:.2f}, L={l:.2f}, C={c:.2f}")
        
        # Calculate pivot point
        pivot = (h + l + c) / 3
        
        # Calculate resistance levels
        r1 = 2 * pivot - l
        r2 = pivot + (h - l)
        r3 = h + 2 * (pivot - l)
        
        # Calculate support levels
        s1 = 2 * pivot - h
        s2 = pivot - (h - l)
        s3 = l - 2 * (h - pivot)
        
        # NOVÝ LOG
        logger.debug(f"[PIVOT] Daily levels calculated: P={pivot:.2f}, "
                    f"Range={h-l:.2f}, R3-S3 span={r3-s3:.2f}")
        
        pivot_set = PivotSet(
            pivot=round(pivot, 5),
            r1=round(r1, 5),
            r2=round(r2, 5),
            r3=round(r3, 5),
            s1=round(s1, 5),
            s2=round(s2, 5),
            s3=round(s3, 5),
            timeframe="daily",
            calculated_at=datetime.now().isoformat()
        )
        
        # NOVÝ LOG
        logger.debug(f"[PIVOT] Daily pivot set created with {len(pivot_set.levels)} levels")
        
        return pivot_set

    def _calculate_weekly_pivots(self, bars: List[Dict], timeframe: str) -> Optional[PivotSet]:
        """
        Calculate weekly floor pivots using previous week's HLC
        """
        # Get previous week's data
        prev_week_data = self._get_previous_period_hlc(bars, "weekly", timeframe)
        
        if not prev_week_data:
            logger.warning("Cannot determine previous week's HLC")
            return None
        
        h, l, c = prev_week_data
        
        # Calculate pivot point
        pivot = (h + l + c) / 3
        
        # Calculate resistance levels
        r1 = 2 * pivot - l
        r2 = pivot + (h - l)
        
        # Calculate support levels
        s1 = 2 * pivot - h
        s2 = pivot - (h - l)
        
        return PivotSet(
            pivot=round(pivot, 5),
            r1=round(r1, 5),
            r2=round(r2, 5),
            r3=None,  # Weekly typically uses only R1/R2
            s1=round(s1, 5),
            s2=round(s2, 5),
            s3=None,  # Weekly typically uses only S1/S2
            timeframe="weekly",
            calculated_at=datetime.now().isoformat()
        )
    
    def _get_previous_period_hlc(self, bars: List[Dict], period: str, timeframe: str) -> Optional[Tuple[float, float, float]]:
        """Extract previous period's High, Low, Close - TIMESTAMP BASED"""
        if not bars or len(bars) < 2:
            return None
        
        # Try timestamp-based approach first (more accurate)
        if period == "daily":
            try:
                return self._get_previous_day_hlc_by_timestamp(bars)
            except Exception as e:
                logger.debug(f"[PIVOT] Timestamp approach failed: {e}, falling back to bar counting")
        
        # Fallback to bar counting approach
        if timeframe == "M5":
            if period == "daily":
                # Conservative approach: ~120 M5 bars per trading session
                # Reduced from 288 (24h) to ~120 (10h trading session)
                session_bars = 120  
                
                if len(bars) >= session_bars:
                    # Get previous trading session
                    period_bars = bars[-session_bars*2:-session_bars] if len(bars) >= session_bars*2 else bars[-session_bars:]
                else:
                    # Not enough data for full session, use what we have
                    period_bars = bars[:-1] if len(bars) > 50 else bars
            else:  # weekly
                # 1440 M5 bars = 1 week (5 days * 288)
                if len(bars) >= 1440:
                    period_bars = bars[-2880:-1440] if len(bars) >= 2880 else bars[-1440:]
                else:
                    period_bars = bars[:-1] if len(bars) > 200 else bars
        
        # M1 calculations (original)
        elif timeframe == "M1":
            if period == "daily":
                if len(bars) >= 1440:
                    period_bars = bars[-2880:-1440]
                else:
                    period_bars = bars[:-1] if len(bars) > 100 else bars
            else:  # weekly
                if len(bars) >= 7200:
                    period_bars = bars[-14400:-7200]
                else:
                    period_bars = bars[:-1] if len(bars) > 500 else bars
        
        # Other timeframes - simple fallback
        else:
            period_bars = bars[:-1] if len(bars) > 20 else bars
        
        if not period_bars:
            return None
        
        high = max(b['high'] for b in period_bars)
        low = min(b['low'] for b in period_bars)
        close = period_bars[-1]['close']
        
        return high, low, close
    
    def _get_previous_day_hlc_by_timestamp(self, bars: List[Dict]) -> Optional[Tuple[float, float, float]]:
        """
        Get previous trading day's OHLC using timestamps
        More accurate than bar counting approach
        """
        from datetime import datetime, timedelta
        
        if not bars or len(bars) < 10:
            return None
        
        # Get the timestamp of the last bar
        last_bar = bars[-1]
        last_timestamp_str = last_bar.get('timestamp')
        
        if not last_timestamp_str:
            raise ValueError("No timestamp in bars")
        
        # Parse timestamp (handle different formats)
        try:
            if isinstance(last_timestamp_str, str):
                # Try common formats
                try:
                    last_time = datetime.fromisoformat(last_timestamp_str.replace('Z', '+00:00'))
                except:
                    try:
                        last_time = datetime.strptime(last_timestamp_str, '%Y-%m-%d %H:%M:%S')
                    except:
                        last_time = datetime.strptime(last_timestamp_str, '%Y-%m-%d %H:%M')
            else:
                last_time = last_timestamp_str
        except Exception as e:
            raise ValueError(f"Cannot parse timestamp: {last_timestamp_str}")
        
        # Calculate previous day time window
        # We want bars from previous trading session (roughly 12-36 hours ago)
        prev_day_end = last_time - timedelta(hours=12)   # Recent boundary
        prev_day_start = last_time - timedelta(hours=36) # Older boundary
        
        logger.debug(f"[PIVOT] Looking for previous day bars between {prev_day_start} and {prev_day_end}")
        
        # Find bars from previous trading day
        prev_day_bars = []
        
        for bar in bars:
            bar_timestamp_str = bar.get('timestamp')
            if not bar_timestamp_str:
                continue
                
            try:
                if isinstance(bar_timestamp_str, str):
                    try:
                        bar_time = datetime.fromisoformat(bar_timestamp_str.replace('Z', '+00:00'))
                    except:
                        try:
                            bar_time = datetime.strptime(bar_timestamp_str, '%Y-%m-%d %H:%M:%S')
                        except:
                            bar_time = datetime.strptime(bar_timestamp_str, '%Y-%m-%d %H:%M')
                else:
                    bar_time = bar_timestamp_str
                    
                # Check if bar is from previous trading session (12-36h ago)
                if prev_day_start <= bar_time <= prev_day_end:
                    prev_day_bars.append(bar)
                    
            except Exception:
                continue  # Skip bars with invalid timestamps
        
        # If no bars found with timestamp method, use simpler approach
        if len(prev_day_bars) < 10:
            logger.debug(f"[PIVOT] Only {len(prev_day_bars)} bars found with timestamp method, using fallback")
            # Take bars from earlier period (roughly previous day equivalent)
            prev_day_bars = bars[-240:-120] if len(bars) >= 240 else bars[-120:] if len(bars) >= 120 else bars[:-10]
        
        if not prev_day_bars:
            return None
        
        # Calculate OHLC from previous day bars
        high = max(b['high'] for b in prev_day_bars)
        low = min(b['low'] for b in prev_day_bars)
        close = prev_day_bars[-1]['close']  # Last close of the session
        
        logger.info(f"[PIVOT] Previous day OHLC from {len(prev_day_bars)} bars: H={high:.2f}, L={low:.2f}, C={close:.2f}")
        
        return high, low, close
    
    def _calculate_atr(self, bars: List[Dict], period: int = 14) -> float:
        """
        Calculate Average True Range for tolerance calculations
        Without NumPy dependency
        """
        if len(bars) < period + 1:
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
        
        # Simple moving average of TR
        if len(tr_values) >= period:
            # Take last 'period' values and calculate average
            recent_tr = tr_values[-period:]
            atr = sum(recent_tr) / len(recent_tr)
        else:
            # Use all available values
            atr = sum(tr_values) / len(tr_values) if tr_values else 0
        
        return atr
    
    def get_nearest_pivot(self, price: float, direction: str = "both") -> Optional[PivotLevel]:
        """
        Find nearest pivot level to current price
        
        Args:
            price: Current price
            direction: "above", "below", or "both"
            
        Returns:
            Nearest PivotLevel or None
        """
        if not self.daily_pivots:
            # NOVÝ LOG
            logger.debug(f"[PIVOT] No daily pivots available for nearest pivot search")
            return None
        
        all_levels = self.daily_pivots.levels.copy()
        
        if self.weekly_pivots:
            all_levels.extend(self.weekly_pivots.levels)
            logger.debug(f"[PIVOT] Searching through {len(all_levels)} levels (daily + weekly)")
        else:
            logger.debug(f"[PIVOT] Searching through {len(all_levels)} daily levels only")
        
        # Filter by direction
        if direction == "above":
            levels = [l for l in all_levels if l.value > price]
            logger.debug(f"[PIVOT] Found {len(levels)} levels above {price:.2f}")
        elif direction == "below":
            levels = [l for l in all_levels if l.value < price]
            logger.debug(f"[PIVOT] Found {len(levels)} levels below {price:.2f}")
        else:
            levels = all_levels
        
        if not levels:
            # NOVÝ LOG
            logger.debug(f"[PIVOT] No pivot levels found {direction} price {price:.2f}")
            return None
        
        # Sort by distance from price
        levels.sort(key=lambda l: abs(l.value - price))
        
        nearest = levels[0]
        distance = abs(nearest.value - price)
        
        # NOVÝ LOG
        logger.info(f"[PIVOT] Nearest pivot to {price:.2f}: {nearest.name} at {nearest.value:.2f} "
                f"({nearest.timeframe}), distance: {distance:.2f} "
                f"({distance/self.current_atr if self.current_atr > 0 else 0:.2f} ATR)")
        
        # Debug log pro další blízké pivoty
        if len(levels) > 1:
            logger.debug(f"[PIVOT] Next nearest: {levels[1].name} at {levels[1].value:.2f}")
        
        return nearest
    
    def check_pivot_touch(self, price: float, pivot_level: float) -> bool:
        """
        Check if price touches/tests a pivot level within ATR tolerance
        
        Args:
            price: Current price
            pivot_level: Pivot level to check
            
        Returns:
            True if price is within tolerance of pivot
        """
        tolerance = self.current_atr * self.atr_tolerance
        distance = abs(price - pivot_level)
        is_touch = distance <= tolerance
        
        # NOVÝ LOG - vždy loguj kontrolu, ale různé úrovně
        if is_touch:
            logger.info(f"[PIVOT] ✅ Touch detected: price={price:.2f} touches pivot={pivot_level:.2f}, "
                    f"distance={distance:.5f} <= tolerance={tolerance:.5f} "
                    f"({distance/self.current_atr if self.current_atr > 0 else 0:.2f} ATR)")
        else:
            # Debug log pro blízké přiblížení
            if distance <= tolerance * 2:
                logger.debug(f"[PIVOT] Near miss: price={price:.2f} approaching pivot={pivot_level:.2f}, "
                            f"distance={distance:.5f} > tolerance={tolerance:.5f}")
        
        return is_touch
    
    def get_pivot_distance(self, price: float, pivot_level: float) -> float:
        """
        Get distance from price to pivot in ATR units
        
        Returns:
            Distance in ATR units (can be negative if below)
        """
        if self.current_atr == 0:
            return 0
        
        return (price - pivot_level) / self.current_atr
    
    def find_pivot_confluence(self, price: float, max_distance_atr: float = 0.5) -> List[PivotLevel]:
        """
        Find all pivots within specified ATR distance
        
        Args:
            price: Current price
            max_distance_atr: Maximum distance in ATR units
            
        Returns:
            List of nearby pivot levels
        """
        if not self.daily_pivots:
            # NOVÝ LOG
            logger.debug(f"[PIVOT] No pivots available for confluence search")
            return []
        
        confluence = []
        max_distance = self.current_atr * max_distance_atr
        
        # NOVÝ LOG
        logger.debug(f"[PIVOT] Searching for confluence within {max_distance:.2f} "
                    f"({max_distance_atr} ATR) of price {price:.2f}")
        
        all_levels = self.daily_pivots.levels.copy()
        if self.weekly_pivots:
            all_levels.extend(self.weekly_pivots.levels)
        
        # Počet testovaných úrovní
        logger.debug(f"[PIVOT] Testing {len(all_levels)} pivot levels for confluence")
        
        for level in all_levels:
            distance = abs(price - level.value)
            if distance <= max_distance:
                confluence.append(level)
                # Debug log pro každou nalezenou úroveň
                logger.debug(f"[PIVOT] Confluence found: {level.name} at {level.value:.2f}, "
                            f"distance={distance:.2f} ({distance/self.current_atr if self.current_atr > 0 else 0:.2f} ATR)")
        
        # Sort by distance
        confluence.sort(key=lambda l: abs(price - l.value))
        
        # NOVÝ LOG - shrnutí
        if confluence:
            levels_str = ', '.join([f"{l.name}({l.value:.2f})" for l in confluence[:3]])
            if len(confluence) > 3:
                levels_str += f" + {len(confluence)-3} more"
            logger.info(f"[PIVOT] Found {len(confluence)} pivots near {price:.2f}: {levels_str}")
        else:
            logger.debug(f"[PIVOT] No pivot confluence found within {max_distance_atr} ATR of {price:.2f}")
        
        return confluence
    
    def get_pivot_summary(self) -> Dict:
        """
        Get summary of current pivots for UI/logging
        """
        summary = {
            "daily": None,
            "weekly": None,
            "atr": round(self.current_atr, 5)
        }
        
        if self.daily_pivots:
            summary["daily"] = {
                "P": self.daily_pivots.pivot,
                "R1": self.daily_pivots.r1,
                "R2": self.daily_pivots.r2,
                "S1": self.daily_pivots.s1,
                "S2": self.daily_pivots.s2
            }
        
        if self.weekly_pivots:
            summary["weekly"] = {
                "P": self.weekly_pivots.pivot,
                "R1": self.weekly_pivots.r1,
                "R2": self.weekly_pivots.r2,
                "S1": self.weekly_pivots.s1,
                "S2": self.weekly_pivots.s2
            }
        
        return summary
    
    def suggest_sl_tp(self, entry_price: float, direction: str, 
                      risk_reward: float = 1.5) -> Optional[Dict]:
        """
        Suggest SL/TP based on pivot levels
        
        Args:
            entry_price: Entry price
            direction: "long" or "short"
            risk_reward: Target risk/reward ratio
            
        Returns:
            Dictionary with suggested SL and TP levels
        """
        if not self.daily_pivots:
            return None
        
        buffer = self.current_atr * 0.25  # ATR buffer for SL
        
        if direction == "long":
            # Find support below for SL
            sl_pivot = self.get_nearest_pivot(entry_price, "below")
            if sl_pivot:
                sl = sl_pivot.value - buffer
                risk = entry_price - sl
                tp = entry_price + (risk * risk_reward)
                
                # Find resistance near TP
                tp_pivot = self.get_nearest_pivot(tp, "both")
                if tp_pivot and tp_pivot.type == "resistance":
                    tp = tp_pivot.value - (buffer * 0.5)  # Smaller buffer for TP
            else:
                return None
                
        else:  # short
            # Find resistance above for SL
            sl_pivot = self.get_nearest_pivot(entry_price, "above")
            if sl_pivot:
                sl = sl_pivot.value + buffer
                risk = sl - entry_price
                tp = entry_price - (risk * risk_reward)
                
                # Find support near TP
                tp_pivot = self.get_nearest_pivot(tp, "both")
                if tp_pivot and tp_pivot.type == "support":
                    tp = tp_pivot.value + (buffer * 0.5)
            else:
                return None
        
        return {
            "sl": round(sl, 5),
            "tp": round(tp, 5),
            "risk": round(abs(entry_price - sl), 5),
            "reward": round(abs(tp - entry_price), 5),
            "rr_ratio": round(abs(tp - entry_price) / abs(entry_price - sl), 2),
            "sl_pivot": sl_pivot.name if sl_pivot else None,
            "tp_pivot": tp_pivot.name if tp_pivot else None
        }