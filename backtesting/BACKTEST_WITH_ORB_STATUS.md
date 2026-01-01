# Status: Backtest s ORB a produkčními parametry

**Datum:** 2025-12-26

## ✅ Provedené úpravy

1. **Přidána ORB detekce do backtestu**
   - Metoda `_detect_orb_signals()` v `production_backtest.py`
   - Používá `microstructure.detect_opening_range()` jako v produkci
   - ORB signály jsou generovány jednou denně (jako v produkci)

2. **Parametry nastaveny na produkční hodnoty**
   - `min_signal_quality: 75` (z 60)
   - `min_confidence: 80` (z 70)
   - `min_rrr: 2.0` (z 1.5)
   - `strict_regime_filter: true` (z false)
   - `adx_threshold: 25` (z 20)
   - `regression_r2_threshold: 0.6` (z 0.5)

3. **Opravena chyba v edges.py**
   - `UnboundLocalError: rejection_reason` - inicializace před použitím

## ⚠️ Problém

**EdgeDetector generuje 0 signálů i když je regime TREND**

Příklad z logů:
```
[US100] Regime: TREND_UP, Trend: UP, Swing: UP, Signals: 0
[US100] Regime: TREND_DOWN, Trend: DOWN, Swing: DOWN, Signals: 0
```

### Možné příčiny:

1. **strict_regime_filter blokuje signály**
   - Vyžaduje, aby BOTH regime=TREND AND EMA34=trend (stejný směr)
   - Pokud EMA34 nesouhlasí s regime trendem, signály jsou blokovány

2. **Přísné parametry**
   - `min_signal_quality: 75` - velmi přísné
   - `min_confidence: 80` - velmi přísné
   - `min_rrr: 2.0` - vyžaduje 2:1 R:R

3. **ORB detekce nefunguje**
   - Warnings: "Unknown symbol for session start: GER40/US100"
   - Microstructure analyzer potřebuje symbol mapping (DAX/NASDAQ místo GER40/US100)

## 🔍 Co dál?

1. **Zkontrolovat produkční parametry**
   - Ověřit, zda produkce skutečně používá `strict_regime_filter: true`
   - Zkontrolovat runtime parametry (ne jen apps.yaml)

2. **Přidat více debug logování**
   - Proč EdgeDetector blokuje signály (důvody rejection)
   - EMA34 trend hodnoty
   - Signal quality a confidence hodnoty

3. **Opravit ORB detekci**
   - Přidat symbol mapping (GER40 -> DAX, US100 -> NASDAQ)
   - Opravit session start detection

4. **Porovnat s realitou**
   - Kolik obchodů produkce skutečně generuje z EdgeDetector vs. ORB?
   - Jaké jsou skutečné parametry v produkci?

## 📊 Aktuální výsledky

- **Obchodů:** 0
- **EdgeDetector signály:** 0 (i při TREND regime)
- **ORB signály:** 0 (pravděpodobně kvůli symbol mapping)

## 💡 Závěr

Backtest nyní používá produkční parametry a ORB detekci, ale generuje 0 obchodů. To naznačuje, že buď:
- Produkce používá jiné parametry než v apps.yaml
- Nebo produkce generuje většinu obchodů z ORB (které nefungují v backtestu kvůli symbol mapping)
- Nebo přísné filtry skutečně blokují většinu signálů

**Potřebujeme více informací o produkčním chování!**

