# Live Status Informace - Implementováno

## ✅ Co bylo přidáno

### 1. System Health Status Card
**Umístění:** Dashboard - hned po Analysis status card

**Zobrazuje:**
- Celkový systémový status: OK / WARNING / ERROR
- Poslední bar pro DAX a NASDAQ (v sekundách/minutách)
- Barevné indikátory:
  - 🟢 Zelená = OK (vše funguje)
  - 🟠 Oranžová = WARNING (něco je pomalé)
  - 🔴 Červená = ERROR (problém)

### 2. Live Activity Card
**Umístění:** Dashboard - pod System Status

**Zobrazuje pro každý symbol (DAX/NASDAQ):**
- **Last Bar:** Kdy byl naposledy přijat bar (např. "5s ago", "2m ago")
- **Last Analysis:** Kdy byla naposledy provedena analýza
- **Last Signal Check:** Kdy byla naposledy zkontrolována možnost signálu

**Formát:** `Bar: 5s | Analysis: 8s | Signal: 12s`

## 🔧 Technické detaily

### Nové entity v kódu:

1. **sensor.trading_system_status**
   - State: OK / WARNING / ERROR
   - Attributes:
     - `symbols`: Dict s informacemi pro každý symbol
     - `ctrader_connected`: on/off
     - `last_update`: ISO timestamp

2. **sensor.{alias}_live_status** (např. `sensor.dax_live_status`)
   - State: OK / STALE / SLOW
   - Attributes:
     - `last_bar_ago`: "5s" nebo "2m"
     - `last_analysis_ago`: "8s" nebo "1m"
     - `last_signal_check_ago`: "12s" nebo "3m"
     - `last_signal_result`: Důvod proč není signál (např. "No signals (check filters)")

### Tracking v kódu:

- `_last_bar_time[alias]` - Trackuje čas posledního baru
- `_last_analysis_time[alias]` - Trackuje čas poslední analýzy
- `_last_signal_check_time[alias]` - Trackuje čas poslední kontroly signálu
- `_last_signal_check_result[alias]` - Ukládá výsledek poslední kontroly

### Aktualizace:

- Status se aktualizuje při každém `log_status()` volání (každých 30 sekund)
- Tracking se aktualizuje v reálném čase při:
  - Příjmu nového baru
  - Provedení analýzy
  - Kontrole signálu

## 📊 Co to řeší

1. **Okamžitá viditelnost** - Vidíte, jestli systém funguje
2. **Detekce problémů** - Pokud bar nepřichází >5 minut = WARNING
3. **Debugging** - Vidíte přesně, kdy byla naposledy provedena každá aktivita
4. **Transparentnost** - Vidíte, proč nejsou generovány signály

## 🎯 Použití

Po nasazení uvidíte v dashboardu:
- **System Status** card s celkovým stavem
- **Live Activity** card s detailními informacemi pro každý symbol

Vše se aktualizuje automaticky každých 30 sekund.

