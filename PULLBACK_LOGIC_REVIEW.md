# Přehled logiky Pullback Detektoru

## Strategie: Swing Trading v jasném trendu, vstup na pullback dnech

---

## 1. ✅ ORB SIGNÁLY - VYPNUTY

**Soubor:** `src/trading_assistant/main.py`
- Metoda `handle_bar_data()` má na začátku `return` - ORB signály jsou kompletně vypnuty
- ✅ **OK** - Strategie je zaměřená pouze na pullbacky

---

## 2. 📊 PULLBACK DETECTOR - HLAVNÍ LOGIKA

### 2.1. Inicializace (`__init__`)

**Konfigurace:**
- `min_trend_strength`: 25 (ADX minimum pro silný trend) ✅
- `max_retracement_pct`: 0.618 (61.8% max Fibonacci) ✅
- `min_retracement_pct`: **0.118 (11.8% min)** ✅ **OPRAVENO**

**Soubor:** `src/trading_assistant/pullback_detector.py:44`
- ✅ Nastaveno na **0.118** (11.8%) - agresivnější Fibonacci hodnota pro swing trading

---

### 2.2. Hlavní metoda: `detect_pullback_opportunity()`

**Kroky detekce:**

1. **Kontrola dat:**
   - ✅ Minimálně 20 barů (100 minut na M5)
   
2. **Kontrola trendu:**
   - ✅ ADX >= 25 (silný trend)
   - ✅ Trend direction musí být UP nebo DOWN (ne SIDEWAYS)
   
3. **Analýza pullback stavu:**
   - Volá `_analyze_pullback_state()` - zjistí, zda probíhá pullback
   
4. **Hledání entry levelů:**
   - Volá `_find_pullback_entry_levels()` - najde možné vstupní levely
   
5. **Kvalita signálu:**
   - Vypočítá quality score (minimum 40% pro přijetí)
   
6. **Výstup:**
   - Vrátí pullback opportunity nebo None

---

### 2.3. Analýza pullback stavu: `_analyze_pullback_state()`

**Logika:**

1. **Najde swing extreme:**
   - Volá `_find_recent_swing_extreme()`
   - Pro UPTREND: hledá swing high (nejvyšší high v posledních 20 barech)
   - Pro DOWNTREND: hledá swing low (nejnižší low v posledních 20 barech)

2. **Vypočítá retracement:**
   - **UPTREND:** `retracement = (swing_high - current_price) / swing_high`
   - **DOWNTREND:** `retracement = (current_price - swing_low) / swing_low`

3. **Kontrola retracement rozsahu:**
   - ✅ Min: **11.8%** (0.118)
   - ✅ Max: 61.8% (0.618)
   - ✅ **OPRAVENO** - nyní používá 11.8% místo 23.6%

4. **Validace:**
   - ✅ Cena musí být v pullback zóně (pro UPTREND: cena < swing_high)

---

### 2.4. Hledání swing extreme: `_find_recent_swing_extreme()`

**Lookback:**
- ✅ 20 barů maximum (100 minut na M5 = 1.5 hodiny)
- ✅ Exkluzivní poslední 2 bary (aby to nebyl aktuální bar)

**Metoda:**
- Pro UPTREND: Najde maximum `high` v lookback rozsahu
- Pro DOWNTREND: Najde minimum `low` v lookback rozsahu

**Hodnocení:**
- ⚠️ **POZNÁMKA:** Pro swing trading by mohlo být užitečné delší lookback (např. 50-100 barů), ale 20 barů by mělo stačit pro detekci nedávných pullbacků

---

### 2.5. Entry levely: `_find_pullback_entry_levels()`

**Typy entry levelů:**

1. **Fibonacci retracement levels:**
   - 23.6%, 38.2%, 50.0%, 61.8%, 78.6%
   - ✅ Silné levely (golden ratio 61.8% má nejvyšší váhu)

2. **Strukturální levely (Pivot points):**
   - R2, R1, PIVOT, S1, S2
   - ✅ Pivot má nejvyšší váhu (85)

3. **VWAP levels:**
   - ✅ Dynamický level, váha 75

4. **EMA levels:**
   - EMA 21, EMA 50
   - ✅ Váha 70-75

5. **Double Top/Bottom patterns:**
   - ✅ Váha 80 (silný S/R level)

6. **HOD/LOD (Highest/Lowest of Day):**
   - ✅ Váha 75 (důležité intraday levely)

**Filtrace:**
- ✅ Vzdálenost minimálně 0.5 ATR od aktuální ceny
- ✅ Level musí být v pullback zóně (pro UPTREND: pod aktuální cenou)

---

### 2.6. Quality scoring: `_calculate_pullback_quality()`

**Faktory:**

1. **Base score:** 40
2. **Trend strength bonus:**
   - ADX > 35: +20
   - ADX > 25: +10
3. **Pullback depth bonus:**
   - 35-65%: +15 (ideální zóna)
   - 25-75%: +8
4. **Confluence bonus:**
   - 3+ levely: +15
   - 2 levely: +7.5
   - Extra bonus pro pivot confluence: +10 (2+ pivots) nebo +5 (1 pivot)
5. **Level strength bonus:**
   - Průměrná síla levelů > 75: +10
   - Průměrná síla levelů > 65: +5
6. **Microstructure bonus:**
   - Liquidity score > 0.6: +8
   - High quality time: +5
7. **Volume bonus:**
   - Klesající volume během pullbacku: +8 (dobré pro pokračování trendu)

**Minimum:** 40% pro přijetí signálu

---

### 2.7. Výběr nejlepšího entry levelu: `_select_best_entry_level()`

**Scoring:**

1. **Základní síla levelu** (strength)
2. **Vzdálenost od aktuální ceny:**
   - Ideální: 0.5% - 2% → +10
   - Příliš blízko (<0.5%): -5
   - Příliš daleko (>5%): -10
3. **Typ levelu:**
   - Fibonacci 61.8%: +15
   - VWAP: +10
   - Double Top/Bottom: +12
   - HOD/LOD: +8

**Výstup:** Level s nejvyšším skóre

---

## 3. 🔗 INTEGRACE DO SIGNAL DETECTION

**Soubor:** `src/trading_assistant/edges.py`

### 3.1. Volání pullback detektoru

**Priorita:** 1 (nejvyšší)

```python
pullback_opportunity = self.pullback_detector.detect_pullback_opportunity(
    bars, regime_state, swing_state, pivot_levels, microstructure_data
)
```

**Filtry před voláním:**
1. ✅ Strict filter: Regime musí být TREND + EMA34 musí souhlasit
2. ✅ Swing quality check: minimální kvalita swingů
3. ✅ Pullback detekce má prioritu před standardními pattern detekcemi

**Po nalezení pullback opportunity:**
- ✅ Vytvoří se pullback signal pomocí `_create_pullback_signal()`
- ✅ Stop loss: 2.0 ATR
- ✅ Take profit: 4.0 ATR (RRR 1:2 minimum)
- ✅ Signál se vrátí okamžitě (bez dalších pattern detekcí)

---

## 4. ✅ SHRNUTÍ - CO JE SPRÁVNĚ

1. ✅ **ORB signály vypnuty** - strategie je zaměřená pouze na pullbacky
2. ✅ **min_retracement_pct = 0.118 (11.8%)** - agresivnější Fibonacci hodnota
3. ✅ **Logika pullback detekce** - správně identifikuje pullbacky v trendu
4. ✅ **Entry levely** - hledá konfluenční levely (Fibonacci, pivots, VWAP, EMA)
5. ✅ **Quality scoring** - komplexní systém hodnocení kvality setupu
6. ✅ **Integrace** - pullback detekce má prioritu v signal detection
7. ✅ **Strict filters** - signály jen v silných trendech s konzistentním směrem

---

## 5. ⚠️ POZNÁMKY A DOPORUČENÍ

### 5.1. Lookback pro swing extreme
- Aktuálně: 20 barů (100 minut = 1.5 hodiny)
- Pro swing trading by mohlo být užitečné delší lookback (např. 50-100 barů = 4-8 hodin)
- **Doporučení:** Zvážit konfigurovatelný lookback parametr

### 5.2. Konfigurace v apps.yaml
- ✅ `min_retracement_pct: 0.118` - **OPRAVENO**
- ✅ Všechny ostatní parametry jsou správně nastavené

### 5.3. Kvalita vs. kvantita
- Quality threshold: 40% (poměrně nízký)
- Pro swing trading by mohlo být užitečné zvýšit na 50-60% pro lepší selektivitu
- **Aktuálně OK** - systém má další filtry (strict filter, swing quality)

---

## 6. 🎯 ZÁVĚR

**Logika pullback detektoru je správně implementovaná pro swing trading v trendu s vstupy na pullback dnech.**

✅ Všechny hlavní komponenty fungují správně:
- Detekce pullbacku v trendu
- Hledání konfluenčních entry levelů
- Quality scoring
- Integrace do signal detection pipeline

✅ **Hlavní oprava provedena:**
- `min_retracement_pct` změněno z 0.236 (23.6%) na 0.118 (11.8%)
- Konfigurace v `apps.yaml` aktualizována

✅ **ORB signály jsou vypnuté** - strategie je zaměřená pouze na pullbacky


