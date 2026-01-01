# Live Status Fix - Zobrazení hodnot

## 🔍 Problém

V dashboardu se zobrazovalo:
- **DAX:** "Bar: 16666m | Analysis: 16666m | Signal: 16666m"
- **NASDAQ:** "Bar: 65s | Analysis: 65s | Signal: 16666m"

**16666m** = 999999 sekund / 60 = ~11.5 dne - to je fallback hodnota, když nejsou data!

## ✅ Oprava

### Před:
```python
bar_age_sec = (now - last_bar).total_seconds() if last_bar else 999999
# Pak se zobrazilo: f"{int(999999/60)}m" = "16666m"
```

### Po:
```python
if last_bar:
    bar_age_sec = (now - last_bar).total_seconds()
    bar_ago = f"{int(bar_age_sec)}s" if bar_age_sec < 60 else f"{int(bar_age_sec/60)}m" if bar_age_sec < 3600 else f"{int(bar_age_sec/3600)}h"
else:
    bar_ago = "N/A"  # ✅ Správně - žádná data
```

## 📊 Vylepšení

1. **"N/A" místo nesmyslných hodnot** - když nejsou data
2. **Lepší formátování:**
   - < 60s → "5s", "30s"
   - < 60min → "5m", "30m"
   - >= 60min → "2h", "12h" (místo "120m")
3. **Status "CLOSED"** když jsou trhy zavřené (místo STALE)

## 🎯 Výsledek

Teď se zobrazí:
- **Když nejsou data:** "Bar: N/A | Analysis: N/A | Signal: N/A"
- **Když jsou data:** "Bar: 65s | Analysis: 70s | Signal: 80s"
- **Když jsou trhy zavřené:** Status = "CLOSED" (ne STALE)
- **Lepší formátování:** "2h" místo "120m"

