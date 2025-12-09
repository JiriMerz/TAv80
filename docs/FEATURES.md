# Trading Assistant - Feature Documentation

## 🔄 Signal Re-evaluation Feature

**Verze:** 1.0
**Implementováno:** 2025-10-28
**Soubory:** `simple_order_executor.py`, `main.py`

---

## 📋 Overview

Automatický re-evaluation mechanismus, který řeší problém kdy signály vygenerované s vypnutým auto-tradingem nebyly nikdy exekuovány, i když byl auto-trading následně zapnut.

### Před implementací:
```
09:53:38 - Signal generated: DAX BUY @ 24262.25
09:53:38 - [ORDER_EXECUTOR] ⏸️ Signal rejected - auto-trading DISABLED
09:56:03 - User enables auto-trading toggle
❌ Signál DAX BUY nebude NIKDY exekuován (natrvalo ztracen)
```

### Po implementaci:
```
09:53:38 - Signal generated: DAX BUY @ 24262.25
09:53:38 - [ORDER_EXECUTOR] ⏸️ Signal rejected - auto-trading DISABLED
09:53:38 - [ORDER_EXECUTOR] 💾 Signal saved for re-evaluation (1 total)
09:56:03 - User enables auto-trading toggle
09:56:03 - [AUTO-TRADING] 🔄 Re-evaluating previously rejected signals...
09:56:03 - [ORDER_EXECUTOR] ✅ Re-evaluation SUCCESS: DAX
✅ Signál DAX BUY automaticky exekuován!
```

---

## 🏗️ Technical Implementation

### 1. Data Structure

**File:** `simple_order_executor.py`

```python
class SimpleOrderExecutor:
    def __init__(self, ...):
        # Rejected signals tracking for re-evaluation
        self.rejected_signals = []  # List of (signal, timestamp) tuples
        self.max_rejected_signals = 10  # Keep only recent rejections
```

**Storage format:**
```python
rejected_signals = [
    (
        {
            'symbol': 'DAX',
            'direction': 'BUY',
            'entry_price': 24262.25,
            'stop_loss': 24222.25,
            'take_profit': 24312.25,
            'signal_quality': 85,
            # ... všechny signálové atributy
        },
        datetime(2025, 10, 28, 9, 53, 38)  # Timestamp odmítnutí
    ),
    # ... další signály
]
```

### 2. Signal Rejection & Storage

**File:** `simple_order_executor.py:217-228`

```python
def execute_signal(self, signal: Dict[str, Any]) -> Dict[str, Any]:
    # ... validation ...

    # 1. Check if auto-trading is enabled
    if not self.enabled:
        issues.append("Auto-trading is disabled via toggle")
        logger.info(f"[ORDER_EXECUTOR] ⏸️ Signal rejected - auto-trading DISABLED: {signal.get('symbol')} {signal.get('direction')}")

        # Save rejected signal for re-evaluation when auto-trading is enabled
        from datetime import datetime
        self.rejected_signals.append((signal.copy(), datetime.now()))

        # Keep only recent rejections
        if len(self.rejected_signals) > self.max_rejected_signals:
            self.rejected_signals = self.rejected_signals[-self.max_rejected_signals:]

        logger.info(f"[ORDER_EXECUTOR] 💾 Signal saved for re-evaluation ({len(self.rejected_signals)} total)")
```

**Key points:**
- ✅ Signal is copied (`.copy()`) to prevent reference issues
- ✅ Timestamp je uložen pro age validation
- ✅ Automatické mazání nejstarších signálů (FIFO queue s max 10 items)

### 3. Re-evaluation Method

**File:** `simple_order_executor.py:1216-1279`

```python
def reevaluate_rejected_signals(self):
    """
    Re-evaluate signals that were previously rejected due to disabled auto-trading.
    Called when auto-trading is enabled via toggle.
    """
    # Guard clause: auto-trading must be enabled
    if not self.enabled:
        logger.warning("[ORDER_EXECUTOR] ⚠️ Cannot re-evaluate: auto-trading is still DISABLED")
        return

    # No signals to process
    if not self.rejected_signals:
        logger.info("[ORDER_EXECUTOR] ℹ️ No rejected signals to re-evaluate")
        return

    logger.info(f"[ORDER_EXECUTOR] 🔄 Re-evaluating {len(self.rejected_signals)} rejected signals...")

    from datetime import datetime, timedelta
    now = datetime.now()
    max_age = timedelta(minutes=30)  # Only re-evaluate signals from last 30 minutes

    executed_count = 0
    expired_count = 0
    failed_count = 0

    # Process signals in order (oldest first)
    for signal, rejected_at in self.rejected_signals[:]:  # Copy list to allow modification
        age = now - rejected_at

        # Skip expired signals
        if age > max_age:
            expired_count += 1
            logger.info(f"[ORDER_EXECUTOR] ⏰ Signal expired: {signal.get('symbol')} (age: {age.total_seconds():.0f}s)")
            continue

        # Try to execute
        try:
            logger.info(f"[ORDER_EXECUTOR] 🔄 Re-evaluating: {signal.get('symbol')} {signal.get('direction')}")
            result = self.execute_signal(signal)

            if result and result.get('success'):
                executed_count += 1
                logger.info(f"[ORDER_EXECUTOR] ✅ Re-evaluation SUCCESS: {signal.get('symbol')}")
            else:
                failed_count += 1
                reason = result.get('reason', 'unknown') if result else 'no result'
                logger.info(f"[ORDER_EXECUTOR] ❌ Re-evaluation FAILED: {signal.get('symbol')} - {reason}")

        except Exception as e:
            failed_count += 1
            logger.error(f"[ORDER_EXECUTOR] ❌ Re-evaluation ERROR: {signal.get('symbol')} - {e}")

    # Clear rejected signals list
    self.rejected_signals = []

    # Summary
    logger.info(f"[ORDER_EXECUTOR] 📊 Re-evaluation complete:")
    logger.info(f"  ✅ Executed: {executed_count}")
    logger.info(f"  ❌ Failed: {failed_count}")
    logger.info(f"  ⏰ Expired: {expired_count}")

    return {
        'executed': executed_count,
        'failed': failed_count,
        'expired': expired_count
    }
```

**Algorithm:**
1. **Guard clauses** - kontrola že auto-trading je zapnutý a že jsou signály k procession
2. **Age validation** - signály starší než 30 minut jsou automaticky zahozeny
3. **Sequential processing** - signály zpracovány v pořadí (oldest first)
4. **Error handling** - každý signál má vlastní try-except
5. **Cleanup** - všechny signály smazány po procesování (úspěšné i neúspěšné)
6. **Summary** - return dict s počty pro notifikace

### 4. Toggle Integration

**File:** `main.py:1896-1926`

```python
def toggle_auto_trading(self, entity, attribute, old, new, kwargs):
    """Toggle auto-trading execution on/off"""
    try:
        if not self.auto_trading_enabled or not self.order_executor:
            self.log("[AUTO-TRADING] ⚠️ Auto-trading module not available - ignoring toggle change")
            return

        is_enabled = (new == "on")
        self.order_executor.enabled = is_enabled

        if is_enabled:
            self.log("[AUTO-TRADING] ✅ Trade execution ENABLED - signals will be executed automatically")
            self.notify("Auto-trading ZAPNUT ✅ - obchody budou automaticky prováděny", "Auto Trading")

            # Re-evaluate previously rejected signals
            try:
                self.log("[AUTO-TRADING] 🔄 Re-evaluating previously rejected signals...")
                result = self.order_executor.reevaluate_rejected_signals()
                if result and result.get('executed', 0) > 0:
                    self.notify(f"✅ {result['executed']} signálů exekuováno po zapnutí auto-tradingu", "Auto Trading")
            except Exception as e:
                self.error(f"[AUTO-TRADING] Error re-evaluating signals: {e}")
        else:
            self.log("[AUTO-TRADING] ⏸️ Trade execution DISABLED - signals will be generated but NOT executed")
            self.notify("Auto-trading VYPNUT ⏸️ - analýzy běží, obchody nebudou prováděny", "Auto Trading")

    except Exception as e:
        self.error(f"[AUTO-TRADING] Error toggling auto-trading: {e}")
        import traceback
        self.error(traceback.format_exc())
```

**Integration points:**
- ✅ Volá `reevaluate_rejected_signals()` pouze při **zapnutí** (not při vypnutí)
- ✅ Exception handling pro robustnost
- ✅ Notifikace v HA když jsou signály exekuovány
- ✅ Nezablokující - chyba v re-evaluation nezabrání toggle změně

---

## 🎯 Use Cases

### Use Case 1: Morning Setup
```
08:00 - AppDaemon start (auto-trading DISABLED po restartu)
08:15 - Signal: DAX BUY @ 24100
        → Rejected, saved for re-evaluation
08:20 - Signal: DAX SELL @ 24150
        → Rejected, saved for re-evaluation
08:30 - User arrives, enables auto-trading
        → Both signals re-evaluated
        → DAX BUY executed (still valid)
        → DAX SELL rejected (opposite direction already in position)
```

### Use Case 2: Temporary Disable
```
10:00 - Auto-trading ENABLED
10:15 - User disables temporarily (news event)
10:20 - Signal: NASDAQ BUY @ 25800
        → Rejected, saved
10:25 - News event ends, user enables auto-trading
        → NASDAQ BUY signal re-evaluated and executed
```

### Use Case 3: Expired Signals
```
09:00 - Auto-trading DISABLED
09:15 - Signal: DAX BUY @ 24100
        → Rejected, saved
09:50 - User enables auto-trading
        → Signal age: 35 minutes (> 30 min limit)
        → Signal expired, not executed
```

### Use Case 4: Multiple Signals
```
10:00 - Auto-trading DISABLED
10:15 - Signal: DAX BUY @ 24100 → Saved
10:20 - Signal: NASDAQ BUY @ 25800 → Saved
10:25 - Signal: DAX SELL @ 24150 → Saved
10:30 - User enables auto-trading
        → Re-evaluation:
          - DAX BUY: ✅ Executed
          - NASDAQ BUY: ✅ Executed
          - DAX SELL: ❌ Failed (opposite to existing DAX position)
```

---

## 📊 Validation & Rejection Reasons

Když se signál re-evaluuje, prochází VŠEMI standardními validacemi:

### 1. Auto-trading status
```python
if not self.enabled:
    → Rejected (ale to by nemělo nastat při re-evaluation)
```

### 2. Time-based symbol trading
```python
if signal.get('symbol') != active_symbol:
    → Rejected ("Wrong symbol: DAX (active: NASDAQ)")
```

### 3. Balance availability
```python
if current_balance <= 1000:
    → Rejected ("Insufficient balance")
```

### 4. Position limits (RiskManager)
```python
if not self.risk_manager.can_trade():
    → Rejected ("Max positions reached" nebo "Daily loss limit")
```

### 5. Risk calculation
```python
if entry_price <= 0 or sl_distance_points <= 0:
    → Rejected ("Invalid entry price or stop loss distance")
```

---

## 🔍 Monitoring & Debugging

### Log Messages:

#### Signal Rejection (storage):
```
[ORDER_EXECUTOR] ⏸️ Signal rejected - auto-trading DISABLED: DAX BUY
[ORDER_EXECUTOR] 💾 Signal saved for re-evaluation (2 total)
```

#### Re-evaluation Start:
```
[AUTO-TRADING] 🔄 Re-evaluating previously rejected signals...
[ORDER_EXECUTOR] 🔄 Re-evaluating 3 rejected signals...
```

#### Individual Signal Processing:
```
[ORDER_EXECUTOR] 🔄 Re-evaluating: DAX BUY
[ORDER_EXECUTOR] ✅ Re-evaluation SUCCESS: DAX
```

#### Summary:
```
[ORDER_EXECUTOR] 📊 Re-evaluation complete:
  ✅ Executed: 2
  ❌ Failed: 1
  ⏰ Expired: 0
```

### Grep Commands:

```bash
# Check saved signals
grep "Signal saved for re-evaluation" /config/logs/appdaemon.log | tail -20

# Check re-evaluation runs
grep "Re-evaluating.*rejected signals" /config/logs/appdaemon.log | tail -10

# Check re-evaluation results
grep "Re-evaluation SUCCESS\|FAILED\|expired" /config/logs/appdaemon.log | tail -20

# Check summary statistics
grep "Re-evaluation complete" -A3 /config/logs/appdaemon.log | tail -20
```

---

## ⚙️ Configuration

### Constants (hardcoded):

```python
# simple_order_executor.py:83-84
self.rejected_signals = []
self.max_rejected_signals = 10  # Max stored signals
```

```python
# simple_order_executor.py:1233
max_age = timedelta(minutes=30)  # Max signal age
```

### Možné úpravy:

Pokud chceš změnit parametry, edituj `simple_order_executor.py`:

```python
# Zvýšit max počet uložených signálů:
self.max_rejected_signals = 20  # Was: 10

# Prodloužit max stáří signálu:
max_age = timedelta(minutes=60)  # Was: 30
```

**Doporučení:** Nechej default hodnoty, jsou vybalancované pro intraday trading.

---

## 🧪 Testing

### Manual Test Procedure:

1. **Setup:**
   - AppDaemon running
   - Auto-trading DISABLED

2. **Generate signal:**
   - Wait for market conditions
   - Or use force signal button

3. **Verify storage:**
   ```bash
   grep "Signal saved for re-evaluation" /config/logs/appdaemon.log | tail -1
   ```
   Should see: `💾 Signal saved for re-evaluation (1 total)`

4. **Enable auto-trading:**
   - Toggle ON in Home Assistant

5. **Verify re-evaluation:**
   ```bash
   grep "Re-evaluation" /config/logs/appdaemon.log | tail -10
   ```
   Should see:
   - `🔄 Re-evaluating 1 rejected signals...`
   - `✅ Re-evaluation SUCCESS` or `❌ Re-evaluation FAILED`
   - `📊 Re-evaluation complete`

6. **Check notification:**
   - Home Assistant should show notification if signals were executed

### Expected Results:

✅ **Success case:**
- Signal stored when rejected
- Signal re-evaluated when toggle enabled
- Signal executed if still valid
- Notification sent

❌ **Failure cases (expected):**
- Signal expired (age > 30 min) → Not executed, logged
- Signal invalid (wrong symbol) → Not executed, logged with reason
- Risk limits exceeded → Not executed, logged with reason

---

## 🚀 Future Enhancements

### Možná vylepšení:

1. **Configurable parameters:**
   - Max age as config parameter
   - Max stored signals as config parameter

2. **Persistence:**
   - Save rejected signals to file
   - Reload on AppDaemon restart

3. **Priority system:**
   - Re-evaluate high quality signals first

4. **Notification improvements:**
   - Detailed breakdown in notification
   - Failed reason in notification

5. **Analytics:**
   - Track re-evaluation success rate
   - Monitor average signal age at execution

---

## 📝 Version History

**v1.0 (2025-10-28):**
- Initial implementation
- Basic re-evaluation on toggle enable
- 30 minute age limit
- 10 signal storage limit
- Summary statistics

---

## 🔗 Related Documentation

- **APPDAEMON_SETUP.md** - Setup guide including re-evaluation feature
- **STATUS_REPORT.md** - Current system status
- **simple_order_executor.py** - Source code with inline comments
- **main.py** - Toggle integration
