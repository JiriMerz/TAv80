# Home Assistant Recorder Configuration

## ⚠️ Operační Riziko: HA Recorder Spam

Pokud systém zapisuje vysokofrekvenční data (tick data, volume metrics) do HA entit každých 5 sekund, může to nafouknout databázi Home Assistanta (SQLite/MariaDB) o gigabajty za týden a odrovnat SD kartu (pokud jsi na RPi).

## ✅ Řešení: Exclude High-Frequency Entities

### 1. Přidat do `configuration.yaml` v Home Assistant:

```yaml
recorder:
  exclude:
    entities:
      # High-frequency trading data (updates every 5 seconds)
      - sensor.*_volume_zscore
      - sensor.*_tick_data
      - sensor.*_microstructure
      - sensor.*_liquidity_score
      - sensor.*_vwap_distance
      - sensor.*_volume_zscore
      # Event queue metrics (updates frequently)
      - sensor.event_queue_metrics
    # Or exclude entire domain (more aggressive)
    # domains:
    #   - sensor  # Excludes ALL sensors (not recommended)
```

### 2. Nebo použít entity attributes:

V kódu můžete přidat `recorder: exclude` do entity attributes:

```python
self._safe_set_state("sensor.volume_zscore", 
                     state=value,
                     attributes={
                         "friendly_name": "Volume Z-Score",
                         "recorder": "exclude"  # Exclude from recorder
                     })
```

### 3. Doporučená konfigurace:

**Exclude (neukládat do historie):**
- `sensor.*_volume_zscore` - Volume metrics
- `sensor.*_tick_data` - Tick data
- `sensor.*_microstructure` - Microstructure metrics
- `sensor.event_queue_metrics` - Queue metrics

**Include (ukládat do historie):**
- `sensor.account_balance` - Account balance
- `sensor.daily_pnl` - Daily P&L
- `binary_sensor.ctrader_connected` - Connection status
- `sensor.*_regime` - Market regime
- `sensor.*_swing_quality` - Swing quality

## 📊 Očekávaný dopad

**Před exclude:**
- ~1000 entity updates/minutu
- ~1.4M updates/den
- ~10GB databáze/týden (na RPi může být problém)

**Po exclude:**
- ~100 entity updates/minutu (pouze důležité metriky)
- ~144K updates/den
- ~1GB databáze/týden (rozumné)

## ✅ Implementace

Tato konfigurace musí být přidána **ručně** do `configuration.yaml` v Home Assistant, protože AppDaemon nemůže měnit HA konfiguraci.

**Status**: Dokumentace připravena, čeká na ruční přidání do HA konfigurace.

