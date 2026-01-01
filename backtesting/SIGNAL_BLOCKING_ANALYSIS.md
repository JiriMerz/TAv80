# Analýza: Kde a proč se blokují signály

**Datum:** 2025-12-26

## 📊 Hlavní zjištění

### 1. **STRICT REGIME FILTER (nejčastější blokování - ~80%)**

**Problém:**
- EMA34 trend často vrací `None` → blokuje všechny signály
- I když regime=TREND, pokud EMA34=None, signály jsou blokovány
- I když regime=TREND a EMA34=trend, pokud nesouhlasí směry, signály jsou blokovány

**Příklady z logů:**
```
STRICT FILTER: regime_is_trend=True, ema34_has_trend=None
→ ❌ Blokováno: EMA34 does not show trend

STRICT FILTER: regime_is_trend=True, ema34_has_trend=True, directions_match=False
→ ❌ Blokováno: Directions don't match (regime: UP, EMA34: DOWN)
```

**Řešení:**
- Zkontrolovat, proč EMA34 vrací None (nedostatek dat? chyba výpočtu?)
- Možná uvolnit strict filter pro backtest (nebo zkontrolovat, zda produkce skutečně používá strict_regime_filter: true)

### 2. **PULLBACK DETECTOR (druhý nejčastější blokování - ~15%)**

**Problém:**
- Pullback detector má přísné podmínky pro "pullback zónu"
- Blokuje signály, pokud je cena "too far" od EMA34
- Příklad: "Price 24954.7 too far above EMA34 24895.1 (uptrend)"

**Příklady z logů:**
```
[PULLBACK] Rejecting: Price 24954.7 too far above EMA34 24895.1 (uptrend)
[PULLBACK] Rejecting: Price 24839.9 too far below EMA34 24910.4 (downtrend)
```

**Řešení:**
- Zkontrolovat tolerance pro "too far" v pullback detectoru
- Možná uvolnit podmínky pro backtest

### 3. **QUALITY/CONFIDENCE THRESHOLDS (~5%)**

**Problém:**
- `min_confidence: 80%` je velmi přísný
- Signály s confidence 70% jsou blokovány
- Příklad z logů: "Confidence: 70.0%" → blokováno (min: 80%)

**Příklady z logů:**
```
ATR: 12.1, Regime: TREND_UP, Quality: 100
Confidence: 70.0%
→ ❌ Blokováno: Confidence 70% < 80%
```

**Řešení:**
- Zkontrolovat, zda produkce skutečně používá min_confidence: 80
- Možná uvolnit pro backtest

### 4. **ADX = 0.0 (podezřelé)**

**Problém:**
- ADX je často 0.0, což je podezřelé
- ADX by neměl být 0, pokud jsou data
- Možná chyba v RegimeDetector

**Řešení:**
- Zkontrolovat výpočet ADX v RegimeDetector
- Možná problém s daty (Yahoo Finance vs. cTrader)

## 📈 Statistiky blokování

Z analýzy logů:

1. **STRICT REGIME FILTER:** ~80% blokování
   - EMA34=None: ~60%
   - Directions don't match: ~20%

2. **PULLBACK DETECTOR:** ~15% blokování
   - Price too far from EMA34: ~15%

3. **QUALITY/CONFIDENCE:** ~5% blokování
   - Confidence < 80%: ~5%

## 💡 Doporučení

### 1. **Okamžité opravy**

**A) EMA34 výpočet:**
- Zkontrolovat, proč vrací None
- Možná nedostatek dat (potřebuje 34 barů)
- Možná chyba v `_calculate_ema()`

**B) ADX výpočet:**
- Zkontrolovat, proč je 0.0
- Možná problém s daty nebo výpočtem

### 2. **Pro backtest**

**A) Uvolnit strict_regime_filter:**
```yaml
strict_regime_filter: false  # Pro backtest
```

**B) Uvolnit pullback podmínky:**
- Zkontrolovat tolerance v pullback detectoru

**C) Uvolnit confidence threshold:**
```yaml
min_confidence: 70  # Místo 80 pro backtest
```

### 3. **Pro produkci**

**A) Zkontrolovat skutečné parametry:**
- Ověřit, zda produkce skutečně používá `strict_regime_filter: true`
- Zkontrolovat runtime parametry (ne jen apps.yaml)

**B) Zkontrolovat EMA34:**
- Proč v produkci funguje, ale v backtestu ne?
- Možná produkce má více dat nebo jiný výpočet

## 🔍 Další kroky

1. **Opravit EMA34 výpočet** - proč vrací None?
2. **Opravit ADX výpočet** - proč je 0.0?
3. **Přidat více debug logování** - zejména pro pullback detector
4. **Porovnat s produkcí** - jaké parametry skutečně používá?

## 📊 Závěr

**Hlavní problém:** STRICT REGIME FILTER blokuje ~80% signálů, protože:
- EMA34 často vrací None (nedostatek dat nebo chyba)
- I když EMA34 funguje, často nesouhlasí s regime trendem

**Druhý problém:** PULLBACK DETECTOR blokuje ~15% signálů kvůli přísným podmínkám.

**Třetí problém:** CONFIDENCE THRESHOLD 80% je velmi přísný.

**Doporučení:** Pro backtest uvolnit parametry nebo opravit EMA34/ADX výpočty.

