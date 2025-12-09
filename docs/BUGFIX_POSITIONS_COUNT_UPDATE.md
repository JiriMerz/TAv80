# BUGFIX: Positions Count & HA Entity Updates

**Date:** 2025-10-28
**Status:** ✅ FIXED
**Severity:** HIGH (Dashboard pokazoval nesprávný počet otevřených pozic)

## Problém

Dashboard v Home Assistant zobrazoval **open positions = 0**, i když byla 1 pozice otevřená. Navíc se vyskytovaly časté HTTP 400 chyby při update-ování HA entit.

### Symptomy
1. `sensor.trading_open_positions` zobrazoval 0 místo skutečného počtu
2. Account balance se aktualizoval správně
3. Logy obsahovaly: `HTTP POST: Bad Request {'attributes': {'last_changed': ..., 'last_reported': ..., 'context': ...}}`

## Root Cause Analysis

### Problém #1: Positions nebyli nikdy obdrženy
**Lokace:** `ctrader_client.py:1638-1668`

AccountStateMonitor nikdy nedostal positions data, protože:
- PT_TRADER_REQ (2124) se posílal správně a PT_TRADER_RES (2125) přicházel s positions
- **ALE** demo účty nevracejí `balance` v PT_TRADER_RES odpovědi (balance=0)
- Byla tam podmínka `if self.account_balance > 0:` která **blokovala** callback
- AccountStateMonitor callback se nikdy nevolal → positions zůstaly na 0

**Poznámka o pojmenování:**
Konstanta `PT_TRADER_REQ/RES` (2124/2125) je ve skutečnosti **PROTO_OA_RECONCILE_REQ/RES** podle oficiální cTrader API dokumentace:
```
PROTO_OA_TRADER_REQ = 2121
PROTO_OA_TRADER_RES = 2122
PROTO_OA_RECONCILE_REQ = 2124  ← Toto máme jako PT_TRADER_REQ
PROTO_OA_RECONCILE_RES = 2125  ← Toto máme jako PT_TRADER_RES
```
Reconcile messages **OBSAHUJÍ positions data**, což je správné pro náš use case.

### Problém #2: HA interní atributy v set_state()
**Lokace:** `account_state_monitor.py:407-424, 427-457`

Při volání `get_state(attribute="all")` se vrátily VŠECHNY atributy včetně HA interních:
- `last_changed`
- `last_reported`
- `last_updated`
- `context`

Tyto atributy se pak posílaly zpět do `set_state()`, což způsobovalo HTTP 400 Bad Request.

## Implementované Opravy

### Fix #1: Callback i když balance=0, pokud máme positions
**Soubor:** `ctrader_client.py:1647-1682`

```python
# CRITICAL FIX: Demo accounts don't return balance in PT_TRADER_RES, but DO return positions
# Always notify Account Monitor if we have position data, even if balance=0
has_positions = 'position' in payload and payload.get('position')

if self.account_balance > 0 or has_positions:
    # ... priprav account_data ...

    # Call legacy callback (only if balance > 0)
    if self.on_account_callback and self.account_balance > 0:
        self.on_account_callback(account_data)

    # CRITICAL: Always notify Account Monitor with PT_TRADER_RES position data (even if balance=0)
    trader_account_data = {
        "trader": {...},
        "position": payload.get('position', []),
        "deals": [],
        "timestamp": datetime.now(timezone.utc),
        "source": "PT_TRADER_RES"
    }
    logger.info(f"[ACCOUNT] 📍 Notifying AccountMonitor with PT_TRADER_RES: {len(payload.get('position', []))} positions")
    self._notify_account_callbacks(trader_account_data)
```

**Klíčové změny:**
- ✅ Přidána kontrola `has_positions` z payload
- ✅ Callback se volá i když `balance=0`, pokud máme positions
- ✅ Legacy callback (BalanceTracker) se volá jen když `balance > 0`
- ✅ AccountMonitor callback se **VŽDY** volá, pokud máme positions data

### Fix #2: Filtrování HA interních atributů
**Soubor:** `account_state_monitor.py:439-457`

```python
# CRITICAL FIX: Create NEW dict instead of updating existing (avoids HA internal attributes)
# Only copy custom application attributes, filter out HA internal ones
filtered_attributes = {
    k: v for k, v in current_risk_attributes.items()
    if k not in ['last_changed', 'last_reported', 'last_updated', 'context', 'state']
}

# Update with new values
filtered_attributes.update({
    "account_monitor_active": True,
    "open_positions": open_positions_count,
    # ... další atributy ...
})

self.app.set_state("sensor.trading_risk_status", current_state, attributes=filtered_attributes)
```

**Klíčové změny:**
- ✅ Vyfiltrování HA interních atributů před update-em
- ✅ Vytvoření nového dict místo update-ování existujícího
- ✅ Explicitní `state=` parametr ve všech `set_state()` voláních

### Fix #3: Požadavek PT_TRADER_REQ při startu
**Soubor:** `ctrader_client.py:1336-1342`

```python
# CRITICAL FIX: Request PT_TRADER_RES for positions data (needed by AccountStateMonitor)
logger.info("[ACCOUNT] Requesting PT_TRADER_REQ for positions data...")
trader_payload = {
    "ctidTraderAccountId": self.ctid_trader_account_id
}
trader_msg_id = await self._send(PT_TRADER_REQ, trader_payload)
logger.info(f"[ACCOUNT] PT_TRADER_REQ sent with msgId={trader_msg_id}, response will be handled by recv_loop")
```

**Klíčové změny:**
- ✅ Explicitní PT_TRADER_REQ (RECONCILE_REQ) při startu
- ✅ Response s positions se zpracovává přes recv_loop
- ✅ Kombinace s PT_DEAL_LIST_REQ pro balance

## Testování

### Před opravou
```
sensor.trading_open_positions = 0  (❌ Mělo být 1)
sensor.trading_account_balance = 1836100.27 CZK  (✅ OK)
LOG: [ACCOUNT_MONITOR] 🔐 Preserving 0 positions after PT_DEAL_LIST_RES
LOG: ERROR HASS: [400] HTTP POST: Bad Request {'attributes': {'last_changed': ...}}
```

### Po opravě
```
sensor.trading_open_positions = 1  (✅ SPRÁVNĚ)
sensor.trading_account_balance = 1836100.27 CZK  (✅ OK)
LOG: [ACCOUNT] 📍 Notifying AccountMonitor with PT_TRADER_RES: 1 positions
LOG: [ACCOUNT_MONITOR] Updated: Balance=1836100.27, Positions=1, PnL=47691.21
```

## Změněné soubory

1. `src/trading_assistant/ctrader_client.py`
   - Oprava callback logiky pro PT_TRADER_RES
   - Přidán explicitní request při startu

2. `src/trading_assistant/account_state_monitor.py`
   - Filtrování HA interních atributů
   - Explicitní `state=` parametry

## Dopady

- ✅ Dashboard nyní zobrazuje správný počet otevřených pozic
- ✅ Zmizely HTTP 400 chyby při update entit
- ✅ Positions tracking funguje i na demo účtech (kde balance=0 v PT_TRADER_RES)
- ✅ Account balance update funguje nadále správně

## Related Issues

- Poznámka: PT_TRADER_REQ/RES konstanty (2124/2125) jsou ve skutečnosti RECONCILE messages podle oficiální API spec
- Demo účty nevracejí balance v RECONCILE_RES, ale vracejí positions
- Pro balance používáme PT_DEAL_LIST_REQ/RES

## Lessons Learned

1. **Demo vs Live API rozdíly:** Demo účty mají odlišné chování (chybějící balance v RECONCILE_RES)
2. **HA entity management:** Nikdy nepoužívat `attribute="all"` bez filtrování interních atributů
3. **Message type naming:** Ověřit oficiální spec - naše PT_TRADER messages jsou ve skutečnosti RECONCILE
4. **Callback conditions:** Být opatrný s podmínkami jako `if balance > 0:` - můžou blokovat data na demo účtech
