# Proč se backtest liší od reality za prosinec 2025?

## 📊 Porovnání výsledků

| Metrika | Backtest | Realita | Rozdíl |
|---------|----------|---------|--------|
| **Obchodů** | 4 | 129 | **32x více v realitě!** |
| **Win Rate** | 75.0% | 48.8% | -26.2% |
| **PnL** | -1,200 CZK (-0.06%) | +254,355 CZK (+14.16%) | +255,555 CZK |
| **Profit Factor** | 0.93 | 1.06 | +0.13 |

## 🔍 Hlavní příčiny rozdílů

### 1. **ROZDÍLNÉ PARAMETRY (KRITICKÉ!)**

**Produkce (apps.yaml):**
- `min_signal_quality: 75`
- `min_confidence: 80`
- `min_rrr: 2.0`
- `strict_regime_filter: true` (default v edges.py)

**Backtest (backtest_config.yaml):**
- `min_signal_quality: 60` ⬇️ (relaxovanější)
- `min_confidence: 70` ⬇️ (relaxovanější)
- `min_rrr: 1.5` ⬇️ (relaxovanější)
- `strict_regime_filter: false` ⬇️ (vypnuto)

**Paradox:** Backtest má **relaxovanější parametry**, ale generuje **32x méně obchodů**!

### 2. **CHYBĚJÍCÍ FILTRY V BACKTESTU**

**Produkce má:**
- ✅ Trading hours check (DAX 09:00-15:30, NASDAQ 15:30-22:00)
- ✅ Active tickets check
- ✅ cTrader connection check
- ✅ Analysis status check

**Backtest má:**
- ❌ Trading hours check **CHYBÍ** → měl by generovat VÍCE signálů
- ❌ Active tickets check **CHYBÍ** → měl by generovat VÍCE signálů
- ❌ cTrader connection check (OK, není potřeba)

**Paradox:** Backtest nemá filtry, které by měly **blokovat** signály, ale generuje **méně** obchodů!

### 3. **MOŽNÉ PŘÍČINY PARADOXU**

#### A) **Produkce má vypnutý `strict_regime_filter`**

**Hypotéza:** Produkce možná má v `apps.yaml` explicitně `strict_regime_filter: false`, což není vidět v grep výsledcích (možná je v jiné sekci).

**Ověření:** Zkontrolovat `apps.yaml` pro `strict_regime_filter`.

#### B) **Backtest má chybu v implementaci**

**Hypotéza:** Backtest možná:
- Nepoužívá správně produkční logiku
- Má chybu v `_process_market_data`
- Neinicializuje komponenty správně
- Má problém s daty (Yahoo Finance vs. cTrader)

#### C) **Produkce generuje signály mimo `detect_signals`**

**Hypotéza:** Produkce možná:
- Generuje signály z jiných zdrojů (ORB, breakouts, atd.)
- Používá jiné komponenty pro detekci signálů
- Má manuální signály nebo jiné triggery

**Důkaz:** V logu vidím `[NASDAQ] ORB LONG triggered` - to jsou signály z jiného zdroje!

#### D) **Různé tržní podmínky**

**Hypotéza:** 
- Backtest data: 01.10.2025 - 23.12.2025 (6,121 barů)
- Reálné obchody: 01.12.2025 - 23.12.2025
- Možná prosinec měl jiné tržní podmínky než říjen-listopad

### 4. **DŮKAZ: ORB SIGNÁLY**

V produkčních logách vidím:
```
[NASDAQ] ORB LONG triggered at 2025-12-23 14:48:00+00:00, breakout above 25513.05
[DAX] ORB LONG triggered at 2025-12-23 08:27:00+00:00, breakout above 24345.47
```

**To znamená:** Produkce generuje signály z **ORB (Opening Range Breakout)** komponenty, která **není v backtestu**!

## 💡 ZÁVĚR

**Hlavní příčina rozdílů:**

1. **Backtest testuje pouze `EdgeDetector.detect_signals()`**
2. **Produkce používá více zdrojů signálů:**
   - `EdgeDetector.detect_signals()` (swing trading, pullbacks)
   - **ORB (Opening Range Breakout)** - **CHYBÍ V BACKTESTU!**
   - Možná další komponenty

3. **ORB signály tvoří velkou část produkčních obchodů** (pravděpodobně většinu z 129 obchodů)

## 🔧 DOPORUČENÍ

### 1. **Přidat ORB do backtestu**
```python
# V production_backtest.py přidat:
from trading_assistant.orb_detector import ORBDetector  # nebo jak se jmenuje

orb_detector = ORBDetector(config)
orb_signals = orb_detector.detect(bars, ...)
```

### 2. **Spustit backtest s produkčními parametry**
```bash
# Použít apps.yaml místo backtest_config.yaml
cp src/apps.yaml backtesting/config/backtest_config.yaml
python3 backtesting/production_backtest.py
```

### 3. **Přidat trading hours check do backtestu**
```python
# V _process_market_data přidat:
from trading_assistant.time_based_manager import TimeBasedSymbolManager

time_manager = TimeBasedSymbolManager()
active_symbol = time_manager.get_active_symbol(timestamp)
if symbol != active_symbol:
    return []  # Mimo trading hours
```

### 4. **Debug logování**
- Kolik signálů generuje `EdgeDetector`?
- Kolik signálů generuje `ORBDetector`?
- Kolik signálů je blokováno filtry?
- Porovnat s produkčními logy

### 5. **Analyzovat produkční logy**
- Kolik obchodů je z ORB vs. EdgeDetector?
- Jaké jsou parametry ORB v produkci?
- Jaké jsou skutečné parametry produkce (ne z apps.yaml, ale z runtime)?

## ⚠️ KRITICKÉ ZJIŠTĚNÍ

**Backtest testuje pouze část produkční logiky!**

- ✅ Testuje: `EdgeDetector` (swing trading, pullbacks)
- ❌ Netestuje: **ORB (Opening Range Breakout)** - **hlavní zdroj signálů v produkci!**

**To vysvětluje, proč:**
- Backtest: 4 obchody (pouze EdgeDetector)
- Produkce: 129 obchodů (EdgeDetector + ORB + další)

