# Bug Fix: Daily P&L Reset Issue

## Problem Description
The Trading Assistant dashboard was displaying daily P&L of 27,265.99 CZK correctly after restart, but the value would reset to 0.00 CZK after a few minutes of operation.

### Root Cause Analysis
1. **Race Condition**: The `main.py` module was running `log_status()` every 60 seconds, which would overwrite Account Monitor data with legacy calculations
2. **Fallback Logic**: Complex conditional logic with multiple fallbacks was causing the system to revert to "legacy" calculations that returned 0
3. **Misleading Fallbacks**: The system would show 0 instead of indicating missing data, making it appear functional when it wasn't

## Solution Implemented

### 1. Removed All Fallback Logic (main.py)
**Location**: `/src/trading_assistant/main.py` lines 923-940

**Before**: System would use legacy calculations when Account Monitor data seemed unavailable
```python
if not account_monitor_active:
    # Use legacy calculation (returns 0)
    risk_attributes.update({
        "daily_pnl_czk": risk_status.daily_pnl_czk,
        "daily_pnl_pct": risk_status.daily_pnl_pct,
    })
```

**After**: Only use Account Monitor data or show error
```python
if current_daily_pnl is not None:
    # Use Account Monitor data
    risk_attributes.update({
        "daily_pnl_czk": current_daily_pnl,
        "daily_pnl_pct": current_attributes.get("daily_pnl_pct", 0),
        "daily_realized_pnl": current_attributes.get("daily_realized_pnl", 0),
        "daily_unrealized_pnl": current_attributes.get("daily_unrealized_pnl", 0),
    })
else:
    # Show error state - no fake values
    risk_attributes.update({
        "daily_pnl_czk": None,
        "daily_pnl_pct": None,
        "error": "Account Monitor not providing data"
    })
```

### 2. Enhanced Dashboard Error Handling
**Location**: `/dashboards/trading_desk_v7_final.yaml` lines 385-404

**Changes**:
- Dashboard now shows "⚠️ No Data" when PnL data is missing
- Orange warning color (#FF9800) indicates missing data
- No more misleading 0.00 values

### 3. Account Monitor Initialization
**Location**: `/src/trading_assistant/account_state_monitor.py` lines 495-524

**Added**: Initial risk status update to prevent "No Data" on startup
- Sets initial PnL values immediately on startup
- Updates `account_monitor_last_update` timestamp
- Ensures main.py recognizes Account Monitor is active

### 4. Timestamp Updates
**Location**: `/src/trading_assistant/account_state_monitor.py` lines 512-514

**Fixed**: Use current time instead of stale timestamps
```python
current_time = datetime.now(timezone.utc)
current_attributes["account_monitor_last_update"] = current_time.isoformat()
```

## Benefits of This Approach
✅ **No misleading data**: System shows actual state, not fake values
✅ **Clear error states**: Problems are immediately visible
✅ **Single source of truth**: Only Account Monitor provides PnL data
✅ **Transparent operation**: Can't hide behind fallback values

## Testing Checklist
- [ ] Restart AppDaemon and verify PnL shows correctly
- [ ] Wait 5+ minutes and confirm PnL doesn't reset to 0
- [ ] Monitor logs for "Using Account Monitor daily PnL data" messages
- [ ] Verify no "legacy daily PnL calculation" messages appear
- [ ] Dashboard shows orange "⚠️ No Data" if Account Monitor fails

## Files Modified
1. `/src/trading_assistant/main.py` - Removed fallback logic
2. `/src/trading_assistant/account_state_monitor.py` - Fixed initialization and timestamps
3. `/dashboards/trading_desk_v7_final.yaml` - Added error state display

## Related Issues
- Initial report: Daily P&L showing 0 instead of 27,265.99 CZK
- Pattern: Value correct after restart, then resets after ~2-5 minutes
- Logs showed: "Using legacy daily PnL calculation" when it should use Account Monitor data