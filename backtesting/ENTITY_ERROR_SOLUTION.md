# Řešení problému s poškozenými entitami (HTTP 400)

**Datum:** 2025-12-28  
**Status:** ⚠️ Po restartu fronta klesla, ale entity stále způsobují chyby

---

## 🔍 Aktuální stav

### ✅ Co se zlepšilo:
- **Fronta klesla** - z 5818 na 165 (po restartu)
- **Aplikace běží** - Trading Assistant se úspěšně spustil
- **Systém je stabilní** - žádné kritické chyby

### ❌ Stále problém:
- **Poškozené entity** - HTTP 400 Bad Request
- **Utility loop pomalý** - 2-3 sekundy (kvůli HTTP 400 chybám)
- **Entity se automaticky rekreují** - restart HA je nevyčistí, protože nemají `unique_id`

---

## 💡 Problém s entitami

**Problém:** Entity vytvořené přes `set_state()` API nemají `unique_id`, takže jsou "temporary" entity. Když se poškodí, HA Core restart je sice vyčistí, ale AppDaemon je okamžitě znovu vytvoří (při inicializaci), a pokud jsou poškozené, způsobují HTTP 400 chyby.

**Poškozené entity:**
- `sensor.trading_open_positions`
- `sensor.trading_daily_pnl`
- `sensor.trading_daily_pnl_percent`
- `sensor.dax_atr_current_v2`
- `sensor.nasdaq_volume_zscore_v2`
- atd.

---

## 🔧 Možná řešení

### Varianta 1: Dočasně vypnout aktualizace problematických entit ⭐

**Upravit `_safe_set_state()`** aby skákalo poškozené entity:

```python
# V main.py, v _safe_set_state() přidat whitelist problematických entit:
CORRUPTED_ENTITIES = [
    'sensor.trading_open_positions',
    'sensor.trading_daily_pnl',
    'sensor.trading_daily_pnl_percent',
    # atd.
]

def _safe_set_state(self, entity_id: str, state=None, **kwargs):
    # Skip poškozené entity
    if entity_id in CORRUPTED_ENTITIES:
        return
    # ... zbytek kódu
```

**Výhody:**
- Rychlé řešení
- Systém přestane být zpomalován HTTP 400 chybami
- Entity se neaktualizují, ale systém běží

**Nevýhody:**
- Entity nebudou aktualizovány
- Data nebudou dostupná v dashboardu

### Varianta 2: Opravit `_safe_set_state()` aby správně zachytávalo ClientResponseError

**Problém:** Kód se pokouší iterovat přes `ClientResponseError`, což způsobuje `TypeError`.

**Fix:** Upravit error handling v `_safe_set_state()`:

```python
except Exception as e:
    error_str = str(e)
    if "ClientResponseError" in error_str or isinstance(e, ClientResponseError):
        # Entity je poškozená - přeskočit
        return
    # ... další error handling
```

### Varianta 3: Použít jinou metodu pro vytváření entit (long-term řešení)

**Místo `set_state()` použít `register_entity()`** s `unique_id` - to vyžaduje větší refaktoring.

---

## 🚀 Doporučený postup (okamžitě)

**Nejrychlejší řešení:** Dočasně vypnout aktualizace poškozených entit, aby systém přestal být zpomalován.

1. **Přidat whitelist poškozených entit do `_safe_set_state()`**
2. **Aplikovat změnu**
3. **Restart AppDaemon**
4. **Systém by měl běžet rychleji**

**Poté (long-term):**
- Opravit error handling v `_safe_set_state()`
- Nebo implementovat proper entity registration s `unique_id`

---

## 📋 Závěr

**Hlavní problém není moje změna** - fronta klesla a aplikace běží.

**Skutečný problém:** Poškozené entity způsobují HTTP 400 chyby, které zpomalují systém (utility loop 2-3 sekundy).

**Řešení:** Dočasně vypnout aktualizace poškozených entit nebo opravit error handling.


