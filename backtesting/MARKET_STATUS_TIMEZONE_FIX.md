# Market Status Timezone Fix

## 🔍 Problém

Dashboard ukazoval "OPEN" i když trhy byly zavřené. Problém byl v timezone - `time_manager` používal lokální čas místo Prague timezone.

## ✅ Oprava

### 1. `_get_market_status_info()` v `main.py`
- **Před:** Předával UTC čas přímo do `time_manager.get_session_info(now)`
- **Po:** Převádí UTC čas na Prague timezone před předáním:
```python
now_utc = self.get_synced_time()
import pytz
prague_tz = pytz.timezone('Europe/Prague')
now_prague = now_utc.astimezone(prague_tz) if now_utc.tzinfo else prague_tz.localize(now_utc)
session_info = self.time_manager.get_session_info(now_prague)
```

### 2. `get_active_session()` v `time_based_manager.py`
- **Před:** Používal `datetime.now()` bez timezone
- **Po:** Používá `datetime.now(prague_tz)` a správně převádí timezone

### 3. `get_session_info()` v `time_based_manager.py`
- **Před:** Používal `datetime.now()` bez timezone
- **Po:** Zajišťuje, že čas je v Prague timezone

## 📊 Výsledek

Nyní systém správně:
- ✅ Detekuje, zda jsou trhy otevřené/zavřené podle Prague timezone
- ✅ Zobrazuje správný status v dashboardu
- ✅ Počítá správný čas do otevření trhů

## 🎯 Trading Hours (Prague timezone, UTC+1)
- **DAX:** 09:00-15:30
- **NASDAQ:** 15:30-22:00
- **CLOSED:** 22:00-09:00

Po nasazení by dashboard měl správně zobrazovat "CLOSED" když jsou trhy zavřené.

