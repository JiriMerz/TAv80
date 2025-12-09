# AppDaemon Setup Documentation - Trading Assistant
**Datum:** 2025-10-28
**Home Assistant:** 2025.10.4
**AppDaemon:** 4.5.12

---

## ⚠️ KRITICKÁ PRAVIDLA PRO FUNKČNOST

### 1. **Umístění apps.yaml** ⭐ NEJDŮLEŽITĚJŠÍ!

```
❌ ŠPATNĚ: /config/apps.yaml
✅ SPRÁVNĚ: /config/apps/apps.yaml
```

**AppDaemon IGNORUJE apps.yaml v root složce `/config/`!**
Soubor MUSÍ být v `/config/apps/apps.yaml`

**Ověření:**
```bash
ls -la /config/apps/apps.yaml  # Musí existovat
```

---

### 2. **appdaemon.yaml - Minimální konfigurace**

**Umístění:** `/config/appdaemon.yaml` (root složka)

**FUNKČNÍ konfigurace:**
```yaml
---
appdaemon:
  latitude: 50.0755      # POVINNÉ
  longitude: 14.4378     # POVINNÉ
  elevation: 200         # POVINNÉ
  time_zone: Europe/Prague  # POVINNÉ
  plugins:
    HASS:
      type: hass
      token: !env_var SUPERVISOR_TOKEN
logs:
  main_log:
    filename: /config/logs/appdaemon.log
http:
  url: http://0.0.0.0:5050
```

**❌ NIKDY nepřidávat:**
- `pin_apps: false` - způsobuje PinOutofRange chybu
- `threads: X` - deprecated, způsobuje chybu
- `total_threads: X` - způsobuje chybu s pin_apps: false

**✅ AppDaemon použije výchozí hodnoty:**
- `pin_apps: true` (výchozí)
- Automatický počet threadů podle CPU

---

### 3. **apps.yaml - Duplicitní klíče**

**❌ CHYBA:** Duplicitní sekce `position_conflicts`

apps.yaml NESMÍ obsahovat duplicitní klíče na stejné úrovni. To způsobuje, že AppDaemon daemon se zasekne při parsování.

**Kontrola duplicit:**
```bash
grep -n "position_conflicts:" /config/apps/apps.yaml
```

Pokud vidíš více než 1 řádek → **PROBLÉM!** Smaž duplicitní sekci.

---

### 4. **Restart procedura** ⭐

**DŮLEŽITÉ:** AppDaemon addon se **AUTOMATICKY NERESTARTUJE** po restartu Home Assistant!

**Správný postup restartu:**
1. Restartuj Home Assistant (Settings → System → Restart)
2. **Počkej 2-3 minuty** než HA plně naběhne
3. **Ručně restartuj AppDaemon addon:**
   - Settings → Add-ons → AppDaemon → RESTART
4. Kontrola logů: Settings → Add-ons → AppDaemon → Log

**Alternativa - SSH:**
```bash
ha addons restart a0d7b954_appdaemon
```

---

## 🔍 Diagnostika problémů

### Kontrola, jestli AppDaemon běží:

```bash
# 1. Zkontroluj log file timestamp
ls -lah /config/logs/appdaemon.log

# 2. Zkontroluj poslední log záznamy
tail -50 /config/logs/appdaemon.log

# 3. Hledej klíčové zprávy
grep "AppDaemon Version\|Starting apps\|initialize" /config/logs/appdaemon.log | tail -10
```

**Očekávaný úspěšný start:**
```
INFO AppDaemon: AppDaemon Version 4.5.12 starting
INFO AppDaemon: Starting apps with X worker threads
INFO AppDaemon: All plugins ready
INFO AppDaemon: Starting apps: ['trading_assistant']
INFO AppDaemon: Calling initialize() for trading_assistant
INFO trading_assistant: Trading Assistant - Sprint 2 (Enhanced)
```

---

### Běžné chyby a řešení:

#### ❌ **"Invalid thread configuration"**
```
InvalidThreadConfiguration: Invalid thread configuration:
  total_threads: None
  pin_apps:      False
  pin_threads:   None
```

**Řešení:** Odstraň `pin_apps` a `total_threads` z `appdaemon.yaml`

---

#### ❌ **"PinOutofRange: Pin thread -1 out of range"**
```
appdaemon.exceptions.PinOutofRange: Pin thread -1 out of range. Must be between 0 and X
```

**Řešení:** Odstraň `pin_apps: false` z `appdaemon.yaml`

---

#### ❌ **AppDaemon se nespustí / žádné logy**

**Možné příčiny:**
1. **apps.yaml není v `/config/apps/apps.yaml`** ← nejčastější!
2. Duplicitní klíče v apps.yaml
3. Syntaktická chyba v YAML
4. Chybějící povinná pole (latitude, longitude, elevation, time_zone)

**Ověření YAML syntaxe:**
```bash
python3 -c "import yaml; yaml.safe_load(open('/config/apps/apps.yaml'))"
```

---

#### ❌ **AppDaemon daemon se zasekne po "Using selector: EpollSelector"**

**Symptom:**
```
DEBUG AppDaemon: Reading config file: /config/appdaemon.yaml
DEBUG AppDaemon: Using selector: EpollSelector
[... žádné další zprávy ...]
```

**Příčina:** Duplicitní klíče v apps.yaml (např. 2x `position_conflicts`)

**Řešení:**
```bash
# Najdi duplicity
grep -n "^[a-z_]*:" /config/apps/apps.yaml | sort | uniq -d

# Smaž duplicitní sekce ručně
```

---

## 📂 Struktura souborů

```
/config/
├── appdaemon.yaml           # ✅ Hlavní konfigurace AppDaemonu
├── apps/
│   ├── apps.yaml            # ✅ Konfigurace aplikací (MUSÍ být zde!)
│   ├── hello_world.py       # Test aplikace
│   └── trading_assistant/   # Trading Assistant kód
│       ├── main.py
│       ├── account_state_monitor.py
│       ├── event_bridge.py
│       └── ... (další moduly)
├── logs/
│   └── appdaemon.log        # ✅ Hlavní log file
└── secrets.yaml             # API klíče
```

---

## 🐛 Známé problémy (2025-10-28)

### ClientResponseError při vytváření HA entit

**Symptom v logu:**
```
[SPRINT2] Error creating entities: argument of type 'ClientResponseError' is not iterable
Error updating microstructure entities: argument of type 'ClientResponseError' is not iterable
Failed to publish metrics: argument of type 'ClientResponseError' is not iterable
```

**Stav:** ⚠️ Nevyřešeno (nízká priorita)
**Dopad:** Kosmetický - aplikace funguje, ale některé entity se nevytvoří v HA

**Řešení (budoucí):**
V souborech `main.py`, `account_state_monitor.py`, `event_bridge.py`:
1. Přidat import: `from aiohttp import ClientResponseError`
2. Obalit `set_state()` volání do try-except bloků

---

## ✅ Checklist pro novou instalaci

- [ ] appdaemon.yaml existuje v `/config/appdaemon.yaml`
- [ ] appdaemon.yaml obsahuje: latitude, longitude, elevation, time_zone
- [ ] appdaemon.yaml **NEOBSAHUJE**: pin_apps, total_threads, threads
- [ ] apps.yaml existuje v `/config/apps/apps.yaml` (NE v /config/)
- [ ] apps.yaml nemá duplicitní klíče
- [ ] Po restartu HA jsem ručně restartoval AppDaemon addon
- [ ] Log file se aktualizuje: `ls -lah /config/logs/appdaemon.log`
- [ ] V logu vidím: "Starting apps: ['trading_assistant']"
- [ ] V logu vidím: "Trading Assistant - Sprint 2"

---

## 🚀 Deployment Workflow

### Doporučený postup (lokální → HA):

**1. Připoj Samba share:**
```bash
# Finder → Go → Connect to Server
smb://homeassistant.local/addon_configs
```

**2. Udělej změny lokálně:**
```bash
cd /Users/jirimerz/Projects/TAv70/src/trading_assistant
# Edituj Python soubory...
```

**3. Deploy na HA:**

**Option A - Pomocí deploy skriptu (doporučeno):**
```bash
cd /Users/jirimerz/Projects/TAv70

# Nejdřív dry-run (simulace)
./deploy.sh --dry-run

# Skutečný deploy
./deploy.sh

# Deploy + automatický restart (pokud máš SSH přístup)
./deploy.sh --restart
```

**Option B - Manuální rsync:**
```bash
rsync -av --exclude='.DS_Store' \
  /Users/jirimerz/Projects/TAv70/src/trading_assistant/ \
  /Volumes/addon_configs/a0d7b954_appdaemon/apps/trading_assistant/
```

**4. Restartuj AppDaemon:**
- Settings → Add-ons → AppDaemon → RESTART
- Nebo SSH: `ha addons restart a0d7b954_appdaemon`

**5. Zkontroluj logy:**
```bash
tail -f /Volumes/addon_configs/a0d7b954_appdaemon/logs/appdaemon.log
```

### Deploy Script Features:

- ✅ **Dry-run mode** - simulace před skutečným deployem
- ✅ **Automatická kontrola** - ověří Samba mount a soubory
- ✅ **Bezpečnost** - excluduje `.DS_Store`, `__pycache__`, `.pyc`
- ✅ **Clear výstup** - barevný progress report
- ✅ **Automatický restart** - s `--restart` flaggem (pokud máš SSH)

---

## 🤖 Auto-Trading Features

### Signal Re-evaluation (2025-10-28)

**Problém:** Když byl signál vygenerován s vypnutým auto-tradingem, byl natrvalo odmítnut a nikdy se neexekuoval, i když jsi pak auto-trading zapnul.

**Řešení:** Implementován automatický re-evaluation mechanismus.

#### Jak to funguje:

1. **Signál odmítnut** když je auto-trading VYPNUTÝ:
```
[ORDER_EXECUTOR] ⏸️ Signal rejected - auto-trading DISABLED: DAX BUY
[ORDER_EXECUTOR] 💾 Signal saved for re-evaluation (1 total)
```

2. **Zapneš toggle** v Home Assistant:
```
[AUTO-TRADING] ✅ Trade execution ENABLED
[AUTO-TRADING] 🔄 Re-evaluating previously rejected signals...
[ORDER_EXECUTOR] 🔄 Re-evaluating 1 rejected signals...
```

3. **Automatická exekuce** platných signálů:
```
[ORDER_EXECUTOR] 🔄 Re-evaluating: DAX BUY
[ORDER_EXECUTOR] ✅ Re-evaluation SUCCESS: DAX
[ORDER_EXECUTOR] 📊 Re-evaluation complete:
  ✅ Executed: 1
  ❌ Failed: 0
  ⏰ Expired: 0
```

#### Limity:

- **Max stáří signálu:** 30 minut (starší se automaticky zahazují)
- **Max počet uložených signálů:** 10 (nejstarší se automaticky mažou)
- **Automatické čištění:** Po každém re-evaluation se seznam vymaže

#### Log Messages:

✅ **Úspěšná exekuce:**
- `💾 Signal saved for re-evaluation` - signál uložen
- `🔄 Re-evaluating X rejected signals` - začíná re-evaluation
- `✅ Re-evaluation SUCCESS` - signál úspěšně exekuován
- Notifikace v HA: "✅ X signálů exekuováno po zapnutí auto-tradingu"

❌ **Exekuce selhala:**
- `❌ Re-evaluation FAILED: [reason]` - signál nesplnil podmínky
- `⏰ Signal expired` - signál je starší než 30 minut

---

## 📝 Historie změn

**2025-10-28 (večer - fáze 3):** Signal re-evaluation mechanismus
- Implementován automatický re-evaluation odmítnutých signálů
- OrderExecutor nyní ukládá signály odmítnuté kvůli vypnutému auto-tradingu
- Při zapnutí auto-tradingu se automaticky pokusí exekuovat uložené signály
- Přidána validace stáří signálů (max 30 minut)
- Soubory: `simple_order_executor.py`, `main.py`

**2025-10-28 (večer - fáze 2):** Deployment workflow a race condition fix
- Vytvořen automatizovaný deploy skript (`deploy.sh`)
- Změněn workflow: opravy lokálně → deploy na HA (místo oprav přímo na HA)
- Opravena race condition: AttributeError při toggle_auto_trading
  - Listener registrace přesunuta za inicializaci `auto_trading_enabled`
  - main.py:266 - listener nyní registrován správně

**2025-10-28 (ráno):** Vytvořena dokumentace po úspěšném troubleshootingu
- Identifikována kritická chyba: apps.yaml v špatném umístění
- Odstraněny problematické konfigurace: pin_apps, total_threads
- Aplikace úspěšně běží s minimální konfigurací

---

## 🆘 Quick fix commands

```bash
# 1. Ověř umístění apps.yaml
test -f /config/apps/apps.yaml && echo "✅ OK" || echo "❌ CHYBA - apps.yaml není v /config/apps/"

# 2. Ověř appdaemon.yaml syntaxi
python3 -c "import yaml; yaml.safe_load(open('/config/appdaemon.yaml'))" && echo "✅ YAML OK"

# 3. Kontrola duplicit v apps.yaml
grep -n "^[a-z_]*:" /config/apps/apps.yaml | awk -F: '{print $2}' | sort | uniq -d

# 4. Restart AppDaemon
ha addons restart a0d7b954_appdaemon

# 5. Sleduj logy live
tail -f /config/logs/appdaemon.log
```

---

**💡 Tip:** Vytvoř si zálohu funkční konfigurace:
```bash
cp /config/appdaemon.yaml /config/appdaemon.yaml.backup
cp /config/apps/apps.yaml /config/apps/apps.yaml.backup
```
