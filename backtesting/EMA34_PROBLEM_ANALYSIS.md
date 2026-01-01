# EMA34 Trend Detection - Analýza problému

**Datum:** 2025-12-26 15:10

## 📊 Situace z logu:

**Log (15:10:11):**
```
[REGIME] EMA34: Price=25675.09, EMA34=25675.40, Diff=-0.31 (-0.001%), Tolerance=12.84
[REGIME] EMA34: Price close to EMA34 (diff=-0.31 < tolerance=12.84), using diff with momentum tiebreaker
[REGIME] EMA34: Diff very small (abs=0.31 < 6.42), checking momentum (3 bars) = -1.50
[REGIME] EMA34: Trend=DOWN (diff-fallback, diff=-0.31, momentum unclear)
[REGIME] EMA34 trend: DOWN
```

**Graf:**
- Cena: ~25675-25680
- EMA (modrá linka): Pod cenou → **uptrend**
- Systém detekuje: **DOWN** ❌

## ⚠️ Problém:

1. **Diff je velmi malý:** -0.31 bodu (0.001%) - cena je téměř přesně na EMA34
2. **Systém detekuje DOWN:** Kvůli fallback logice (price_diff < 0 → DOWN)
3. **Ale graf ukazuje uptrend:** EMA je pod cenou

## 🔍 Analýza:

**Možné důvody:**
1. **Výpočet EMA34 může být špatný** - měli bychom zkontrolovat, jestli je EMA34 skutečně 25675.40
2. **Tolerance je příliš velká** - 12.84 bodů je příliš velké pro detekci trendu
3. **Fallback logika je příliš agresivní** - když diff < 0, detekuje DOWN i když diff je velmi malý

## 💡 Řešení:

### **1. Upravit fallback logiku:**

Když je diff velmi malý (< 10% tolerance), měli bychom detekovat `None` (nejasný trend), ne DOWN.

**Implementováno:**
- Pokud `abs(diff) < tolerance * 0.1` → `None` (nejasný trend)
- Pouze pokud diff je významný → použít diff jako fallback

### **2. Zkontrolovat EMA34 výpočet:**

Měli bychom zkontrolovat, jestli je EMA34 výpočet stejný jako v EdgeDetector (který funguje).

**EdgeDetector používá:**
```python
multiplier = 2.0 / (period + 1.0)
sma_sum = sum(closes[:period])
ema = sma_sum / period
for close in closes[period:]:
    ema = (close * multiplier) + (ema * (1.0 - multiplier))
```

**RegimeDetector používá:**
```python
multiplier = 2.0 / (period + 1.0)
sma_sum = sum(closes[:period])
ema = sma_sum / period
for close in closes[period:]:
    ema = (close * multiplier) + (ema * (1.0 - multiplier))
```

✅ Výpočet je stejný.

### **3. Upravit toleranci:**

Možná bychom měli použít menší toleranci pro detekci trendu, ne pro "blízko EMA34" kontrolu.

**Aktuální tolerance:** 0.05% = 12.84 bodů při ceně ~25675
**Problém:** To je příliš velké pro detekci "blízko EMA34"

**Řešení:** 
- Tolerance pro "blízko EMA34": 0.05% (zůstane)
- Threshold pro diff-based rozhodování: tolerance * 0.5 = 6.42 bodů
- Threshold pro "velmi malý diff": tolerance * 0.1 = 1.28 bodů

## ✅ Implementované změny:

1. ✅ **Upravena fallback logika:** Pokud diff < 10% tolerance → `None` (nejasný trend)
2. ✅ **Lepší logování:** Zobrazuje důvod pro každé rozhodnutí

## 📊 Očekávané chování po změnách:

**Pro diff = -0.31:**
- abs(diff) = 0.31 < tolerance * 0.1 (1.28) → `None` (nejasný trend)
- Ne detekuje DOWN kvůli velmi malému diff

**Pro diff = -2.0:**
- abs(diff) = 2.0 > 1.28 ale < 6.42 → momentum check
- Pokud momentum unclear → `None` (nejasný trend)

**Pro diff = -8.0:**
- abs(diff) = 8.0 > 6.42 → diff-based DOWN

---

**Poznámka:** Pokud graf ukazuje uptrend, ale EMA34 detekuje DOWN, může to být také problém s výpočtem EMA34 nebo s časováním (používáme správný close price?). Ale s novou logikou by se velmi malé diffy (< 1.28 bodů) měly detekovat jako `None` místo DOWN.

