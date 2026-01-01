# Deployment Checklist - Systémová Vylepšení
**Datum:** 2025-12-22  
**Status:** ✅ Implementace dokončena, připraveno k nasazení

---

## ✅ Implementované Změny

### FÁZE 1: Okamžité Vylepšení
- ✅ Zvýšené R:R ratio (min_rrr: 2.0, standard_rrr: 2.5)
- ✅ Dřívější trailing stops (breakeven: 20%, trailing: 30%)
- ✅ Vyšší quality thresholds (quality: 75, confidence: 80)
- ✅ Delší cooldown mezi signály (12 barů = 1 hodina)

### FÁZE 2: Pokročilé Vylepšení
- ✅ Partial exits na R:R 1.5:1 a 2.5:1
- ✅ Dynamic risk reduction při drawdownu >10%
- ✅ Daily loss soft cap při 1.5%

---

## 📋 Deployment Steps

### 1. ✅ Code Review
- [x] Všechny změny implementovány
- [x] Žádné linter chyby
- [x] Konfigurace aktualizována v `apps.yaml`

### 2. 🔄 Deployment (Manuální - uživatel provádí)
```bash
# 1. Zkontrolovat změny v git
git status

# 2. Commit změn (volitelné)
git add .
git commit -m "System improvements Phase 1+2: Higher R:R, better risk management"

# 3. Deploy do Home Assistant (podle vašeho workflow)
# Příklad:
# scp -r src/trading_assistant user@homeassistant:/config/appdaemon/apps/
# Nebo jiný způsob dle vašeho setupu

# 4. Restart AppDaemon na Home Assistant
ssh homeassistant
ha addons restart appdaemon
# Nebo přes HA UI: Settings → Add-ons → AppDaemon → Restart
```

### 3. 🔍 Post-Deployment Verification

#### 3.1 Zkontrolovat Logy
```bash
# Sledovat AppDaemon logy
tail -f /config/appdaemon/logs/appdaemon.log | grep -E "RISK|EDGE|TRAILING|PARTIAL_EXIT"
```

**Co hledat:**
- ✅ `[RISK] RiskManager initialized` - potvrzení inicializace
- ✅ `[EDGE] min_rrr: 2.0` - nový R:R threshold
- ✅ `[TRAILING] Breakeven: 20%, Trailing: 30%` - nové trailing nastavení
- ✅ `[PARTIAL_EXIT] Exit levels: 2 configured` - partial exits aktivní
- ❌ Žádné ERROR zprávy při startu

#### 3.2 Ověřit Konfiguraci v UI
V Home Assistant dashboard zkontrolovat:
- [ ] Entity `sensor.account_balance` se aktualizuje
- [ ] Trading assistant se správně inicializoval
- [ ] Žádné error entity

#### 3.3 Test Prvního Signálu
Při prvním signálu zkontrolovat v logách:
```
[EDGE] Signal generated - RRR validation: 2.0:1 ✅
[RISK] Drawdown adjustment: X.X% drawdown → risk adjusted
[PARTIAL_EXIT] Added position ... to management
[TRAILING] Added position ... to trailing management
```

---

## 📊 Monitoring Checklist (První Týden)

### Denní Kontroly

#### Den 1-2: Základní Ověření
- [ ] Systém běží bez chyb
- [ ] Signály se generují (méně než předtím je OK)
- [ ] Průměrná kvalita signálů >75%
- [ ] Průměrná confidence >80%
- [ ] Minimální R:R nových signálů ≥2.0

#### Den 3-5: Výkonnost
- [ ] Profit Factor sledování
- [ ] Winrate tracking
- [ ] Realizovaný R:R vs. plánovaný
- [ ] Drawdown monitoring

#### Den 6-7: Optimalizace
- [ ] Analýza equity curve
- [ ] Porovnání s předchozím měsícem
- [ ] Identifikace případných problémů

### Klíčové Metriky ke Sledování

#### Signály
- **Počet signálů/den**: Očekáváno 3-5 (místo 8-10)
- **Průměrná kvalita**: >75% (z 60%)
- **Průměrná confidence**: >80% (z 70%)
- **Minimální R:R**: Všechny ≥2.0:1

#### Trading Výkon
- **Profit Factor**: Cíl 1.35-1.50 (z 1.10)
- **Winrate**: Cíl 55-60% (z 49.6%)
- **Průměrný R:R realizovaný**: Cíl 2.0-2.5:1
- **Biggest winner vs. loser**: Cíl 2:1+ (z 1.21:1)

#### Risk Management
- **Max drawdown**: Cíl <-15k Kč (z -30k)
- **Daily loss soft cap**: Funguje při 1.5%
- **Dynamic risk reduction**: Aktivuje se při drawdownu >10%
- **Partial exits**: Spouští se na R:R 1.5:1 a 2.5:1

---

## ⚠️ Co Sledovat a Kdy Zasáhnout

### 🟢 Vše v Pořádku
- Signály se generují (i když méně)
- Kvalita signálů >75%
- R:R všech signálů ≥2.0
- Trailing stops se aktivují při 30% profit
- Partial exits se spouštějí na správných úrovních

### 🟡 Pozor - Sledovat
- Příliš málo signálů (<2/den po 3 dny) → možná příliš přísné thresholdy
- Winrate <50% po 20+ trades → možná problém s entry timing
- Drawdown >20k Kč → zkontrolovat risk reduction aktivaci

### 🔴 Zásah Nutný
- Systém negeneruje žádné signály po 2 dny → příliš přísné thresholdy, snížit min_rrr na 1.8
- Winrate <40% po 30+ trades → problém s entry/exit logikou
- Drawdown >30k Kč → problém s risk managementem

---

## 🔧 Rollback Plán (Pokud Potřeba)

### Rychlý Rollback
Pokud potřebujete vrátit změny:

1. **Vratit R:R thresholdy:**
```yaml
edges:
  min_rrr: 1.2  # Vrátit z 2.0
  standard_rrr: 2.0  # Vrátit z 2.5
```

2. **Vratit quality thresholds:**
```yaml
edges:
  min_signal_quality: 60  # Vrátit z 75
  min_confidence: 70  # Vrátit z 80
  min_bars_between_signals: 6  # Vrátit z 12
```

3. **Vypnout nové funkce:**
```yaml
partial_exits:
  enabled: false  # Vypnout partial exits

risk_adjustments:
  drawdown_reduction_enabled: false  # Vypnout drawdown reduction
```

4. **Restart AppDaemon**

---

## 📝 Poznámky

### Očekávané Změny
1. **Méně signálů** - to je OK, znamená to selektivnější vstupy
2. **Vyšší kvalita** - signály by měly být lepší
3. **Lepší R:R** - všechny signály mají minimálně 2.0:1
4. **Lepší ochrana zisku** - trailing stops a partial exits

### Postupný Monitoring
- **Týden 1**: Základní funkčnost
- **Týden 2-4**: Výkonnost a optimalizace
- **Měsíc 1**: Porovnání s předchozím měsícem

### Kontaktní Body
- Pokud se objeví problémy, zkontrolovat logy
- Sledovat equity curve denně
- Porovnávat metriky týdně

---

## 🎯 Cílové Metriky (Po 1 Měsíci)

- **Profit Factor**: 1.60-1.80
- **Winrate**: 55-60%
- **Max Drawdown**: <-10k Kč
- **Return**: 6-8% měsíčně
- **Trades/měsíc**: 80-100 (z 125)
- **Průměrný R:R**: 2.0-2.5:1

---

*Checklist vytvořen: 2025-12-22*  
*Next review: Po 1 týdnu testování*

