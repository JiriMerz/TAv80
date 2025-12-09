# Bugfix: Thread Explosion in Account State Monitor

**Date:** 2025-10-22
**Author:** Claude Code
**Severity:** 🔴 CRITICAL
**Status:** ✅ FIXED

---

## 🐛 Problem Description

**Symptom:** System hang with thousands of concurrent threads being created, causing AppDaemon to freeze for 20+ minutes.

**Error Log:**
```
Thread-23808, Thread-24214, Thread-24219, Thread-24247...
Exception in thread Thread-XXXXX:
  File "account_state_monitor.py", line 720, in request_deals
  File "account_state_monitor.py", line 733, in schedule_next_check
    timer.start()
WARNING AppDaemon: Excessive time spent in callback - 22:11 (limit=20.0s)
WARNING AppDaemon: Coroutine took too long (01:00), cancelling the task
```

**Impact:**
- AppDaemon becomes unresponsive
- Trading system cannot process signals
- All WebSocket communication blocked
- Requires manual restart

---

## 🔍 Root Cause Analysis

### Infinite Recursion Loop

**File:** `src/trading_assistant/account_state_monitor.py`

**Problem Flow:**
```
request_deals() (line 691)
    ↓
    finally: schedule_next_check() (line 728)
        ↓
        timer = threading.Timer(interval, request_deals) (line 751)
        timer.start() (line 753)
            ↓
            [After interval] → request_deals() ← RECURSIVE CALL
                ↓
                finally: schedule_next_check()
                    ↓ ← NO PROTECTION AGAINST CONCURRENT TIMERS!
```

### Why Thread Explosion Happened

1. **No concurrent timer protection**
   - `schedule_next_check()` had NO check if timer was already running
   - Each call created NEW timer immediately

2. **Multiple trigger sources**
   - Initial timer (line 766)
   - Fallback timer (line 707)
   - Execution event triggers (line 310)
   - Each source could spawn independent timer

3. **Race condition**
   - Timer A starts → schedules Timer B
   - Execution event triggers → schedules Timer C
   - Timer B fires → schedules Timer D
   - Timer C fires → schedules Timer E
   - **Result:** Exponential growth of concurrent timers

4. **Missing cleanup**
   - No flag to mark timer as "running"
   - No thread-safe lock mechanism
   - `daemon=True` was present but insufficient

---

## ✅ Solution Implemented

### Thread Protection Mechanism

**Added to `__init__` (lines 57-59):**
```python
# CRITICAL FIX: Thread protection for timer scheduling
self._timer_running = False
self._timer_lock = threading.Lock()
```

### Modified `request_deals()` (lines 694-696)

**Before:**
```python
def request_deals():
    """Request deals list from cTrader API"""
    try:
        current_time = datetime.now(timezone.utc)
        # ... rest of logic
```

**After:**
```python
def request_deals():
    """Request deals list from cTrader API - with event-driven logic"""
    try:
        # CRITICAL FIX: Mark timer as not running at start of execution
        with self._timer_lock:
            self._timer_running = False

        current_time = datetime.now(timezone.utc)
        # ... rest of logic
```

**Why:** Reset flag when timer fires, allowing next timer to be scheduled.

### Modified `schedule_next_check()` (lines 730-754)

**Before (UNSAFE):**
```python
def schedule_next_check():
    """Schedule next timer check"""
    if self.enabled:
        interval = self.fallback_update_interval if self.update_on_execution_only else self.legacy_periodic_interval
        mode_desc = "fallback" if self.update_on_execution_only else "periodic legacy"
        logger.info(f"[ACCOUNT_MONITOR] 📅 Scheduling next {mode_desc} check in {interval} seconds...")

        timer = threading.Timer(interval, request_deals)
        timer.daemon = True
        timer.start()  # ← NO PROTECTION AGAINST CONCURRENT CALLS!
        logger.debug(f"[ACCOUNT_MONITOR] ⏰ Timer scheduled: {timer}")
```

**After (THREAD-SAFE):**
```python
def schedule_next_check():
    """Schedule next timer check - THREAD-SAFE with protection against concurrent timers"""
    # CRITICAL FIX: Check if timer is already running
    with self._timer_lock:
        if self._timer_running:
            logger.debug(f"[ACCOUNT_MONITOR] ⏭️  Timer already running, skipping duplicate schedule")
            return

        if not self.enabled:
            logger.info(f"[ACCOUNT_MONITOR] ❌ Not scheduling next request - monitoring disabled")
            return

        # Mark timer as running BEFORE starting it
        self._timer_running = True

    # Use appropriate interval based on mode
    interval = self.fallback_update_interval if self.update_on_execution_only else self.legacy_periodic_interval

    mode_desc = "fallback" if self.update_on_execution_only else "periodic legacy"
    logger.info(f"[ACCOUNT_MONITOR] 📅 Scheduling next {mode_desc} check in {interval} seconds...")

    timer = threading.Timer(interval, request_deals)
    timer.daemon = True  # CRITICAL: Allows clean shutdown
    timer.start()
    logger.debug(f"[ACCOUNT_MONITOR] ⏰ Timer scheduled: {timer}")
```

**Key improvements:**
1. **Lock protection:** All flag access wrapped in `with self._timer_lock:`
2. **Duplicate check:** Returns immediately if timer already running
3. **Flag set BEFORE start:** Prevents race condition
4. **Clean exit:** Returns early if disabled

### Modified Initial Timer Start (lines 762-768)

**Before:**
```python
timer = threading.Timer(initial_delay, request_deals)
timer.daemon = True
timer.start()
```

**After:**
```python
# CRITICAL FIX: Mark timer as running before starting
with self._timer_lock:
    self._timer_running = True

timer = threading.Timer(initial_delay, request_deals)
timer.daemon = True  # CRITICAL: Allows clean shutdown
timer.start()
```

**Why:** Ensure flag is set before very first timer starts.

---

## 🔐 Thread Safety Guarantees

### Lock Strategy

```python
_timer_lock = threading.Lock()  # Mutual exclusion for flag access
_timer_running = False          # Protected state variable
```

### State Machine

```
State: IDLE (_timer_running = False)
    ↓
    schedule_next_check() called
    ↓
    [LOCK ACQUIRED]
    if _timer_running == False:
        _timer_running = True  ← Set flag
        [LOCK RELEASED]
        Start timer
    else:
        [LOCK RELEASED]
        Return (skip)
    ↓
State: TIMER_ACTIVE (_timer_running = True)
    ↓
    [Timer fires after interval]
    ↓
    request_deals() executes
    ↓
    [LOCK ACQUIRED]
    _timer_running = False  ← Reset flag
    [LOCK RELEASED]
    ↓
State: IDLE (_timer_running = False)
```

### Concurrency Scenarios

**Scenario 1: Duplicate schedule attempt**
```
Thread A: schedule_next_check() → Lock → Check flag=False → Set flag=True → Release → Start timer
Thread B: schedule_next_check() → Lock → Check flag=True → Return → No timer created ✅
```

**Scenario 2: Timer firing**
```
Timer: request_deals() → Lock → Set flag=False → Release → Process → finally: schedule_next_check()
```

**Scenario 3: Execution event during active timer**
```
Timer Active (_timer_running=True)
Execution Event → schedule_next_check() → Lock → Check flag=True → Return immediately ✅
```

---

## 📊 Testing Verification

### Test 1: Normal Operation
**Expected:**
- One timer active at a time
- Logs show: `"⏭️ Timer already running, skipping duplicate schedule"` when concurrent schedule attempted

### Test 2: Execution Event Triggers
**Expected:**
- Execution events don't create duplicate timers
- Fallback timer only schedules if no recent execution

### Test 3: System Restart
**Expected:**
- Clean initialization
- No thread accumulation
- System responsive throughout

### Test 4: Long Running
**Expected:**
- No thread count increase over time
- Stable memory usage
- No log spam

---

## 🔄 Deployment Steps

1. **Stop HA AppDaemon:**
   ```bash
   ssh ha
   sudo systemctl stop appdaemon
   ```

2. **Backup current version:**
   ```bash
   cd /config/appdaemon/apps
   cp trading_assistant/account_state_monitor.py trading_assistant/account_state_monitor.py.backup
   ```

3. **Deploy fixed version:**
   ```bash
   # On dev machine:
   scp src/trading_assistant/account_state_monitor.py ha:/config/appdaemon/apps/trading_assistant/
   ```

4. **Verify file:**
   ```bash
   ssh ha
   grep "_timer_lock" /config/appdaemon/apps/trading_assistant/account_state_monitor.py
   # Should show: self._timer_lock = threading.Lock()
   ```

5. **Start AppDaemon:**
   ```bash
   sudo systemctl start appdaemon
   ```

6. **Monitor logs:**
   ```bash
   tail -f /config/appdaemon/appdaemon.log | grep ACCOUNT_MONITOR
   ```

7. **Verify fix:**
   - Check for `"⏭️ Timer already running"` messages
   - Monitor thread count: `ps -eLf | grep appdaemon | wc -l` (should stay < 100)
   - System should remain responsive

---

## 📈 Monitoring Checklist

After deployment, monitor for:

- [ ] **Thread count stable:** `ps -eLf | grep appdaemon | wc -l` stays < 100
- [ ] **No timer spam:** Logs show controlled timer scheduling
- [ ] **System responsive:** AppDaemon responds to signals within 1-2 seconds
- [ ] **No warnings:** No "Excessive time spent in callback" warnings
- [ ] **Execution events work:** Position opens/closes trigger proper updates

---

## 🎯 Files Modified

| File | Changes | Lines Modified |
|------|---------|----------------|
| `account_state_monitor.py` | Thread protection for timer scheduling | +21 lines |
| `BUGFIX_THREAD_EXPLOSION.md` | This documentation | NEW |

**Total:** ~21 lines modified in production code

---

## 🔑 Key Takeaways

### What Went Wrong
1. **No concurrent timer protection** - Classic race condition
2. **Missing state management** - No flag to track timer status
3. **Multiple trigger sources** - Timer + events could trigger simultaneously

### What Was Fixed
1. **Thread-safe flag** - `_timer_running` with `_timer_lock` protection
2. **Duplicate prevention** - Early return if timer already active
3. **Clean state reset** - Flag cleared when timer fires

### Best Practices Applied
1. **Mutual exclusion** - Lock for shared state access
2. **State machine** - Clear IDLE ↔ ACTIVE transitions
3. **Defensive coding** - Early returns prevent errors
4. **Daemon threads** - Clean shutdown support

---

## ✅ Status

**Fixed:** 2025-10-22
**Deployed:** Pending user deployment to HA RPi
**Tested:** Code review complete, deployment verification pending

**Next Step:** User deploys to production and monitors thread count stability

---

**Related Issue:** Thread explosion during account monitoring (not related to Close & Reverse feature)
**Prevention:** All future timer-based code should use similar thread protection patterns
