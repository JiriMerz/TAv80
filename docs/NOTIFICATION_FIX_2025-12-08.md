# Notification Fix - Send Only When Position Confirmed

**Datum:** 2025-12-08  
**Problém:** Notifikace se posílaly příliš brzy - při vytvoření signálu, ne při potvrzení otevření pozice. Notifikace přišla i hned po restartu, když ještě nebyly splněny podmínky Connected a Running.

---

## Problém

Notifikace se posílaly v těchto momentech:
1. **NEW** - při vytvoření signálu (příliš brzy - signál ještě není odeslán)
2. **TRIGGERED** - při aktivaci signálu (příliš brzy - order ještě není odeslán)
3. **EXPIRED** - při expiraci signálu (OK)

**Problém:** Notifikace se posílaly dřív, než byla pozice skutečně otevřena a potvrzena platformou.

---

## Řešení

### 1. Vypnutí předčasných notifikací
**Soubor**: `src/trading_assistant/main.py` (řádky 310-312)

**Před**:
```python
"notify_on_new": True,
"notify_on_trigger": True,
```

**Po**:
```python
"notify_on_new": False,  # Disabled - notify only when position is CONFIRMED opened
"notify_on_trigger": False,  # Disabled - notify only when position is CONFIRMED opened
```

### 2. Kontrola stavu na začátku process_market_data()
**Soubor**: `src/trading_assistant/main.py` (řádky 1044-1077)

**Přidáno**:
```python
def process_market_data(self, alias: str):
    # === KONTROLA STAVU SYSTÉMU PŘED ZPRACOVÁNÍM ===
    # Analýza se provádí jen když je cTrader Connected a Analysis Running
    ctrader_connected = self.get_state("binary_sensor.ctrader_connected")
    analysis_status = self.get_state("sensor.trading_analysis_status")
    
    if ctrader_connected != "on":
        return  # Skip analysis
    
    if analysis_status != "RUNNING":
        return  # Skip analysis
    
    # ... pokračuje analýza ...
```

### 3. Přidání notifikace při potvrzení otevření pozice
**Soubor**: `src/trading_assistant/simple_order_executor.py`

**Nové**:
- Přidán parametr `hass_instance` do `__init__`
- Přidána metoda `_send_position_opened_notification()`
- Volání notifikace v `_handle_execution_event()` při `execution_type == 3` (ORDER_FILLED)

**Kód**:
```python
def _handle_execution_event(self, execution_data: Dict):
    execution_type = execution_data.get('executionType', 0)
    
    if execution_type == 3:  # ORDER_FILLED
        # ... position confirmed logic ...
        
        # Send notification to mobile - position is CONFIRMED opened by platform
        self._send_position_opened_notification(symbol, position_data)
```

---

## Jak to funguje

1. **Vytvoření signálu**: Žádná notifikace (notify_on_new=False)
2. **Trigger signálu**: Žádná notifikace (notify_on_trigger=False)
3. **Odeslání orderu**: Žádná notifikace (order je jen odeslán, ještě není potvrzen)
4. **EXECUTION_EVENT type 3**: ✅ **Notifikace se posílá** - pozice je PROKAZATELNĚ otevřena platformou

---

## Výhody

✅ **Spolehlivost**: Notifikace se posílá až když je pozice skutečně otevřena  
✅ **Přesnost**: Uživatel dostane notifikaci jen pro skutečně otevřené pozice  
✅ **Žádné falešné poplachy**: Žádné notifikace pro signály, které se neotevřely

---

## Obsah notifikace

**Title**: `✅ Pozice otevřena: {symbol} {direction}`

**Message**:
```
Symbol: {symbol}
Směr: {direction}
Velikost: {position_size} lots
Entry: {entry_price}
SL: {stop_loss}
TP: {take_profit}
Riziko: {risk_amount} CZK
```

---

## Soubory změněny

- `src/trading_assistant/simple_order_executor.py`:
  - Přidán parametr `hass_instance` do `__init__`
  - Přidána metoda `_send_position_opened_notification()`
  - Volání notifikace při EXECUTION_EVENT type 3

- `src/trading_assistant/main.py`:
  - Vypnuty notifikace v signal_manager (notify_on_new=False, notify_on_trigger=False)
  - Předán `hass_instance=self` do SimpleOrderExecutor
  - **Přidána kontrola stavu na začátku `process_market_data()`** - analýza se nespustí, pokud není cTrader Connected a Analysis Running
  - Aktualizován komentář v `_publish_single_trade_ticket` - signal_manager má notify_on_new=False

---

*Oprava dokončena - notifikace se nyní posílají až když je pozice prokazatelně otevřena platformou*

