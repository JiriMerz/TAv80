# Rychlý restart Home Assistant bez Web UI

**Datum:** 2025-12-28

---

## 🚀 Nejjednodušší způsob: SSH

### Zkus toto (z macOS Terminal):

```bash
# 1. Restart Home Assistant Core
ssh root@homeassistant.local "ha core restart"

# 2. Restart AppDaemon addon
ssh root@homeassistant.local "ha addons restart a0d7b954_appdaemon"
```

**Pokud to funguje:**
- Počkej 2-3 minuty
- Zkus se připojit k webovému rozhraní: http://homeassistant.local:8123

---

## 🔄 Alternativa: Restart celého RPi

Pokud SSH nefunguje nebo nemáš `ha` CLI:

```bash
# Restart celého Raspberry Pi
ssh root@homeassistant.local "reboot"
```

**⚠️ POZOR:** Toto restartuje celý systém, nejen Home Assistant!

Po restartu:
- Počkej 3-5 minut než se RPi restart dokončí
- Zkus se připojit k webovému rozhraní

---

## 📋 Co zkusit, pokud SSH nefunguje:

1. **Zkus jiný hostname:**
   ```bash
   ssh root@10.0.1.23  # Nahraď svou IP adresou
   ```

2. **Zkus jiný port:**
   ```bash
   ssh -p 22222 root@homeassistant.local
   ```

3. **Zkus jiného uživatele:**
   ```bash
   ssh hassio@homeassistant.local
   ```

4. **Fyzický restart RPi:**
   - Vypni a zapni napájení RPi
   - Počkej 3-5 minut
   - Zkus se připojit k webovému rozhraní

---

## ✅ Po restartu - kontrola

```bash
# Zkontroluj logy AppDaemon
tail -50 /Volumes/addon_configs/a0d7b954_appdaemon/logs/appdaemon.log

# Hledej chyby
grep -i "error\|failed" /Volumes/addon_configs/a0d7b954_appdaemon/logs/appdaemon.log | tail -20
```

**Očekávané výsledky po restartu:**
- ✅ Fronta by měla klesnout (< 100 položek)
- ✅ Utility loop by měl být rychlejší
- ✅ Entity chyby (HTTP 400) by měly zmizet


