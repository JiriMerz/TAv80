# Robust Template Entities - Best Practices

**Datum:** 2025-12-28  
**Účel:** Bezpečné použití regex v Home Assistant template entitách

---

## ❌ Problém: `regex_findall_index` bez kontroly

**Nebezpečné použití:**
```yaml
# ❌ ŠPATNĚ - může způsobit chybu, pokud regex nenajde shodu
{{ states('sensor.nasdaq_m1_regime_raw') | regex_findall_index('adx=([0-9.]+)', 0) | float }}
```

**Problémy:**
- Pokud regex nenajde shodu, `regex_findall_index` vrátí `None` nebo prázdný seznam
- `float(None)` způsobí chybu
- Neřeší stavy `unknown`, `unavailable`, `None`, `''`

---

## ✅ Řešení: Robustní varianty

### 1. Robustní číslo (s fallback na 0)

```yaml
{% set s = states('sensor.nasdaq_m1_regime_raw') %}
{% if s in ['unknown','unavailable','none','None',''] %}
  {{ 0 }}
{% else %}
  {% set m = s | regex_findall('adx=([0-9.]+)') %}
  {{ (m[0] if m|length else 0) | float }}
{% endif %}
```

**Výhody:**
- ✅ Kontroluje `unknown/unavailable/none/None/''` před regex
- ✅ Kontroluje, zda regex našel shodu (`m|length`)
- ✅ Fallback na `0` pokud regex nenajde shodu
- ✅ Bezpečná konverze na `float`

---

### 2. Robustní text (s fallback na 'NA')

```yaml
{% set s = states('sensor.nasdaq_m1_regime_raw') %}
{% if s in ['unknown','unavailable','none','None',''] %}
  {{ 'NA' }}
{% else %}
  {% set m = s | regex_findall('pivot=([A-Z0-9]+|NA)') %}
  {{ m[0] if m|length else 'NA' }}
{% endif %}
```

**Výhody:**
- ✅ Kontroluje `unknown/unavailable/none/None/''` před regex
- ✅ Kontroluje, zda regex našel shodu (`m|length`)
- ✅ Fallback na `'NA'` pokud regex nenajde shodu

---

## 📋 Kompletní příklady pro Trading Assistant

### ADX hodnota z regime_raw

```yaml
template:
  - sensor:
      - name: "DAX M1 ADX"
        unique_id: dax_m1_adx
        state: >
          {% set s = states('sensor.dax_m1_regime_raw') %}
          {% if s in ['unknown','unavailable','none','None',''] %}
            {{ 0 }}
          {% else %}
            {% set m = s | regex_findall('adx=([0-9.]+)') %}
            {{ (m[0] if m|length else 0) | float }}
          {% endif %}
        unit_of_measurement: ""
        device_class: none

  - sensor:
      - name: "NASDAQ M1 ADX"
        unique_id: nasdaq_m1_adx
        state: >
          {% set s = states('sensor.nasdaq_m1_regime_raw') %}
          {% if s in ['unknown','unavailable','none','None',''] %}
            {{ 0 }}
          {% else %}
            {% set m = s | regex_findall('adx=([0-9.]+)') %}
            {{ (m[0] if m|length else 0) | float }}
          {% endif %}
        unit_of_measurement: ""
        device_class: none
```

---

### R² hodnota z regime_raw

```yaml
template:
  - sensor:
      - name: "DAX M1 R²"
        unique_id: dax_m1_r2
        state: >
          {% set s = states('sensor.dax_m1_regime_raw') %}
          {% if s in ['unknown','unavailable','none','None',''] %}
            {{ 0 }}
          {% else %}
            {% set m = s | regex_findall('r2=([0-9.]+)') %}
            {{ (m[0] if m|length else 0) | float }}
          {% endif %}
        unit_of_measurement: ""
        device_class: none

  - sensor:
      - name: "NASDAQ M1 R²"
        unique_id: nasdaq_m1_r2
        state: >
          {% set s = states('sensor.nasdaq_m1_regime_raw') %}
          {% if s in ['unknown','unavailable','none','None',''] %}
            {{ 0 }}
          {% else %}
            {% set m = s | regex_findall('r2=([0-9.]+)') %}
            {{ (m[0] if m|length else 0) | float }}
          {% endif %}
        unit_of_measurement: ""
        device_class: none
```

---

### Pivot hodnota z regime_raw

```yaml
template:
  - sensor:
      - name: "DAX M1 Pivot"
        unique_id: dax_m1_pivot
        state: >
          {% set s = states('sensor.dax_m1_regime_raw') %}
          {% if s in ['unknown','unavailable','none','None',''] %}
            {{ 'NA' }}
          {% else %}
            {% set m = s | regex_findall('pivot=([A-Z0-9]+|NA)') %}
            {{ m[0] if m|length else 'NA' }}
          {% endif %}
        device_class: none

  - sensor:
      - name: "NASDAQ M1 Pivot"
        unique_id: nasdaq_m1_pivot
        state: >
          {% set s = states('sensor.nasdaq_m1_regime_raw') %}
          {% if s in ['unknown','unavailable','none','None',''] %}
            {{ 'NA' }}
          {% else %}
            {% set m = s | regex_findall('pivot=([A-Z0-9]+|NA)') %}
            {{ m[0] if m|length else 'NA' }}
          {% endif %}
        device_class: none
```

---

## 🔍 Alternativní přístup: `regex_search` (pokud je k dispozici)

Pokud Home Assistant podporuje `regex_search` (který vrací první shodu přímo), můžeš použít:

```yaml
{% set s = states('sensor.nasdaq_m1_regime_raw') %}
{% if s in ['unknown','unavailable','none','None',''] %}
  {{ 0 }}
{% else %}
  {% set m = s | regex_search('adx=([0-9.]+)') %}
  {{ (m if m else 0) | float }}
{% endif %}
```

**Poznámka:** `regex_search` nemusí být dostupný ve všech verzích Home Assistant. Použij `regex_findall` s kontrolou délky jako bezpečnější variantu.

---

## 📝 Shrnutí pravidel

1. **Vždy kontroluj `unknown/unavailable/none/None/''` před regex**
2. **Vždy kontroluj délku výsledku regex (`m|length`)**
3. **Vždy použij fallback hodnotu** (0 pro čísla, 'NA' pro text)
4. **Nikdy nepoužívej `regex_findall_index` bez kontroly**
5. **Preferuj `regex_findall` + kontrola délky** před `regex_findall_index`

---

## 🎯 Architektonicky nejčistší varianta

```yaml
{% set s = states('sensor.nasdaq_m1_regime_raw') %}
{% if s in ['unknown','unavailable','none','None',''] %}
  {{ 0 }}
{% else %}
  {% set m = s | regex_findall('adx=([0-9.]+)') %}
  {{ (m[0] if m|length else 0) | float }}
{% endif %}
```

**Tato varianta je:**
- ✅ Robustní (řeší všechny edge cases)
- ✅ Čitelná (jasná logika)
- ✅ Bezpečná (nikdy nezpůsobí chybu)
- ✅ Konzistentní (stejný pattern pro všechny podobné entity)

