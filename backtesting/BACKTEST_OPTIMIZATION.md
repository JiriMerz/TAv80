# Optimalizace Backtestu - Jak získat více signálů

**Datum:** 2025-12-25  
**Problém:** Backtest generuje pouze 1 obchod na 10,000+ barech

## 🔍 Analýza problému

Aktuální konfigurace z `apps.yaml` má velmi přísné filtry:

### Přísné filtry v produkci:
1. **STRICT Regime Filter**: 
   - Regime musí být TREND_UP/DOWN
   - EMA34 musí souhlasit se směrem
   - Oba musí být ve stejném směru

2. **Vysoké kvalitní prahy:**
   - `min_signal_quality: 75` (velmi vysoká)
   - `min_confidence: 80` (velmi vysoká)
   - `min_rrr: 2.0` (vysoká)

3. **Další filtry:**
   - Microstructure checks (quality trading time)
   - Swing extreme checks
   - Pullback zone validation
   - Trading hours (v backtestu nejsou použity)

### Proč máme jen 1 obchod?
- Produkční konfigurace je navržena pro **kvalitu, ne kvantitu**
- Filtry jsou nastaveny pro **snižování falešných signálů** v reálném obchodování
- Pro backtesting potřebujeme **více signálů pro statistiku**

## 💡 Navržená řešení

### Option 1: Backtest-specifická konfigurace (Doporučeno)

Vytvořit `backtesting/config/backtest_config.yaml` s relaxovanějšími prahy:

```yaml
# Relaxované prahy pro backtesting
edges:
  min_signal_quality: 60  # ↓ Z 75 na 60
  min_confidence: 70      # ↓ Z 80 na 70
  min_rrr: 1.5           # ↓ Z 2.0 na 1.5
  min_bars_between_signals: 6  # ↓ Z 12 na 6 (30 min místo 1h)

regime:
  # Méně přísné prahy
  adx_threshold: 20      # ↓ Z 25 na 20
  regression_r2_threshold: 0.5  # ↓ Z 0.6 na 0.5

microstructure:
  min_liquidity_score: 0.05  # ↓ Z 0.1 na 0.05
  use_time_filter: false     # Vypnout time filtering pro backtest
```

**Výhody:**
- Produkční konfigurace zůstane beze změny
- Backtest bude generovat více signálů
- Můžeme testovat různé úrovně přísnosti

### Option 2: Vypnout STRICT regime filter pro backtest

Dočasně vypnout STRICT regime filter (regime TREND + EMA34 souhlas):

```python
# V edges.py - přidat flag
if backtest_mode:
    # Vypnout STRICT regime filter
    allow_signals_in_range = True
    require_ema34_confirmation = False
```

**Výhody:**
- Rychlá úprava
- Umožní signály i v RANGE režimu

**Nevýhody:**
- Změna v produkčním kódu (ne ideální)

### Option 3: Debug logování

Přidat detailní logování, proč jsou signály blokovány:

```python
# Logovat každé odmítnutí signálu s důvodem
- "Regime filter: TREND required but got RANGE"
- "EMA34 confirmation: DOWN but regime is UP"
- "Quality too low: 65 < 75"
- "Confidence too low: 72 < 80"
- "RRR too low: 1.8 < 2.0"
```

**Výhody:**
- Vidíme přesně, co blokuje signály
- Můžeme optimalizovat jednotlivé filtry

### Option 4: Postupná optimalizace

1. Nejdřív vypnout STRICT regime filter
2. Snížit kvalitní prahy o 10-20%
3. Snížit min_rrr na 1.5
4. Vypnout microstructure time filtering

**Výhody:**
- Systematický přístup
- Vidíme vliv každé změny

## 🎯 Doporučený postup

1. **Vytvořit backtest config** (`backtesting/config/backtest_config.yaml`)
2. **Načíst tento config místo apps.yaml** v backtest runneru
3. **Přidat debug logování** pro analýzu odmítnutých signálů
4. **Spustit backtest** a porovnat výsledky

## 📊 Očekávané výsledky

S relaxovanějšími prahy bychom měli vidět:
- **10-50 obchodů** místo 1
- **Lepší statistiku** (win rate, profit factor, atd.)
- **Možnost optimalizace** parametrů

## ⚠️ Poznámka

Relaxované prahy jsou pro **backtesting a analýzu**. 
Pro produkci zůstávají přísné prahy z `apps.yaml` - ty jsou navrženy pro kvalitu, ne kvantitu.

