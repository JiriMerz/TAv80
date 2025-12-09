# Changelog - Auto Trading Toggle Feature

## 2025-10-02 - Auto Trading Toggle Implementation

### ✨ Nové funkce

**Auto-Trading Toggle (input_boolean.auto_trading_enabled)**
- Přidáno tlačítko pro zapnutí/vypnutí exekuce obchodů z dashboardu
- Tlačítko je umístěno v Trading Desk dashboardu (CONTROL BUTTONS sekce)
- Vizuální indikace: zelené = zapnuto, šedé = vypnuto
- Dynamické styly s gradientem a border efekty

**Bezpečnostní funkce**
- Auto-trading je **VŽDY vypnutý po restartu** AppDaemon
- Musí být ručně zapnut přes dashboard
- Notifikace při každé změně stavu (zapnuto/vypnuto)
- Jasné log messages v AppDaemon logách

**Chování**
- Analýzy a logy běží NEUSTÁLE (i když je auto-trading vypnutý)
- Signály se GENERUJÍ, ale NEPROVÁDĚJÍ se obchody když je vypnuto
- Account monitoring, risk tracking a všechny ostatní funkce fungují normálně

### 📝 Změny v kódu

**main.py**
- Řádek 165: Přidán listener pro `input_boolean.auto_trading_enabled`
- Řádek 243-245: Auto-trading se nastaví na `False` při startu (bezpečnost)
- Řádek 1507-1514: Entity se vytváří s inicializačním stavem "off"
- Řádek 1831-1864: Nová metoda `toggle_auto_trading()` - handler pro změny stavu
  - Aktualizuje `order_executor.enabled`
  - Mění ikonu podle stavu
  - Posílá notifikace
  - Loguje změny

**simple_order_executor.py**
- Řádek 204-205: Vylepšené logování když je signal rejected kvůli vypnutému auto-tradingu
- Jasná zpráva: `⏸️ Signal rejected - auto-trading DISABLED`

**dashboards/trading_desk.yaml**
- Řádek 293-315: Přidáno AUTO TRADING tlačítko do control buttons
- Dynamické styly s color coding:
  - Zelený gradient když zapnuto
  - Šedý gradient když vypnuto
- Show state: zobrazuje ON/OFF
- Box shadow pro lepší viditelnost

### 📚 Dokumentace

**Nové soubory**
- `docs/AUTO_TRADING_TOGGLE.md` - Kompletní dokumentace funkce
  - Přehled a chování
  - Dashboard konfigurace (3 varianty)
  - Bezpečnostní funkce
  - Technická implementace
  - Příklady použití
  - Log messages
  - Monitoring

- `docs/README.md` - Hlavní index dokumentace
  - Rychlý start
  - Struktura projektu
  - Konfigurace
  - Debugging
  - Common issues

- `docs/CHANGELOG_AUTO_TRADING_TOGGLE.md` - Tento soubor

**Organizace**
- Všechna dokumentace přesunuta do `/docs/`
- Dashboard konfigurace v `/dashboards/`
- Root directory čistý (žádné .md soubory)

### 🔍 Testování

**Test scénáře**
1. ✅ Po restartu je toggle OFF
2. ✅ Kliknutí na tlačítko změní stav
3. ✅ Notifikace se zobrazí
4. ✅ Logs obsahují správné zprávy
5. ✅ Signály jsou rejected když OFF
6. ✅ Signály jsou prováděny když ON
7. ✅ Analýzy běží neustále

**Očekávané logy**

Při startu:
```
[AUTO-TRADING] ⚠️ Auto-trading execution DISABLED by default - use dashboard toggle to enable
```

Při zapnutí:
```
[AUTO-TRADING] ✅ Trade execution ENABLED - signals will be executed automatically
```

Při vypnutí:
```
[AUTO-TRADING] ⏸️ Trade execution DISABLED - signals will be generated but NOT executed
```

Při pokusu o exekuci (vypnuto):
```
[ORDER_EXECUTOR] ⏸️ Signal rejected - auto-trading DISABLED: DAX SIGNALTYPE.BUY
```

### 🎯 Použití

**Scénář 1: Testování strategie**
1. Vypni auto-trading
2. Sleduj signály v logách
3. Ověř kvalitu
4. Zapni až když jsi spokojený

**Scénář 2: Vysoká volatilita**
1. Vypni při news events
2. Analýzy stále běží
3. Po uklidnění zapni znovu

**Scénář 3: Noční režim**
1. Vypni před spaním
2. Ranní analýza signálů
3. Manuální rozhodnutí

### 🔐 Bezpečnost

- ✅ Auto-trading VŽDY OFF po restartu
- ✅ Musí být ručně zapnut
- ✅ Notifikace při změnách
- ✅ Jasné log messages
- ✅ Vizuální indikace v dashboardu
- ✅ Pokud není order executor, toggle se vypne

### 📊 Dashboard

**Tlačítko umístění**: Trading Desk → CONTROL BUTTONS (první zleva)

**Vizuální vlastnosti**:
- Icon: `mdi:robot-industrial`
- Barvy:
  - ON: Zelený gradient (#059669 → #10b981), border #34d399
  - OFF: Šedý gradient (#4b5563 → #6b7280), border #9ca3af
- Show state: Zobrazuje ON/OFF text
- Font: Bold, white
- Shadow: 0 4px 10px rgba(0,0,0,0.3)

### 🔄 Breaking Changes

**ŽÁDNÉ** - Všechny změny jsou zpětně kompatibilní.

Existující funkce:
- ✅ Auto-trading module funguje stejně
- ✅ Order execution logika beze změny
- ✅ Risk management beze změny
- ✅ Account monitoring beze změny

Jediná změna v chování:
- ⚠️ Auto-trading je **VŽDY vypnutý po restartu** (místo použití hodnoty z configu)
- ✅ Toto je **bezpečnostní feature**, ne bug!

### 📈 Future Enhancements

Možná vylepšení do budoucna:
- [ ] Scheduling - automatické zapnutí/vypnutí v určitý čas
- [ ] History tracking - graf změn stavu
- [ ] API endpoint pro remote control
- [ ] Multi-level enabling (partial trading, test mode, full mode)
- [ ] Symbol-specific toggles (DAX pouze, NASDAQ pouze)

### 🙏 Credits

Implementováno s pomocí Claude (Anthropic) - 2025-10-02
