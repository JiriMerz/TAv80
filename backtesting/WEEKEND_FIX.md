# Weekend Fix - Market Status

## 🔍 Problém

Dashboard ukazoval "Market Status: OPEN" i když trhy byly zavřené o víkendu. `time_manager` kontroloval pouze čas (09:00-15:30 pro DAX, 15:30-22:00 pro NASDAQ), ale nezkoumál, jestli je to víkend.

**Příklad:** Sobota 27.12.2025 15:39
- `time_manager` vracel "NASDAQ" protože 15:39 je v rozsahu 15:30-22:00
- Ale trhy jsou zavřené o víkendech!

## ✅ Oprava

Přidána kontrola na víkendy do `_get_market_status_info()`:

```python
# Check if it's weekend (Saturday or Sunday) - markets are closed
weekday = now_prague.weekday()  # 0=Monday, 6=Sunday
is_weekend = weekday >= 5  # Saturday (5) or Sunday (6)

if is_weekend:
    # Markets are closed on weekends
    # Calculate time until Monday 09:00
    days_until_monday = 2 if weekday == 5 else 1  # Saturday=2, Sunday=1
    next_monday = now_prague.replace(hour=9, minute=0, second=0, microsecond=0)
    next_monday = next_monday + timedelta(days=days_until_monday)
    
    # Calculate and format time until open
    time_until_open_seconds = (next_monday - now_prague).total_seconds()
    # ... format as HH:MM:SS
    
    return {
        "status": "CLOSED",
        "current_session": "CLOSED",
        "next_session": "DAX",
        "time_until_open": time_until_open,  # e.g., "28:33:23"
        ...
    }
```

## 📊 Výsledek

Nyní systém správně:
- ✅ Detekuje víkendy (sobota, neděle)
- ✅ Zobrazuje "CLOSED" o víkendech
- ✅ Počítá správný čas do otevření (pondělí 09:00)
- ✅ Používá `time_manager` pouze ve všední dny

## 🎯 Trading Schedule

**Všední dny:**
- DAX: 09:00-15:30
- NASDAQ: 15:30-22:00
- CLOSED: 22:00-09:00

**Víkendy:**
- CLOSED: Celý víkend
- Otevře se: Pondělí 09:00

Po nasazení by dashboard měl správně zobrazovat "CLOSED" o víkendech s countdownem do pondělí 09:00.

