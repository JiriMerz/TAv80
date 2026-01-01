# Systémová Vylepšení - Analýza Equity Curve
**Datum:** 2025-12-22  
**Založeno na:** Equity curve analýze za poslední měsíc

---

## 📊 Analýza Současného Výkonu

### Klíčové Metriky
- **Trades:** 125 (62 wins, 63 losses)
- **Winrate:** 49.60% (téměř 50/50)
- **Profit Factor:** 1.10 ⚠️ (KRITICKY NÍZKÝ)
- **Return:** 4%
- **Biggest Winner:** Kč 20,003.83
- **Biggest Loser:** Kč -16,545.49
- **Avg. P&L:** Kč 589.46

### Equity Curve Analýza
1. **Začátek:** 0 Kč
2. **Peak:** ~80,000 Kč (trade ~21) - rychlý nárůst
3. **Drawdown 1:** -20,000 Kč (trade ~60) - **100k drop z peaku**
4. **Drawdown 2:** -30,000 Kč (trade ~94) - další **50k drop**
5. **Finál:** ~60,000 Kč (trade 119)

### Identifikované Problémy

#### 🔴 KRITICKÉ
1. **Profit Factor 1.10** - Průměrný výherní obchod je jen o 10% větší než ztrátový
   - S winrate 50% = téměř breakeven trading
   - Pro ziskovost potřebujeme PF ≥ 1.5 (ideálně ≥ 2.0)

2. **Velké Drawdowny**
   - 100k+ drop z peaku (125% z finálního zisku)
   - Dva po sobě jdoucí hluboké drawdowny
   - Indikuje problémy s risk managementem a exit strategií

3. **Nedostatečná Asymetrie**
   - Biggest winner: 20k vs Biggest loser: -16.5k (poměr 1.21:1)
   - Pro PF 1.5+ potřebujeme poměr alespoň 2:1

#### 🟡 STŘEDNÍ
4. **Volatilní Equity Curve**
   - Velké výkyvy nahoru a dolů
   - Chybí stabilní růst
   - Indikuje nekonzistentní výkon

5. **Winrate téměř 50/50**
   - Není problém, ale s PF 1.10 to nestačí
   - Potřebujeme buď vyšší winrate (55%+) nebo vyšší PF (1.8+)

---

## 🎯 Navrhovaná Vylepšení

### PRIORITA 1: Zvýšení Profit Factor (KRITICKÉ)

#### 1.1 Zvýšit Minimum R:R Ratio
**Současný stav:** `min_rrr: 1.2` (v apps.yaml:339)
```yaml
edges:
  min_rrr: 1.2  # Příliš nízké!
```

**Doporučení:** Zvýšit na 2.0-2.5
```yaml
edges:
  min_rrr: 2.0  # Minimální R:R pro všechny signály
  standard_rrr: 2.5  # Cílový R:R
```

**Dopad:** 
- Eliminuje signály s malým profit potenciálem
- Zvýší průměrnou velikost výherních obchodů
- Očekávaný PF: 1.10 → 1.40-1.60

**Riziko:** 
- Snížení počtu signálů o ~30-40%
- Kompenzace: Lepší kvalita = vyšší winrate

---

#### 1.2 Zlepšit Exit Strategii - Dřívější Trailing Stops
**Současný stav:** Trailing aktivován při 50% profit (`trailing_activation_pct: 0.5`)

**Problém:** Příliš pozdní aktivace - obchody často vrací zisky před aktivací trailing stopu

**Doporučení:**
```yaml
trailing_stops:
  breakeven_activation_pct: 0.2  # ↓ z 0.3 - brzy breakeven
  trailing_activation_pct: 0.3   # ↓ z 0.5 - dřívější trailing
  trailing_distance_atr: 1.0     # ↓ z 1.5 - těsnější trailing
```

**Dopad:**
- Ochrání zisky dříve
- Sníží počet obchodů, které vrací zisky
- Očekávané zlepšení PF: +0.15-0.20

---

#### 1.3 Partial Exits - Zajištění Zisku
**Současný stav:** Žádné partial exits (celá pozice se uzavírá najednou)

**Doporučení:** Implementovat 50% partial exit při 1.5× risk
```yaml
partial_exits:
  enabled: true
  exit_1_trigger_rrr: 1.5  # Uzavřít 50% při 1.5× risk
  exit_1_percent: 0.5      # 50% pozice
  exit_2_trigger_rrr: 2.5  # Uzavřít další 25% při 2.5× risk
  exit_2_percent: 0.25     # 25% pozice
  # Zbývajících 25% běží do TP nebo trailing stop
```

**Dopad:**
- Zajištění zisku při dosažení R:R 1.5
- Zbývající část může běžet do většího TP
- Očekávané zlepšení: Ochrání zisky v drawdownových fázích
- Očekávaný PF: +0.10-0.15

---

### PRIORITA 2: Snížení Drawdownů

#### 2.1 Dynamic Risk Reduction po Drawdownu
**Doporučení:** Snížit risk per trade po drawdownu
```yaml
risk_adjustments:
  drawdown_reduction_enabled: true
  drawdown_threshold_pct: 0.10  # 10% drawdown
  risk_reduction_factor: 0.5    # Snížit risk na 50%
  recovery_threshold_pct: 0.05  # Zotavit při 5% drawdownu
```

**Logika:**
- Při drawdownu >10%: Risk per trade 0.5% → 0.25%
- Při zotavení <5%: Návrat k normálnímu risku
- Zabraňuje "revenge trading" během drawdownu

**Dopad:**
- Snížení velikosti drawdownů o ~30-40%
- Ochrana kapitálu během špatných období

---

#### 2.2 Daily Loss Limit - Aktivnější Monitoring
**Současný stav:** `daily_loss_limit: 0.05` (5%)

**Problém:** 5% je vysoké - při 2M balance = 100k Kč denní ztráta

**Doporučení:**
```yaml
daily_loss_limit: 0.02  # ↓ z 0.05 na 2%
daily_loss_soft_cap: 0.015  # 1.5% = zastavit nové vstupy
```

**Dopad:**
- Zastavení obchodování při větších denních ztrátách
- Zabraňuje "snowball effect" během špatných dní

---

#### 2.3 Selektivnější Signály - Vyšší Kvalita
**Současný stav:**
```yaml
edges:
  min_signal_quality: 60
  min_confidence: 70
  min_swing_quality: 25
```

**Problém:** Příliš nízké thresholdy = generují se i slabé signály

**Doporučení:**
```yaml
edges:
  min_signal_quality: 75  # ↑ z 60
  min_confidence: 80       # ↑ z 70
  min_swing_quality: 50    # ↑ z 25 (již jsme upravili pro pullback)
  min_bars_between_signals: 12  # ↑ z 6 (1 hodina na M5)
```

**Dopad:**
- Snížení počtu signálů o ~40%
- Zvýšení průměrné kvality
- Očekávaný winrate: 49.6% → 55-60%
- Očekávaný PF: +0.10-0.15

---

### PRIORITA 3: Lepší Position Management

#### 3.1 Dynamic Position Sizing podle Recent Performance
**Doporučení:** Upravovat velikost pozice podle recent win rate
```python
# Pseudo-kód
recent_trades = get_last_n_trades(20)
recent_winrate = calculate_winrate(recent_trades)

if recent_winrate > 0.65:
    position_multiplier = 1.2  # Zvýšit při dobré formě
elif recent_winrate < 0.40:
    position_multiplier = 0.7  # Snížit při špatné formě
else:
    position_multiplier = 1.0  # Normální
```

**Dopad:**
- Zvýšení velikosti pozice během "hot streaks"
- Snížení rizika během "cold streaks"
- Očekávané zlepšení: +5-10% celkového výnosu

---

#### 3.2 Vylepšit Pullback Detection (již implementováno)
**Status:** ✅ Již jsme implementovali pullback-only entries v trendech

**Doporučení:** Upravit pullback detekci pro lepší timing
```yaml
pullback:
  min_trend_strength: 30  # ↑ z 25 - jen silné trendy
  max_retracement_pct: 0.5  # ↓ z 0.618 - dřívější entry
  min_retracement_pct: 0.3   # ↑ z 0.236 - hlubší pullback
```

**Dopad:**
- Lepší vstupní ceny (lepší R:R)
- Vyšší pravděpodobnost úspěchu

---

## 📋 Implementační Plán

### Fáze 1: Okamžité Změny (Riziko: Nízké)
1. ✅ Zvýšit `min_rrr` na 2.0
2. ✅ Upravit trailing stops (dřívější aktivace)
3. ✅ Zvýšit quality thresholds

**Očekávaný dopad:** PF 1.10 → 1.35-1.50, Drawdowny -30%

### Fáze 2: Krátkodobé (Riziko: Střední)
4. Implementovat partial exits
5. Dynamic risk reduction po drawdownu
6. Daily loss soft cap

**Očekávaný dopad:** PF 1.35-1.50 → 1.60-1.80, Drawdowny -50%

### Fáze 3: Dlouhodobé (Riziko: Vysoké)
7. Dynamic position sizing
8. Vylepšit pullback detection parametry
9. Backtest všechny změny

---

## 🎯 Cílové Metriky (Po Implementaci)

### Short-term (Fáze 1)
- **Profit Factor:** 1.35-1.50 (z 1.10)
- **Winrate:** 52-55% (z 49.6%)
- **Max Drawdown:** -15k Kč (z -30k)
- **Trades/měsíc:** 80-90 (z 125) - méně, ale kvalitnější

### Long-term (Fáze 1+2)
- **Profit Factor:** 1.60-1.80
- **Winrate:** 55-60%
- **Max Drawdown:** -10k Kč
- **Return:** 6-8% měsíčně (z 4%)

---

## ⚠️ Rizika a Opatření

### Rizika
1. **Snížení počtu signálů** - Kompenzace vyšší kvalitou
2. **Delší doba bez obchodů** - Přijatelné pro stabilnější výkon
3. **Možné přeoptimalizování** - Testovat postupně, ne vše najednou

### Opatření
- **Backtest před implementací** - Otestovat změny na historických datech
- **Postupná implementace** - Jedna fáze najednou, monitorovat 1-2 týdny
- **Rollback plán** - Možnost vrátit změny pokud performance klesne

---

## 📊 Monitoring Metriky

### Denně sledovat:
- Počet signálů
- Průměrná kvalita signálů
- Realizovaný R:R (vs. plánovaný)
- Win rate
- Profit Factor

### Týdně hodnotit:
- Equity curve vývoj
- Max drawdown
- Average winner vs. average loser
- Partial exit efektivita

---

*Analýza dokončena: 2025-12-22*

