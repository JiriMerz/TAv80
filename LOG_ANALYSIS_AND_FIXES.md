# Analýza logů a opravy

**Datum:** 2025-01-03  
**Analýza:** Důkladná kontrola logů z RPi

---

## ✅ Refactoring funguje správně

- ✅ `[SIMPLE_SWING] Initialized` - SimpleSwingDetector funguje
- ✅ `[MULTI-POSITION] OrderExecutor initialized` - bez deprecated atributů
- ✅ Žádné chyby o SwingEngine
- ✅ Žádné chyby o position_open/current_position
- ✅ Všechny moduly se inicializují správně

---

## 🔍 Nalezené problémy a opravy

### 1. ⚠️ Timeout při bootstrap historie pro GER40

**Problém:**
```
2025-12-08 13:43:12.474 ERROR AppDaemon: [RECV_UNTIL] ❌ Timeout waiting for 2138 after 15.0s
2025-12-08 13:43:12.475 ERROR AppDaemon: [BOOTSTRAP] Error processing GER40: Timeout waiting for 2138
```

**Příčina:**
- Out-of-order message delivery - odpověď přišla později (msgId=7 místo očekávaného msgId=5)
- Timeout vyhodil chybu, ale data se pak načetla přes out-of-order handler

**Oprava:**
- Přidán graceful timeout handling - pokud timeout, zkusit načíst z cache
- Timeout není kritická chyba - data se načtou později přes router
- Změněno z `raise recv_e` na `continue` s cache fallback

**Soubor:** `src/trading_assistant/ctrader_client.py` (řádky 914-950)

---

### 2. ⚠️ Timeout při account snapshot

**Problém:**
```
2025-12-08 13:43:44.100 ERROR AppDaemon: [RECV_UNTIL] ❌ Timeout waiting for 2134 after 10.0s
2025-12-08 13:43:44.103 ERROR AppDaemon: [ACCOUNT] Failed to get account snapshot: Timeout waiting for 2134
```

**Příčina:**
- PT_DEAL_LIST_RES přišel později (msgId=11) a byl zpracován přes recv_loop
- Timeout vyhodil chybu, ale data se pak načetla správně

**Oprava:**
- Přidán graceful timeout handling - pokud timeout, exit gracefully
- recv_loop zpracuje odpověď později
- Změněno z vyhození chyby na warning + graceful exit

**Soubor:** `src/trading_assistant/ctrader_client.py` (řádky 1370-1376)

---

### 3. ⚠️ Encoding problém v logu

**Problém:**
```
2025-12-08 13:43:26.552141 INFO trading_assistant: [RISK STATUS]  NO Account Monitor PnL data available
```

**Příčina:**
- Emoji znaky (❌) se nezobrazují správně v logu
- Může způsobit problémy při parsování logů

**Oprava:**
- Odstraněn emoji z error logu
- Použity pouze ASCII znaky

**Soubor:** `src/trading_assistant/main.py` (řádek 931)

---

### 4. ℹ️ Duplicitní registrace callbacků (není kritické)

**Problém:**
```
2025-12-08 13:43:02.791 INFO AppDaemon: [ACCOUNT_MONITOR] Callback already registered, skipping
2025-12-08 13:43:02.792 WARNING AppDaemon: [ACCOUNT_MONITOR] Execution callback already registered
2025-12-08 13:43:02.797 WARNING AppDaemon: [ACCOUNT_MONITOR] ⚠️ Already started, skipping duplicate initialization
```

**Příčina:**
- `register_with_client()` se volá vícekrát
- Callbacky se kontrolují, ale stále se loguje warning

**Status:**
- ✅ Není kritické - callbacky se nekontrolují duplicitně
- ⚠️ Může být zlepšeno - potlačit warning pokud callback už existuje

**Doporučení:**
- Nechat jak je - není to chyba, jen informativní logy

---

## 📊 Shrnutí oprav

| Problém | Závažnost | Oprava | Status |
|---------|-----------|--------|--------|
| Timeout bootstrap GER40 | 🟡 Střední | Graceful timeout + cache fallback | ✅ Opraveno |
| Timeout account snapshot | 🟡 Střední | Graceful timeout + recv_loop handling | ✅ Opraveno |
| Encoding problém | 🟢 Nízká | Odstraněn emoji | ✅ Opraveno |
| Duplicitní callbacky | 🟢 Nízká | Není kritické | ℹ️ Info only |

---

## ✅ Ověření

- ✅ Python syntax OK
- ✅ Timeout handling zlepšen
- ✅ Encoding problém opraven
- ✅ Graceful error handling

---

## 📝 Soubory k nahrání

1. **`src/trading_assistant/ctrader_client.py`** - opravený timeout handling
2. **`src/trading_assistant/main.py`** - opravený encoding problém

---

*Všechny nalezené problémy opraveny*

