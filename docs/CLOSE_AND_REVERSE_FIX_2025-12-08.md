# Close and Reverse Fix

**Datum:** 2025-12-08  
**Problém:** Otevřel se obchod do protisměru a předchozí pozice se neuzavřela

---

## Problém

Když se vygeneroval signál do protisměru existující pozice:
- Kontrola opačné pozice probíhala jen v `risk_manager.open_positions`
- Pozice se ale přidává do `risk_manager` až po EXECUTION_EVENT (type 3)
- Pokud pozice ještě není v `risk_manager`, kontrola selže a otevře se nová pozice bez uzavření předchozí

**Příklad z logu:**
- 17:15:52 - Otevřena BUY pozice (NASDAQ, 10 lots)
- 17:16:25 - Zpracováván SELL signál (NASDAQ) - **bez logu o uzavírání**
- 17:17:07 - Synchronizace pozic z PT_TRADER_RES do risk_manager

---

## Řešení

### Rozšířená kontrola pozic
**Soubor**: `src/trading_assistant/main.py` (řádky 3611-3668)

**Před**:
```python
existing_positions = [p for p in self.risk_manager.open_positions if p.symbol == alias]
if existing_positions:
    # Kontrola opačné pozice...
```

**Po**:
```python
# Check for existing positions in BOTH risk_manager AND account_state_monitor
existing_positions = [p for p in self.risk_manager.open_positions if p.symbol == alias]

# Also check account_state_monitor for real positions from account
if self.account_state_monitor:
    with self.account_state_monitor._lock:
        account_positions = self.account_state_monitor._account_state.get('open_positions', [])
        # Convert account positions to match risk_manager format
        for acc_pos in account_positions:
            # Map symbol_id to alias
            # Check if position is for same symbol
            # Add to existing_positions if not already tracked
```

---

## Jak to funguje

1. **Kontrola risk_manager**: Standardní kontrola pozic v `risk_manager.open_positions`
2. **Kontrola account_state_monitor**: Dodatečná kontrola skutečných pozic z účtu
3. **Mapování symbol_id**: Symbol ID z účtu se mapuje na alias pomocí `symbol_id_overrides` a `symbol_alias`
4. **Vytvoření TempPosition**: Pokud pozice není v risk_manager, vytvoří se dočasný objekt pro kontrolu konfliktu
5. **Detekce opačné pozice**: Pokud je detekována opačná pozice, spustí se logika CLOSE_AND_REVERSE

---

## Výhody

✅ **Okamžitá detekce**: Pozice se detekují i před přidáním do risk_manager  
✅ **Spolehlivost**: Kontrola probíhá v obou zdrojích (risk_manager + account_state_monitor)  
✅ **Správné mapování**: Symbol ID se správně mapuje na alias  
✅ **Thread-safe**: Používá lock z account_state_monitor

---

## Testing

1. **Otevřít BUY pozici**
2. **Vygenerovat SELL signál** (před EXECUTION_EVENT)
3. **Ověřit**, že se pozice uzavře před otevřením nové
4. **Ověřit logy**: Měly by obsahovat "REVERSE signal detected" a "Closing"

---

## Soubory změněny

- `src/trading_assistant/main.py`:
  - Rozšířena kontrola pozic o account_state_monitor (řádky 3611-3668)
  - Mapování symbol_id na alias pomocí symbol_id_overrides
  - Vytvoření TempPosition pro pozice, které ještě nejsou v risk_manager

---

*Oprava dokončena - systém nyní správně detekuje opačné pozice i před přidáním do risk_manager*

