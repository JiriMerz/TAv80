# Auto Trading Toggle - Dokumentace

## ⚠️ DŮLEŽITÉ: Nejdřív vytvoř Helper!

**PŘED použitím tlačítka musíš vytvořit Helper v Home Assistant:**

1. Otevři Home Assistant
2. Jdi do **Settings** → **Devices & Services** → **Helpers** tab
3. Klikni na **+ CREATE HELPER**
4. Vyber **Toggle**
5. Vyplň:
   - **Name**: `Auto Trading Enabled`
   - **Icon**: `mdi:robot-industrial`
6. Klikni **CREATE**

To vytvoří entitu `input_boolean.auto_trading_enabled` kterou můžeš ovládat z dashboardu.

## Přehled

Tlačítko `input_boolean.auto_trading_enabled` umožňuje zapnout/vypnout exekuci obchodů přímo z Home Assistant dashboardu.

**📍 YAML kód pro tlačítko najdeš níže** (přidej ho ručně do svého dashboardu)

**Důležité**:
- ✅ Analýzy a logy **BĚŽÍ NEUSTÁLE**, i když je auto-trading vypnutý
- ✅ Signály se **GENERUJÍ**, ale **NEPROVÁDĚJÍ** se obchody
- ✅ Všechny ostatní funkce (account monitoring, risk tracking, atd.) **FUNGUJÍ NORMÁLNĚ**

## Přidání do dashboardu

### Varianta 1: Toggle Switch (doporučeno)

```yaml
type: entities
entities:
  - entity: input_boolean.auto_trading_enabled
    name: Auto Trading
    icon: mdi:robot-industrial
```

### Varianta 2: Button Card (s vizuální indikací)

```yaml
type: button
entity: input_boolean.auto_trading_enabled
name: Auto Trading
icon: mdi:robot-industrial
show_state: true
tap_action:
  action: toggle
hold_action:
  action: none
```

### Varianta 3: Kompletní card s detaily

```yaml
type: vertical-stack
cards:
  - type: entities
    title: Trading Control
    entities:
      - entity: input_boolean.auto_trading_enabled
        name: Auto Trading Execution
        icon: mdi:robot-industrial
      - entity: sensor.trading_risk_status
        name: Risk Status
      - entity: sensor.trading_account_balance
        name: Account Balance

  - type: conditional
    conditions:
      - entity: input_boolean.auto_trading_enabled
        state: "on"
    card:
      type: markdown
      content: |
        ✅ **Auto-trading AKTIVNÍ**

        Signály budou automaticky prováděny

  - type: conditional
    conditions:
      - entity: input_boolean.auto_trading_enabled
        state: "off"
    card:
      type: markdown
      content: |
        ⏸️ **Auto-trading POZASTAVEN**

        Analýzy běží, ale obchody se neprovádějí
```

## ⚠️ BEZPEČNOSTNÍ FUNKCE

**Po každém restartu AppDaemon je auto-trading AUTOMATICKY VYPNUTÝ!**

- ✅ Musíš ho **RUČNĚ ZAPNOUT** přes dashboard
- ✅ Zabraňuje nechtěné exekuci po restartu
- ✅ V logu uvidíš: `⚠️ Auto-trading execution DISABLED by default`

## Chování

### Když je zapnuto (ON):
- 🟢 Signály se **GENERUJÍ A PROVÁDĚJÍ**
- 🟢 Obchody se odesílají na cTrader
- 🟢 Notifikace: "Auto-trading ZAPNUT ✅"

### Když je vypnuto (OFF):
- 🟡 Signály se **GENERUJÍ, ALE NEPROVÁDĚJÍ**
- 🟡 V logu: `⏸️ Signal rejected - auto-trading DISABLED`
- 🟡 Notifikace: "Auto-trading VYPNUT ⏸️"
- ✅ Všechny analýzy běží normálně
- ✅ Logy se generují
- ✅ Account monitoring funguje

## Technická implementace

### Entity
- **ID**: `input_boolean.auto_trading_enabled`
- **Friendly Name**: Auto Trading
- **Icon**: `mdi:robot-industrial` (zapnuto) / `mdi:robot-industrial-outline` (vypnuto)

### Atributy
```yaml
friendly_name: Auto Trading
icon: mdi:robot-industrial
last_changed: 2025-10-02T09:00:00.000000
```

### Callback
- **Handler**: `toggle_auto_trading()` v `main.py:1831`
- **Listener**: Reaguje na změnu stavu entity
- **Aktualizuje**: `order_executor.enabled`

### Order Executor Check
- **Metoda**: `can_execute_trade()` v `simple_order_executor.py:203`
- **Kontrola**: `if not self.enabled:`
- **Výsledek**: Signal rejected s reason "Auto-trading is disabled via toggle"

## Příklad použití

### Scénář 1: Testování strategie
1. Vypni auto-trading
2. Sleduj signály v logách
3. Ověř kvalitu signálů
4. Zapni auto-trading až když jsi spokojený

### Scénář 2: Vysoká volatilita
1. Vypni auto-trading při news events
2. Analýzy stále běží
3. Po uklidnění trhu zapni znovu

### Scénář 3: Noční režim
1. Vypni auto-trading před spaním
2. Ranní analýza signálů z noci
3. Manuální rozhodnutí o zapnutí

## Log Messages

### Při zapnutí:
```
[AUTO-TRADING] ✅ Trade execution ENABLED - signals will be executed automatically
```

### Při vypnutí:
```
[AUTO-TRADING] ⏸️ Trade execution DISABLED - signals will be generated but NOT executed
```

### Při pokusu o exekuci (vypnuto):
```
[ORDER_EXECUTOR] ⏸️ Signal rejected - auto-trading DISABLED: DAX SIGNALTYPE.BUY
[ORDER_EXECUTOR] Signal execution rejected:
  - Auto-trading is disabled via toggle
```

## Persistence

**POZOR**: Entity se **VŽDY** obnoví jako **OFF** po restartu AppDaemon!

- ❌ **NEPERSISTUJE** stav z předchozí session
- ✅ Vždy musíš ručně zapnout po restartu
- ✅ Bezpečnostní opatření proti nechtěné exekuci

## Safety Features

- ✅ Pokud není dostupný order executor, toggle se automaticky vypne
- ✅ Notifikace při každé změně stavu
- ✅ Jasné log messages
- ✅ Vizuální indikace v dashboardu (ikona se mění)

## Monitoring

Pro sledování stavu auto-tradingu:

```yaml
type: history-graph
entities:
  - entity: input_boolean.auto_trading_enabled
title: Auto Trading History
hours_to_show: 24
```
