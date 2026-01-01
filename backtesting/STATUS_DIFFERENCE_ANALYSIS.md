# Analýza rozdílných statusů DAX/NASDAQ při zavřených trzích

**Datum:** 2025-12-28  
**Problém:** Když jsou trhy zavřené, DAX a NASDAQ mají různé statusy a hodnoty

---

## 🔍 Analýza problému

### Aktuální logika určování statusu (src/trading_assistant/main.py, řádky 1124-1157)

```python
for alias, raw in self.alias_to_raw.items():
    n = len(self.market_data.get(alias, []))  # Počet barů pro daný symbol
    in_hours = self._is_within_trading_hours(alias)  # Je v trading hodinách?
    has_data = n >= self.analysis_min_bars  # Má dostatek dat?
    
    if up != "on":
        status = "DISCONNECTED"
    elif not has_data:
        status = "WARMING_UP"  # ⚠️ Tato podmínka má prioritu!
    elif in_hours:
        status = "TRADING"
    else:
        status = "ANALYSIS_ONLY"
```

### Problém

**Když jsou trhy zavřené (víkend/outside trading hours):**

1. **DAX může mít status "WARMING_UP":**
   - Pokud `n < analysis_min_bars` (nemá dostatek historických dat)
   - Podmínka `not has_data` má prioritu před `in_hours`
   - → Status: `"WARMING_UP"` (i když trhy jsou zavřené)

2. **NASDAQ může mít status "ANALYSIS_ONLY":**
   - Pokud `n >= analysis_min_bars` (má dostatek historických dat)
   - Ale `in_hours = False` (trhy jsou zavřené)
   - → Status: `"ANALYSIS_ONLY"`

### Příčina rozdílných hodnot

Každý symbol má vlastní `market_data[alias]`, která se shromažďují pouze během jejich trading hodin:
- **DAX:** 09:00-15:30 Praha
- **NASDAQ:** 15:30-22:00 Praha

Když jsou trhy zavřené, každý symbol může mít:
- Různé množství historických dat (závisí na tom, kdy se naposledy obchodovalo)
- Různé hodnoty metrik (VWAP, ATR, pivots, atd.) - ty se vypočítávají z historických dat

---

## 💡 Navržené řešení

### Varianta 1: Priorita "CLOSED" statusu

Když jsou trhy zavřené, měl by být status "CLOSED" nebo "ANALYSIS_ONLY" pro oba symboly, **bez ohledu na množství dat**.

```python
if up != "on":
    status = "DISCONNECTED"
elif not in_hours:
    # Trhy jsou zavřené - jednotný status bez ohledu na data
    status = "ANALYSIS_ONLY"  # nebo "CLOSED"
elif not has_data:
    status = "WARMING_UP"
else:
    status = "TRADING"
```

### Varianta 2: Separace "data availability" a "trading status"

Rozdělit status na dva atributy:
- `status`: Trading status (TRADING/ANALYSIS_ONLY/CLOSED)
- `data_status`: Data availability (WARMING_UP/READY)

```python
# Trading status
if not in_hours:
    status = "CLOSED"
elif has_data:
    status = "TRADING"
else:
    status = "ANALYSIS_ONLY"

# Data status (atribut)
data_status = "WARMING_UP" if not has_data else "READY"
```

### Varianta 3: Jednotný status při zavřených trzích (doporučeno)

Upravit logiku tak, aby při zavřených trzích měly oba symboly stejný status:

```python
if up != "on":
    status = "DISCONNECTED"
elif not in_hours:
    # Trhy zavřené - jednotný status
    status = "ANALYSIS_ONLY"
elif not has_data:
    status = "WARMING_UP"
else:
    status = "TRADING"
```

**Výhody:**
- Jednoduchá změna
- Konzistentní chování při zavřených trzích
- "WARMING_UP" se zobrazí pouze když jsou trhy otevřené, ale chybí data

---

## 📊 Dopad na hodnoty

Hodnoty (VWAP, ATR, pivots, atd.) budou stále různé, protože:
- Jsou založené na historických datech
- Každý symbol má vlastní historii
- To je **očekávané chování** - není to bug

**Nicméně:** Pokud chceme při zavřených trzích zobrazit "N/A" nebo prázdné hodnoty, můžeme přidat kontrolu v dashboardu nebo v publikování entit.

---

## ✅ Doporučení

**Okamžité řešení:** Implementovat Variantu 3 - upravit pořadí podmínek tak, aby `in_hours` mělo prioritu před `has_data`.

**Budoucí vylepšení:** Zvážit zobrazení "N/A" nebo "—" pro hodnoty metrik při zavřených trzích, pokud jsou data starší než X hodin.



