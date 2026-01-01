# Regime Detection Improvements - Implementováno

**Datum:** 2025-12-26  
**Cíl:** Lepší interpretace trhu pro intradenní swing trading v trendech

---

## ✅ Implementovaná vylepšení:

### **1. Multi-Timeframe Regime Detection** ⭐⭐⭐

**Popis:**  
Systém nyní analyzuje trh ve dvou timeframech:
- **Primary (100 barů = 8 hodin):** Recentní trend pro trading rozhodnutí
- **Secondary (180 barů = 15 hodin):** Celkový kontext trhu

**Logika:**
- Pokud primary má confidence ≥ 70% → použije primary
- Pokud secondary má confidence ≥ 70% → použije secondary
- Jinak použije primary (recentní trend má prioritu)

**Výhody:**
- Lepší detekce recentních trendů
- Rychlejší reakce na změny trhu
- Zachytí recovery trend dříve

**Konfigurace (`apps.yaml`):**
```yaml
regime:
  use_multi_timeframe: true
  primary_window: 100    # 8 hodin na M5
  secondary_window: 180  # 15 hodin na M5
```

---

### **2. Trend Change Detection** ⭐⭐⭐

**Popis:**  
Detekuje změny trendu porovnáním krátkodobého a střednědobého trendu.

**Logika:**
- Krátkodobý trend: 30 barů (2.5 hodiny)
- Střednědobý trend: 60 barů (5 hodin)
- Pokud se liší → detekuje reversal

**Výhody:**
- Rychlejší detekce trend reversals
- Lepší pro swing trading (zachytí recovery dříve)
- Identifikuje změny trendu i když celkový trend je opačný

**Konfigurace:**
```yaml
regime:
  use_trend_change_detection: true
  short_trend_window: 30   # 2.5 hodiny
  medium_trend_window: 60  # 5 hodin
```

**Detekované změny:**
- `REVERSAL_UP`: Downtrend se mění na uptrend
- `REVERSAL_DOWN`: Uptrend se mění na downtrend

---

### **3. EMA34 Trend as Primary Indicator** ⭐⭐

**Popis:**  
EMA34 trend je používán jako primární indikátor pro recentní trend, pokud regime detection říká RANGE.

**Logika:**
- Pokud regime = RANGE, ale EMA34 ukazuje trend → použije EMA34 trend
- EMA34 má exponenciální vážení → lépe reflektuje recentní trend
- Pokud EMA34 trend konfliktuje s regime trendem → použije EMA34

**Výhody:**
- Lepší detekce recentního trendu
- EMA34 je spolehlivější pro swing trading
- Konzistentní s strict regime filterem v EdgeDetector

**Konfigurace:**
```yaml
regime:
  use_ema34_primary: true
```

---

### **4. Exponential Weighted Regression** ⭐⭐

**Popis:**  
Exponenciálně vážená regression, kde recentní bary mají větší váhu.

**Logika:**
- Decay factor: 0.95 (nejnovější bar = 1.0, starší = 0.95^n)
- Stále používá všechna data, ale recentní mají větší vliv
- Lze použít místo standardní regression

**Výhody:**
- Recentní bary mají větší vliv na trend
- Lepší pro swing trading (důležitý recentní trend)
- Stále používá všechna data

**Konfigurace:**
```yaml
regime:
  use_weighted_regression: false  # Experimentální, defaultně vypnuto
  weight_decay: 0.95
```

---

## 📊 Nové logy pro ověření:

### **Struktura logů:**

```
[REGIME] Starting detection with 508 bars
[REGIME] PRIMARY (100 bars): TREND_UP, Confidence: 85.0%
[REGIME] SECONDARY (180 bars): TREND_DOWN, Confidence: 75.0%
[REGIME] Using PRIMARY timeframe (confidence 85.0% >= 70%)
[REGIME] TREND CHANGE detected: REVERSAL_UP
[REGIME] EMA34 trend: UP
[REGIME] EMA34 priority: Changed RANGE → TREND_UP (EMA34=UP)
[REGIME] ===== FINAL REGIME STATE =====
[REGIME] Regime: TREND_UP
[REGIME] Confidence: 85.0%
[REGIME] Used Timeframe: primary
[REGIME] Primary (100 bars): TREND_UP (85.0%)
[REGIME] Secondary (180 bars): TREND_DOWN (75.0%)
[REGIME] ADX: 32.41, Vote: TREND
[REGIME] Regression: Slope=0.001800%, R²=0.247, Vote: TREND_UP
[REGIME] Trend Direction: UP
[REGIME] EMA34 Trend: UP
[REGIME] Trend Change: REVERSAL_UP
[REGIME] =============================
```

### **Co hledat v logách:**

1. **Used Timeframe:**
   - `primary` = používá recentní trend (lepší pro swing trading)
   - `secondary` = používá celkový kontext
   - `combined` = standardní detekce (multi-timeframe vypnut)

2. **Primary vs Secondary:**
   - Pokud primary říká TREND_UP a secondary TREND_DOWN → systém detekuje recovery
   - Pokud oba říkají stejně → silný trend

3. **Trend Change:**
   - `REVERSAL_UP` = downtrend se mění na uptrend (recovery)
   - `REVERSAL_DOWN` = uptrend se mění na downtrend

4. **EMA34 Trend:**
   - Pokud EMA34 trend se liší od regime trendu → použije EMA34
   - To indikuje, že recentní trend je jiný než celkový

---

## 🔍 Jak ověřit interpretaci trhu:

### **Příklad 1: Recovery Trend**

**Scénář:** Graf ukazuje downtrend od 04:00, recovery od 09:00

**Očekávané logy:**
```
[REGIME] PRIMARY (100 bars): TREND_UP, Confidence: 75.0%
[REGIME] SECONDARY (180 bars): TREND_DOWN, Confidence: 80.0%
[REGIME] Using PRIMARY timeframe (confidence 75.0% >= 70%)
[REGIME] Trend Change: REVERSAL_UP
[REGIME] EMA34 trend: UP
[REGIME] Final Regime: TREND_UP (from PRIMARY)
```

**Interpretace:** ✅ Systém správně detekuje recovery pomocí PRIMARY timeframe a EMA34

---

### **Příklad 2: Silný Trend**

**Scénář:** Graf ukazuje silný uptrend v celém okně

**Očekávané logy:**
```
[REGIME] PRIMARY (100 bars): TREND_UP, Confidence: 90.0%
[REGIME] SECONDARY (180 bars): TREND_UP, Confidence: 85.0%
[REGIME] Using PRIMARY timeframe (confidence 90.0% >= 70%)
[REGIME] Trend Change: None
[REGIME] EMA34 trend: UP
[REGIME] Final Regime: TREND_UP
```

**Interpretace:** ✅ Oba timeframy souhlasí → silný trend

---

### **Příklad 3: RANGE s EMA34 Trendem**

**Scénář:** Regime detection říká RANGE, ale EMA34 ukazuje trend

**Očekávané logy:**
```
[REGIME] PRIMARY (100 bars): RANGE, Confidence: 60.0%
[REGIME] EMA34 trend: UP
[REGIME] EMA34 priority: Changed RANGE → TREND_UP (EMA34=UP)
[REGIME] Final Regime: TREND_UP (from EMA34)
```

**Interpretace:** ✅ EMA34 má prioritu → používá EMA34 trend

---

## 📈 Home Assistant Dashboard:

Nové atributy v `sensor.{alias}_m1_regime_state`:

- `used_timeframe`: "primary" | "secondary" | "combined"
- `primary_regime`: "TREND_UP" | "TREND_DOWN" | "RANGE"
- `secondary_regime`: "TREND_UP" | "TREND_DOWN" | "RANGE"
- `trend_change`: "REVERSAL_UP" | "REVERSAL_DOWN" | null
- `ema34_trend`: "UP" | "DOWN" | null
- `confidence`: 0-100

---

## 🎯 Očekávané výsledky:

### **Před vylepšeními:**
- Systém detekuje TREND_DOWN i když recentní trend je UP
- Missuje obchodní příležitosti v recovery trendech
- Pomalejší detekce trend reversals

### **Po vylepšeních:**
- ✅ Rychlejší detekce recentních trendů
- ✅ Lepší detekce trend reversals
- ✅ Více spolehlivých signálů v trendových obchodech
- ✅ Lepší interpretace trhu podle grafů

---

## 🔧 Konfigurace:

Všechna vylepšení jsou **aktivní** v `apps.yaml`:

```yaml
regime:
  # Multi-timeframe
  use_multi_timeframe: true
  primary_window: 100
  secondary_window: 180
  
  # Trend change detection
  use_trend_change_detection: true
  short_trend_window: 30
  medium_trend_window: 60
  
  # EMA34 integration
  use_ema34_primary: true
  
  # Weighted regression (experimentální)
  use_weighted_regression: false
  weight_decay: 0.95
```

---

**Poznámka:** Všechna vylepšení jsou implementována a aktivní. Logy obsahují detailní informace pro ověření interpretace trhu podle grafů.

