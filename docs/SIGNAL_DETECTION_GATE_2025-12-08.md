# Signal Detection Gate - Wait for System Ready

**Datum:** 2025-12-08  
**Účel:** Hledání signálů se spustí až když je cTrader Connected a Analysis Running

---

## Problém

Hledání signálů se spouštělo i když:
- cTrader nebyl připojen
- Analysis nebyla spuštěna

To mohlo vést k:
- Generování signálů bez dat z platformy
- Zbytečnému zpracování když systém není připraven
- Potenciálním chybám při zpracování neúplných dat

---

## Řešení

### Kontrola stavu před hledáním signálů
**Soubor**: `src/trading_assistant/main.py` (řádky 1225-1250)

**Přidáno**:
```python
# === KONTROLA STAVU SYSTÉMU PŘED HLEDÁNÍM SIGNÁLŮ ===
# Signály se hledají jen když je cTrader Connected a Analysis Running
ctrader_connected = self.get_state("binary_sensor.ctrader_connected")
analysis_status = self.get_state("sensor.trading_analysis_status")

if ctrader_connected != "on":
    # Skip signal detection - cTrader not connected
    return

if analysis_status != "RUNNING":
    # Skip signal detection - Analysis not running
    return

# === EDGE DETECTION pro signály ===
# (pokračuje jen pokud jsou oba stavy OK)
```

---

## Jak to funguje

1. **Kontrola cTrader stavu**:
   - Kontroluje `binary_sensor.ctrader_connected`
   - Musí být `"on"` (Connected)
   - Pokud není, hledání signálů se přeskočí

2. **Kontrola Analysis stavu**:
   - Kontroluje `sensor.trading_analysis_status`
   - Musí být `"RUNNING"`
   - Pokud není, hledání signálů se přeskočí

3. **Hledání signálů**:
   - Spustí se jen když jsou oba stavy OK
   - `edge.detect_signals()` se volá až po kontrole

---

## Výhody

✅ **Spolehlivost**: Signály se generují jen když je systém připraven  
✅ **Efektivita**: Žádné zbytečné zpracování když systém není připraven  
✅ **Bezpečnost**: Žádné signály bez dat z platformy  
✅ **Logování**: Throttled logy (max jednou za 5 minut) pro monitoring

---

## Logování

Při přeskočení hledání signálů se loguje (throttled):
```
[SIGNAL_DETECTION] ⏸️ Skipping signal detection for {alias} - cTrader not connected (status: {status})
[SIGNAL_DETECTION] ⏸️ Skipping signal detection for {alias} - Analysis not running (status: {status})
```

---

## Soubory změněny

- `src/trading_assistant/main.py`:
  - Přidána kontrola cTrader stavu před hledáním signálů (řádek 1227)
  - Přidána kontrola Analysis stavu před hledáním signálů (řádek 1237)
  - Throttled logování pro monitoring (max jednou za 5 minut)

---

*Oprava dokončena - hledání signálů se nyní spustí až když je cTrader Connected a Analysis Running*

