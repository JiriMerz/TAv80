# Auto-Trading Enable Fix

**Datum:** 2025-01-03  
**Problém:** Auto-trading se neaktivuje i když jsou signály generovány

---

## 🔍 Problém

V logu vidíme:
```
[ORDER_EXECUTOR] ⏸️ Signal rejected - auto-trading DISABLED: DAX SIGNALTYPE.BUY
```

**Důvod:**
- Auto-trading je ve výchozím stavu **VYPNUTÝ** (bezpečnostní opatření)
- I když je v `apps.yaml` `enabled: true`, kód to při startu přepisuje na `False`
- Systém čeká na toggle `input_boolean.auto_trading_enabled` v Home Assistant UI

---

## ✅ Oprava

**Před:**
```python
# SAFETY: Disable auto-trading by default after restart - must be manually enabled via dashboard
self.order_executor.enabled = False
self.log("[AUTO-TRADING] ⚠️ Auto-trading execution DISABLED by default - use dashboard toggle to enable")
```

**Po:**
```python
# SAFETY: Check Home Assistant toggle state, or disable by default
try:
    toggle_state = self.get_state("input_boolean.auto_trading_enabled")
    if toggle_state == "on":
        self.order_executor.enabled = True
        self.auto_trading_enabled = True
        self.log("[AUTO-TRADING] ✅ Auto-trading ENABLED (toggle is ON)")
    else:
        self.order_executor.enabled = False
        self.auto_trading_enabled = False
        self.log("[AUTO-TRADING] ⚠️ Auto-trading DISABLED - toggle is OFF (use dashboard to enable)")
except Exception as e:
    # If toggle doesn't exist or error, disable for safety
    self.order_executor.enabled = False
    self.auto_trading_enabled = False
    self.log(f"[AUTO-TRADING] ⚠️ Auto-trading DISABLED by default (toggle check failed: {e})")
    self.log("[AUTO-TRADING] Create toggle in HA: Settings → Devices & Services → Helpers → Toggle")
```

---

## 📋 Co se změnilo

1. **Kontrola toggle při startu** - systém nyní kontroluje stav `input_boolean.auto_trading_enabled` při inicializaci
2. **Automatická aktivace** - pokud je toggle ON, auto-trading se automaticky zapne
3. **Lepší logování** - jasně se loguje, zda je auto-trading zapnutý nebo vypnutý a proč

---

## 🎯 Jak zapnout auto-trading

### Možnost 1: Home Assistant UI (doporučeno)
1. Jdi do Home Assistant UI
2. Settings → Devices & Services → Helpers
3. Najdi nebo vytvoř `input_boolean.auto_trading_enabled`
4. Zapni toggle na **ON**

### Možnost 2: Po restartu
- Pokud je toggle už ON, auto-trading se automaticky zapne při startu
- Pokud je toggle OFF, musíš ho zapnout ručně

---

## 📝 Soubor k nahrání

- `src/trading_assistant/main.py` (řádky 245-247)

---

*Oprava dokončena - auto-trading se nyní aktivuje podle toggle stavu*

