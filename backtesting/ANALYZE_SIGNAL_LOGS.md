# Signal Log Analysis Guide

## Purpose
This script analyzes AppDaemon logs to identify why trading signals were not generated.

## Usage

### Option 1: Run locally
```bash
cd /Users/jirimerz/Projects/TAv80
python3 backtesting/analyze_signal_logs.py <log_file_path>
```

### Option 2: Analyze from HA logs
If you have HA logs mounted or copied:
```bash
python3 backtesting/analyze_signal_logs.py /Volumes/addon_configs/a0d7b954_appdaemon/logs/appdaemon.log
```

### Option 3: Analyze recent logs only
To analyze just the last N lines:
```bash
tail -1000 /path/to/appdaemon.log | python3 backtesting/analyze_signal_logs.py /dev/stdin
```

## What it detects

The script identifies these blocking conditions:

1. **System-level blocking** (in `process_market_data`):
   - cTrader not connected
   - Analysis not running
   - Insufficient bars
   - Active tickets
   - Outside trading hours
   - Risk manager blocking

2. **Signal detection blocking** (in `detect_signals`):
   - **STRICT REGIME FILTER**: Both regime and EMA34 must be in TREND with same direction
   - **SWING QUALITY**: Swing quality below minimum threshold
   - **PULLBACK ZONE**: Not in pullback zone during trends
   - **SIGNAL QUALITY**: Quality/confidence below minimum threshold
   - **MICROSTRUCTURE**: Poor market conditions (liquidity/volume)
   - **COOLDOWN**: Signal cooldown period active

## Output

The script provides:
- Summary of signal detection attempts
- Blocking reasons with frequency
- Last detected regime state
- Recommendations for each blocking reason

## Example Output

```
📊 Analyzing log file: appdaemon.log
📝 Total lines: 50000

🚫 Line 1523: NASDAQ - Strict regime filter blocked
🚫 Line 1524: NASDAQ - Not in pullback zone

================================================================================
📊 SUMMARY
================================================================================

🔍 Signal detection attempts: 25

🚫 Blocking reasons found: 2 categories

  • Strict regime filter: 15 occurrence(s)
    Line 1523: 🚫 [STRICT_FILTER] BLOCKED: regime=RANGE, EMA34=UP, reasons=...

  • Not in pullback zone: 10 occurrence(s)
    Line 1524: ⏭️ [PATTERN_DETECT] Skipping - not in pullback zone (trend: UP)

📈 Last detected regime state:
   regime: RANGE
   confidence: 50.0
   ema34_trend: UP

================================================================================
💡 RECOMMENDATIONS
================================================================================
  • Regime and EMA34 must both confirm trend direction
    Check regime state and EMA34 trend alignment
    To disable: Set strict_regime_filter: false in config
  • System is in trend but price is not at pullback level
    This is expected behavior - signals only in pullback zones during trends
```

## Common Issues

### No signals generated even though market is trending
- Check if `STRICT REGIME FILTER` is blocking (most common)
- Verify regime state vs EMA34 trend alignment
- Consider disabling strict filter for testing: `strict_regime_filter: false`

### Signals blocked by "Not in pullback zone"
- This is expected behavior in trends
- System only generates signals at pullback levels
- Price must retrace to entry zone before signal is generated

### Microstructure quality blocking
- Market conditions are suboptimal (low liquidity/volume)
- Wait for better market conditions
- Or adjust `min_liquidity_score` in config

