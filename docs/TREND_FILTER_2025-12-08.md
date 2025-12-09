# Trend Filter Improvement

**Datum:** 2025-12-08  
**Účel:** Omezit protitrendové vstupy - povolit jen vstupy ve směru trendu (včetně pullbacků)

---

## Problém

Systém generoval signály i proti trendu, což mohlo vést k:
- Ztrátovým obchodům proti silnému trendu
- Vysokému riziku při protitrendových vstupech
- Neefektivnímu využití trendových příležitostí

---

## Jak systém identifikuje trend

### RegimeDetector
**Soubor**: `src/trading_assistant/regime.py`

Systém používá **ensemble voting** (2 z 3):
1. **ADX (Average Directional Index)**: Měří sílu trendu
2. **Linear Regression**: Určuje směr trendu (slope β a R²)
3. **Hurst Exponent** (volitelné): Měří trendovost časové řady

**Výstup**:
- `regime_type`: `TREND_UP`, `TREND_DOWN`, nebo `RANGE`
- `trend_direction`: `"UP"`, `"DOWN"`, nebo `"SIDEWAYS"`
- `confidence`: Jistota detekce (%)

---

## Řešení

### Rozšířená kontrola trend alignment
**Soubor**: `src/trading_assistant/edges.py` (řádky 474-517)

**Před**:
```python
# Kontrola jen pro TREND regime
if regime_type == 'TREND' and trend_direction:
    if bullish_count > bearish_count and trend_direction != 'UP':
        return None  # Reject
```

**Po**:
```python
# STRICT: Kontrola vždy, když je trend_direction definován
if trend_direction and trend_direction in ['UP', 'DOWN']:
    # Zakázat protitrendové vstupy
    if signal_wants_buy and trend_direction != 'UP':
        return None  # Reject counter-trend BUY
    elif signal_wants_sell and trend_direction != 'DOWN':
        return None  # Reject counter-trend SELL
    # Povolit vstupy ve směru trendu (včetně pullbacků)
```

---

## Jak to funguje

### 1. Identifikace trendu
- **RegimeDetector** analyzuje trh pomocí ADX, Linear Regression a Hurst Exponent
- Vrací `trend_direction`: `"UP"`, `"DOWN"`, nebo `"SIDEWAYS"`

### 2. Kontrola signálu
- **Pokud trend_direction = "UP"**:
  - ✅ Povoleno: BUY signály (ve směru trendu)
  - ✅ Povoleno: Pullback BUY signály (na pullback ve směru trendu)
  - ❌ Zakázáno: SELL signály (proti trendu)

- **Pokud trend_direction = "DOWN"**:
  - ✅ Povoleno: SELL signály (ve směru trendu)
  - ✅ Povoleno: Pullback SELL signály (na pullback ve směru trendu)
  - ❌ Zakázáno: BUY signály (proti trendu)

- **Pokud trend_direction = "SIDEWAYS" nebo None**:
  - ✅ Povoleno: Oba směry (range trading)

### 3. Pullback signály
- **PullbackDetector** generuje signály **jen ve směru trendu**:
  - Trend UP → Pullback BUY signály
  - Trend DOWN → Pullback SELL signály
- Pullback signály jsou automaticky ve směru trendu, takže projdou filtrem

---

## Výhody

✅ **Ochrana proti protitrendovým vstupům**: Žádné signály proti silnému trendu  
✅ **Lepší využití trendu**: Vstupy jen ve směru trendu  
✅ **Pullback vstupy**: Povoleny pullback vstupy ve směru trendu  
✅ **Range trading**: Povoleno obchodování v range režimu (SIDEWAYS)

---

## Konfigurace

V `apps.yaml`:
```yaml
edges:
  require_regime_alignment: true  # Musí být zapnuto
```

---

## Testing

1. **Trend UP**:
   - Ověř, že BUY signály procházejí
   - Ověř, že SELL signály jsou odmítnuty
   - Ověř, že pullback BUY signály procházejí

2. **Trend DOWN**:
   - Ověř, že SELL signály procházejí
   - Ověř, že BUY signály jsou odmítnuty
   - Ověř, že pullback SELL signály procházejí

3. **Range (SIDEWAYS)**:
   - Ověř, že oba směry jsou povoleny

---

## Soubory změněny

- `src/trading_assistant/edges.py`:
  - Rozšířena kontrola trend alignment (řádky 474-517)
  - Kontrola se provádí vždy, když je trend_direction definován
  - Zakázány protitrendové vstupy
  - Povoleny jen vstupy ve směru trendu (včetně pullbacků)

---

## Logování

Při odmítnutí protitrendového signálu se loguje:
```
Trend filter: BUY signal against trend (counter-trend blocked)
  - signal_direction: BUY
  - trend_direction: DOWN
  - reason: Only trend-following entries allowed (no counter-trend)
```

---

*Implementace dokončena - systém nyní blokuje protitrendové vstupy a povoluje jen vstupy ve směru trendu*

