# Time Synchronization Setup

## ✅ Implementováno (2025-12-24)

Systém nyní synchronizuje čas s NTP servery pro přesné časové značky.

---

## Jak to funguje

### 1. **TimeSync třída** (`src/trading_assistant/time_sync.py`)

- Synchronizuje systémový čas s NTP servery
- Používá pool NTP serverů (pool.ntp.org, time.google.com, time.cloudflare.com)
- Vypočítává offset mezi systémovým a NTP časem
- Automatická resynchronizace každou hodinu

### 2. **Integrace do main.py**

- Inicializace při startu aplikace
- Helper metoda `get_synced_time()` pro získání synchronizovaného času
- Automatická resynchronizace každou hodinu

### 3. **Konfigurace** (`apps.yaml`)

```yaml
time_sync:
  enable_time_sync: true  # Enable NTP time synchronization
  sync_interval_seconds: 3600  # Resync every hour (3600 seconds)
```

---

## Použití

### V kódu

Místo:
```python
now = datetime.now()
```

Použij:
```python
now = self.get_synced_time()  # Synchronizovaný UTC čas
```

### Helper metoda

```python
def get_synced_time(self) -> datetime:
    """
    Vrací synchronizovaný UTC čas (s NTP korekcí)
    
    Returns:
        datetime object s timezone.utc
    """
    if hasattr(self, 'time_sync') and self.time_sync.enabled:
        return self.time_sync.now()
    return datetime.now(timezone.utc)
```

---

## NTP servery

Systém zkouší tyto servery v pořadí:
1. `pool.ntp.org` (hlavní)
2. `time.google.com`
3. `time.cloudflare.com`
4. `0.pool.ntp.org`
5. `1.pool.ntp.org`

Pokud první selže, zkusí další.

---

## Logování

Při startu uvidíš:
```
[TIME_SYNC] Starting time synchronization...
[TIME_SYNC] ✅ Synchronized with pool.ntp.org
[TIME_SYNC]   NTP time: 2025-12-24 19:30:45 UTC
[TIME_SYNC]   System time: 2025-12-24 19:30:44 UTC
[TIME_SYNC]   Offset: 1.234 seconds
[TIME_SYNC] ✅ Time synchronization enabled - will resync every hour
```

Pokud je offset > 60 sekund, uvidíš varování:
```
[TIME_SYNC] ⚠️ Large time offset detected (65.2s) - system clock may be incorrect!
```

---

## Automatická resynchronizace

- Resynchronizace probíhá automaticky každou hodinu
- Používá `run_every()` v AppDaemon
- Pokud synchronizace selže, systém použije systémový čas (fallback)

---

## Výhody

1. **Přesné časové značky**: Všechny timestampy jsou synchronizované s NTP
2. **Korekce driftu**: Automatická korekce, pokud se systémový čas posune
3. **Spolehlivost**: Fallback na systémový čas, pokud NTP selže
4. **Transparentnost**: Logování offsetu a stavu synchronizace

---

## Konfigurace

### Zapnout/vypnout

V `apps.yaml`:
```yaml
time_sync:
  enable_time_sync: true  # false pro vypnutí
  sync_interval_seconds: 3600  # Interval resynchronizace (sekundy)
```

### Vypnutí synchronizace

Pokud chceš použít pouze systémový čas:
```yaml
time_sync:
  enable_time_sync: false
```

---

## Technické detaily

### NTP protokol

- Používá UDP port 123
- Timeout: 5 sekund na server
- NTP packet format: `!12I` (12 unsigned integers)

### Offset výpočet

```python
time_offset = ntp_timestamp - system_timestamp
corrected_time = system_time + time_offset
```

### Timezone

- Všechny časy jsou v UTC
- Pro lokální čas použij `astimezone()` s požadovanou timezone

---

## Testování

Pro test synchronizace:

1. **Zkontroluj logy při startu**:
   ```
   [TIME_SYNC] ✅ Synchronized with ...
   ```

2. **Zkontroluj offset**:
   - Offset by měl být < 1 sekunda (pokud je systémový čas správně)
   - Pokud je > 60 sekund, systémový čas je pravděpodobně špatně

3. **Zkontroluj resynchronizaci**:
   - Po hodině by měla proběhnout automatická resynchronizace
   - Log: `[TIME_SYNC] Starting time synchronization...`

---

## Troubleshooting

### Synchronizace selže

**Příčiny**:
- Žádné internetové připojení
- Firewall blokuje UDP port 123
- Všechny NTP servery nedostupné

**Řešení**:
- Systém automaticky použije systémový čas (fallback)
- Zkontroluj internetové připojení
- Zkontroluj firewall nastavení

### Velký offset (> 60 sekund)

**Příčiny**:
- Systémový čas je špatně nastaven
- RTC baterie je vybitá
- Manuální změna času

**Řešení**:
- Nastav správný systémový čas
- Vyměň RTC baterii
- Systém automaticky koriguje offset

---

## Závěr

✅ **Systém nyní používá synchronizovaný čas z NTP serverů**

- Přesné časové značky pro všechny operace
- Automatická korekce driftu
- Spolehlivý fallback na systémový čas
- Transparentní logování

**Všechny časové operace nyní používají `get_synced_time()` místo `datetime.now()`**

