# Market Status - Přidáno do Dashboardu

## ✅ Co bylo přidáno

### 1. Nová entita: `sensor.market_status`
Publikuje informace o stavu trhů:
- **State:** `OPEN` / `CLOSED` / `UNKNOWN`
- **Attributes:**
  - `current_session`: Aktuální session (DAX / NASDAQ / CLOSED)
  - `next_session`: Další session (DAX / NASDAQ / CLOSED)
  - `time_until_open`: Čas do otevření (formát: "HH:MM:SS" nebo "MM:SS")
  - `time_until_open_seconds`: Čas do otevření v sekundách (pro automatizace)
  - `is_open`: Boolean - zda jsou trhy otevřené
  - `next_change_time`: Čas další změny (např. "09:00", "15:30")

### 2. Nová karta v dashboardu: "Market Status"
- **Umístění:** Před "Live Activity" kartou
- **Zobrazuje:**
  - Status: OPEN (zelená) / CLOSED (oranžová)
  - Label: Aktuální session a čas do otevření
    - Při otevřených trzích: "DAX | Opens: Now"
    - Při zavřených trzích: "CLOSED | Opens in: 29:04:18"
- **Barevné indikátory:**
  - 🟢 Zelená = Trhy otevřené
  - 🟠 Oranžová = Trhy zavřené
  - ⚪ Šedá = Neznámý stav

## 🔧 Technické detaily

### Metoda `_get_market_status_info()`
- Používá `time_manager.get_session_info()` pokud je dostupný
- Fallback na `_is_within_trading_hours()` pokud time_manager není dostupný
- Počítá čas do otevření na základě aktuálního času a plánu session

### Aktualizace
- Status se aktualizuje každých 30 sekund v `_publish_live_status()`
- Používá synchronizovaný čas (`get_synced_time()`)

### Formátování času
- Pokud je čas > 1 hodina: "HH:MM:SS" (např. "29:04:18")
- Pokud je čas < 1 hodina: "MM:SS" (např. "45:30")
- Pokud jsou trhy otevřené: "Now"

## 📊 Příklad zobrazení

### Když jsou trhy zavřené:
```
Market Status
🔴 CLOSED
CLOSED | Opens in: 29:04:18
```

### Když jsou trhy otevřené (DAX):
```
Market Status
🟢 OPEN
DAX | Opens: Now
```

### Když jsou trhy otevřené (NASDAQ):
```
Market Status
🟢 OPEN
NASDAQ | Opens: Now
```

## 🎯 Výhody

1. **Okamžitá viditelnost** - Vidíte, jestli jsou trhy otevřené
2. **Countdown** - Vidíte přesně, kdy se trhy otevřou
3. **Session info** - Vidíte, která session je aktivní nebo bude další
4. **Automatizace** - `time_until_open_seconds` lze použít v HA automatizacích

## 📝 Poznámky

- Status se aktualizuje automaticky každých 30 sekund
- Používá Prague timezone pro určení session
- Respektuje trading hours konfiguraci
- Pokud time_manager není dostupný, používá fallback na trading_hours check

