# Instrukce pro Deploy na RPi

**Datum:** 2025-01-03  
**Refactoring:** Fáze 1 - Rychlé výhry

---

## 📦 Soubory k nahrání na RPi

### 1. Konfigurace
- **`src/apps.yaml`** - Oprava duplicitního `position_conflicts`

### 2. Python moduly
- **`src/trading_assistant/main.py`** - Odstranění SwingEngine
- **`src/trading_assistant/simple_order_executor.py`** - Odstranění deprecated atributů

---

## 🚀 Postup deploy

### Krok 1: Backup současných souborů na RPi
```bash
# Na RPi (přes SSH nebo Samba)
cd /config/appdaemon/apps/trading_assistant
cp apps.yaml apps.yaml.backup_$(date +%Y%m%d_%H%M%S)
cp trading_assistant/main.py trading_assistant/main.py.backup_$(date +%Y%m%d_%H%M%S)
cp trading_assistant/simple_order_executor.py trading_assistant/simple_order_executor.py.backup_$(date +%Y%m%d_%H%M%S)
```

### Krok 2: Nahrání nových souborů
**Přes Samba share:**
```bash
# Na macOS
cd /Users/jirimerz/Projects/TAv80

# Zkopírovat soubory na Samba share
cp src/apps.yaml /Volumes/addon_configs/a0d7b954_appdaemon/apps/trading_assistant/
cp src/trading_assistant/main.py /Volumes/addon_configs/a0d7b954_appdaemon/apps/trading_assistant/trading_assistant/
cp src/trading_assistant/simple_order_executor.py /Volumes/addon_configs/a0d7b954_appdaemon/apps/trading_assistant/trading_assistant/
```

**Nebo použít deploy.sh (upravit cesty):**
```bash
cd /Users/jirimerz/Projects/TAv80
./deploy.sh
```

### Krok 3: Restart AppDaemon
- Home Assistant UI: **Settings → Add-ons → AppDaemon → RESTART**
- Nebo přes SSH: `ha addons restart a0d7b954_appdaemon`

### Krok 4: Kontrola logů
```bash
# Na RPi
tail -f /config/logs/appdaemon.log
```

**Očekávané logy:**
- ✅ `[SWING] Using SimpleSwingDetector (lookback=5, min_move=0.15%)`
- ✅ Žádné chyby o SwingEngine
- ✅ Žádné chyby o deprecated atributech

---

## ⚠️ Důležité poznámky

1. **Backup je kritický** - vždy si zálohuj současné soubory před deploy
2. **Restart je nutný** - AppDaemon načte nový kód až po restartu
3. **Kontrola logů** - vždy zkontroluj logy po restartu
4. **Rollback** - pokud něco nefunguje, vrať backup soubory

---

## 🔍 Ověření úspěšného deploy

Po restartu zkontroluj:

1. **Logy bez chyb:**
   - Žádné `ImportError` nebo `AttributeError`
   - Žádné reference na SwingEngine
   - Žádné reference na deprecated atributy

2. **Funkčnost:**
   - Trading Assistant se inicializuje bez chyb
   - Swing detection funguje (SimpleSwingDetector)
   - Position tracking funguje (risk_manager)

---

## 📋 Checklist před deploy

- [ ] Backup vytvořen na RPi
- [ ] Soubory zkopírovány na Samba share
- [ ] AppDaemon restartován
- [ ] Logy zkontrolovány (žádné chyby)
- [ ] Funkčnost ověřena

---

*Deploy instrukce pro Refactoring Fáze 1*

