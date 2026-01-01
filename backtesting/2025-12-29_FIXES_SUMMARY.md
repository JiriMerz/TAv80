# Opravy provedené 2025-12-29

## 📝 Upravené soubory

### 1. `/Volumes/config/configuration.yaml`
**Hlavní konfigurační soubor Home Assistant**

**Opravy:**
- **Template entity s `regex_findall_index`** (16 entit):
  - DAX M1: `regime_state`, `adx`, `r2`, `beta_atr`, `pivot_nearest`, `pivot_dist_atr`, `swing_quality`, `last_impulse_atr`
  - NASDAQ M1: `regime_state`, `adx`, `r2`, `beta_atr`, `pivot_nearest`, `pivot_dist_atr`, `swing_quality`, `last_impulse_atr`
  - **Problém:** `regex_findall_index` způsobovalo `IndexError: list index out of range` když regex nenašel shodu
  - **Řešení:** Nahrazeno za `regex_findall` s kontrolou délky a ošetřením `unknown/unavailable`

- **Energy snapshot entity** (4 entity):
  - `sm_imp_kwh_snap`
  - `sm_exp_kwh_snap`
  - `diff_imp_kwh_snap`
  - `diff_exp_kwh_snap`
  - **Problém:** `ValueError` když hodnota byla `'unknown'` - entity s `unit_of_measurement` musí mít číselnou hodnotu
  - **Řešení:** Použito `| float(0)` místo `| default(0) | float` nebo podmínek

- **Recorder konfigurace**:
  - **Problém:** Wildcard entity ID (`sensor.*_volume_zscore`) v `exclude->entities` způsobovalo `Invalid config`
  - **Řešení:** Wildcardy přesunuty do `exclude->entity_globs`, konkrétní entity zůstaly v `exclude->entities`

---

### 2. `/Volumes/config/.storage/lovelace`
**Lovelace dashboard (storage mode)**

**Opravy:**
- Nahrazeno `|float` za `|float(0)` u všech referencí na:
  - `sensor.sm_imp_kwh_snap`
  - `sensor.sm_exp_kwh_snap`
  - `sensor.diff_imp_kwh_snap`
  - `sensor.diff_exp_kwh_snap`
- **Účel:** Zajistit, že UI nezobrazuje chyby když jsou entity `unknown`

---

### 3. `/Volumes/config/.storage/lovelace.fve_na_kopci`
**Lovelace dashboard pro FVE**

**Opravy:**
- Stejné jako u `lovelace` - nahrazeno `|float` za `|float(0)` u energy snapshot entit

---

## 📚 Vytvořené dokumentační soubory

### 4. `docs/ROBUST_TEMPLATE_ENTITIES.md`
**Dokumentace k robustním template entitám**
- Best practices pro použití regex v Home Assistant templates
- Příklady robustních variant s ošetřením `unknown/unavailable`
- Kompletní příklady pro DAX a NASDAQ M1 entity

### 5. `HA_TEMPLATE_ENTITIES.yaml`
**Příklad konfiguračního souboru s robustními template entitami**
- Ukázkové template entity pro DAX a NASDAQ M1
- Parsování ADX, R², Pivot z `regime_raw` entit

### 6. `backtesting/TEMPLATE_ENTITIES_FIX_SUMMARY.md`
**Shrnutí oprav template entit**
- Seznam všech opravených entit
- Před/po příklady
- Vzorové opravy

### 7. `backtesting/FINAL_DIAGNOSIS_AND_SOLUTION.md`
**Diagnostika a řešení problémů s HA startup**
- Možné příčiny loading screen problému
- Postup řešení krok za krokem

### 8. `backtesting/HA_WEB_INTERFACE_LOADING.md`
**Dokumentace k problému s loading screen**
- Diagnostika problému
- Rychlá řešení
- Kontrolní seznamy

---

## ✅ Výsledek

**Před opravami:**
- ❌ Home Assistant se nespouštěl kvůli `IndexError` v template entitách
- ❌ `ValueError` při renderování energy snapshot entit
- ❌ Recorder/history/energy se nespouštěly kvůli invalid config
- ❌ UI zobrazovalo chyby při `unknown` hodnotách

**Po opravách:**
- ✅ Home Assistant se spouští bez chyb
- ✅ Všechny template entity fungují robustně s ošetřením `unknown/unavailable`
- ✅ Recorder/history/energy běží správně
- ✅ UI zobrazuje správné hodnoty (0 místo chyb)

---

## 🔧 Klíčové změny

1. **`regex_findall_index` → `regex_findall` + kontrola délky**
2. **`| default(0) | float` → `| float(0)`** (pro energy entity)
3. **Wildcardy v `exclude->entities` → `exclude->entity_globs`**
4. **Přidána kontrola `unknown/unavailable/none/None/''`** před regex operacemi

---

## 📊 Statistiky

- **Opraveno entit:** 20 (16 template + 4 energy snapshot)
- **Opraveno dashboardů:** 2
- **Opraveno konfiguračních sekcí:** 1 (recorder)
- **Vytvořeno dokumentačních souborů:** 5

