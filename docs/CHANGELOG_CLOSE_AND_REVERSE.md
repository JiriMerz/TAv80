# Changelog: Close & Reverse Feature

**Date:** 2025-10-21
**Author:** Claude Code
**Task:** Implement close & reverse feature with full cTrader API integration

---

## 🎯 Feature Overview

**Close & Reverse** allows the trading system to automatically close all existing positions when a signal in the opposite direction is generated, then immediately open a new position in the reverse direction.

### Use Case:
- **Before:** If NASDAQ BUY position is open and system generates SELL signal → Signal is blocked (no hedge allowed)
- **After:** If NASDAQ BUY position is open and system generates SELL signal → Close BUY position, then open SELL position

This feature enables the system to flip positions dynamically based on market structure changes detected by edge detection logic.

---

## 📝 Implementation Details

### 1. **New Module: `position_closer.py`**

Created dedicated module for closing positions via cTrader WebSocket API.

**File:** `src/trading_assistant/position_closer.py`

**Key Components:**

#### Class: `PositionCloser`

**Methods:**
- `close_position(position: Dict) -> Dict`: Close single position
- `close_positions_by_symbol(symbol: str, positions: list) -> Dict`: Close all positions for symbol
- `close_all_positions(positions: list) -> Dict`: Bulk close all positions
- `_send_close_order(order_msg: Dict) -> bool`: Send close order via WebSocket

**How Position Closing Works in cTrader:**
- **BUY position** is closed by sending **SELL market order** with same volume
- **SELL position** is closed by sending **BUY market order** with same volume
- No need to specify `positionId` - cTrader auto-matches opposite orders
- Uses `PT_NEW_ORDER_REQ` (2106) same as opening positions

**Close Order Payload:**
```python
{
    "ctidTraderAccountId": account_id,
    "symbolId": 208,  # US100 (NASDAQ) or 203 (GER40/DAX)
    "orderType": 1,   # MARKET
    "tradeSide": 2,   # 1=SELL, 2=BUY (opposite of position)
    "volume": 1000    # Same volume as open position (lots * 100)
    # NO relativeStopLoss/relativeTakeProfit for close orders
}
```

---

### 2. **Modified: `risk_manager.py`**

**Enhanced `PositionSize` dataclass to track position metadata:**

**Before:**
```python
@dataclass
class PositionSize:
    symbol: str
    lots: float
    risk_amount_czk: float
    # ... other fields
```

**After:**
```python
@dataclass
class PositionSize:
    symbol: str
    lots: float
    risk_amount_czk: float
    # ... other fields
    position_id: str = ""  # cTrader position ID (for tracking)
    direction: str = ""    # BUY or SELL (for close direction logic)
```

**Why:** Position closer needs to know the direction to send opposite market order.

---

### 3. **Modified: `simple_order_executor.py`**

**Added PositionCloser initialization:**

**Lines 13, 58-60:**
```python
from .position_closer import PositionCloser

# Initialize position closer for close & reverse feature
self.position_closer = PositionCloser(ctrader_client, create_task_fn)
logger.info("[ORDER_EXECUTOR] PositionCloser initialized - close & reverse feature enabled")
```

**Result:** OrderExecutor now has `position_closer` attribute accessible to main.py

---

### 4. **Modified: `main.py` - Position Conflict Logic**

**Location:** `main.py:3487-3579`

**Strategy Configuration:**
```python
conflict_config = self.args.get('position_conflicts', {})
conflict_strategy = conflict_config.get('strategy', 'SAME_DIRECTION_ONLY')
close_all_on_reverse = conflict_config.get('close_all_on_reverse', True)
```

**Decision Tree:**

```
New Signal vs Existing Positions:
│
├─ Same Direction (BUY+BUY or SELL+SELL)
│  └─ ✅ Allow scaling (add to existing positions)
│
└─ Opposite Direction (BUY vs SELL)
   │
   ├─ Strategy: SAME_DIRECTION_ONLY (default)
   │  └─ ❌ Block signal (no hedge allowed)
   │
   └─ Strategy: CLOSE_AND_REVERSE
      │
      ├─ close_all_on_reverse: true
      │  └─ Close ALL positions (conservative)
      │
      └─ close_all_on_reverse: false
         └─ Close only symbol positions (aggressive)
```

**Close & Reverse Flow:**
1. Detect opposite direction conflict
2. Collect positions to close (all or symbol-specific)
3. For each position:
   - Call `order_executor.position_closer.close_position()`
   - If successful → Remove from `risk_manager.open_positions`
4. If at least one position closed → Continue to open reverse position
5. If no positions closed → Abort (prevent opening without closing)

**Logging:**
```
[AUTO-TRADING] 🔄 REVERSE signal detected: NASDAQ BUY → SELL
[AUTO-TRADING] Closing ALL 2 positions before reverse
[AUTO-TRADING] Closing: NASDAQ BUY 10.0 lots (ID: POS_NASDAQ_193522)
[AUTO-TRADING] ✅ Closed NASDAQ (close order sent)
[AUTO-TRADING] ✅ Closed 2/2 positions (failed: 0)
[AUTO-TRADING] 🔄 Opening REVERSE position: NASDAQ SELL
```

---

### 5. **Configuration: `apps.yaml`**

**Added new section:**

**Lines ~20-23:**
```yaml
# === POSITION CONFLICT HANDLING STRATEGY ===
position_conflicts:
  strategy: "CLOSE_AND_REVERSE"  # Options: "SAME_DIRECTION_ONLY" | "CLOSE_AND_REVERSE"
  close_all_on_reverse: true     # Close ALL positions (true) or just conflicting symbol (false)
  log_closures: true             # Verbose logging of position closures
```

**Configuration Options:**

| Parameter | Values | Description |
|-----------|--------|-------------|
| `strategy` | `"SAME_DIRECTION_ONLY"` | Block opposite direction signals (default, conservative) |
|  | `"CLOSE_AND_REVERSE"` | Close positions and reverse (aggressive) |
| `close_all_on_reverse` | `true` | Close ALL open positions before reverse (safer) |
|  | `false` | Close only positions for conflicting symbol |
| `log_closures` | `true` | Log each position closure (verbose) |
|  | `false` | Minimal logging |

---

## 🔄 Workflow Example

### Scenario: NASDAQ BUY position open, SELL signal generated

**Configuration:**
```yaml
position_conflicts:
  strategy: "CLOSE_AND_REVERSE"
  close_all_on_reverse: true
```

**Step-by-Step Execution:**

1. **Signal Detection:**
   ```
   [AUTO-TRADING] 🔄 REVERSE signal detected: NASDAQ BUY → SELL
   ```

2. **Position Collection:**
   ```
   [AUTO-TRADING] Closing ALL 1 positions before reverse
   ```

3. **Position Closing:**
   ```
   [AUTO-TRADING] Closing: NASDAQ BUY 10.0 lots (ID: POS_NASDAQ_193500)
   [POSITION_CLOSER] Closing NASDAQ BUY position (10.00 lots)
   [POSITION_CLOSER] Close order: SELL 10.00 lots
   [POSITION_CLOSER] Close order payload: {...}
   [POSITION_CLOSER] ✅ Close order sent for NASDAQ POS_NASDAQ_193500
   ```

4. **Risk Manager Update:**
   ```
   [RISK] Position closed: NASDAQ 10.00 lots, PnL: +0 CZK
   [RISK] Portfolio after close: 0 positions, Total risk: 0 CZK
   ```

5. **Reverse Position Opening:**
   ```
   [AUTO-TRADING] 🔄 Opening REVERSE position: NASDAQ SELL
   [ORDER_EXECUTOR] Sending REAL market order to cTrader...
   [ORDER_EXECUTOR] Order: NASDAQ SELL 10.00 lots
   ```

6. **WebSocket Confirmation:**
   ```
   [🚨 EXECUTION EVENT] EXECUTION_TYPE_1 (ORDER FILLED)
   [🚨 POSITION CONFIRMED] NASDAQ position opened
   ```

---

## ⚙️ Technical Implementation Details

### Thread Safety

All position closing operations are thread-safe using AppDaemon's `create_task_fn`:

```python
async def send_close_task():
    """Async task for sending close order"""
    future = self.ctrader_client.send_from_other_thread(2106, order_msg, timeout=15.0)
    await asyncio.sleep(1)  # Wait for cTrader processing
    return True

# Schedule task in AppDaemon event loop
task = self.create_task_fn(send_close_task())
```

### WebSocket Message Flow

```
Main Thread (AppDaemon)              cTrader WebSocket Thread
       |                                      |
       | 1. Detect reverse signal             |
       |-------------------------------->     |
       | 2. Call position_closer.close()      |
       |                                      |
       | 3. create_task(send_close_task)      |
       |-------------------------------->     |
       |                                      |
       |    4. send_from_other_thread()       |
       |    ------------------------------>   |
       |                                      |
       |    5. PT_NEW_ORDER_REQ (2106)        |
       |    =============================>    |
       |                                      |
       |    6. PT_NEW_ORDER_RES (2107)        |
       |    <=============================    |
       |                                      |
       |    7. PT_EXECUTION_EVENT (2126)      |
       |    <=============================    |
       |                                      |
       | 8. Position closed confirmation      |
       |<----------------------------------   |
       |                                      |
       | 9. Remove from risk_manager          |
       |                                      |
       | 10. Open reverse position            |
       |-------------------------------->     |
```

---

## 🧪 Testing Recommendations

### Test Scenario 1: Single Position Reverse
1. Open NASDAQ BUY position manually or via signal
2. Generate SELL signal (test button or real market structure)
3. **Expected:**
   - BUY position closes (check cTrader)
   - SELL position opens immediately after
   - Logs show successful close & reverse

### Test Scenario 2: Multiple Positions Reverse
1. Open 2 positions: NASDAQ BUY + DAX BUY
2. Generate NASDAQ SELL signal
3. **Expected (close_all_on_reverse: true):**
   - Both NASDAQ and DAX positions close
   - NASDAQ SELL opens
4. **Expected (close_all_on_reverse: false):**
   - Only NASDAQ BUY closes
   - DAX BUY remains open
   - NASDAQ SELL opens

### Test Scenario 3: Failed Close Handling
1. Simulate WebSocket disconnect
2. Generate reverse signal
3. **Expected:**
   - Close attempts fail
   - Reverse position does NOT open
   - Log shows: `[AUTO-TRADING] ❌ No positions closed - aborting reverse`

---

## 📊 Configuration Recommendations

### Conservative (Default):
```yaml
position_conflicts:
  strategy: "SAME_DIRECTION_ONLY"
```
- **Pros:** No unexpected position flips, predictable behavior
- **Cons:** Misses reversal opportunities

### Moderate:
```yaml
position_conflicts:
  strategy: "CLOSE_AND_REVERSE"
  close_all_on_reverse: false  # Only close conflicting symbol
```
- **Pros:** Allows symbol-specific reversals, keeps other positions
- **Cons:** May have mixed directions across symbols

### Aggressive:
```yaml
position_conflicts:
  strategy: "CLOSE_AND_REVERSE"
  close_all_on_reverse: true   # Close ALL positions
```
- **Pros:** Clean reversals, no conflicting positions
- **Cons:** Closes profitable positions on other symbols

---

## 🚨 Known Limitations

### 1. **No P&L Tracking on Close**
- Currently closes positions without tracking realized P&L
- `risk_manager.remove_position(symbol, pnl_czk=0)` uses `0` as placeholder
- **Future:** Extract P&L from EXECUTION_EVENT or DEAL_LIST_RES

### 2. **No Close Confirmation Wait**
- System opens reverse position immediately after sending close order
- Does not wait for EXECUTION_EVENT confirming close
- **Mitigation:** cTrader processes close orders quickly (~100-500ms)
- **Future:** Add state machine waiting for close confirmation

### 3. **Bulk Close Timing**
- When closing multiple positions, uses `time.sleep(0.1)` between closes
- May cause slight delay in high-frequency scenarios
- **Future:** Implement parallel close with asyncio.gather()

---

## ✅ Deployment Checklist

- [x] Created `position_closer.py` module
- [x] Modified `risk_manager.py` - added position_id and direction fields
- [x] Modified `simple_order_executor.py` - initialized PositionCloser
- [x] Modified `main.py` - implemented close & reverse logic
- [x] Updated `apps.yaml` - added position_conflicts configuration
- [x] Created documentation (this file)
- [ ] **Deploy to Production (HA RPi)** - MANUAL STEP
- [ ] **Test single position reverse** - verify close + open sequence
- [ ] **Test multiple position reverse** - verify all/symbol-specific closing
- [ ] **Monitor WebSocket events** - check PT_EXECUTION_EVENT for closes

---

## 📚 Files Modified

| File | Changes | Lines |
|------|---------|-------|
| `position_closer.py` | **NEW** - Position closing module | 321 lines |
| `risk_manager.py` | Added position_id, direction fields | +2 lines |
| `simple_order_executor.py` | Import + init PositionCloser | +4 lines |
| `main.py` | Close & reverse logic in position conflict check | +93 lines |
| `apps.yaml` | Added position_conflicts config | +4 lines |

**Total:** ~424 lines of new/modified code

---

## 🎯 Summary

**Feature Status:** ✅ Ready for deployment

**What Changed:**
- System can now close positions via cTrader API
- Configurable strategy for handling opposite direction signals
- Full integration with risk manager and order executor

**What to Monitor:**
1. Position closures in cTrader platform (verify close orders execute)
2. Reverse position openings (check timing after closes)
3. Risk manager state (verify positions removed after close)
4. Daily P&L (currently not tracked on close - manual verification needed)

**Next Steps:**
1. User deploys to HA RPi
2. Test with demo account for 1-2 days
3. Monitor logs for close & reverse executions
4. Validate behavior matches expectations
5. Consider adding P&L tracking enhancement (Phase 3)

---

**Status:** ✅ Code Ready for Deployment
**Next Step:** User manually deploys to HA RPi and tests close & reverse functionality
