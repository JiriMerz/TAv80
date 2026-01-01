# Chování systému při zavřených trzích

## 📊 Aktuální chování

### 1. Signal Generation (process_market_data)
**Když jsou trhy zavřené:**
- ✅ Kontrola `_is_within_trading_hours(alias)` vrací `False`
- ✅ Systém loguje: `[PROCESS_DATA] {alias}: BLOCKED - Outside trading hours at {time} UTC`
- ✅ `process_market_data` se vrací early return - **signály se negenerují**
- ✅ Analýza (regime, pivots, swings, ATR) se **NEprovádí** během zavřených trhů

### 2. Status Tracking (log_status)
**Když jsou trhy zavřené:**
- ✅ Status se nastavuje na `"ANALYSIS_ONLY"` místo `"TRADING"`
- ✅ Entity `sensor.{alias}_trading_status` ukazuje správný stav
- ✅ Attributes obsahují `market_hours: false` a `signals_enabled: false`

### 3. Live Status Tracking (_publish_live_status)
**PROBLÉM:** ⚠️ 
- ❌ Původně zobrazovalo "STALE" když bar byl starší než 5 minut
- ❌ Nezohledňovalo, jestli jsou trhy zavřené
- ✅ **OPRAVENO:** Nyní kontroluje `_is_within_trading_hours()` 
- ✅ Pokud jsou trhy zavřené → status = "CLOSED" (ne "STALE")

## 🔧 Oprava aplikována

### Před opravou:
```python
# Determine status
if bar_age_sec > 300:  # 5 minutes
    status = "STALE"  # ❌ Špatně - ukazovalo STALE i když trhy byly zavřené
```

### Po opravě:
```python
# Check if markets are open for this symbol
in_trading_hours = self._is_within_trading_hours(alias) if hasattr(self, '_is_within_trading_hours') else True

# Determine status - only check for STALE if markets are open
if in_trading_hours:
    # Markets are open - check if data is fresh
    if bar_age_sec > 300:
        status = "STALE"
    ...
else:
    # Markets are closed - this is expected, don't show warning
    status = "CLOSED"  # ✅ Správně
```

## ✅ Jak to teď funguje

### Když jsou trhy otevřené:
- Bar přijde → `_last_bar_time` se aktualizuje
- Analýza proběhne → `_last_analysis_time` se aktualizuje
- Signal check proběhne → `_last_signal_check_time` se aktualizuje
- Live status ukazuje: **OK** (pokud data jsou čerstvá)

### Když jsou trhy zavřené:
- Nové bary nepřicházejí (to je očekávané)
- `process_market_data` se vůbec nevolá (early return)
- Live status ukazuje: **CLOSED** (místo STALE)
- Poslední známé časy se neaktualizují (to je v pořádku)
- Dashboard správně ukazuje, že trhy jsou zavřené

## 📝 Poznámky

1. **Data se neaktualizují** během zavřených trhů - to je správné chování
2. **Live status ukazuje "CLOSED"** - to je informativní, ne chyba
3. **Poslední časy** zůstávají z doby, kdy trhy byly otevřené - to je v pořádku
4. **Systém negeneruje signály** během zavřených trhů - správné chování

## 🎯 Výsledek

Systém se nyní chová správně během zavřených trhů:
- ✅ Negeneruje signály (správně)
- ✅ Ukazuje status "CLOSED" místo "STALE" (správně)
- ✅ Nehlásí falešné varování (správně)
- ✅ Dashboard ukazuje správný stav (správně)

