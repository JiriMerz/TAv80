# EMA34 Trend Detection - Oprava V2

**Datum:** 2025-12-26 15:40

## 📊 Problém:

**Log (15:30:00):**
```
[REGIME] EMA34: Price=25678.84, EMA34=25678.47, Diff=0.37 (0.001%), Tolerance=12.84
[REGIME] EMA34: Price close to EMA34 (diff=0.37 < tolerance=12.84), using diff with momentum tiebreaker
[REGIME] EMA34: Diff very small (abs=0.37 < 6.42), checking momentum (3 bars) = -7.13
[REGIME] EMA34: Trend=DOWN (momentum-tiebreaker, momentum=-7.13)
```

**Problém:**
- Diff je extrémně malý (0.37 bodu = 0.001%)
- Momentum z 3 barů (-7.13) může být zavádějící (krátkodobý šum)
- Graf ukazuje uptrend, ale systém detekuje DOWN

## 💡 Řešení:

**Upravit logiku tak, aby při extrémně malém diffu (< 10% tolerance = 1.28 bodů) použila `None` (nejasný trend) místo momentum tiebreakeru.**

### Nová logika:

1. **Diff > threshold (6.42 bodů):** → diff-based trend (UP/DOWN)
2. **Diff < -threshold (-6.42 bodů):** → diff-based trend (DOWN/UP)
3. **abs(diff) < very_small_threshold (1.28 bodů):** → `None` (nejasný trend) - **NOVÉ**
4. **very_small_threshold <= abs(diff) < threshold:** → momentum tiebreaker (pouze pokud diff není extrémně malý)

### Implementace:

```python
very_small_diff_threshold = tolerance * 0.1  # 1.28 bodů

# Pokud je diff extrémně malý, použít None (nejasný trend) - nevěřit momentum
if abs(price_diff) < very_small_diff_threshold:
    logger.info(f"[REGIME] EMA34: Diff extremely small (abs={abs(price_diff):.2f} < {very_small_diff_threshold:.2f}), using None (trend unclear)")
    return None

# Diff je malý, ale ne extrémně malý - použít momentum jako tiebreaker
# ... (momentum logika)
```

## ✅ Výsledek:

**Pro diff = 0.37:**
- Před: `Trend=DOWN` (momentum=-7.13 < -6.42)
- Po: `Trend=None` (abs(0.37) < 1.28 → nejasný trend)

**Pro diff = 4.89:**
- `Trend=UP` (diff-fallback, protože abs(4.89) > 1.28 ale momentum unclear)

**Pro diff = 7.82:**
- `Trend=UP` (diff-based, protože diff > 6.42)

---

**Důvod:** Když je cena téměř přesně na EMA34 (diff < 1.28 bodů), momentum z 3 barů může být ovlivněno krátkodobým šumem a není spolehlivé pro detekci trendu. Lepší je detekovat `None` (nejasný trend).

