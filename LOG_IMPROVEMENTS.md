# Vylepšení logů - doporučené opravy

**Datum:** 2025-01-03  
**Analýza:** Nový log po deploy oprav

---

## ✅ Co funguje dobře

1. **Timeout handling** - funguje správně:
   - `[BOOTSTRAP] Timeout waiting for GER40 (msgId=7) - response may arrive out-of-order`
   - `[BOOTSTRAP] Continuing - out-of-order handler will process response if it arrives`
   - Data se pak načetla správně přes out-of-order handler

2. **Account snapshot timeout** - také funguje:
   - `[ACCOUNT] Timeout waiting for PT_DEAL_LIST_RES (msgId=11) - response may arrive out-of-order`
   - `[ACCOUNT] Account snapshot will be updated when response arrives via recv_loop`
   - Data se načetla později

3. **Encoding problém** - opraven:
   - `[RISK STATUS] NO Account Monitor PnL data available` (bez emoji)

---

## 🔧 Doporučené vylepšení

### 1. RISK STATUS warning při startu

**Problém:**
```
2025-12-08 13:50:06.321342 INFO trading_assistant: [RISK STATUS] NO Account Monitor PnL data available - system not properly initialized!
```

**Příčina:**
- `log_status()` se volá dříve než Account Monitor má data
- Je to normální chování při startu, ale loguje se jako ERROR

**Oprava:**
- Rozlišit startup period (prvních 30 sekund) vs. skutečný problém
- Během startup: INFO log
- Po startup: WARNING log

**Soubor:** `src/trading_assistant/main.py` (řádky 929-936)

---

### 2. PT_TRADER_RES balance warning

**Problém:**
```
2025-12-08 13:50:16.558 WARNING AppDaemon: [BALANCE] Invalid balance from PT_TRADER_RES: balance_raw=0, trader_data keys=['ctidTraderAccountId']
```

**Příčina:**
- Demo API nevrátí balance v PT_TRADER_RES (známý problém)
- Systém to správně ignoruje a používá PT_DEAL_LIST_RES
- Warning je zbytečný a rušivý

**Oprava:**
- Změnit z WARNING na DEBUG
- Přidat vysvětlení, že je to známý problém demo API

**Soubor:** `src/trading_assistant/balance_tracker.py` (řádek 66)

---

### 3. Duplicitní callback warnings

**Problém:**
```
2025-12-08 13:49:45.355 WARNING AppDaemon: [ACCOUNT_MONITOR] Execution callback already registered
2025-12-08 13:49:45.359 WARNING AppDaemon: [ACCOUNT_MONITOR] ⚠️ Already started, skipping duplicate initialization
```

**Příčina:**
- `register_with_client()` se volá vícekrát
- Callbacky se správně nekontrolují duplicitně, ale loguje se warning

**Oprava:**
- Kontrolovat, zda callback už existuje před registrací
- Změnit "Already started" z WARNING na DEBUG

**Soubory:**
- `src/trading_assistant/account_state_monitor.py` (řádky 127-132, 812)

---

## 📊 Shrnutí oprav

| Problém | Závažnost | Oprava | Status |
|---------|-----------|--------|--------|
| RISK STATUS startup warning | 🟡 Střední | Rozlišit startup vs. problém | ✅ Opraveno |
| PT_TRADER_RES balance warning | 🟢 Nízká | Změnit na DEBUG | ✅ Opraveno |
| Duplicitní callback warnings | 🟢 Nízká | Kontrola před registrací | ✅ Opraveno |

---

## 📝 Soubory k nahrání

1. **`src/trading_assistant/main.py`** - startup detection pro RISK STATUS
2. **`src/trading_assistant/balance_tracker.py`** - změna warning na debug
3. **`src/trading_assistant/account_state_monitor.py`** - kontrola duplicitních callbacků

---

*Všechna doporučená vylepšení implementována*

