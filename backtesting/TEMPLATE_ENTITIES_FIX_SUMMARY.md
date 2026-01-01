# Oprava Template Entities - Regex Findall Index

**Datum:** 2025-12-28  
**Problém:** Home Assistant se nespustil kvůli `IndexError: list index out of range` v template entitách používajících `regex_findall_index` bez kontroly.

---

## ❌ Problém

Template entity v `/Volumes/config/configuration.yaml` používaly `regex_findall_index` bez kontroly, což způsobovalo chyby když:
- Entity `sensor.*_m1_regime_raw` má stav `unknown`, `unavailable`, nebo prázdný
- Regex nenajde shodu (prázdný seznam)

**Chybové logy:**
```
IndexError: list index out of range
TemplateError('IndexError: list index out of range') while processing template
```

---

## ✅ Řešení

Všechny `regex_findall_index` volání byly nahrazeny robustními variantami používajícími:

1. **Kontrola `unknown/unavailable/none/None/''`** před regex
2. **`regex_findall`** místo `regex_findall_index`
3. **Kontrola délky výsledku** (`m|length`) před přístupem k indexu
4. **Fallback hodnoty** (0 pro čísla, 'unknown'/'NA' pro text, `none` pro NaN)

---

## 📋 Opravené entity

### DAX M1:
- `sensor.dax_m1_regime_state` - state text
- `sensor.dax_m1_adx` - číslo (fallback: 0)
- `sensor.dax_m1_r2` - číslo (fallback: 0)
- `sensor.dax_m1_beta_atr` - číslo (fallback: 0)
- `sensor.dax_m1_pivot_nearest` - text (fallback: 'NA')
- `sensor.dax_m1_pivot_dist_atr` - číslo/NaN (fallback: `none`)
- `sensor.dax_m1_swing_quality` - číslo (fallback: 0)
- `sensor.dax_m1_last_impulse_atr` - číslo (fallback: 0)

### NASDAQ M1:
- `sensor.nasdaq_m1_regime_state` - state text
- `sensor.nasdaq_m1_adx` - číslo (fallback: 0)
- `sensor.nasdaq_m1_r2` - číslo (fallback: 0)
- `sensor.nasdaq_m1_beta_atr` - číslo (fallback: 0)
- `sensor.nasdaq_m1_pivot_nearest` - text (fallback: 'NA')
- `sensor.nasdaq_m1_pivot_dist_atr` - číslo/NaN (fallback: `none`)
- `sensor.nasdaq_m1_swing_quality` - číslo (fallback: 0)
- `sensor.nasdaq_m1_last_impulse_atr` - číslo (fallback: 0)

---

## 🔧 Vzorové opravy

### Před (nebezpečné):
```yaml
state: "{{ (states('sensor.nasdaq_m1_regime_raw') | regex_findall_index('adx=([0-9.]+)')) | float(0) }}"
```

### Po (robustní):
```yaml
state: >
  {% set s = states('sensor.nasdaq_m1_regime_raw') %}
  {% if s in ['unknown','unavailable','none','None',''] %}
    {{ 0 }}
  {% else %}
    {% set m = s | regex_findall('adx=([0-9.]+)') %}
    {{ (m[0] if m|length else 0) | float }}
  {% endif %}
```

---

## ✅ Výsledek

- ✅ Všechny `regex_findall_index` byly nahrazeny
- ✅ Přidána kontrola `unknown/unavailable` stavů
- ✅ Přidána kontrola délky regex výsledku
- ✅ Fallback hodnoty pro všechny případy
- ✅ Home Assistant by se nyní měl spustit bez chyb

---

## 📝 Poznámky

1. **NaN hodnoty:** Pro `pivot_dist_atr` se používá `none` místo `float('nan')`, protože `float('nan')` není správná syntaxe v Jinja2 templates.

2. **Fallback hodnoty:**
   - Číselné entity: `0`
   - Textové entity: `'unknown'` nebo `'NA'`
   - NaN hodnoty: `none`

3. **Pattern:** Všechny opravy následují stejný pattern:
   ```yaml
   {% set s = states('sensor.*_m1_regime_raw') %}
   {% if s in ['unknown','unavailable','none','None',''] %}
     {{ fallback_value }}
   {% else %}
     {% set m = s | regex_findall('pattern') %}
     {{ (m[0] if m|length else fallback_value) | filter }}
   {% endif %}
   ```

