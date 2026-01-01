# Ruční Nastavení - Checklist

## ✅ Co je již hotovo v kódu

Všechny kritické opravy jsou implementovány v kódu:
- ✅ EventBridge priority queues
- ✅ Odstranění time.sleep()
- ✅ Watchdog Manager (kód)
- ✅ Broker timestamp sync
- ✅ Reconcile on startup
- ✅ Recorder exclude (přidáno do configuration.yaml)
- ✅ Watchdog automatizace (přidáno do configuration.yaml)
- ✅ Watchdog entity (přidáno do configuration.yaml)

---

## 🔧 Co je potřeba udělat ručně

### 1. ✅ Restart Home Assistant

**Proč**: Aby se načetly nové entity a automatizace z `configuration.yaml`

**Jak**:
1. Jdi do Home Assistant → Settings → System → Restart
2. Nebo použij Developer Tools → YAML → Restart

**Ověření**:
- Po restartu by se měly objevit nové entity:
  - `input_boolean.trading_watchdog`
  - `input_boolean.trading_kill_switch`
  - `input_boolean.trading_kill_switch_enabled`
  - `input_boolean.auto_trading_enabled`

---

### 2. ✅ Ověřit Watchdog Entity

**Proč**: Ujistit se, že watchdog entity existuje a funguje

**Jak**:
1. Jdi do Developer Tools → States
2. Vyhledej `input_boolean.trading_watchdog`
3. Mělo by se měnit každou minutu (on/off/on/off...)

**Ověření**:
- Entity existuje: ✅
- Mění se každou minutu: ✅
- V attributes vidíš `last_update` a `update_count`: ✅

---

### 3. ✅ Otestovat Watchdog Automatizaci

**Proč**: Ujistit se, že automatizace funguje

**Jak**:
1. Jdi do Settings → Automations
2. Najdi "Trading Watchdog Alert"
3. Ověř, že je aktivní (enabled)

**Test**:
1. Manuálně nastav `input_boolean.trading_watchdog` na `off`
2. Počkej 3 minuty (nebo změň automatizaci na 1 minutu pro test)
3. Měla by přijít notifikace na mobil

**Ověření**:
- Automatizace existuje: ✅
- Je aktivní: ✅
- Po timeoutu pošle notifikaci: ✅

---

### 4. ✅ Ověřit Recorder Exclude

**Proč**: Ujistit se, že high-frequency entity se neukládají do databáze

**Jak**:
1. Jdi do Developer Tools → States
2. Vyhledej `sensor.event_queue_metrics`
3. Zkontroluj, zda se entity aktualizuje (měla by)
4. Zkontroluj recorder databázi (volitelné)

**Ověření**:
- Entity se aktualizuje: ✅
- V recorder databázi není (nebo je málo záznamů): ✅

**Poznámka**: Pokud máš přístup k recorder databázi, můžeš zkontrolovat:
```sql
SELECT COUNT(*) FROM states WHERE entity_id LIKE '%volume_zscore%';
-- Mělo by být 0 nebo velmi málo
```

---

### 5. ✅ Ověřit Watchdog v Logs

**Proč**: Ujistit se, že WatchdogManager běží

**Jak**:
1. Jdi do AppDaemon logs
2. Vyhledej `[WATCHDOG]`
3. Měly by být logy každou minutu: `[WATCHDOG] ✅ Updated (count: X, state: on/off)`

**Ověření**:
- Logy se objevují každou minutu: ✅
- Count se zvyšuje: ✅
- Žádné chyby: ✅

---

### 6. ✅ Ověřit EventBridge Priority Queues

**Proč**: Ujistit se, že kritické eventy se nezahazují

**Jak**:
1. Jdi do AppDaemon logs
2. Vyhledej `[EVENT_BRIDGE]`
3. Měly by být logy: `[EVENT_BRIDGE] ✅ Critical event queued: EXECUTION_EVENT`

**Ověření**:
- Kritické eventy se logují: ✅
- Market data se může zahazovat (to je OK): ✅
- Critical events queue depth je rozumný (< 10): ✅

---

### 7. ✅ Ověřit Broker Timestamp Sync

**Proč**: Ujistit se, že time_based_manager používá broker čas

**Jak**:
1. Jdi do AppDaemon logs
2. Vyhledej `[TIME_MANAGER]`
3. Měly by být logy: `[TIME_MANAGER] Broker timestamp updated: ...`

**Ověření**:
- Broker timestamp se aktualizuje: ✅
- Offset je rozumný (< 5 sekund): ✅

---

### 8. ✅ Ověřit Reconcile on Startup

**Proč**: Ujistit se, že bot adoptuje existující pozice po restartu

**Jak**:
1. Restartuj AppDaemon
2. Jdi do AppDaemon logs
3. Vyhledej `[RECONCILE]`
4. Měly by být logy: `[RECONCILE] ✅ Startup reconcile complete`

**Ověření**:
- Reconcile se spustí po 5 sekundách: ✅
- Adoptuje existující pozice: ✅
- Aktualizuje balance: ✅

---

### 9. ⚠️ Volitelné: Nastavit Kill Switch Handler v Botu

**Proč**: Pokud chceš, aby bot automaticky zavíral pozice při aktivaci kill switch

**Jak**:
1. V `main.py` přidat listener na `input_boolean.trading_kill_switch`
2. Když se aktivuje, zavolat `position_closer.close_all_positions()`

**Kód** (volitelné):
```python
# V initialize() přidat:
self.listen_state(self._handle_kill_switch, "input_boolean.trading_kill_switch")

# Přidat metodu:
def _handle_kill_switch(self, entity, attribute, old, new, kwargs):
    if new == 'on':
        self.log("[KILL_SWITCH] 🛑 Kill switch activated - closing all positions")
        if hasattr(self, 'order_executor') and self.order_executor:
            positions = self.risk_manager.open_positions
            if positions:
                self.order_executor.position_closer.close_all_positions(positions)
```

**Status**: Volitelné - automatizace už posílá notifikaci, bot může reagovat manuálně

---

## 📋 Rychlý Checklist

- [ ] **Restart Home Assistant** (nutné)
- [ ] **Ověřit watchdog entity** (nutné)
- [ ] **Otestovat watchdog automatizaci** (doporučeno)
- [ ] **Ověřit recorder exclude** (doporučeno)
- [ ] **Ověřit watchdog v logs** (doporučeno)
- [ ] **Ověřit EventBridge priority queues** (doporučeno)
- [ ] **Ověřit broker timestamp sync** (doporučeno)
- [ ] **Ověřit reconcile on startup** (doporučeno)
- [ ] **Otestovat kill switch handler** (doporučeno) - ✅ Implementováno

---

## 🎯 Minimální Požadavky (Must Do)

1. ✅ **Restart Home Assistant** - aby se načetly entity a automatizace
2. ✅ **Ověřit watchdog entity** - že existuje a funguje

Zbytek je doporučený pro ověření, že vše funguje správně.

---

## 🚨 Pokud něco nefunguje

### Watchdog se neaktualizuje:
- Zkontroluj AppDaemon logs pro chyby
- Ověř, že `watchdog_manager` je inicializován v `main.py`
- Ověř, že `run_every()` je naplánováno

### Automatizace nefunguje:
- Zkontroluj, že automatizace je aktivní (enabled)
- Zkontroluj trigger podmínky
- Zkontroluj, že `input_boolean.auto_trading_enabled` existuje

### Recorder exclude nefunguje:
- Zkontroluj syntax v `configuration.yaml`
- Restartuj Home Assistant
- Ověř, že entity pattern matchuje (např. `sensor.*_volume_zscore`)

---

## ✅ Status

**Všechny kritické opravy jsou implementovány v kódu.**

**Ruční kroky jsou minimální** - hlavně restart HA a ověření, že vše funguje.

**Systém je připraven na demo testování!** 🚀

