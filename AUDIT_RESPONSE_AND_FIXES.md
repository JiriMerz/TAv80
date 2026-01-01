# Audit Response - Kritická Rizika a Řešení

## ✅ Analýza Auditu

**Verdikt**: Audit je **VÝBORNÝ a HIGHLY RELEVANTNÍ**. Konzultant identifikoval skutečné kritické problémy, které mohou vést ke ztrátě peněz nebo kontrole nad účtem.

**Hodnocení**: ⭐⭐⭐⭐⭐ (5/5) - Profesionální, detailní, akční

---

## 🛑 KRITICKÁ RIZIKA - Analýza a Řešení

### 1. ✅ EventBridge Bottleneck - **POTVRZENO**

**Problém**: 
- `event_bridge.py` používá `put_nowait()` s `maxsize=1000`
- Pokud je fronta plná, **kritické EXECUTION_EVENT se zahodí**
- RiskManager pak neví o otevřených/zavřených pozicích

**Důkaz v kódu**:
```python
# event_bridge.py:43
self.queue.put_nowait({...})  # ❌ Může zahodit!

# event_bridge.py:58-62
except queue.Full:
    self.metrics['events_dropped'] += 1
    logger.warning(f"Event queue full, dropping {event_type}")
    return False  # ❌ Kritické události se ztratí!
```

**Řešení** (Priorita: **KRITICKÁ**):
1. Rozdělit na 2 fronty:
   - `market_data_queue` (LifoQueue, maxsize=500) - tick data, staré se zahazují
   - `critical_events_queue` (Queue, maxsize=None) - EXECUTION, ORDER_STATUS, ERROR - **NIKDY se nezahazují**

2. Implementovat prioritizaci:
   - Kritické eventy mají `priority=1`
   - Market data má `priority=0`
   - Při zpracování nejdřív kritické eventy

**Implementace**: Vytvořit `PriorityEventBridge` s dvěma frontami.

---

### 2. ✅ Async/Sync Race Conditions - **POTVRZENO**

**Problém**:
- `position_closer.py:450` používá `time.sleep(0.1)` - **blokuje hlavní vlákno**
- Během `time.sleep` se nečte EventBridge → fronta přeteče
- Mix async/sync v `simple_order_executor.py` může způsobit race conditions

**Důkaz v kódu**:
```python
# position_closer.py:450
time.sleep(0.1)  # ❌ Blokuje vlákno!

# simple_order_executor.py:918
time.sleep(0.1)  # ❌ Blokuje vlákno!
```

**Řešení** (Priorita: **KRITICKÁ**):
1. Odstranit všechny `time.sleep()` z hlavního vlákna
2. Použít `self.run_in()` nebo `self.run_every()` pro plánování úloh
3. Pro async operace použít `asyncio.create_task()` nebo `run_coroutine_threadsafe()`

**Implementace**: Refaktorovat `position_closer.py` a `simple_order_executor.py`.

---

### 3. ✅ Dead Man's Switch - **CHYBÍ**

**Problém**:
- Žádný watchdog mechanismus
- Pokud Python skript spadne, WebSocket může zůstat aktivní
- Pozice zůstanou bez kontroly

**Důkaz v kódu**:
```bash
# grep -r "watchdog\|dead.*man\|kill.*switch" src/
# ❌ Žádné výsledky!
```

**Řešení** (Priorita: **VYSOKÁ**):
1. Implementovat `WatchdogManager`:
   - Každou minutu aktualizovat `input_boolean.trading_watchdog`
   - HA automatizace: Pokud se watchdog nezměnil 3 minuty → kritická notifikace
   - Volitelně: Kill Switch API call na brokera

2. Vytvořit HA automatizaci:
```yaml
automation:
  - alias: "Trading Watchdog Alert"
    trigger:
      - platform: state
        entity_id: input_boolean.trading_watchdog
        to: 'off'
        for:
          minutes: 3
    action:
      - service: notify.mobile_app
        data:
          message: "🚨 TRADING BOT DOWN! Check immediately!"
      - service: input_boolean.trading_kill_switch
        data:
          state: 'on'
```

**Implementace**: Vytvořit `watchdog_manager.py`.

---

## ⚠️ OPERAČNÍ RIZIKA - Analýza a Řešení

### 4. ⚠️ NTP Time vs Broker Time - **ČÁSTEČNĚ POTVRZENO**

**Problém**:
- `time_based_manager.py` používá `datetime.now()` místo času z broker zpráv
- Rozdíl v čase může způsobit špatné rozhodnutí o "Close of Bar"

**Důkaz v kódu**:
```python
# time_based_manager.py:63, 117, 228
current_time = datetime.now()  # ❌ Lokální čas, ne broker čas!
```

**Řešení** (Priorita: **STŘEDNÍ**):
1. Všechna rozhodnutí o "Close of Bar" dělat na základě timestampu z `SPOT_EVENT` nebo `BAR_DATA`
2. Ukládat poslední broker timestamp a používat ho místo `datetime.now()`
3. Logovat rozdíl mezi lokálním a broker časem pro monitoring

**Implementace**: Upravit `time_based_manager.py` a `main.py`.

---

### 5. ⚠️ HA Recorder Spam - **POTENCIÁLNÍ PROBLÉM**

**Problém**:
- Hodně `_safe_set_state()` volání může nafouknout HA databázi
- Tick data, volume metrics se mohou zapisovat každých 5 sekund

**Důkaz v kódu**:
```python
# main.py:715, 1051, 1133 - mnoho set_state volání
self._safe_set_state("sensor.account_balance", ...)
```

**Řešení** (Priorita: **NÍZKÁ**):
1. Přidat do `configuration.yaml`:
```yaml
recorder:
  exclude:
    entities:
      - sensor.*_volume_zscore
      - sensor.*_tick_data
      - sensor.*_microstructure
    domains:
      - sensor  # Exclude all sensors with high frequency updates
```

2. Nebo použít `recorder: exclude` v entity attributes:
```python
self._safe_set_state("sensor.volume", state=value, 
                     attributes={"recorder": "exclude"})
```

**Implementace**: Přidat konfiguraci do `apps.yaml` a dokumentaci.

---

### 6. ⚠️ Restart Persistence - **ČÁSTEČNĚ IMPLEMENTOVÁNO**

**Problém**:
- Při restartu bot neví o pending orders
- Může si myslet, že je flat, ale má pending order

**Důkaz v kódu**:
```python
# main.py:3975 - reconcile existuje
if hasattr(self.ctrader_client, 'reconcile_data'):
    reconcile_data = self.ctrader_client.reconcile_data
```

**Ale**: Musím zkontrolovat, zda se volá automaticky při startu.

**Řešení** (Priorita: **STŘEDNÍ**):
1. V `initialize()` zavolat `reconcile()`:
   - Stáhnout všechny otevřené pozice
   - Stáhnout všechny pending orders
   - "Adoptovat" je do RiskManageru a AccountStateMonitoru

2. Implementovat `reconcile_on_startup()` metodu.

**Implementace**: Přidat reconcile do `initialize()`.

---

## 💡 SILNÉ STRÁNKY (Souhlas s Auditorem)

✅ **Defenzivní Risk Management** - `daily_risk_tracker.py` s hard stopem
✅ **Trade Decision Logger** - JSONL ukládání kontextu
✅ **AppDaemon Integrace** - EventBridge architektura

---

## 📋 Plán Implementace

### Fáze 1: Kritické Opravy (Tento týden)

1. **EventBridge Refactoring** (2-3 hodiny)
   - Vytvořit `PriorityEventBridge` s dvěma frontami
   - Implementovat prioritizaci
   - Testovat pod zátěží

2. **Odstranit time.sleep()** (1-2 hodiny)
   - Refaktorovat `position_closer.py`
   - Refaktorovat `simple_order_executor.py`
   - Použít `self.run_in()` místo `time.sleep()`

3. **Watchdog Manager** (1-2 hodiny)
   - Vytvořit `watchdog_manager.py`
   - Implementovat HA automatizaci
   - Testovat failover scenáře

### Fáze 2: Operační Vylepšení (Příští týden)

4. **Broker Time Sync** (1 hodina)
   - Upravit `time_based_manager.py`
   - Používat broker timestamp

5. **Reconcile on Startup** (1 hodina)
   - Přidat do `initialize()`
   - Testovat restart scenáře

6. **HA Recorder Config** (30 minut)
   - Přidat exclude konfiguraci
   - Dokumentace

---

## 🎯 Závěr

**Audit je VÝBORNÝ a HIGHLY RELEVANTNÍ.**

Všechny identifikované problémy jsou **skutečné a kritické**. Systém je architektonicky na úrovni 9/10, ale implementačně (concurrency/safety) na úrovni 6/10, což je pro peníze nebezpečné.

**Doporučení**: 
1. ✅ Opravit všechny 3 kritické problémy před demo testováním
2. ✅ Implementovat watchdog před reálnými penězi
3. ✅ Testovat pod zátěží (simulace NFP, flash crash)
4. ✅ Měsíc bezchybného chodu na Demu před reálnými penězi

**Status**: Připraveno k implementaci oprav.

