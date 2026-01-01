# Home Assistant Web Interface - Loading Screen Problém

**Datum:** 2025-12-28  
**Problém:** HA webové rozhraní zobrazuje pouze loading screen

---

## 🔍 Možné příčiny

### 1. Home Assistant Core se nespustil správně

**Symptom:** Loading screen, žádná odezva

**Zkontroluj:**
```bash
# Přes SSH
ssh root@homeassistant.local "ha core info"
```

**Možné řešení:**
- Restart Home Assistant Core
- Zkontroluj logy: `/config/home-assistant.log`

### 2. Příliš velká databáze nebo poškozená databáze

**Symptom:** HA se snaží načíst, ale trvá velmi dlouho nebo se zasekne

**Zkontroluj:**
```bash
# Velikost databáze
ls -lh /config/home-assistant_v2.db
```

**Řešení:**
- Databáze může být příliš velká (např. 17GB jak bylo vidět dříve)
- Zvážit cleanup nebo restart

### 3. AppDaemon způsobuje problémy

**Symptom:** HA běží, ale AppDaemon způsobuje výkonnostní problémy

**Zkontroluj:**
```bash
# AppDaemon logy
tail -50 /Volumes/addon_configs/a0d7b954_appdaemon/logs/appdaemon.log
```

### 4. Fronta je stále přetížená

**Symptom:** Utility loop stále pomalý, fronta stále velká

**Zkontroluj:**
```bash
grep -i "queue\|utility" /Volumes/addon_configs/a0d7b954_appdaemon/logs/appdaemon.log | tail -10
```

---

## 🚀 Rychlé řešení

### Varianta 1: Restart Home Assistant Core

```bash
ssh root@homeassistant.local "ha core restart"
```

Počkej 3-5 minut a zkus znovu.

### Varianta 2: Restart celého systému

```bash
ssh root@homeassistant.local "reboot"
```

Počkej 5-10 minut než se RPi restart dokončí.

### Varianta 3: Dočasně vypnout AppDaemon

```bash
ssh root@homeassistant.local "ha addons stop a0d7b954_appdaemon"
```

Pak zkus, jestli se webové rozhraní načte. Pokud ano, problém je v AppDaemon.

---

## 📋 Diagnostika

### Zkontroluj stav Home Assistant:

```bash
ssh root@homeassistant.local "ha core info"
```

**Očekávaný výstup:**
- `version:` - verze HA
- `state:` - mělo by být `running`
- `last_version:` - poslední verze

### Zkontroluj stav AppDaemon:

```bash
ssh root@homeassistant.local "ha addons info a0d7b954_appdaemon"
```

### Zkontroluj logy Home Assistant:

```bash
tail -100 /Volumes/config/home-assistant.log 2>/dev/null | grep -i "error\|failed\|traceback" | tail -20
```

---

## 💡 Co zkusit

1. **Nejdřív:** Restart Home Assistant Core
2. **Pokud to nepomůže:** Zkontroluj logy
3. **Pokud to stále nefunguje:** Dočasně vypni AppDaemon a zkus, jestli se HA načte
4. **Poslední možnost:** Restart celého RPi


