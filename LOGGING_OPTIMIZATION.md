# Optimalizace logování - Implementováno

## ✅ Implementováno (2025-12-24)

Systém nyní má optimalizované logování s konfigurovatelnými úrovněmi a throttlingem.

---

## Problém

- **Příliš mnoho logů**: 343 logů v main.py, 135 v edges.py
- **Zbytečné opakování**: Stejné rejecty se logovaly opakovaně
- **Chybějící detaily**: Při otevření pozice chyběly důležité informace pro fine-tuning

---

## Řešení

### 1. **LoggingConfig třída** (`src/trading_assistant/logging_config.py`)

- **Úrovně logování**: minimal, normal, verbose, debug
- **Throttling**: Omezuje opakující se zprávy
- **Kategorie**: rejection, validation, breakout, position, error

### 2. **Úrovně logování**

#### **MINIMAL** (nejméně logů)
- Pouze kritické události
- Otevření/zavření pozice
- Chyby

#### **NORMAL** (default - doporučeno)
- Důležité události
- Detailní log při otevření pozice
- Breakout validace
- **NELOGUJE**: Opakující se rejecty

#### **VERBOSE**
- Vše z NORMAL
- Rejecty signálů (s throttlingem)
- Validace

#### **DEBUG**
- Maximum verbosity
- Všechny detaily
- Bez throttlingu

---

## Detailní log při otevření pozice

Při otevření pozice se nyní loguje:

```
============================================================
📊 POSITION OPENED
============================================================
Symbol: NASDAQ
Direction: BUY
Entry: 25540.18
SL: 25500.18
TP: 25590.18
Size: 12.00 lots
Risk: 29,359 CZK

Signal Quality:
  Quality: 85.2
  Confidence: 75.0%
  R:R Ratio: 1.5

Market Context:
  Regime: TREND_UP
  Trend Direction: UP
  ADX: 28.5
  ATR: 11.4

Patterns:
  - SWING_HIGH_BREAK_RETEST
  - PULLBACK_FIB_38.2

Structure Break: SWING_HIGH_BREAK_RETEST

Microstructure:
  Liquidity: 0.65
  Volume Z-score: 1.8
  VWAP Distance: 0.15%
  ORB Triggered: true

Swing Context:
  Last High: 25513.05
  Last Low: 25450.00
  Swing Quality: 75.0

Decision Reasons:
  - Breakout retest confirmed
  - Pullback to Fibonacci 38.2%
  - High volume confirmation
  - Strong trend (ADX 28.5)
============================================================
```

---

## Konfigurace

### V `apps.yaml`:

```yaml
logging:
  log_level: normal  # minimal, normal, verbose, debug
  throttle_repeated_logs: true  # Throttle repeated messages
  throttle_window_seconds: 300  # Throttle window (5 minutes)
```

### Doporučené nastavení

**Produkce**: `normal` (default)
- Detailní logy při otevření pozice
- Méně zbytečných logů
- Throttling opakujících se zpráv

**Fine-tuning**: `verbose`
- Všechny rejecty (s throttlingem)
- Validace
- Více detailů

**Debugging**: `debug`
- Maximum verbosity
- Bez throttlingu
- Všechny detaily

---

## Co se loguje na každé úrovni

| Kategorie | MINIMAL | NORMAL | VERBOSE | DEBUG |
|-----------|---------|--------|---------|-------|
| Position opened | ✅ | ✅ | ✅ | ✅ |
| Position closed | ✅ | ✅ | ✅ | ✅ |
| Errors | ✅ | ✅ | ✅ | ✅ |
| Position details | ❌ | ✅ | ✅ | ✅ |
| Breakout validation | ❌ | ✅ | ✅ | ✅ |
| Signal rejections | ❌ | ❌ | ✅ (throttled) | ✅ |
| Validations | ❌ | ❌ | ❌ | ✅ |

---

## Throttling

### Jak to funguje

- Stejná zpráva se loguje **max 1x za 5 minut** (default)
- Snižuje zbytečné opakování
- Důležité zprávy (pozice, chyby) nejsou throttlovány

### Příklad

**Před**:
```
[FALSE_BREAKOUT] Blocking: Low volume (zscore: 0.5 < 1.0)
[FALSE_BREAKOUT] Blocking: Low volume (zscore: 0.5 < 1.0)
[FALSE_BREAKOUT] Blocking: Low volume (zscore: 0.5 < 1.0)
... (opakuje se každý bar)
```

**Po** (s throttlingem):
```
[FALSE_BREAKOUT] Blocking: Low volume (zscore: 0.5 < 1.0)
... (další log až za 5 minut)
```

---

## Informace pro fine-tuning

### Při otevření pozice se loguje:

1. **Signal Quality**
   - Quality score
   - Confidence
   - R:R ratio

2. **Market Context**
   - Regime (TREND_UP, TREND_DOWN, RANGE)
   - Trend direction
   - ADX (trend strength)
   - ATR (volatility)

3. **Patterns**
   - Všechny detekované patterny
   - Structure breaks

4. **Microstructure**
   - Liquidity score
   - Volume Z-score
   - VWAP distance
   - ORB triggered

5. **Swing Context**
   - Last swing high/low
   - Swing quality

6. **Decision Reasons**
   - Proč se pozice otevřela
   - Které podmínky byly splněny

---

## Výhody

1. **Méně zbytečných logů**: Throttling opakujících se zpráv
2. **Více informací**: Detailní log při otevření pozice
3. **Konfigurovatelné**: Úroveň logování podle potřeby
4. **Fine-tuning ready**: Všechny důležité informace pro analýzu

---

## Migrace

### Před:
```python
self.app.log(f"[FALSE_BREAKOUT] Blocking: ...")
```

### Po:
```python
if self.app and self.logging.should_log('breakout', message_key):
    self.app.log(f"[FALSE_BREAKOUT] Blocking: ...")
```

---

## Závěr

✅ **Systém nyní má optimalizované logování**

- Méně zbytečných logů
- Více informací pro fine-tuning
- Konfigurovatelné úrovně
- Throttling opakujících se zpráv
- Detailní log při otevření pozice

**Doporučení**: Použij `normal` pro produkci, `verbose` pro fine-tuning.

