# Restart Home Assistant bez Webového Rozhraní

**Datum:** 2025-12-28  
**Problém:** Webové rozhraní Home Assistant neběží, potřebujem restart

---

## 🔧 Možnosti restartu

### 1. Přes SSH (nejjednodušší) ⭐

**Požadavky:**
- SSH přístup k Home Assistant
- Příkazový řádek (Terminal)

**Postup:**
```bash
# 1. Připoj se k Home Assistant přes SSH
ssh root@homeassistant.local
# Nebo pokud máš jiný hostname/IP:
ssh root@10.0.1.23

# 2. Restart Home Assistant Core
ha core restart

# 3. Restart AppDaemon addon
ha addons restart a0d7b954_appdaemon

# 4. Zkontroluj stav
ha core info
ha addons info a0d7b954_appdaemon
```

**Poznámka:** Pokud nemáš SSH povolený, můžeš ho povolit přes:
- Home Assistant UI (pokud se ti povede připojit)
- Nebo fyzicky na RPi: `ha core update` a pak `ha core info` pro kontrolu

---

### 2. Přes Samba Share (pokud máš SSH)

Pokud máš SSH, můžeš použít Terminal na macOS:

```bash
# Restart přes SSH z macOS
ssh root@homeassistant.local "ha core restart"
ssh root@homeassistant.local "ha addons restart a0d7b954_appdaemon"
```

---

### 3. Fyzicky na Raspberry Pi

Pokud máš fyzický přístup k RPi:

```bash
# Připoj se přímo k RPi (klávesnice + monitor)
# Nebo přes SSH z jiného zařízení

# Restart Home Assistant
ha core restart

# Restart AppDaemon
ha addons restart a0d7b954_appdaemon
```

---

### 4. Pomocí Home Assistant API (pokud je API dostupné)

I když webové rozhraní neběží, API může být dostupné:

```bash
# Z macOS Terminal
# Potřebuješ long-lived access token (generuje se v HA UI pod profilem)

# Restart Home Assistant Core
curl -X POST \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  http://homeassistant.local:8123/api/services/homeassistant/restart
```

**Problém:** Pokud webové rozhraní neběží, API obvykle také neběží.

---

### 5. Restart celého systému (poslední možnost)

Pokud nic jiného nefunguje:

```bash
# Přes SSH
ssh root@homeassistant.local "reboot"

# Nebo fyzicky na RPi
sudo reboot
```

**⚠️ POZOR:** Toto restartuje celý systém (RPi), nejen Home Assistant!

---

## 🎯 Doporučený postup

### Krok 1: Zkus SSH

```bash
# Zkus se připojit
ssh root@homeassistant.local

# Pokud funguje, restartuj:
ha core restart
ha addons restart a0d7b954_appdaemon
```

### Krok 2: Pokud SSH nefunguje

1. **Zkontroluj, jestli je SSH povolený:**
   - Pokud máš jiný způsob přístupu (např. Home Assistant OS na RPi)
   - SSH může být vypnutý ve výchozím nastavení

2. **Zkus najít jiný způsob:**
   - Fyzický přístup k RPi
   - Jiný síťový přístup

### Krok 3: Restart celého systému

Pokud nic jiného nefunguje, restartuj celý RPi:
```bash
ssh root@homeassistant.local "reboot"
# Nebo fyzicky na RPi: sudo reboot
```

---

## 📋 Co dělat po restartu

1. **Počkej 2-3 minuty** než se HA restart dokončí
2. **Zkus se připojit k webovému rozhraní:**
   - http://homeassistant.local:8123
   - Nebo http://10.0.1.23:8123 (podle tvé IP)
3. **Zkontroluj logy AppDaemon:**
   ```bash
   tail -f /Volumes/addon_configs/a0d7b954_appdaemon/logs/appdaemon.log
   ```
4. **Zkontroluj, jestli fronta klesla:**
   - V logu hledej "Queue size" - měl by být < 100 položek

---

## 🔍 Troubleshooting SSH

### Pokud SSH nefunguje:

1. **Zkontroluj, jestli je SSH addon instalovaný:**
   - Home Assistant obvykle má SSH addon
   - Ale pokud webové rozhraní neběží, nemůžeš ho povolit přes UI

2. **Zkus jiný port:**
   ```bash
   ssh -p 22222 root@homeassistant.local
   ```

3. **Zkus IP adresu místo hostname:**
   ```bash
   ssh root@10.0.1.23
   ```

4. **Zkontroluj, jestli je SSH vůbec povolený:**
   - Na Home Assistant OS je SSH obvykle dostupný
   - Ale může být vypnutý ve výchozím nastavení

---

## ✅ Alternativní řešení (pokud SSH není dostupné)

Pokud nemáš SSH a webové rozhraní neběží, zkus:

1. **Restart RPi fyzicky** (vypni/zapni napájení)
2. **Počkej na automatický restart** - některé HA instalace mají auto-restart
3. **Kontaktuj podporu** - pokud je to production systém

---

## 📝 Poznámky

- **Restart přes SSH je nejbezpečnější** - restartuje jen HA, ne celý systém
- **Restart celého RPi je poslední možnost** - restartuje vše
- **Po restartu počkej 2-3 minuty** než se systém načte
- **Zkontroluj logy** pro ověření, že vše běží správně


