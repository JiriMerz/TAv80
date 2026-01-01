# Finální Diagnostika a Řešení

**Datum:** 2025-12-28 19:10  
**Problém:** HA webové rozhraní zobrazuje pouze loading screen

---

## ✅ Co funguje:

1. **AppDaemon běží** - restartoval se v 19:06:27
2. **Blacklist je nasazen** - vidím v account_state_monitor.py
3. **Trading Assistant se spouští** - logy ukazují úspěšný start

---

## ❌ Problém:

**Home Assistant Core** - webové rozhraní se nenačítá (loading screen)

---

## 🔍 Možné příčiny:

### 1. Home Assistant Core se nespustil správně
- Databáze může být poškozená nebo příliš velká
- Core může být zaseklý při startu

### 2. AppDaemon způsobuje výkonnostní problémy
- I když běží, může způsobovat zpomalení HA Core

### 3. Jiný addon nebo komponenta způsobuje problém

---

## 🚀 Postup řešení (krok za krokem):

### Krok 1: Dočasně vypni AppDaemon

**Zkus, jestli se HA načte bez AppDaemon:**

```bash
ssh root@homeassistant.local "ha addons stop a0d7b954_appdaemon"
```

**Počkej 2-3 minuty a zkus se připojit k webovému rozhraní.**

**Výsledek:**
- ✅ **Pokud se HA načte** → Problém je v AppDaemon/Trading Assistant
- ❌ **Pokud se HA nenačte** → Problém je v HA Core samotném

---

### Krok 2A: Pokud se HA načte bez AppDaemon

**Problém je v AppDaemon/Trading Assistant.**

**Řešení:**
1. Nech AppDaemon vypnutý
2. Restartuj Home Assistant Core (vyčistí poškozené entity)
3. Zapni AppDaemon zpět
4. Zkontroluj logy

---

### Krok 2B: Pokud se HA nenačte ani bez AppDaemon

**Problém je v Home Assistant Core samotném.**

**Řešení:**
1. Restart Home Assistant Core
2. Pokud to nepomůže, restart celého RPi

---

### Krok 3: Restart Home Assistant Core

```bash
ssh root@homeassistant.local "ha core restart"
```

**Počkej 3-5 minut** než se HA restart dokončí.

---

### Krok 4: Pokud to stále nefunguje - Restart RPi

```bash
ssh root@homeassistant.local "reboot"
```

**Počkej 5-10 minut** než se RPi restart dokončí.

---

## 📋 Shrnutí:

**Problém s loading screenem není v mojí změně kódu** - AppDaemon běží a blacklist je nasazen.

**Skutečný problém:** Home Assistant Core samotný.

**Doporučený postup:**
1. Dočasně vypni AppDaemon
2. Zkus se připojit k HA
3. Pokud to funguje → problém je v AppDaemon
4. Pokud to nefunguje → restartuj HA Core


