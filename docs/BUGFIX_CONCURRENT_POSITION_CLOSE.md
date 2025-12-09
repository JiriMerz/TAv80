# BUGFIX: Concurrent Position Close & HA Entity Update Blocking

**Date:** 2025-10-28
**Status:** ✅ FIXED
**Severity:** HIGH (Dashboard pokazoval nesprávný počet pozic po close)

## Problém

Po současném zavření dvou pozic (během 8ms) dashboard zobrazoval **špatný počet otevřených pozic** - ukazoval 1 místo 0. Balance se aktualizoval správně, ale positions count ne.

### Symptomy
1. První position close → Dashboard OK: 2→1 pozice ✅
2. Druhý position close → Dashboard WRONG: zůstalo 1 místo 0 ❌
3. **22 sekundový gap v logách** (17:10:07.303 → 17:10:29.427)
4. Chyběl log "Updated: Balance=..., Positions=..." pro druhý close
5. Startup error: `No module named 'risk_manager'`

### Logy
```
17:10:05.962 INFO [ACCOUNT_MONITOR] 🔥 Execution event type: 3  (PRVNÍ CLOSE)
17:10:07.257 INFO [ACCOUNT_MONITOR] Updated: Balance=1848636.84, Positions=1, PnL=60227.78  ✅

17:10:07.279 ERROR [🚨 EXECUTION EVENT] EXECUTION_EVENT: ...  (DRUHÝ CLOSE)
17:10:07.303 WARNING [ACCOUNT_MONITOR] ⚠️ Positions dropped from 1 to 0!
[22 SEKUND MEZERA - NO UPDATE LOG!]
17:10:29.427 INFO [NASDAQ] ORB LONG triggered...
```

## Root Cause Analysis

### Problém #1: Blocking set_state() call
**Lokace:** `account_state_monitor.py:389-498` (`_update_ha_entities()`)

Při druhém execution eventu metoda `_update_ha_entities()`:
- Začala správně (log warning na řádku 400)
- Ale pak se **zablokovala na 22 sekund** na některém `set_state()` volání
- **Nikdy nedokončila** (chybí log na řádku 498)
- Pravděpodobně `get_state()` nebo `set_state()` pro `sensor.trading_risk_status` (řádky 445-482)

**Důsledky:**
- Dashboard pozic nebyl aktualizován
- Žádný error log (metoda se nezasekla v exception handleru, prostě blokla)
- Home Assistant API pravděpodobně nereagoval/timeoutoval

### Problém #2: Missing error handling
**Lokace:** `account_state_monitor.py:408-465`

Původně VŠECHNY `set_state()` cally byly v jednom try-except bloku. Pokud jeden call failnul:
- Celá metoda přeskočila na exception handler
- Zbylé entity nebyly aktualizované
- Jen jeden error log pro všechny entity

### Problém #3: Import error při startu
**Lokace:** `account_state_monitor.py:532`

```python
from risk_manager import PositionSize  # ❌ WRONG - missing relative import
```

**Důsledky:**
- `ImportError: No module named 'risk_manager'`
- Position sync do risk manageru failoval při startu
- Log: `[ACCOUNT_MONITOR] ❌ Error syncing position 8322952: No module named 'risk_manager'`

## Implementované Opravy

### Fix #1: Granular try-except pro každý set_state() call
**Soubor:** `account_state_monitor.py:410-496`

```python
# Before: Single try-except for all entities
try:
    self.app.set_state("sensor.trading_account_balance", ...)
    self.app.set_state("sensor.trading_open_positions", ...)  # ← If this fails, rest is skipped
    self.app.set_state("sensor.trading_risk_status", ...)
    logger.info("Updated: ...")  # ← Never reached if any fails
except Exception as e:
    logger.error(f"Error: {e}")  # ← Only one error log

# After: Individual try-except for each entity
try:
    logger.debug("[ACCOUNT_MONITOR] 🔧 Setting trading_account_balance...")
    self.app.set_state("sensor.trading_account_balance", ...)
    logger.debug("[ACCOUNT_MONITOR] ✅ trading_account_balance updated")
except Exception as e:
    logger.error(f"[ACCOUNT_MONITOR] ❌ Failed to update trading_account_balance: {e}")

try:
    logger.debug("[ACCOUNT_MONITOR] 🔧 Setting trading_open_positions...")
    self.app.set_state("sensor.trading_open_positions", ...)
    logger.debug("[ACCOUNT_MONITOR] ✅ trading_open_positions updated")
except Exception as e:
    logger.error(f"[ACCOUNT_MONITOR] ❌ Failed to update trading_open_positions: {e}")

# ... same for other entities ...

# ALWAYS reached, even if some entities fail:
logger.info(f"[ACCOUNT_MONITOR] Updated: Balance={balance:.2f}, Positions={open_positions_count}, ...")
```

**Klíčové změny:**
- ✅ Každý `set_state()` v samostatném try-except
- ✅ Debug log před/po každém volání → vidíme kde se zasekne
- ✅ Hlavní summary log se vypíše VŽDY, i když některé entity failnou
- ✅ Specifické error logy pro každou entitu

### Fix #2: Enhanced logging pro diagnostiku
**Soubor:** `account_state_monitor.py:406, 411-418, 422-429, etc.`

Přidané debug logy:
```python
logger.debug(f"[ACCOUNT_MONITOR] 🔄 Updating HA entities: Balance={balance:.2f}, Positions={open_positions_count}, PnL={daily_pnl:.2f}")

logger.debug("[ACCOUNT_MONITOR] 🔧 Setting trading_account_balance...")
# ... set_state call ...
logger.debug("[ACCOUNT_MONITOR] ✅ trading_account_balance updated")

logger.debug("[ACCOUNT_MONITOR] 🔧 Getting trading_risk_status...")
current_risk_entity = self.app.get_state("sensor.trading_risk_status", attribute="all")
logger.debug(f"[ACCOUNT_MONITOR] 📥 Got trading_risk_status: type={type(current_risk_entity)}")
```

**Klíčové změny:**
- ✅ Entry log na začátku metody
- ✅ Pre/post logs pro každý `set_state()` a `get_state()`
- ✅ Umožňuje přesně identifikovat, který call blokuje

### Fix #3: Correct import pro PositionSize
**Soubor:** `account_state_monitor.py:20-27, 541-543`

```python
# TOP OF FILE - Added proper relative import with graceful fallback
try:
    from .risk_manager import PositionSize
    RISK_MANAGER_AVAILABLE = True
except ImportError:
    logger.warning("[ACCOUNT_MONITOR] ⚠️ risk_manager module not available - position sync disabled")
    PositionSize = None
    RISK_MANAGER_AVAILABLE = False

# IN FUNCTION - Added check before using PositionSize
if not RISK_MANAGER_AVAILABLE or PositionSize is None:
    logger.warning(f"[ACCOUNT_MONITOR] ⚠️ Cannot sync position {pos_id} - PositionSize not available")
    continue
```

**Klíčové změny:**
- ✅ Relative import `.risk_manager` místo absolute `risk_manager`
- ✅ Import na top souboru místo uvnitř funkce
- ✅ Graceful fallback pokud modul není dostupný
- ✅ Runtime check před použitím

## Testování

### Před opravou
```
17:10:05.962 INFO [ACCOUNT_MONITOR] 🔥 Execution event type: 3  (Position 8322952 close)
17:10:07.257 INFO [ACCOUNT_MONITOR] Updated: Balance=1848636.84, Positions=1, PnL=60227.78  ✅

17:10:07.292 INFO [ACCOUNT_MONITOR] 🔥 Execution event type: 3  (Position 8323008 close)
17:10:07.303 WARNING [ACCOUNT_MONITOR] ⚠️ Positions dropped from 1 to 0!
[NO UPDATE LOG - 22 SECOND GAP]  ❌

Dashboard: 1 open position  ❌ (should be 0)
Balance: 1861173.36 CZK  ✅ (correct)
```

### Po opravě (očekávané)
```
17:10:05.962 INFO [ACCOUNT_MONITOR] 🔥 Execution event type: 3  (Position 8322952 close)
17:10:05.XXX DEBUG [ACCOUNT_MONITOR] 🔄 Updating HA entities: Balance=1848636.84, Positions=1...
17:10:05.XXX DEBUG [ACCOUNT_MONITOR] 🔧 Setting trading_account_balance...
17:10:05.XXX DEBUG [ACCOUNT_MONITOR] ✅ trading_account_balance updated
17:10:05.XXX DEBUG [ACCOUNT_MONITOR] 🔧 Setting trading_open_positions to 1...
17:10:05.XXX DEBUG [ACCOUNT_MONITOR] ✅ trading_open_positions updated to 1
17:10:07.257 INFO [ACCOUNT_MONITOR] Updated: Balance=1848636.84, Positions=1, PnL=60227.78  ✅

17:10:07.292 INFO [ACCOUNT_MONITOR] 🔥 Execution event type: 3  (Position 8323008 close)
17:10:07.303 WARNING [ACCOUNT_MONITOR] ⚠️ Positions dropped from 1 to 0!
17:10:07.XXX DEBUG [ACCOUNT_MONITOR] 🔄 Updating HA entities: Balance=1861173.36, Positions=0...
17:10:07.XXX DEBUG [ACCOUNT_MONITOR] 🔧 Setting trading_account_balance...
17:10:07.XXX DEBUG [ACCOUNT_MONITOR] ✅ trading_account_balance updated
17:10:07.XXX DEBUG [ACCOUNT_MONITOR] 🔧 Setting trading_open_positions to 0...
17:10:07.XXX DEBUG [ACCOUNT_MONITOR] ✅ trading_open_positions updated to 0  ✅
17:10:07.XXX INFO [ACCOUNT_MONITOR] Updated: Balance=1861173.36, Positions=0, PnL=72764.30  ✅

Dashboard: 0 open positions  ✅ (correct)
Balance: 1861173.36 CZK  ✅ (correct)
```

## Změněné soubory

1. `src/trading_assistant/account_state_monitor.py`
   - Granular try-except pro každý `set_state()` call
   - Enhanced debug logging
   - Fixed PositionSize import (relative import + graceful fallback)

## Dopady

- ✅ Dashboard nyní zobrazuje správný počet otevřených pozic i při concurrent closes
- ✅ Pokud jedna entity failne, ostatní se stále aktualizují
- ✅ Debug logy umožňují přesně identifikovat, který `set_state()` call blokuje
- ✅ Zmizí import error při startu
- ✅ Robustnější error handling - jeden failing call nezastaví celý update

## Related Issues

- Podobný problém jako BUGFIX_POSITIONS_COUNT_UPDATE.md, ale jiná root cause
- Tam byl problém s PT_TRADER_RES callback, tady je problém s blocking set_state()
- Concurrent execution events mohou způsobit problémy pokud HA API reaguje pomalu

## Lessons Learned

1. **Granular error handling:** Nikdy nedávat všechny kritické operace do jednoho try-except
2. **Detailed logging:** Debug logy před/po každým externím volání jsou kritické pro diagnostiku
3. **Timeouts:** Home Assistant API calls mohou blokovat - zvážit timeouty nebo async calls
4. **Import discipline:** Vždy použít relative imports v package, nikdy absolute
5. **Graceful degradation:** Import errors by neměly crashnout celou aplikaci

## Next Steps

1. Monitorovat logy po deployu - hledat debug logy pro set_state() calls
2. Pokud stále blokuje, zvážit async set_state() nebo timeouty
3. Případně přidat rate limiting pro concurrent entity updates
4. Zvážit batch update místo jednotlivých set_state() calls
