# Home Assistant Startup Diagnosis

**Datum:** 2025-12-28 18:50  
**Status:** ✅ AppDaemon běží, ale jsou výkonnostní problémy

---

## 🔍 Zjištění z logů

### ✅ Co funguje:
- AppDaemon addon běží
- Trading Assistant aplikace běží
- **Moje změna v `main.py` není problém** - žádné chyby související s `log_status` nebo `_is_within_trading_hours`

### ❌ Problémy:

#### 1. Poškozené entity (HTTP 400 Bad Request)
```
ERROR HASS: [400] HTTP POST: Bad Request
- sensor.trading_open_positions
- sensor.trading_daily_pnl
- sensor.trading_daily_pnl_percent
```

**Důvod:** Entity jsou poškozené v HA database (známý problém z dřívějška)

#### 2. Thread starvation (fronta 4469 položek)
```
WARNING AppDaemon: Queue size for thread thread-0 is 4468
WARNING AppDaemon: Excessive time spent in utility loop: 2.0s-3.0s
```

**Důvod:** AppDaemon je přetížený, fronta se nezpracovává rychle enough

#### 3. Performance degradace
- Utility loop trvá 2-3 sekundy (měl by být < 100ms)
- Fronta roste (4469 položek)
- Aplikace běží, ale pomalu

---

## 💡 Řešení

### Okamžité opatření (doporučeno):

#### 1. Restart Home Assistant Core
**Cíl:** Vyčistit poškozené entity

**Postup:**
- Home Assistant UI: Settings → System → Restart (Restart Home Assistant)
- Nebo přes SSH: `ha core restart`
- Počkej 2-3 minuty než HA restart dokončí

#### 2. Restart AppDaemon Addon
**Cíl:** Vyčistit frontu a resetovat stav

**Postup:**
- Home Assistant UI: Settings → Add-ons → AppDaemon → RESTART
- Nebo přes SSH: `ha addons restart a0d7b954_appdaemon`

#### 3. Po restartu zkontroluj logy
```bash
tail -f /Volumes/addon_configs/a0d7b954_appdaemon/logs/appdaemon.log
```

**Očekávané výsledky:**
- Fronta by měla klesnout na normální úroveň (< 100 položek)
- Utility loop by měl být rychlejší (< 100ms)
- Entity chyby by měly zmizet (po HA restart)

---

## 🚨 Pokud problém přetrvá

### Možné příčiny:

1. **Příliš mnoho callbacků** - aplikace generuje příliš mnoho eventů
2. **Pomalé HA API** - Home Assistant API je pomalé
3. **Poškozené entity stále existují** - potřebují manuální odstranění

### Možná řešení:

1. **Snížit frekvenci aktualizací** - zvýšit `status_interval_sec` v `apps.yaml`
2. **Odstranit poškozené entity** - manuálně přes HA API nebo restart HA
3. **Zkontrolovat jiné addony** - možná jiný addon způsobuje problém

---

## ✅ Závěr

**Moje změna v `main.py` (logika statusu) není problém!**

Problém je v:
- Poškozených entitách v HA (HTTP 400)
- Přetížené frontě AppDaemon (4469 položek)
- Výkonnostní degradaci

**Doporučený postup:**
1. Restart Home Assistant Core
2. Restart AppDaemon Addon
3. Kontrola logů

Po restartu by měl systém běžet normálně.


