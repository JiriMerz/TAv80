# Seznam všech input_boolean v configuration.yaml

**Datum:** 2025-12-29  
**Soubor:** `config/configuration.yaml`  
**Sekce:** Řádky 288-359

---

## 📋 Kompletní seznam (14 entit)

### 1. `clear_signals`
- **Název:** Clear All Signals
- **Ikona:** `mdi:delete-sweep`
- **Initial:** (není specifikováno, default `false`)

### 2. `trading_signals_enabled`
- **Název:** Trading Signals Active
- **Initial:** `true`
- **Ikona:** `mdi:chart-line`

### 3. `trading_notifications_enabled`
- **Název:** Trading Notifications
- **Initial:** `true`
- **Ikona:** `mdi:bell`

### 4. `trading_london_session_only`
- **Název:** London Session Only
- **Initial:** `false`
- **Ikona:** `mdi:clock-time-eight`

### 5. `trading_news_filter`
- **Název:** News Filter Active
- **Initial:** `false`
- **Ikona:** `mdi:newspaper-variant`

### 6. `force_signal_dax`
- **Název:** Force DAX Test Signal
- **Initial:** `false`
- **Ikona:** `mdi:test-tube`

### 7. `force_signal_nasdaq`
- **Název:** Force NASDAQ Test Signal
- **Initial:** `false`
- **Ikona:** `mdi:test-tube`

### 8. `dax_signal_executed`
- **Název:** DAX Signal Executed
- **Initial:** `false`
- **Ikona:** (není specifikováno)

### 9. `nasdaq_signal_executed`
- **Název:** NASDAQ Signal Executed
- **Initial:** `false`
- **Ikona:** (není specifikováno)

### 10. `dax_signal_cancelled`
- **Název:** DAX Signal Cancelled
- **Initial:** `false`
- **Ikona:** (není specifikováno)

### 11. `nasdaq_signal_cancelled`
- **Název:** NASDAQ Signal Cancelled
- **Initial:** `false`
- **Ikona:** (není specifikováno)

### 12. `trading_watchdog`
- **Název:** Trading Bot Watchdog
- **Initial:** `false`
- **Ikona:** `mdi:heart-pulse`
- **Kategorie:** Watchdog & Kill Switch

### 13. `trading_kill_switch`
- **Název:** Trading Kill Switch
- **Initial:** `false`
- **Ikona:** `mdi:alert-octagon`
- **Kategorie:** Watchdog & Kill Switch

### 14. `trading_kill_switch_enabled`
- **Název:** Kill Switch Enabled
- **Initial:** `false`
- **Ikona:** `mdi:shield-alert`
- **Kategorie:** Watchdog & Kill Switch

### 15. `auto_trading_enabled`
- **Název:** Auto Trading Enabled
- **Initial:** `false`
- **Ikona:** `mdi:robot`

---

## 📊 Statistiky

- **Celkem entit:** 15
- **S initial: true:** 2 (`trading_signals_enabled`, `trading_notifications_enabled`)
- **S initial: false:** 12
- **Bez initial:** 1 (`clear_signals`)

---

## ⚠️ Poznámka k duplicitě

V logách se objevuje varování:
```
ERROR: Platform input_boolean does not generate unique IDs. 
ID auto_trading_enabled already exists - ignoring input_boolean.auto_trading_enabled
```

To znamená, že `auto_trading_enabled` je pravděpodobně definován i jinde (např. přes UI jako Helper), což způsobuje konflikt. Doporučuje se:
1. Zkontrolovat, zda není definován v UI (Settings → Devices & Services → Helpers)
2. Pokud ano, odstranit duplicitní definici
3. Nebo odstranit z `configuration.yaml` a nechat jen UI verzi

---

## 🔍 Použití v automacích

Následující `input_boolean` entity jsou použity v automacích:

- `input_boolean.trading_signals_enabled` - řádky 1557, 1619, 1639
- `input_boolean.trading_notifications_enabled` - řádek 1560
- `input_boolean.trading_watchdog` - řádky 1656, 1661, 1669
- `input_boolean.auto_trading_enabled` - řádky 1671, 1719
- `input_boolean.trading_kill_switch_enabled` - řádek 1691
- `input_boolean.trading_kill_switch` - řádky 1692, 1693, 1715
- `input_boolean.trading_london_session_only` - řádek 1077 (v template)

