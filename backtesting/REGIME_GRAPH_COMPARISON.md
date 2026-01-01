# Porovnání: Graf US100 vs. Produkční Logy

**Datum:** 26.12.2025 10:03:29 UTC+1  
**Symbol:** US100 (NASDAQ)  
**Časový rámec:** M5  
**Stav:** Premarket (mimo hlavní obchodní hodiny NASDAQ)

---

## 📊 Co ukazuje graf (cTrader screenshot):

### **Vizuální analýza:**
1. **Silný uptrend** od 24.12. 14:45 do 26.12. 01:30
   - Cena stoupla z ~25560 na ~25690
   - Dominují zelené svíčky (růst)
   - Jasný trend směrem nahoru

2. **EMA34:** 25640.41
   - Potvrzuje uptrend
   - Cena je nad EMA34
   - EMA34 stoupá

3. **RSI:** 56
   - Mírně nad středem (50)
   - Není přeprodané ani překoupené
   - Potvrzuje uptrend

4. **Pivot Points:**
   - R1: ~25680 (odpor)
   - PP: ~25610 (pivot point)
   - S1: ~25560 (support)
   - Cena je nad PP, blízko R1

5. **Po 26.12. 01:30:**
   - Konsolidace
   - Mírný downtrend
   - Ale celkově stále uptrend od 24.12.

---

## 🔍 Co by měl systém logovat (očekávání):

### **Regime Detection:**
- **Regime:** `TREND_UP` nebo `TREND`
- **Confidence:** Vysoká (80-100%)
- **Trend Direction:** `UP`
- **ADX:** > 25 (silný trend)
- **Regression:** Pozitivní slope, R² > 0.3

### **EMA34 Trend:**
- **EMA34 Trend:** `UP`
- **Price vs EMA34:** Cena nad EMA34
- **EMA34 Value:** ~25640.41

### **Swing State:**
- **Swing:** `UP` (poslední swing je high)
- **Swing Quality:** Vysoká (jasný trend)

---

## ⚠️ Co se může dít v premarketu:

### **Problémy s detekcí v premarketu:**
1. **Nízký objem** → ADX může být nižší
2. **Méně barů** → Regime detection může být méně spolehlivá
3. **Nízká likvidita** → Microstructure může být zkreslená
4. **Časový filtr** → Systém může být nastaven na hlavní obchodní hodiny

### **Možné nesoulady:**
- **Regime:** `RANGE` místo `TREND_UP`
  - Důvod: Nízký objem v premarketu → ADX < 25
  - Důvod: Méně barů → Regression R² < 0.3
  
- **Trend Direction:** `DOWN` nebo `SIDEWAYS` místo `UP`
  - Důvod: Poslední bary (konsolidace) mohou ovlivnit regression slope
  - Důvod: ADX DI- může být vyšší než DI+ (krátkodobě)

- **EMA34:** `None` nebo `SIDEWAYS`
  - Důvod: Nedostatek barů pro výpočet EMA34
  - Důvod: EMA34 se může počítat jen z hlavních obchodních hodin

---

## 🔧 Co zkontrolovat v logu:

### **1. Regime Detection Log:**
```
[REGIME] Final result: ???, Confidence: ???%, Votes: ADX=???, REG=???
```
**Očekávání:** `TREND_UP` nebo `TREND`, Confidence > 70%

### **2. ADX Values:**
```
[REGIME] ADX: ???, DI+: ???, DI-: ???, Vote: ???
```
**Očekávání:** ADX > 25, DI+ > DI- (pro uptrend)

### **3. Regression:**
```
[REGIME] Regression - Slope: ???%, R²: ???, Vote: ???
```
**Očekávání:** Pozitivní slope, R² > 0.3

### **4. EMA34:**
```
[EDGES] EMA34 Trend: ???
```
**Očekávání:** `UP`

### **5. Time Filter:**
```
[TIME_MANAGER] NASDAQ session: ???
```
**Očekávání:** Možná `OUT_OF_SESSION` nebo `PREMARKET`

---

## 📝 Doporučení:

1. **Zkontrolovat logy** pro US100 kolem 10:03 UTC+1
2. **Porovnat** regime detection s grafem
3. **Zkontrolovat** časový filtr - možná blokuje detekci v premarketu
4. **Zkontrolovat** počet barů - možná nedostatek dat pro spolehlivou detekci

---

## 🎯 Očekávané problémy:

1. **Premarket = nízký objem** → ADX může být < 25 → `RANGE`
2. **Konsolidace po 01:30** → Regression slope může být negativní → `TREND_DOWN`
3. **Časový filtr** → Systém může být nastaven jen na hlavní hodiny → žádná detekce
4. **Méně barů** → EMA34 může být `None` → strict regime filter blokuje signály

---

**Poznámka:** Pro přesnou analýzu potřebuji produkční logy z 26.12.2025 kolem 10:03 UTC+1.

