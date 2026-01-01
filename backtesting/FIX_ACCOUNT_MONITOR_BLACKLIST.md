# Fix: Přidání blacklistu do account_state_monitor.py

**Datum:** 2025-12-28  
**Problém:** Blacklist v main.py nefungoval, protože entity se volají z account_state_monitor.py

---

## 🔍 Zjištění

Poškozené entity se aktualizují z `account_state_monitor.py`, který má vlastní metodu `_set_state_safe()` bez blacklistu. Blacklist v `main.py` proto nefungoval.

**Entity volané z account_state_monitor.py:**
- `sensor.trading_open_positions`
- `sensor.trading_daily_pnl`
- `sensor.trading_daily_pnl_percent`

---

## ✅ Oprava

Přidán blacklist do `account_state_monitor.py`, metoda `_set_state_safe()`:

```python
# Blacklist of corrupted entities that cause HTTP 400 errors
CORRUPTED_ENTITIES_BLACKLIST = {
    'sensor.trading_open_positions',
    'sensor.trading_daily_pnl',
    'sensor.trading_daily_pnl_percent',
}

# Skip corrupted entities silently
if entity_id in CORRUPTED_ENTITIES_BLACKLIST:
    return None
```

---

## 📋 Deploy

1. **Zkopíruj upravený soubor:**
   ```bash
   cp src/trading_assistant/account_state_monitor.py \
      /Volumes/addon_configs/a0d7b954_appdaemon/apps/trading_assistant/account_state_monitor.py
   ```

2. **Restart AppDaemon:**
   ```bash
   ssh root@homeassistant.local "ha addons restart a0d7b954_appdaemon"
   ```

3. **Zkontroluj logy:**
   ```bash
   tail -50 /Volumes/addon_configs/a0d7b954_appdaemon/logs/appdaemon.log | grep -i "error\|queue\|utility"
   ```

**Očekávané výsledky:**
- ✅ Žádné HTTP 400 chyby pro blacklisted entity
- ✅ Utility loop rychlejší (< 100ms místo 2-3 sekund)
- ✅ Systém běží plynuleji


