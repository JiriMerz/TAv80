# Home Assistant Startup Checklist

**Datum:** 2025-12-28  
**Problém:** HA se nechce rozběhnout

---

## 🔍 Co zkontrolovat přes Samba Share

### 1. AppDaemon Logy (priorita #1)

**Cesta:** `/Volumes/addon_configs/a0d7b954_appdaemon/logs/appdaemon.log`

**Co hledat:**
```bash
# Syntax errors
grep -i "syntax\|traceback\|error" appdaemon.log | tail -30

# Import errors
grep -i "import\|module" appdaemon.log | tail -30

# Trading Assistant startup
grep -i "trading_assistant\|initialize" appdaemon.log | tail -30
```

**Očekávané chyby po mé změně:**
- Pokud je problém s mou změnou, uvidíš chybu při volání `_is_within_trading_hours` nebo `log_status`

### 2. Home Assistant Logy

**Cesta:** `/Volumes/config/home-assistant.log`

**Co hledat:**
```bash
# Errors
tail -100 home-assistant.log | grep -i "error\|failed\|traceback"

# Startup errors
grep -i "startup\|initialization\|failed to load" home-assistant.log | tail -30
```

### 3. Configuration.yaml

**Cesta:** `/Volumes/config/configuration.yaml`

**Zkontrolovat:**
- Syntaxe YAML (bez duplicitních klíčů)
- AppDaemon konfigurace
- Žádné chyby v YAML

### 4. Apps.yaml

**Cesta:** `/Volumes/addon_configs/a0d7b954_appdaemon/apps/apps.yaml`

**Zkontrolovat:**
- Syntaxe YAML
- Duplicitní klíče (zejména `position_conflicts`)
- Trading Assistant konfigurace je kompletní

### 5. Trading Assistant Kód

**Cesta:** `/Volumes/addon_configs/a0d7b954_appdaemon/apps/trading_assistant/main.py`

**Zkontrolovat:**
- Že můj kód je nasazený (řádky 1135-1143)
- Syntaxe Python kódu

---

## 📋 Krok-za-krokem diagnostika

### Krok 1: Zkontroluj AppDaemon logy

1. Otevři Samba share
2. Jdi do: `addon_configs/a0d7b954_appdaemon/logs/`
3. Otevři `appdaemon.log`
4. Scrolluj na konec souboru (nejnovější logy)
5. Hledej chyby typu:
   - `SyntaxError`
   - `IndentationError`
   - `AttributeError`
   - `NameError`
   - `ImportError`

### Krok 2: Zkontroluj, jestli je můj kód nasazený

1. Jdi do: `addon_configs/a0d7b954_appdaemon/apps/trading_assistant/`
2. Otevři `main.py`
3. Najdi řádek ~1137 (kolem metody `log_status`)
4. Zkontroluj, jestli vidíš:
   ```python
   elif not in_hours:
       # Trhy jsou zavřené - jednotný status bez ohledu na množství dat
       status = "ANALYSIS_ONLY"
   ```

### Krok 3: Pokud není kód nasazený

**Znamená to, že moje změna ještě není na HA, takže problém není v mé změně!**

V tom případě zkontroluj:
- Jiné nedávné změny
- YAML syntaxe
- Import errors v logu

### Krok 4: Pokud je kód nasazený a jsou chyby

**Pošli mi konkrétní chybovou hlášku z logu.**

---

## 🚨 Rychlá oprava (pokud je problém s mou změnou)

**Vrátit původní kód:**

V `/Volumes/addon_configs/a0d7b954_appdaemon/apps/trading_assistant/main.py` na řádku ~1137 změň:

```python
# NOVÁ (moje změna) - VRÁTIT na PŮVODNÍ:
if up != "on":
    status = "DISCONNECTED"
elif not has_data:  # ← PŮVODNÍ POŘADÍ
    status = "WARMING_UP"
elif in_hours:
    status = "TRADING"
else:
    status = "ANALYSIS_ONLY"
```

Pak restartuj AppDaemon addon.

---

## 💡 Co může být problém (kromě mé změny)

1. **YAML syntaxe** - duplicitní klíče v `apps.yaml`
2. **Import errors** - chybějící moduly
3. **Permissions** - soubory nejsou čitelné
4. **Python syntaxe** - jiná chyba v kódu
5. **Database corruption** - `home-assistant_v2.db` problém
6. **Disk space** - plný disk


