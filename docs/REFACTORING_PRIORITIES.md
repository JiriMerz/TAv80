# Refaktoring Priorities - Trading Assistant v7.0

**Datum:** 2025-01-03  
**Analýza:** Identifikace technického dluhu a architektonických problémů

## ⚠️ DŮLEŽITÉ: Omezení prostředí

**Development:** macOS (MacBook)  
**Production:** Home Assistant na Raspberry Pi 4  
**Deploy:** Ruční přes Samba share (pomalý proces)  
**Runtime:** AppDaemon addon na RPi (omezené zdroje)

**Důsledky pro refaktoring:**
- 🔴 **Velké změny = vysoké riziko** - pomalý deploy a obtížný rollback
- 🟠 **Více souborů = pomalejší start** - import overhead na RPi
- 🟡 **Samba deploy je pomalý** - preferovat malé, inkrementální změny
- 🟡 **Omezená paměť RPi** - minimalizovat duplicitní kód a importy

**Strategie:** Postupné, malé změny s možností rychlého rollbacku

---

## 🎯 5 Prioritních Kroků pro Refaktoring

### 1. **Rozdělení God Object - main.py (4055 řádků)**

**Problém:**
- `main.py` obsahuje 4055 řádků kódu - klasický "God Object" anti-pattern
- Obsahuje příliš mnoho zodpovědností:
  - Inicializace všech modulů
  - Zpracování market data
  - Signal generation pipeline
  - Auto-trading orchestration
  - Home Assistant entity management
  - Threading coordination
  - Account monitoring
  - Risk management integration
  - Test signal generation
  - Entity cleanup

**Dopad:**
- Těžká údržba a testování
- Vysoká kognitivní zátěž
- Riziko regresí při změnách
- Pomalé načítání a parsování

**Řešení:**
```
src/trading_assistant/
├── main.py (200-300 řádků) - pouze orchestrátor
├── core/
│   ├── market_data_handler.py - zpracování barů a ticků
│   ├── signal_pipeline.py - orchestrace signal generation
│   ├── auto_trading_orchestrator.py - auto-trading logika
│   └── entity_manager.py - Home Assistant entity management
├── coordination/
│   ├── thread_coordinator.py - unified threading management
│   └── event_dispatcher.py - unified event dispatching
```

**Priorita:** 🟡 STŘEDNÍ (upraveno pro RPi prostředí)

**⚠️ RPi specifické úvahy:**
- Rozdělení na více souborů = více importů = pomalejší start na RPi
- Samba deploy velkých změn = pomalý a rizikový proces
- **Doporučení:** Začít s malými, izolovanými extrakcemi (např. entity_manager jako první)

---

### 2. **Odstranění duplicitního a legacy kódu**

**Problém A: Duplicitní swing detection**
- `SwingEngine` (swings.py) - legacy, označen jako "kept for compatibility"
- `SimpleSwingDetector` (simple_swing_detector.py) - nový, měl nahradit SwingEngine
- Oba jsou importovány v main.py, ale používá se pouze SimpleSwingDetector
- SwingEngine stále existuje a zabírá místo

**Problém B: Duplicitní microstructure**
- `microstructure.py` - full NumPy verze
- `microstructure_lite.py` - fallback bez NumPy
- Fallback logika v main.py (try/except import)
- Oba soubory mají podobnou strukturu, ale duplicitní kód

**Problém C: Deprecated kód**
- `simple_order_executor.py`: `position_open` a `current_position` označeny jako DEPRECATED
- TODO komentáře v `ctrader_client.py` (řádky 1236, 1770, 1805)
- Nepoužívané metody a atributy

**Řešení:**
1. **Odstranit SwingEngine** - nahradit všechny reference SimpleSwingDetector
2. **Unifikovat microstructure** - vytvořit jednu třídu s volitelnou NumPy závislostí
3. **Vyčistit deprecated kód** - odstranit DEPRECATED atributy a metody
4. **Dokončit TODO** - implementovat nebo odstranit TODO komentáře

**Priorita:** 🔴 KRITICKÁ (upraveno - rychlá výhra, nízké riziko)

**⚠️ RPi specifické úvahy:**
- Odstranění duplicitního kódu = **snížení paměťové zátěže** na RPi
- Menší soubory = rychlejší parsování a import
- **Doporučení:** Začít ZDE - nejrychlejší výhra s minimálním rizikem

---

### 3. **Rozdělení ctrader_client.py (1800+ řádků)**

**Problém:**
- `ctrader_client.py` má 1800+ řádků
- Obsahuje příliš mnoho zodpovědností:
  - WebSocket connection management
  - Authentication flow
  - Market data subscription
  - Bar aggregation (M5)
  - Historical data bootstrap
  - Cache management
  - Account state handling
  - Position management
  - Order execution
  - Message routing
  - Thread-safe command queue

**Dopad:**
- Těžká údržba
- Složité testování
- Riziko race conditions

**Řešení:**
```
src/trading_assistant/
├── ctrader/
│   ├── client.py (300 řádků) - hlavní WebSocket client
│   ├── auth.py - authentication flow
│   ├── market_data.py - spot events, subscriptions
│   ├── bar_aggregator.py - M5 bar aggregation
│   ├── history_manager.py - bootstrap a cache
│   ├── account_handler.py - account state management
│   ├── order_handler.py - order execution
│   └── message_router.py - message routing a pairing
```

**Priorita:** 🟡 STŘEDNÍ (upraveno - komplexní, odložit po krocích 1-2)

**⚠️ RPi specifické úvahy:**
- Rozdělení ctrader_client = více importů = pomalejší start
- WebSocket client je kritický - změny vyžadují pečlivé testování
- **Doporučení:** Odložit až po úspěšném dokončení kroků 1-2

---

### 4. **Konfigurační duplicity a hardcoded hodnoty**

**Problém A: Duplicitní klíče v apps.yaml**
- `position_conflicts` definován dvakrát (řádky 20 a 272)
- Může způsobit problémy při parsování YAML

**Problém B: Hardcoded hodnoty v kódu**
- `main.py`: hardcoded thresholds (confidence >= 80.0, >= 60.0)
- `risk_manager.py`: `daily_loss_limit = 0.05` vždy přepisuje config
- `ctrader_client.py`: hardcoded timeouty a retry logika
- `edges.py`: některé thresholdy nejsou konfigurovatelné

**Problém C: Rozptýlená konfigurace**
- Některé hodnoty v apps.yaml
- Některé v kódu jako defaulty
- Některé jako konstanty na začátku souborů

**Řešení:**
1. **Opravit apps.yaml** - odstranit duplicitní `position_conflicts`
2. **Centralizovat konfiguraci** - vytvořit `config_manager.py`
3. **Odstranit hardcoded hodnoty** - vše přes config
4. **Validace konfigurace** - při startu ověřit všechny hodnoty

**Priorita:** 🟢 NÍZKÁ (ale rychlá výhra - opravit duplicity)

**⚠️ RPi specifické úvahy:**
- Oprava duplicitního `position_conflicts` = rychlá změna, žádné riziko
- Centralizace config = může počkat (neblokuje)
- **Doporučení:** Opravit duplicity okamžitě, centralizaci odložit

---

### 5. **Unifikace threading a async komunikace**

**Problém:**
- **4 různé mechanismy** pro komunikaci mezi WebSocket threadem a AppDaemon threadem:
  1. `EventBridge` - queue-based event system
  2. `ThreadSafeAppState` - thread-safe state container
  3. `_command_queue` v ctrader_client - asyncio.Queue pro příkazy
  4. `_dispatch_queue` v main.py - micro-dispatcher pro callbacks

**Dopad:**
- Složitost a riziko race conditions
- Duplicitní logika
- Těžké debugování
- Potenciální memory leaks (viz BUGFIX_THREAD_EXPLOSION.md)

**Řešení:**
```
src/trading_assistant/
├── coordination/
│   ├── unified_event_bridge.py - jediný mechanismus
│   │   ├── Event types: MARKET_DATA, ACCOUNT_UPDATE, EXECUTION, COMMAND
│   │   ├── Thread-safe queue s prioritami
│   │   ├── Metrics a monitoring
│   │   └── Automatic backpressure handling
│   └── thread_manager.py - centralizované thread lifecycle
```

**Priorita:** 🟠 VYSOKÁ (důležité pro stabilitu na RPi)

**⚠️ RPi specifické úvahy:**
- Thread explosion bug již opraven, ale 4 mechanismy = riziko
- Unifikace = **snížení paměťové zátěže** a rizika race conditions
- **Doporučení:** Důležité, ale komplexní - provést po stabilizaci kroků 1-2

---

## 📊 Souhrn Technického Dluhu

| Kategorie | Hodnota | Dopad |
|----------|---------|-------|
| **God Objects** | 2 soubory (main.py 4055, ctrader_client.py 1800) | 🔴 Kritický |
| **Duplicitní kód** | 3 oblasti (swing, microstructure, deprecated) | 🟠 Vysoký |
| **Konfigurace** | Duplicity + hardcoded hodnoty | 🟡 Střední |
| **Threading** | 4 různé mechanismy | 🟡 Střední |
| **TODO/FIXME** | 6+ míst | 🟢 Nízký |

---

## 🎯 Doporučené Pořadí Implementace (upraveno pro RPi)

### Fáze 1: Rychlé výhry (nízké riziko, okamžitý benefit)
1. **Krok 1a** - Opravit duplicitní `position_conflicts` v apps.yaml (5 min, žádné riziko)
2. **Krok 1b** - Odstranit SwingEngine (pouze import, nevyužívaný kód) - **snížení paměti**
3. **Krok 1c** - Odstranit deprecated atributy (`position_open`, `current_position`) - **snížení paměti**

### Fáze 2: Optimalizace (střední riziko, střední benefit)
4. **Krok 2a** - Unifikovat microstructure (jedna třída s volitelnou NumPy) - **snížení duplicit**
5. **Krok 2b** - Dokončit TODO komentáře (implementovat nebo odstranit)

### Fáze 3: Architektura (vysoké riziko, vysoký benefit - odložit)
6. **Krok 3** - Unifikovat threading (důležité pro stabilitu na RPi)
7. **Krok 4** - Rozdělit ctrader_client.py (komplexní, vyžaduje testování)
8. **Krok 5** - Rozdělit main.py (největší úkol, provést až po stabilizaci)

**Doporučení:** Začít s Fází 1, pokračovat Fází 2, Fázi 3 odložit na později

---

## ⚠️ Rizika Refaktoringu (RPi specifické)

1. **Breaking changes** - změny v API mezi moduly
2. **Test coverage** - potřeba testů před refaktoringem
3. **Deployment** - **pomalý Samba deploy** - velké změny jsou bolestivé
4. **Rollback plan** - možnost rychlého návratu přes Samba
5. **RPi výkon** - více souborů = pomalejší start, více importů = vyšší paměť
6. **Ruční restart** - po každém deploy musí uživatel restartovat AppDaemon

**Doporučení pro RPi prostředí:**
- ✅ **Začít s Fází 1** - rychlé výhry, minimální riziko
- ✅ **Malé, izolované změny** - max 1-2 soubory najednou
- ✅ **Testovat lokálně na macOS** před deploy
- ✅ **Deploy po malých krocích** - ne všechno najednou
- ✅ **Backup před změnami** - možnost rychlého rollbacku
- ⚠️ **Vyhnout se velkým refaktoringům** - rozdělení God Objects počkat
- ⚠️ **Minimalizovat počet souborů** - preferovat menší počet větších modulů
- ⚠️ **Sledovat paměť** - RPi má omezené zdroje

**Deploy workflow:**
1. Změna na macOS
2. Lokální test (pokud možno)
3. Deploy přes Samba (`./deploy.sh`)
4. Restart AppDaemon (ručně v HA UI)
5. Kontrola logů
6. Pokud problém → rychlý rollback přes Samba

---

## 📋 RPi Optimalizace - Specifické doporučení

### Co dělat (pro RPi):
- ✅ Odstranit nevyužívaný kód (SwingEngine, deprecated atributy)
- ✅ Snížit duplicity (microstructure unifikace)
- ✅ Opravit konfigurační chyby (duplicitní klíče)
- ✅ Minimalizovat import overhead (kombinovat související moduly)

### Co NEdělat (kvůli RPi):
- ❌ Rozdělit velké soubory na mnoho malých (více importů = pomalejší start)
- ❌ Velké refaktoringy najednou (pomalý Samba deploy, těžký rollback)
- ❌ Přidávat těžké závislosti (NumPy je OK, ale minimalizovat)
- ❌ Měnit kritické části bez testování (WebSocket client, threading)

### Kompromisní řešení:
- 🟡 Místo rozdělení na 8 souborů → rozdělit na 3-4 větší moduly
- 🟡 Místo úplné unifikace → postupná konsolidace
- 🟡 Místo velkého refaktoringu → malé, inkrementální změny

---

*Vygenerováno automatickou analýzou codebase - 2025-01-03*  
*Upraveno s ohledem na RPi prostředí a ruční Samba deploy*

