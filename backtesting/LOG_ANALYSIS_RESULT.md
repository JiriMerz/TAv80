# Analýza logu - Proč se negenerovaly signály

**Datum analýzy:** 2025-12-26  
**Log soubor:** `/Users/jirimerz/Downloads/log.md`

## 🔍 Zjištění

### ✅ Co funguje:
1. **Bary se uzavírají** - vidím `[M5] Closing bar for US100` zprávy každých 5 minut
2. **Regime detekce probíhá** - vidím `[REGIME] Starting detection` a `FINAL REGIME STATE`
3. **Pivot výpočty probíhají** - vidím `[PIVOT] Starting pivot calculation`
4. **Swing detekce probíhá** - vidím `[SIMPLE_SWING] Detected X swings`

### ❌ Co chybí:
1. **ŽÁDNÉ `[PROCESS_DATA]` zprávy** - `process_market_data` se buď nevolá, nebo je blokováno před prvním logem
2. **ŽÁDNÉ `[SIGNAL_CHECK]` zprávy** - `detect_signals` se nevolá
3. **ŽÁDNÉ `[SIGNAL_DETECT]` zprávy** - Edge detection se nespouští
4. **ŽÁDNÉ `[BAR]` zprávy** typu "Calling process_market_data" nebo "Not enough bars"

## 🎯 Problém

**Regime, Pivot a Swing detekce probíhá, ale `process_market_data` se nevolá nebo je blokováno dříve než se dostane k logování.**

### Možné příčiny:

1. **`_on_bar_direct` se nevolá správně**
   - Bary se uzavírají (`[M5] Closing bar`), ale `_on_bar_direct` možná není voláno
   - Nebo je voláno, ale podmínka `bars_count >= self.analysis_min_bars` není splněna

2. **Regime/Pivot/Swing se volají z jiného místa**
   - Možná se volají přímo z nějakého timeru nebo jiné metody
   - Ne z `process_market_data`

3. **`process_market_data` je blokováno před prvním logem**
   - První log v `process_market_data` je na řádku 1284: `[PROCESS_DATA] {alias}: Entry`
   - Pokud se tato zpráva neobjevuje, znamená to, že metoda se buď nevolá, nebo je exception před tímto logem

## 📊 Analýza konkrétního případu (18:05:00)

```
2025-12-26 18:05:00.336 INFO AppDaemon: [M5] Closing bar for US100 at 17:00
2025-12-26 18:05:00.336 DEBUG AppDaemon: [M5] Sent closed bar to main.py
2025-12-26 18:05:00.349 DEBUG AppDaemon: [M5] New bar started for US100 at 17:05
2025-12-26 18:05:12.871 INFO AppDaemon: [REGIME] Starting detection with 354 bars
...
2025-12-26 18:05:14.943 INFO AppDaemon: [PIVOT] Starting pivot calculation with 354 bars
...
2025-12-26 18:05:19.109 INFO AppDaemon: [SIMPLE_SWING] Detected 9 swings from 354 bars
```

**Pozorování:**
- Bar se uzavřel v 18:05:00
- Regime detekce začala v 18:05:12 (12 sekund zpoždění)
- Pivot výpočet začal v 18:05:14 (14 sekund zpoždění)
- Swing detekce proběhla v 18:05:19 (19 sekund zpoždění)
- **ALE ŽÁDNÁ `[PROCESS_DATA]` zpráva!**

## 🔧 Doporučení pro opravu

### 1. Zkontrolovat, jestli se `_on_bar_direct` vůbec volá

Přidat log na začátek `_on_bar_direct`:

```python
def _on_bar_direct(self, raw_symbol: str, bar: Dict[str, Any], all_bars: List = None):
    """Upravená metoda pro příjem barů s historií - runs in main thread"""
    try:
        alias = self.symbol_alias.get(raw_symbol, raw_symbol)
        self.log(f"[BAR_DIRECT] {alias}: Received bar, all_bars={all_bars is not None}, bar_count={len(self.market_data.get(alias, []))}")
        # ... zbytek kódu
```

### 2. Zkontrolovat, jestli se `process_market_data` volá

Přidat log před voláním `process_market_data`:

```python
if bars_count >= self.analysis_min_bars:
    self.log(f"[BAR] {alias}: About to call process_market_data (bars: {bars_count} >= {self.analysis_min_bars})")
    self.process_market_data(alias)
else:
    self.log(f"[BAR] {alias}: Not enough bars ({bars_count}/{self.analysis_min_bars}), skipping process_market_data")
```

### 3. Zkontrolovat, jestli není exception v `process_market_data`

Přidat try-except na začátek `process_market_data`:

```python
def process_market_data(self, alias: str):
    """Process market data - COMPLETE FIXED VERSION"""
    try:
        from datetime import datetime, timedelta
        
        # Always log entry (removed throttling for visibility)
        bars_count = len(self.market_data.get(alias, []))
        self.log(f"[PROCESS_DATA] {alias}: Entry - {bars_count} bars available")
        # ... zbytek kódu
    except Exception as e:
        import traceback
        self.error(f"[PROCESS_DATA] {alias}: EXCEPTION at entry: {e}")
        self.error(f"[PROCESS_DATA] {alias}: Traceback: {traceback.format_exc()}")
        return
```

### 4. Zkontrolovat, jestli se regime/pivot/swing nevolají z jiného místa

Hledat všechny volání `regime_detector.detect`, `pivot_calc.calculate_pivots`, `swing_engine.detect_swings` v kódu a zjistit, odkud se volají.

## 📝 Závěr

**Hlavní problém:** `process_market_data` se buď nevolá, nebo je blokováno před prvním logem. Regime/Pivot/Swing detekce probíhá, ale ne z `process_market_data`, což znamená, že signály se negenerují, protože `detect_signals` se volá pouze z `process_market_data`.

**Akce:** Přidat diagnostické logy do `_on_bar_direct` a `process_market_data` pro zjištění, kde se to zastavuje.

