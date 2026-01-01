# Analýza Breakoutů a Chart Patterns

## Současný stav breakoutů v systému

### 1. Structure Breaks (`_check_structure_breaks`)

**Soubor**: `src/trading_assistant/edges.py`

**Co detekuje**:
- **Swing High Break**: Cena prorazila swing high → bullish breakout
- **Swing Low Break**: Cena prorazila swing low → bearish breakout
- **Pivot Tests**: Cena je blízko pivot levelů (R2, R1, PIVOT, S1, S2)

**Jak to funguje**:
```python
# Swing breaks
if last_high and current_price > last_high:
    breaks.append({
        'type': 'SWING_HIGH_BREAK',
        'level': last_high,
        'direction': 'bullish'
    })

# Pivot tests (tolerance: 0.3 ATR)
for level_name, level_value in pivot_levels.items():
    if abs(current_price - level_value) <= tolerance:
        breaks.append({
            'type': f'PIVOT_{level_name}_TEST',
            'level': level_value,
            'direction': 'neutral'
        })
```

**Použití**:
- Structure breaks se používají jako confluence v `_evaluate_confluence_wide_stops()`
- Přidávají se k pattern count pro zvýšení confidence

### 2. Opening Range Breakout (ORB)

**Soubor**: `src/trading_assistant/microstructure_lite.py`

**Co detekuje**:
- **ORB LONG**: Breakout nad OR high (prvních 30 minut)
- **ORB SHORT**: Breakout pod OR low

**Jak to funguje**:
```python
# Check for breakout in subsequent bars
for bar in post_or_bars:
    if bar['high'] > or_high and not orb_triggered:
        orb_triggered = True
        orb_direction = 'LONG'
    elif bar['low'] < or_low and not orb_triggered:
        orb_triggered = True
        orb_direction = 'SHORT'
```

**Použití**:
- ORB signály se používají v microstructure analysis
- Bonus pro ORB alignment v signal quality

### 3. Pattern Detection

**Soubor**: `src/trading_assistant/edges.py` - `_detect_patterns()`

**Co detekuje**:
- **Pin Bars**: Reversal pattern
- **Momentum**: Silný pohyb (> threshold ATR)

**Limity**:
- Detekuje jen základní patterny
- Chybí pokročilejší chart patterns

---

## 11 Chart Patterns z forex.com - Co by se dalo použít

### 1. ✅ Head and Shoulders (H&S)
**Status**: NENÍ implementováno
**Použití**: Reversal pattern - velmi spolehlivý
**Implementace**: 
- Detekce 3 peaků (left shoulder, head, right shoulder)
- Head je nejvyšší, shoulders podobné výšky
- Neckline support
- Breakout pod neckline → bearish signal

### 2. ✅ Inverse Head and Shoulders
**Status**: NENÍ implementováno
**Použití**: Reversal pattern - bullish
**Implementace**: Opačný k H&S

### 3. ✅ Double Top (již implementováno!)
**Status**: ✅ IMPLEMENTOVÁNO v `pullback_detector.py`
**Použití**: Resistance level pro pullback entry

### 4. ✅ Double Bottom (již implementováno!)
**Status**: ✅ IMPLEMENTOVÁNO v `pullback_detector.py`
**Použití**: Support level pro pullback entry

### 5. ✅ Triangles (Ascending/Descending/Symmetrical)
**Status**: NENÍ implementováno
**Použití**: Continuation patterns - velmi užitečné pro breakouts
**Implementace**:
- **Ascending Triangle**: Higher lows, horizontal resistance → bullish breakout
- **Descending Triangle**: Lower highs, horizontal support → bearish breakout
- **Symmetrical Triangle**: Converging trendlines → breakout direction uncertain

### 6. ✅ Flags and Pennants
**Status**: NENÍ implementováno
**Použití**: Continuation patterns po silném pohybu
**Implementace**:
- **Flag**: Rectangular consolidation
- **Pennant**: Triangular consolidation
- Breakout ve směru původního trendu

### 7. ✅ Wedges (Rising/Falling)
**Status**: NENÍ implementováno
**Použití**: Reversal nebo continuation podle kontextu
**Implementace**:
- **Rising Wedge**: Higher highs, higher lows (converging) → bearish
- **Falling Wedge**: Lower highs, lower lows (converging) → bullish

### 8. ✅ Cup and Handle
**Status**: NENÍ implementováno
**Použití**: Bullish continuation pattern
**Implementace**:
- Cup shape (U-shaped bottom)
- Handle (small pullback)
- Breakout nad handle → bullish

### 9. ✅ Rectangle (Trading Range)
**Status**: ČÁSTEČNĚ (pivot levels)
**Použití**: Support/resistance range
**Implementace**: 
- Horizontal support a resistance
- Breakout z range → trend continuation

### 10. ✅ Channel (Upward/Downward)
**Status**: NENÍ implementováno
**Použití**: Trend continuation
**Implementace**:
- Parallel trendlines
- Breakout z channel → acceleration

### 11. ✅ Triple Top/Bottom
**Status**: NENÍ implementováno (máme double)
**Použití**: Silnější než double top/bottom
**Implementace**: Podobné jako double, ale 3 peaky/troughs

---

## Doporučení pro implementaci

### Priorita 1: Triangles (nejdůležitější pro breakouts)

**Proč**:
- ✅ Continuation patterns - ideální pro trend trading
- ✅ Jasné breakout levely
- ✅ Dobrá R:R ratio

**Implementace**:
```python
def _detect_triangles(bars, trend_direction):
    """
    Detekuje triangle patterny:
    - Ascending: Higher lows, horizontal resistance
    - Descending: Lower highs, horizontal support
    - Symmetrical: Converging trendlines
    """
    # Find swing highs and lows
    # Calculate trendlines
    # Check for convergence
    # Return breakout level
```

### Priorita 2: Flags and Pennants

**Proč**:
- ✅ Continuation patterns po silném pohybu
- ✅ Často následují po ORB
- ✅ Dobrá confluence s momentum

### Priorita 3: Head and Shoulders

**Proč**:
- ✅ Velmi spolehlivý reversal pattern
- ✅ Dobrá pro exit signály
- ✅ Může blokovat counter-trend vstupy

### Priorita 4: Wedges

**Proč**:
- ✅ Může signalizovat reversal
- ✅ Užitečné pro pullback trading

---

## Navržená implementace

### 1. Triangle Detector

**Soubor**: `src/trading_assistant/pattern_detector.py` (nový)

**Funkce**:
- Detekce ascending/descending/symmetrical triangles
- Výpočet breakout levelů
- Validace pattern (min swing count, convergence)

**Integrace**:
- Přidat do `_check_structure_breaks()` nebo nová metoda
- Použít jako confluence level pro breakouts

### 2. Flag/Pennant Detector

**Funkce**:
- Detekce po silném momentum move
- Identifikace consolidation
- Breakout ve směru trendu

### 3. H&S Detector

**Funkce**:
- Detekce reversal patternů
- Použití pro exit signály nebo blokování counter-trend

---

## Výhody implementace

1. **Více confluence levelů** → vyšší quality score
2. **Lepší breakout detekce** → méně false breakouts
3. **Pattern-based entries** → lepší R:R
4. **Reversal detection** → lepší exit timing

---

## Současné limity

1. **Chybí triangle detection** - nejdůležitější pro breakouts
2. **Chybí flag/pennant** - užitečné po ORB
3. **Chybí H&S** - důležité pro reversal detection
4. **Structure breaks jsou základní** - jen swing breaks, chybí pattern-based

---

## Závěr

**Doporučení**: Implementovat **Triangles** jako první - jsou nejdůležitější pro breakout trading a dobře se hodí k současnému pullback systému.

