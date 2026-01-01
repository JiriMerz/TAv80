# Soubory ke změně pro ruční deploy

## 📁 Pracovní adresář:
```
/Users/jirimerz/.cursor/worktrees/TAv80/jir/
```

---

## ✅ Soubory změněné v této session:

### 1. **ORB Signály vypnuty**
**Soubor:** `src/trading_assistant/main.py`
**Cesta:** `/Users/jirimerz/.cursor/worktrees/TAv80/jir/src/trading_assistant/main.py`

**Změna:** V metodě `handle_bar_data()` přidán early return na začátku - ORB signály jsou kompletně vypnuty.

---

### 2. **Pullback Detector - Reversal Patterns + Fibonacci fix**
**Soubor:** `src/trading_assistant/pullback_detector.py`
**Cesta:** `/Users/jirimerz/.cursor/worktrees/TAv80/jir/src/trading_assistant/pullback_detector.py`

**Změny:**
- ✅ Přidána metoda `_detect_reversal_candlestick()` - detekce reversal svíčkových formací
- ✅ Integrace reversal pattern detekce do `detect_pullback_opportunity()`
- ✅ Přidán reversal pattern bonus do `_calculate_pullback_quality()`
- ✅ Změna `min_retracement_pct` z 0.118 (11.8%) na 0.382 (38.2%) - best practices

---

### 3. **Konfigurace**
**Soubor:** `src/apps.yaml`
**Cesta:** `/Users/jirimerz/.cursor/worktrees/TAv80/jir/src/apps.yaml`

**Změny v sekci `pullback:`**
- ✅ `min_retracement_pct: 0.382` (změněno z 0.118)
- ✅ Přidány parametry pro reversal pattern detekci:
  - `reversal_pattern_bonus: 15`
  - `pin_bar_ratio: 0.3`
  - `min_wick_ratio: 0.6`

---

## 🚀 Deploy cesty:

Pokud deployuješ přes Samba share (jak bylo dříve):
- Zdroj: `/Users/jirimerz/.cursor/worktrees/TAv80/jir/src/trading_assistant/main.py`
- Cíl: `/Volumes/addon_configs/a0d7b954_appdaemon/apps/trading_assistant/main.py`

- Zdroj: `/Users/jirimerz/.cursor/worktrees/TAv80/jir/src/trading_assistant/pullback_detector.py`
- Cíl: `/Volumes/addon_configs/a0d7b954_appdaemon/apps/trading_assistant/pullback_detector.py`

- Zdroj: `/Users/jirimerz/.cursor/worktrees/TAv80/jir/src/apps.yaml`
- Cíl: `/Volumes/addon_configs/a0d7b954_appdaemon/appdaemon.yaml` (nebo tam, kde máš apps.yaml)

---

## 📋 Seznam souborů ke kopírování:

```
src/trading_assistant/main.py
src/trading_assistant/pullback_detector.py
src/apps.yaml
```

---

## 🔍 Ověření změn:

Po deploy můžeš zkontrolovat v logách:
- `[ORB_CHECK]` - ORB signály by se neměly generovat
- `[PULLBACK] ✅ Reversal pattern detected` - reversal pattern detekce
- `[PULLBACK_STATE] ✅ Valid pullback: X.X% (range 38.2%-61.8%)` - nový rozsah retracementu


