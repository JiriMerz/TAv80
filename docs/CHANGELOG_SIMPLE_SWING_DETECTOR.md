# Changelog: Simple Swing Detector Integration

**Date:** 2025-10-21
**Author:** Claude Code
**Task:** Replace SwingEngine with SimpleSwingDetector based on analytics findings

---

## 🎯 Problem Identified

**Analytics Analysis Results (10 trading days, NASDAQ M5, 15:30-22:00 CET):**

| Detector | Bars Analyzed | Swings Detected | Result |
|----------|---------------|-----------------|---------|
| **SwingEngine** | 1199 | **2 swings** | ❌ BROKEN |
| **SimpleSwingDetector** | 1199 | **95 swings** | ✅ CORRECT |

**SwingEngine Issue:**
- Detected only 2 swings from 1199 bars (0.17%)
- Missing 93 legitimate swing points
- Too strict/buggy ZigZag implementation
- Production trades would miss most swing opportunities

**Analysis showed:**
- Average: **9.5 swings/day** (realistic)
- Typical swing: **50-100 points** (median 88 points)
- Range: 2-17 swings/day depending on volatility

---

## ✅ Solution: Simple Swing Detector

Implemented reliable swing detection using **local extrema method**:

### Algorithm:
```python
For each bar i (with lookback=5):
  - Check if bar[i].high > all bars[i-5:i+5].high → LOCAL HIGH
  - Check if bar[i].low < all bars[i-5:i+5].low → LOCAL LOW
  - Minimum move filter: 0.15% from previous swing
```

### Configuration:
- **Lookback:** 5 bars (checks 5 bars on each side)
- **Min Move:** 0.0015 (0.15% minimum price change)

### Advantages:
- ✅ Simple, reliable, no complex ZigZag logic
- ✅ Detects 95 swings from 1199 bars (8% hit rate)
- ✅ Matches realistic swing count (9-10/day)
- ✅ Compatible with existing SwingState interface

---

## 📝 Changes Made

### 1. New File: `src/trading_assistant/simple_swing_detector.py`

**Classes:**
- `SimpleSwingDetector` - Main detector class
- `SimpleSwing` - Swing point dataclass
- `SimpleSwingState` - State container (compatible with SwingEngine)

**Key Methods:**
```python
def detect_swings(bars: List[Dict], timeframe: str = "M5") -> SimpleSwingState
```

**Returns:**
- `swings`: List of detected swing points
- `last_high/last_low`: Most recent swing points
- `trend`: "UP", "DOWN", "SIDEWAYS"
- `swing_quality`: 0-100 score
- `rotation_count`: Alternating high/low count

### 2. Modified: `src/trading_assistant/main.py`

**Line 23: Added Import**
```python
from .simple_swing_detector import SimpleSwingDetector  # NEW: More reliable swing detection
```

**Lines 198-207: Replaced SwingEngine initialization**
```python
# OLD:
self.swing_engine = SwingEngine(swing_config, pivot_calculator=self.pivot_calc)

# NEW:
self.swing_engine = SimpleSwingDetector(config={
    'lookback': 5,
    'min_move_pct': 0.0015
})
```

**Lines 1006-1023: Enhanced swing detection handling**
- Added compatibility for both Enum and string trend values
- Added swing_count to published data
- Added logging: `[SWING] {alias}: {count} swings, trend={trend}, quality={quality}%`

### 3. Modified: `src/apps.yaml`

**Swing Detection Parameters (lines 303-313):**
```yaml
swings:
  atr_multiplier_m5: 0.5  # LOWERED from 1.2 for better detection
  min_bars_between: 2     # LOWERED from 3 to allow closer swings
  min_swing_quality: 20   # LOWERED from 25 to allow more signals
```

**Fixed SL/TP (lines 113-117):**
```yaml
use_fixed_sl_tp: true
base_sl_pips: 4000        # 40 points NASDAQ
fixed_rrr: 1.25           # TP = 5000 pips (50 points)
sl_flexibility_percent: 0 # NO flexibility - pure fixed
```

**Disabled Dynamic Adjustments:**
```yaml
use_swing_stops: false           # Use fixed SL instead
use_market_structure_sl: false   # No adjustments
```

---

## 📊 Expected Production Impact

### Before (SwingEngine):
- **Swing detection:** 2 swings per 1199 bars
- **Daily swings:** ~0.2 swings/day
- **Trading opportunities:** MINIMAL ❌

### After (SimpleSwingDetector):
- **Swing detection:** 95 swings per 1199 bars
- **Daily swings:** ~9.5 swings/day
- **Trading opportunities:** REALISTIC ✅

### Trade Parameters:
- **SL:** 4000 pips (40 points NASDAQ)
- **TP:** 5000 pips (50 points) - targets median swing
- **RRR:** 1.25:1
- **Risk:** 0.5% per trade (10,000 CZK)
- **Potential profit:** 12,500 CZK per winning trade

---

## 🔍 Monitoring After Deployment

**Key Metrics to Watch:**

1. **Swing Count Per Session:**
   - Expected: 8-14 swings/day (NASDAQ 15:30-22:00)
   - Monitor: Check logs for `[SWING] {symbol}: {count} swings`

2. **Swing Quality:**
   - Expected: 25-100% (varies by swing count)
   - Monitor: Published to `sensor.{symbol}_swing_quality`

3. **Trend Detection:**
   - Values: UP, DOWN, SIDEWAYS
   - Monitor: Published to `sensor.{symbol}_swing_trend`

4. **Trade Frequency:**
   - Before: Very rare (1-2 trades/week due to missing swings)
   - After: More frequent (based on 9-10 swings/day)

**Alert Thresholds:**
- ⚠️ If swing_count < 5/day → Investigate (too strict)
- ⚠️ If swing_count > 20/day → Investigate (too sensitive)
- ✅ Normal range: 8-14 swings/day

---

## 🧪 Testing Recommendations

1. **Monitor first 2-3 trading days** after deployment
2. **Compare swing counts** with manual chart analysis
3. **Verify TP targets** hit median swing size (50-75 points)
4. **Check trade quality** - should trigger on legitimate swings

---

## 📚 Related Documentation

- **Analytics Report:** `analytics/reports/swing_analysis_nasdaq.json`
- **Analytics Script:** `analytics/swing_analysis_nasdaq.py`
- **Simple Detector:** `analytics/simple_swing_detector.py` (reference implementation)

---

## 🐛 Post-Deployment Fixes (2025-10-21)

### Issue #1: SimpleSwingDetector Missing Compatibility Methods
**Symptom:** `'SimpleSwingDetector' object has no attribute 'get_swing_summary'` and `'current_state'`

**Cause:** SimpleSwingDetector was missing SwingEngine compatibility interface

**Fix:** Added to `simple_swing_detector.py`:
- `self.current_state` attribute initialized in `__init__()`
- `get_swing_summary()` method for UI/logging compatibility

**File:** `src/trading_assistant/simple_swing_detector.py:69-70, 220-247`

---

### Issue #2: TP Band Adjustment Overriding Fixed TP
**Symptom:** TP adjusted from 5000 pips to 7500 pips despite `sl_flexibility_percent: 0`

**Log Evidence:**
```
[AUTO-TRADING] TP: 5000 pips = 50.0 points (RRR: 1.25:1)  ← CORRECT
[AUTO-TRADING] TP adjusted by band: 50.0pt → 75.0pt (7500 pips)  ← WRONG
```

**Cause:** Band adjustment system in main.py was always running, regardless of `sl_flexibility_percent` setting

**Fix:** Modified `src/trading_assistant/main.py:3611-3664`
```python
# Check sl_flexibility_percent
sl_flexibility = self.args.get('sl_flexibility_percent', 25)

if sl_flexibility > 0:
    # Apply band adjustment system
    ...
else:
    # Fixed SL/TP mode - skip band adjustments
    self.log("[AUTO-TRADING] Fixed SL/TP mode - using structural values without band adjustment")
```

**Result:** When `sl_flexibility_percent: 0`, band adjustment is completely skipped, preserving fixed TP of 5000 pips

---

### Issue #3: Trade Logging JSON Serialization Error
**Symptom:** `Object of type SignalType is not JSON serializable`

**Cause:** SignalType enum (BUY/SELL) being passed directly to `json.dumps()`

**Fix:** Modified `src/trading_assistant/trade_decision_logger.py`:

1. **Added Enum import** (line 12):
```python
from enum import Enum
```

2. **Added helper method** (lines 148-155):
```python
def _to_serializable(self, value):
    """Convert Enum to string for JSON serialization"""
    if isinstance(value, Enum):
        return value.value
    return value
```

3. **Applied to all enum fields** (lines 111, 172, 232, 258):
- `"pattern": self._to_serializable(signal.get('pattern_type', ...))`
- `'pattern_type': self._to_serializable(signal.get('pattern_type', ...))`
- In `_classify_setup()` and `_extract_reasons()`

**Result:** Trade decisions now log successfully to JSONL files

---

## ✅ Deployment Checklist

- [x] Created `simple_swing_detector.py` in production
- [x] Modified `main.py` to use SimpleSwingDetector
- [x] Updated `apps.yaml` with swing config
- [x] Set fixed SL/TP (4000/5000 pips)
- [x] Disabled dynamic SL adjustments
- [x] **Fixed Issue #1:** Added SwingEngine compatibility methods
- [x] **Fixed Issue #2:** Disabled TP band adjustment for fixed SL/TP mode
- [x] **Fixed Issue #3:** Fixed trade logging JSON serialization
- [ ] **Deploy v2 to Production (HA RPi)** - MANUAL STEP
- [ ] **Test on demo account** - 1-2 days
- [ ] **Monitor swing detection** - verify 8-14 swings/day
- [ ] **Validate trade entries** - check swing quality

---

**Status:** ✅ Code Ready for Re-Deployment (v2 with fixes)
**Next Step:** User manually re-deploys fixed version to HA RPi
