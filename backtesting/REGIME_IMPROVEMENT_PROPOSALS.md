# Návrhy na vylepšení regime detection pro intradenní swing trading

**Cíl:** Lepší interpretace trhu pro generování spolehlivých signálů v intradenních swing obchodech  
**Strategie:** Swing trading pouze v trendech

---

## 🎯 Aktuální problémy:

### **1. Time Window Mismatch:**
- Systém analyzuje **celkové okno** (~180 barů = ~15 hodin)
- Pro intradenní swing trading je důležitější **recentní trend** (poslední 2-4 hodiny)
- Systém může detekovat TREND_DOWN i když recentní trend je UP (recovery)

### **2. Regression Weighting:**
- Lineární regression dává **stejnou váhu** všem barům
- Pro swing trading by recentní bary měly mít **větší váhu**
- Starší data (např. 10 hodin zpět) by měla mít menší váhu

### **3. Trend Change Detection:**
- Systém nedetekuje **změny trendu** (trend reversals)
- Pokud recentní trend (20-30 barů) je UP, ale celkový je DOWN, měli bychom použít recentní

---

## 💡 Návrhy na vylepšení:

### **1. Multi-Timeframe Regime Detection** ⭐⭐⭐ (Vysoká priorita)

**Nápad:** Použít **dvouúrovňovou** regime detection:
- **Primary Regime:** Kratší okno (50-100 barů = 4-8 hodin) pro recentní trend
- **Secondary Regime:** Delší okno (180 barů) pro kontext

**Implementace:**
```python
# Primary regime (recentní trend - pro trading rozhodnutí)
primary_regime = detect_regime(bars[-100:])  # Posledních 100 barů

# Secondary regime (celkový kontext)
secondary_regime = detect_regime(bars[-180:])  # Celkové okno

# Pro trading použít primary, pokud je jasný trend
if primary_regime.confidence > 70:
    trading_regime = primary_regime
else:
    # Fallback na secondary pokud primary není jasný
    trading_regime = secondary_regime
```

**Výhody:**
- Lepší detekce recentních trendů
- Zachytí trend reversals rychleji
- Stále máme kontext z delšího okna

---

### **2. Exponential Weighted Regression** ⭐⭐ (Střední priorita)

**Nápad:** Použít **exponenciální vážení** pro regression - recentní bary mají větší váhu

**Implementace:**
```python
def _calculate_weighted_regression(self, closes: List[float]) -> Tuple[float, float, str]:
    """Exponentiálně vážená regression"""
    y = closes[-self.regression_period:]
    n = len(y)
    x = list(range(n))
    
    # Exponenciální váhy (recentní bary mají větší váhu)
    alpha = 0.95  # Decay factor
    weights = [alpha ** (n - 1 - i) for i in range(n)]  # Nejnovější má váhu 1.0
    
    # Weighted means
    x_mean = sum(x[i] * weights[i] for i in range(n)) / sum(weights)
    y_mean = sum(y[i] * weights[i] for i in range(n)) / sum(weights)
    
    # Weighted slope
    numerator = sum(weights[i] * (x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
    denominator = sum(weights[i] * (x[i] - x_mean) ** 2 for i in range(n))
    slope = numerator / denominator if denominator != 0 else 0
    
    # ... zbytek výpočtu
```

**Výhody:**
- Recentní bary mají větší vliv na trend
- Lepší pro swing trading kde je důležitý recentní trend
- Stále používá všechna data (ne jen posledních X barů)

---

### **3. Trend Change Detection** ⭐⭐⭐ (Vysoká priorita)

**Nápad:** Detekovat **změny trendu** - pokud recentní trend se liší od celkového

**Implementace:**
```python
def detect_trend_change(self, bars: List[Dict]) -> Optional[str]:
    """Detekovat změnu trendu"""
    if len(bars) < 60:
        return None
    
    # Krátkodobý trend (posledních 30 barů = 2.5 hodiny)
    short_trend = self._calculate_regression(bars[-30:])
    
    # Střednědobý trend (posledních 60 barů = 5 hodin)
    medium_trend = self._calculate_regression(bars[-60:])
    
    # Pokud se liší → trend change
    if short_trend.vote == "TREND_UP" and medium_trend.vote == "TREND_DOWN":
        return "REVERSAL_UP"  # Downtrend se mění na uptrend
    elif short_trend.vote == "TREND_DOWN" and medium_trend.vote == "TREND_UP":
        return "REVERSAL_DOWN"  # Uptrend se mění na downtrend
    
    return None
```

**Výhody:**
- Rychlejší detekce trend reversals
- Můžeme použít recentní trend pro trading i když celkový je opačný
- Lepší pro swing trading (zachytíme recovery dříve)

---

### **4. EMA34 Trend as Primary Indicator** ⭐⭐ (Střední priorita)

**Nápad:** Použít **EMA34 trend** jako primární indikátor pro recentní trend (už implementováno, ale můžeme zvýšit váhu)

**Aktuální stav:**
- EMA34 se už používá pro strict regime filter
- Ale regime detection stále používá regression + ADX

**Vylepšení:**
```python
# Použít EMA34 trend pro primary regime detection
ema34_trend = self._get_ema34_trend(bars)

# Pokud EMA34 je jasný trend a recentní regression souhlasí
if ema34_trend in ["UP", "DOWN"]:
    # Použít EMA34 trend jako primary
    primary_regime = ema34_trend
else:
    # Fallback na regression
    primary_regime = regression_vote
```

**Výhody:**
- EMA34 je lepší pro recentní trend (exponenciální vážení)
- Již implementováno - jen zvýšit váhu
- Konzistentní s strict regime filterem

---

### **5. Adaptive Time Window** ⭐ (Nízká priorita)

**Nápad:** Dynamicky přizpůsobit velikost okna podle volatility/trend clarity

**Implementace:**
```python
def _calculate_adaptive_window(self, bars: List[Dict]) -> int:
    """Vypočítat optimální velikost okna"""
    # Pokud je trend jasný → kratší okno (rychlejší reakce)
    # Pokud je RANGE → delší okno (více dat pro analýzu)
    
    recent_atr = self._calculate_atr(bars[-20:])
    long_atr = self._calculate_atr(bars[-100:])
    
    if recent_atr > long_atr * 1.5:
        # Vysoká volatilita → kratší okno
        return 50
    else:
        # Normální volatilita → standardní okno
        return 100
```

**Výhody:**
- Automatické přizpůsobení podmínkám trhu
- Lepší pro různé market regimes

---

## 🎯 Doporučená implementace (Prioritizace):

### **Fáze 1 (Okamžitě):**
1. ✅ **Multi-Timeframe Regime Detection** - Největší dopad
2. ✅ **EMA34 Trend as Primary** - Snadné (už implementováno)

### **Fáze 2 (Brzy):**
3. ✅ **Trend Change Detection** - Důležité pro swing trading
4. ✅ **Exponential Weighted Regression** - Vylepšení přesnosti

### **Fáze 3 (Později):**
5. ⚠️ **Adaptive Time Window** - Složitější, menší dopad

---

## 📊 Očekávané výsledky:

### **Před vylepšením:**
- Systém detekuje TREND_DOWN i když recentní trend je UP
- Může missnout obchodní příležitosti v recovery trendech
- Pomalejší detekce trend reversals

### **Po vylepšení:**
- ✅ Rychlejší detekce recentních trendů
- ✅ Lepší detekce trend reversals
- ✅ Více spolehlivých signálů v trendových obchodech
- ✅ Menší počet false signals (lepší filtrování)

---

## 🔧 Konkrétní implementační kroky:

### **1. Multi-Timeframe (Nejvyšší priorita):**

```python
# V regime.py
def detect(self, bars: List[Dict]) -> RegimeState:
    """Multi-timeframe regime detection"""
    
    # Primary: Recentní trend (100 barů = 8 hodin)
    primary_bars = bars[-100:] if len(bars) >= 100 else bars
    primary_state = self._detect_single_timeframe(primary_bars)
    
    # Secondary: Celkový kontext (180 barů)
    secondary_state = self._detect_single_timeframe(bars[-180:]) if len(bars) >= 180 else primary_state
    
    # Pokud primary má vysokou confidence → použít primary
    if primary_state.confidence >= 70:
        return primary_state
    else:
        # Fallback na secondary
        return secondary_state
```

### **2. Trend Change Detection:**

```python
# V regime.py
def detect_trend_change(self, bars: List[Dict]) -> Dict:
    """Detekovat změnu trendu"""
    if len(bars) < 60:
        return {"change": None}
    
    # Krátkodobý (30 barů)
    short_slope, short_r2, short_vote = self._calculate_regression(bars[-30:])
    
    # Střednědobý (60 barů)
    medium_slope, medium_r2, medium_vote = self._calculate_regression(bars[-60:])
    
    # Detekovat reversal
    if short_vote == "TREND_UP" and medium_vote == "TREND_DOWN":
        return {"change": "REVERSAL_UP", "strength": abs(short_slope)}
    elif short_vote == "TREND_DOWN" and medium_vote == "TREND_UP":
        return {"change": "REVERSAL_DOWN", "strength": abs(short_slope)}
    
    return {"change": None}
```

---

**Poznámka:** Tyto vylepšení by měla zlepšit detekci recentních trendů a generovat více spolehlivých signálů pro intradenní swing trading v trendech.

