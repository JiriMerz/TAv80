# Live Status Informace - Doporučení pro Dashboard

## 🎯 Navržené Live Status Informace

### 1. **System Health Status** ⭐ TOP PRIORITY
**Co zobrazuje:**
- Poslední přijatý bar (timestamp)
- Poslední analýza (timestamp)
- Poslední kontrola signálu (timestamp)
- Status: OK / WARNING / ERROR

**Užitečnost:** Vysoká - okamžitě vidíte, jestli systém funguje a zpracovává data

### 2. **Signal Detection Status**
**Co zobrazuje:**
- Poslední pokus o detekci signálu
- Důvod blokování (pokud žádný signál)
- Počet barů od posledního signálu
- Cooldown status

**Užitečnost:** Vysoká - vidíte, proč nejsou generovány signály

### 3. **Data Freshness**
**Co zobrazuje:**
- Stáří posledního baru (sekundy/minuty)
- Stáří poslední ceny (sekundy/minuty)
- Status: Fresh / Stale / No Data

**Užitečnost:** Střední - detekce problémů s připojením

### 4. **Event Queue Status**
**Co zobrazuje:**
- Počet eventů v queue
- Typy eventů (bars, prices, executions)
- Queue health: OK / Warning / Critical

**Užitečnost:** Střední - monitoring výkonu systému

### 5. **Last Activity Timeline**
**Co zobrazuje:**
- Timeline posledních aktivit:
  - Last bar: 2s ago
  - Last analysis: 5s ago
  - Last signal check: 10s ago
  - Last error: None / 5m ago

**Užitečnost:** Vysoká - kompletní přehled o aktivitě systému

## 💡 Doporučení

**Doporučuji implementovat:**

1. **System Health Status Card** - nejdůležitější, dá okamžitý přehled
2. **Last Activity Timeline** - užitečné pro debugging
3. **Signal Detection Status** - důležité pro pochopení, proč nejsou signály

Tyto tři dají kompletní přehled o stavu systému bez zahlcení informacemi.

## 🔧 Implementace

Navrhnu kód pro publikování těchto statusů a pak přidám karty do dashboardu.

