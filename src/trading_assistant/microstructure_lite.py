"""
Microstructure Analysis Module - LITE version for RPi
No numpy/pandas dependencies - uses only Python stdlib
FIXED: All timestamp issues resolved
"""
from datetime import datetime, time, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from collections import deque, defaultdict
import statistics
import logging
import pytz

logger = logging.getLogger(__name__)

def ensure_datetime(timestamp):
    """Convert string timestamp to timezone-aware datetime if needed"""
    if timestamp is None:
        return datetime.now(timezone.utc)
    
    if isinstance(timestamp, str):
        # Handle ISO format with or without timezone
        if 'Z' in timestamp:
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        elif '+' in timestamp or '-' in timestamp[-6:]:
            dt = datetime.fromisoformat(timestamp)
        else:
            # Assume UTC if no timezone
            dt = datetime.fromisoformat(timestamp).replace(tzinfo=timezone.utc)
        return dt
    
    # If already datetime, ensure it has timezone
    if isinstance(timestamp, datetime):
        if timestamp.tzinfo is None:
            return timestamp.replace(tzinfo=timezone.utc)
        return timestamp
    
    return datetime.now(timezone.utc)


class MicrostructureAnalyzer:
    """
    Lightweight microstructure analysis without numpy/pandas
    """
    
    def __init__(self, config: Dict = None):
        self.config = config or {}
        
        # Time windows for profile building (30-minute buckets)
        self.time_buckets = self._create_time_buckets()
        
        # Historical data storage per symbol
        self.volume_profiles = defaultdict(lambda: defaultdict(list))
        self.atr_profiles = defaultdict(lambda: defaultdict(list))
        self.spread_profiles = defaultdict(lambda: defaultdict(list))
        
        # Rolling windows for real-time calculation
        self.volume_window = defaultdict(lambda: deque(maxlen=100))
        self.atr_window = defaultdict(lambda: deque(maxlen=14))
        
        # VWAP anchors storage
        self.vwap_anchors = {}
        
        # Opening range data
        self.opening_ranges = {}
        
        # Configuration
        self.lookback_days = self.config.get('lookback_days', 20)
        self.z_score_threshold = self.config.get('z_score_threshold', 2.0)
        self.or_duration_minutes = self.config.get('or_duration_minutes', 30)
        
        logger.info("MicrostructureAnalyzer LITE initialized (no numpy/pandas)")
    
    def _create_time_buckets(self) -> List[time]:
        """Create 30-minute time buckets for the trading day"""
        buckets = []
        for hour in range(24):
            for minute in [0, 30]:
                buckets.append(time(hour, minute))
        return buckets
    
    def _get_time_bucket(self, timestamp: datetime) -> time:
        """Get the time bucket for a given timestamp"""
        timestamp = ensure_datetime(timestamp)
        minutes = timestamp.hour * 60 + timestamp.minute
        bucket_idx = minutes // 30
        return self.time_buckets[min(bucket_idx, len(self.time_buckets) - 1)]
    
    def _calculate_mean(self, values: List[float]) -> float:
        """Calculate mean without numpy"""
        if not values:
            return 0.0
        return sum(values) / len(values)
    
    def _calculate_std(self, values: List[float]) -> float:
        """Calculate standard deviation without numpy"""
        if len(values) < 2:
            return 0.0
        return statistics.stdev(values)
    
    def update_volume_profile(self, symbol: str, timestamp, volume: float):
        """Update volume profile with new data"""
        timestamp = ensure_datetime(timestamp)
        bucket = self._get_time_bucket(timestamp)
        self.volume_profiles[symbol][bucket].append(volume)
        
        # Keep only recent data
        if len(self.volume_profiles[symbol][bucket]) > self.lookback_days:
            self.volume_profiles[symbol][bucket].pop(0)
        
        # Update rolling window
        self.volume_window[symbol].append((timestamp, volume))

    def update_spread_profile(self, symbol: str, timestamp, spread: float):
        """Update spread profile with new data"""
        timestamp = ensure_datetime(timestamp)
        bucket = self._get_time_bucket(timestamp)
        self.spread_profiles[symbol][bucket].append(spread)

        # Keep only recent data
        if len(self.spread_profiles[symbol][bucket]) > self.lookback_days:
            self.spread_profiles[symbol][bucket].pop(0)

    def get_volume_zscore(self, symbol: str, timestamp, volume: float) -> float:
        """Calculate Z-score for volume relative to time-of-day normal"""
        timestamp = ensure_datetime(timestamp)
        bucket = self._get_time_bucket(timestamp)
        historical = self.volume_profiles[symbol].get(bucket, [])
        
        if len(historical) < 5:  # Need minimum history
            return 0.0
        
        mean_vol = self._calculate_mean(historical)
        std_vol = self._calculate_std(historical)
        
        if std_vol == 0:
            return 0.0
        
        z_score = (volume - mean_vol) / std_vol
        return z_score
    
    def calculate_anchored_vwap(self, symbol: str, bars: List[Dict], 
                              anchor_type: str = 'session') -> Optional[float]:
        """Calculate VWAP anchored from specific points"""
        if not bars:
            return None
        
        # Ensure all timestamps are datetime objects
        for bar in bars:
            bar['timestamp'] = ensure_datetime(bar.get('timestamp'))
        
        now = datetime.now(timezone.utc)
        
        # Determine anchor point
        if anchor_type == 'session':
            # Today's session start
            today_start = now.replace(hour=8, minute=0, second=0, microsecond=0)
            anchor_idx = 0
            for i, bar in enumerate(bars):
                if bar['timestamp'] >= today_start:
                    anchor_idx = i
                    break
        elif anchor_type == 'week':
            # Monday's start
            days_since_monday = now.weekday()
            week_start = now - timedelta(days=days_since_monday)
            week_start = week_start.replace(hour=8, minute=0, second=0, microsecond=0)
            anchor_idx = 0
            for i, bar in enumerate(bars):
                if bar['timestamp'] >= week_start:
                    anchor_idx = i
                    break
        else:
            anchor_idx = 0
        
        # Calculate VWAP from anchor
        total_volume = 0
        total_pv = 0  # price * volume
        
        for bar in bars[anchor_idx:]:
            price = (bar['high'] + bar['low'] + bar['close']) / 3  # Typical price
            volume = bar.get('volume', 0)
            
            total_pv += price * volume
            total_volume += volume
        
        if total_volume == 0:
            return None
        
        vwap = total_pv / total_volume
        
        # Store for later reference
        self.vwap_anchors[symbol] = {
            'value': vwap,
            'anchor_type': anchor_type,
            'timestamp': now,
            'total_volume': total_volume
        }
        
        return vwap

    def get_session_start_utc(self, symbol: str, date: datetime.date) -> Optional[datetime]:
        """Convert session start time to UTC"""
        try:
            tz = pytz.timezone('Europe/Prague')

            # Get session start times from config
            if symbol == 'DAX':
                session_start = datetime.combine(date, time(9, 0))  # 09:00 Prague
            elif symbol == 'NASDAQ':
                session_start = datetime.combine(date, time(14, 30))  # 14:30 Prague
            else:
                logger.warning(f"Unknown symbol for session start: {symbol}")
                return None

            # Convert Prague time to UTC
            local_dt = tz.localize(session_start)
            return local_dt.astimezone(timezone.utc)
        except Exception as e:
            logger.error(f"Error calculating session start for {symbol}: {e}")
            return None

    def detect_opening_range(self, symbol: str, bars: List[Dict]) -> Dict:
        """
        OPRAVENÁ logika - OR od session start, ne od půlnoci
        Detect Opening Range (OR) and Opening Range Breakout (ORB)
        """
        if not bars:
            return {}

        # Ensure datetime objects
        for bar in bars:
            bar['timestamp'] = ensure_datetime(bar.get('timestamp'))

        # Get today's session start in UTC
        today = datetime.now(timezone.utc).date()
        session_start_utc = self.get_session_start_utc(symbol, today)

        if not session_start_utc:
            logger.warning(f"Could not get session start for {symbol}")
            return {}

        # Filter bars from session start onwards (not from midnight!)
        session_bars = []
        for bar in bars:
            bar_ts = ensure_datetime(bar.get('timestamp'))
            bar_date = bar_ts.date()

            if (bar_ts >= session_start_utc and bar_date == today):
                session_bars.append(bar)


        logger.debug(f"[{symbol}] Session bars from {session_start_utc}: {len(session_bars)} bars")
        logger.debug(f"[{symbol}] Today UTC: {today}, Total bars: {len(bars)}")

        # Progressive OR calculation
        if len(session_bars) == 0:
            return {}
        elif len(session_bars) < self.or_duration_minutes // 5:
            # NOVĚ: Progressive OR během prvních 30 minut
            # OPRAVENO: Použít jen prvních or_duration_minutes // 5 barů (stejně jako final OR)
            or_bars_progressive = session_bars[:min(len(session_bars), self.or_duration_minutes // 5)]
            or_high = max(b['high'] for b in or_bars_progressive)
            or_low = min(b['low'] for b in or_bars_progressive)
            or_range = or_high - or_low

            result = {
                'progressive_or': True,
                'bars_collected': len(session_bars),
                'bars_needed': self.or_duration_minutes // 5,
                'or_high': or_high,
                'or_low': or_low,
                'or_range': or_range,
                'or_midpoint': (or_high + or_low) / 2,
                'orb_triggered': False,
                'session_start_utc': session_start_utc
            }
            logger.debug(f"[{symbol}] Progressive OR: {result}")
            return result
        else:
            # Final OR calculation (existing logic)
            or_bars = session_bars[:self.or_duration_minutes // 5]
            or_high = max(b['high'] for b in or_bars)
            or_low = min(b['low'] for b in or_bars)
            or_range = or_high - or_low

            # Check for breakout in subsequent bars
            post_or_bars = session_bars[self.or_duration_minutes // 5:]

            orb_triggered = None
            orb_direction = None
            orb_timestamp = None

            for bar in post_or_bars:
                if bar['high'] > or_high and not orb_triggered:
                    orb_triggered = True
                    orb_direction = 'LONG'
                    orb_timestamp = bar['timestamp']
                    logger.info(f"[{symbol}] ORB LONG triggered at {orb_timestamp}, breakout above {or_high}")
                    break
                elif bar['low'] < or_low and not orb_triggered:
                    orb_triggered = True
                    orb_direction = 'SHORT'
                    orb_timestamp = bar['timestamp']
                    logger.info(f"[{symbol}] ORB SHORT triggered at {orb_timestamp}, breakout below {or_low}")
                    break

            result = {
                'progressive_or': False,
                'bars_collected': len(or_bars),
                'bars_needed': self.or_duration_minutes // 5,
                'or_high': or_high,
                'or_low': or_low,
                'or_range': or_range,
                'or_midpoint': (or_high + or_low) / 2,
                'orb_triggered': orb_triggered,
                'orb_direction': orb_direction,
                'orb_timestamp': orb_timestamp,
                'session_start_utc': session_start_utc
            }
        
        # Store for reference
        self.opening_ranges[symbol] = result
        
        return result

    def calculate_liquidity_score(self, symbol: str, timestamp, 
                                 spread: float, volume: float) -> float:
        """Calculate dynamic liquidity score (0-1)"""
        timestamp = ensure_datetime(timestamp)
        
        # Get time-of-day normalized metrics
        bucket = self._get_time_bucket(timestamp)
        
        # Volume component (0-1)
        vol_zscore = self.get_volume_zscore(symbol, timestamp, volume)
        vol_score = min(1.0, max(0.0, (vol_zscore + 2) / 4))  # Map z-score to 0-1
        
        # Spread component (0-1)
        spread_history = self.spread_profiles[symbol].get(bucket, [])
        if spread_history:
            avg_spread = self._calculate_mean(spread_history)
            spread_score = max(0.0, 1.0 - (spread / avg_spread)) if avg_spread > 0 else 0.5
        else:
            spread_score = 0.5  # Neutral if no history
        
        # Time-of-day component (0-1)
        hour = timestamp.hour
        
        # Peak liquidity times (adjust per market)
        if symbol in ['DAX', 'DE40']:
            # DAX peak: 9-11 AM and 2-4 PM CET
            if (9 <= hour < 11) or (14 <= hour < 16):
                time_score = 1.0
            elif (8 <= hour < 9) or (11 <= hour < 14) or (16 <= hour < 17):
                time_score = 0.7
            else:
                time_score = 0.3
        else:  # NASDAQ
            # NASDAQ peak: 3:30-5 PM and 8:30-10 PM CET
            if (15 <= hour < 17) or (20 <= hour < 22):
                time_score = 1.0
            elif (17 <= hour < 20):
                time_score = 0.7
            else:
                time_score = 0.3
        
        # Combine scores with weights
        liquidity_score = (
            vol_score * 0.4 +
            spread_score * 0.3 +
            time_score * 0.3
        )
        
        return liquidity_score
    
    def get_time_of_day_atr(self, symbol: str, timestamp, 
                           current_atr: float) -> Dict:
        """Get ATR adjusted for time-of-day patterns"""
        timestamp = ensure_datetime(timestamp)
        bucket = self._get_time_bucket(timestamp)
        
        # Update profile
        self.atr_profiles[symbol][bucket].append(current_atr)
        if len(self.atr_profiles[symbol][bucket]) > self.lookback_days:
            self.atr_profiles[symbol][bucket].pop(0)
        
        # Calculate statistics
        historical = self.atr_profiles[symbol][bucket]
        if len(historical) < 5:
            return {
                'current': current_atr,
                'expected': current_atr,
                'ratio': 1.0,
                'percentile': 50
            }
        
        expected_atr = self._calculate_mean(historical)
        atr_std = self._calculate_std(historical)
        
        # Calculate percentile
        below_count = sum(1 for h in historical if h <= current_atr)
        percentile = (below_count * 100) / len(historical)
        
        return {
            'current': current_atr,
            'expected': expected_atr,
            'std': atr_std,
            'ratio': current_atr / expected_atr if expected_atr > 0 else 1.0,
            'percentile': percentile,
            'is_elevated': current_atr > expected_atr + atr_std
        }
    
    def detect_absorption(self, symbol: str, bars: List[Dict], 
                        threshold: float = 1.5) -> Optional[Dict]:
        """Detect absorption patterns"""
        if len(bars) < 3:
            return None
        
        recent_bar = bars[-1]
        prev_bars = bars[-4:-1]  # Last 3 bars before current
        
        # Calculate average volume and range
        avg_volume = self._calculate_mean([b.get('volume', 0) for b in prev_bars])
        avg_range = self._calculate_mean([b['high'] - b['low'] for b in prev_bars])
        
        current_volume = recent_bar.get('volume', 0)
        current_range = recent_bar['high'] - recent_bar['low']
        
        # Check for absorption: high volume, small range
        if avg_volume > 0 and avg_range > 0:
            volume_ratio = current_volume / avg_volume
            range_ratio = current_range / avg_range
            
            if volume_ratio > threshold and range_ratio < 0.5:
                return {
                    'detected': True,
                    'volume_ratio': volume_ratio,
                    'range_ratio': range_ratio,
                    'type': 'bullish' if recent_bar['close'] > recent_bar['open'] else 'bearish',
                    'strength': volume_ratio / range_ratio if range_ratio > 0 else volume_ratio
                }
        
        return None
    
    def get_microstructure_summary(self, symbol: str, bars: List[Dict]) -> Dict:
        """Get comprehensive microstructure analysis summary"""
        if not bars:
            return {}
        
        # Ensure all timestamps are datetime objects
        for bar in bars:
            bar['timestamp'] = ensure_datetime(bar.get('timestamp'))
        
        current_bar = bars[-1]
        timestamp = current_bar['timestamp']

        # Bootstrap spread history from all bars if needed
        if symbol not in self.spread_profiles or not any(self.spread_profiles[symbol].values()):
            # Process historical bars to build spread profile
            for bar in bars[-min(50, len(bars)):]:  # Last 50 bars or all available
                bar_timestamp = bar['timestamp']
                bar_spread = bar.get('spread', 0)
                if bar_spread > 0:
                    self.update_spread_profile(symbol, bar_timestamp, bar_spread)

        # Update profiles with current data
        current_volume = current_bar.get('volume', 0)
        current_spread = current_bar.get('spread', 0)

        self.update_volume_profile(symbol, timestamp, current_volume)
        if current_spread > 0:  # Only update if we have valid spread data
            self.update_spread_profile(symbol, timestamp, current_spread)

        # Calculate all microstructure metrics
        volume_zscore = self.get_volume_zscore(symbol, timestamp, current_volume)
        vwap = self.calculate_anchored_vwap(symbol, bars, 'session')
        or_data = self.detect_opening_range(symbol, bars)
        liquidity = self.calculate_liquidity_score(
            symbol, timestamp,
            current_spread,
            current_volume
        )
        
        # Current ATR analysis (simple calculation without numpy)
        atr_values = [b['high'] - b['low'] for b in bars[-14:]]
        current_atr = self._calculate_mean(atr_values) if atr_values else 0
        atr_data = self.get_time_of_day_atr(symbol, timestamp, current_atr)
        
        absorption = self.detect_absorption(symbol, bars)
        
        return {
            'timestamp': timestamp,
            'volume_zscore': volume_zscore,
            'vwap': vwap,
            'vwap_distance': ((current_bar['close'] - vwap) / vwap * 100) if vwap else 0,
            'opening_range': or_data,
            'liquidity_score': liquidity,
            'atr_analysis': atr_data,
            'absorption': absorption,
            'is_high_quality_time': liquidity > self.config.get('min_liquidity_score', 0.5) and not atr_data.get('is_elevated', False)
        }
