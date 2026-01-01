# Analýza: Proč se neotevřel obchod

**Datum:** 2025-12-17 19:35  
**Signál:** NASDAQ_183510_656050 BUY(STOP) @ 24760.45  
**Status:** ❌ Obchod se neotevřel

---

## 📊 Logy z analýzy

### Co se stalo:

1. **19:35:08** - Position sizing byl vypočítán:
   ```
   [RISK] === POSITION CALCULATION FOR NASDAQ ===
   [RISK] Size: 13.20 lots
   [RISK] SL: 15000 pips = 39600 CZK (1.97%)
   [RISK] TP: 6000 pips = 15840 CZK
   ```

2. **19:35:14** - Signál byl vytvořen v signal_manager:
   ```
   New signal: NASDAQ_183510_656050 BUY(STOP) @ 24760.45
   ```

3. **Chybí logy:**
   - ❌ Chybí log "[AUTO-TRADING] 🔍 Signal generated for..."
   - ❌ Chybí log "[AUTO-TRADING] 🔍 Checking signal:..."
   - ❌ Chybí jakékoliv logy z `_try_auto_execute_signal()`

---

## 🔍 Analýza problému

### Možné příčiny:

1. **`position` je `None` nebo `False`**
   - `_try_auto_execute_signal()` se volá pouze pokud `if position:` je True (řádek 1487)
   - Position sizing byl vypočítán, ale možná `calculate_position_size()` vrátil `None`

2. **Výjimka před voláním `_try_auto_execute_signal()`**
   - Možná výjimka v `_publish_single_trade_ticket()` nebo v signal tracking

3. **`auto_trading_enabled` je `False`**
   - Ale pak by měl být log "[AUTO-TRADING] 🔍 Signal generated for..." s `auto_trading_enabled=False`

4. **Signál je typu STOP a čeká se na trigger**
   - Ale `_try_auto_execute_signal()` by se měl zavolat i pro STOP signály

---

## ✅ Přidané debug logy

Přidán debug log na řádku 1502:
```python
self.log(f"[AUTO-TRADING] 🔍 Signal generated for {alias}: auto_trading_enabled={self.auto_trading_enabled}, order_executor={'exists' if self.order_executor else 'None'}")
```

Tento log by měl být vidět při dalším signálu, pokud se kód dostane až sem.

---

## 🔧 Doporučené kroky

1. **Zkontrolovat, proč `position` může být `None`**
   - Přidat log před `if position:` (řádek 1487)
   - Zkontrolovat, co vrací `calculate_position_size()`

2. **Zkontrolovat, jestli není výjimka**
   - Přidat try-except kolem celého bloku (řádky 1487-1524)

3. **Zkontrolovat stav auto-trading**
   - Přidat log na začátek `process_market_data()` s `auto_trading_enabled`

4. **Zkontrolovat, jestli se `process_market_data()` volá**
   - Přidat log na začátek `process_market_data()`

---

## 📝 Související soubory

- `src/trading_assistant/main.py` - `process_market_data()` (řádek 1169)
- `src/trading_assistant/main.py` - `_try_auto_execute_signal()` (řádek 4163)
- `src/trading_assistant/risk_manager.py` - `calculate_position_size()`

---

*Analýza dokončena: 2025-12-17*








