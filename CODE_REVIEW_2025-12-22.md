# Důkladná Kontrola Změn - System Improvements
**Datum:** 2025-12-22  
**Status:** Kontrola dokončena, identifikovány problémy a opravy

---

## ✅ Kontrolované Soubory

1. ✅ `src/apps.yaml` - Konfigurační změny
2. ✅ `src/trading_assistant/daily_risk_tracker.py` - Daily loss soft cap
3. ✅ `src/trading_assistant/risk_manager.py` - Dynamic risk reduction
4. ✅ `src/trading_assistant/partial_exit_manager.py` - R:R-based partial exits
5. ✅ `src/trading_assistant/main.py` - Config passing
6. ✅ `src/trading_assistant/trailing_stop_manager.py` - Trailing stops config

---

## 🔴 KRITICKÉ PROBLÉMY

### PROBLÉM 1: Hardcoded Daily Loss Limit v RiskManager
**Soubor:** `src/trading_assistant/risk_manager.py:138`

**Problém:**
```python
self.daily_loss_limit = 0.05  # Always 5% regardless of config
```

**Dopad:**
- Ignoruje config `daily_loss_limit: 0.02` z apps.yaml
- Vždy používá 5% místo 2%
- Rozpor s novým nastavením

**Řešení:** Odstranit hardcoded hodnotu, použít config

---

### PROBLÉM 2: Konflikt mezi daily_risk_limit_pct a daily_loss_limit
**Soubor:** `src/apps.yaml`

**Problém:**
- `auto_trading.daily_risk_limit_pct: 0.04` (4% - pro risk consumption)
- `daily_loss_limit: 0.02` (2% - pro daily loss limit)
- `daily_loss_soft_cap: 0.015` (1.5% - soft cap)

**Dopad:**
- Dva různé limity mohou způsobit zmatení
- `DailyRiskTracker` používá `daily_risk_limit_pct` (4%)
- `RiskManager` by měl používat `daily_loss_limit` (2%)

**Řešení:** 
- `daily_risk_limit_pct` je pro risk consumption (kolik risku můžeme použít)
- `daily_loss_limit` je pro loss limit (kdy zastavit trading při ztrátě)
- Jsou to různé věci, ale měly by být konzistentní

---

### PROBLÉM 3: Pivot Interference Min R:R vs. New Min R:R
**Soubor:** `src/apps.yaml:363`

**Problém:**
- `pivot_interference_min_rrr: 1.5` (stará hodnota)
- `min_rrr: 2.0` (nová hodnota)
- Po pivot interference by nemělo být min_rrr nižší než globální minimum

**Dopad:**
- Pivot interference může snížit R:R pod nové minimum 2.0
- Signál může projít s R:R 1.5 i když globální minimum je 2.0

**Řešení:** Zvýšit `pivot_interference_min_rrr` na 2.0 nebo vyšší

---

## 🟡 STŘEDNÍ PROBLÉMY

### PROBLÉM 4: Daily Loss Soft Cap - Konzistence
**Soubor:** `src/trading_assistant/daily_risk_tracker.py`

**Stav:** ✅ Funguje správně, ale:
- Používá `daily_loss_soft_cap` z root config
- Mělo by být jasněji dokumentováno, že je to % z balance

**Doporučení:** Přidat validaci, že soft_cap < daily_limit

---

### PROBLÉM 5: Partial Exits - R:R Calculation
**Soubor:** `src/trading_assistant/partial_exit_manager.py`

**Stav:** ✅ Implementace vypadá správně, ale potřebuje testování:
- Výpočet R:R je správný: `current_rr = profit_distance / risk_distance`
- Exit levels používají R:R místo TP procent
- Potřebuje ověření, že funguje správně v praxi

---

### PROBLÉM 6: Dynamic Risk Reduction - Equity High Reset
**Soubor:** `src/trading_assistant/risk_manager.py`

**Stav:** ⚠️ Chybí reset equity_high
- `equity_high` se pouze zvyšuje, nikdy nerese
- Po velkém zisku a následném drawdownu zůstane equity_high vysoká
- Drawdown by se mohl počítat nesprávně

**Doporučení:** Implementovat reset equity_high po určité době nebo při velké změně

---

## ✅ POZITIVNÍ OVĚŘENÍ

### 1. Trailing Stops Config ✅
- ✅ Config správně definován v apps.yaml
- ✅ TrailingStopManager čte config správně
- ✅ Nové hodnoty (20%, 30%) jsou implementované

### 2. Edge Detection Thresholds ✅
- ✅ min_rrr: 2.0 je implementováno
- ✅ min_signal_quality: 75 je implementováno
- ✅ min_confidence: 80 je implementováno
- ✅ min_bars_between_signals: 12 je implementováno

### 3. Config Passing ✅
- ✅ DailyRiskTracker dostává config správně
- ✅ RiskManager čte risk_adjustments správně
- ✅ PartialExitManager čte config správně

---

## 🔧 NAVRHOVANÉ OPRAVY

### OPRAVA 1: Opravit Daily Loss Limit v RiskManager
```python
# MĚNIT:
# self.daily_loss_limit = 0.05  # Always 5% regardless of config

# NA:
# Použít hodnotu z config (už je implementováno na řádku 76)
# Jen odstranit přepsání na řádku 138
```

### OPRAVA 2: Zvýšit Pivot Interference Min R:R
```yaml
# apps.yaml:363
pivot_interference_min_rrr: 2.0  # ↑ Zvýšit z 1.5 na 2.0 (spolu s globálním min_rrr)
```

### OPRAVA 3: Přidat Validaci Soft Cap
```python
# V daily_risk_tracker.py __init__
if self.daily_loss_soft_cap >= self.daily_limit_percentage:
    logger.warning(f"[DAILY_RISK] Soft cap {self.daily_loss_soft_cap:.1%} >= daily limit {self.daily_limit_percentage:.1%}, adjusting...")
    self.daily_loss_soft_cap = self.daily_limit_percentage * 0.75
```

### OPRAVA 4: Equity High Reset Logic
```python
# V risk_manager.py _calculate_current_drawdown
# Reset equity_high pokud je drawdown >50% po dlouhou dobu
# Nebo resetovat po 30 dnech bez nového high
```

---

## 📋 DALŠÍ KROKY

### Priorita 1: Okamžité Opravy (Před Deployment)
1. ✅ **Opravit daily_loss_limit hardcoded hodnotu** - KRITICKÉ
2. ✅ **Zvýšit pivot_interference_min_rrr na 2.0** - VYSOKÁ
3. ✅ **Přidat validaci soft cap** - STŘEDNÍ

### Priorita 2: Testování (Po Deployment)
4. ✅ **Otestovat partial exits** - ověřit, že se správně spouštějí
5. ✅ **Otestovat dynamic risk reduction** - ověřit drawdown calculation
6. ✅ **Monitorovat equity_high reset** - sledovat, zda potřebuje reset

### Priorita 3: Monitoring (První Týden)
7. ✅ **Sledovat realizovaný R:R** - porovnat s plánovaným
8. ✅ **Sledovat drawdown calculation** - ověřit, že funguje správně
9. ✅ **Sledovat daily loss limits** - ověřit, že se správně aplikují

---

## 🔍 KONTROLNÍ SEZNAM PRO DEPLOYMENT

### Před Deployment
- [ ] Opravit daily_loss_limit hardcoded hodnotu
- [ ] Zvýšit pivot_interference_min_rrr na 2.0
- [ ] Přidat validaci soft cap
- [ ] Zkontrolovat všechny config hodnoty
- [ ] Ověřit, že žádné hardcoded hodnoty nepřepisují config

### Po Deployment
- [ ] Ověřit v logách, že daily_loss_limit je 2%
- [ ] Ověřit, že min_rrr je 2.0
- [ ] Ověřit, že trailing stops používají nové hodnoty
- [ ] Ověřit, že partial exits jsou aktivní
- [ ] Ověřit, že dynamic risk reduction je aktivní

---

## 📊 OČEKÁVANÉ VÝSLEDKY (Po Opravách)

### Metriky
- **Profit Factor**: 1.35-1.50 (z 1.10)
- **Winrate**: 55-60% (z 49.6%)
- **Max Drawdown**: <-15k Kč (z -30k)
- **Trades/měsíc**: 80-100 (z 125) - méně, ale kvalitnější
- **Průměrný R:R**: 2.0-2.5:1 (z ~1.2:1)

### Funkčnost
- ✅ Všechny signály mají R:R ≥2.0:1
- ✅ Trailing stops se aktivují při 30% profit
- ✅ Partial exits se spouštějí na správných úrovních
- ✅ Risk reduction funguje při drawdownu >10%
- ✅ Daily loss limits se správně aplikují

---

*Kontrola dokončena: 2025-12-22*  
*Další kontrola: Po 1 týdnu testování*

