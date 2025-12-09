# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is **TAv70**, an automated trading assistant for AppDaemon/Home Assistant that trades DAX (GER40) and NASDAQ (US100) via cTrader WebSocket API. The system implements a wide stops strategy with M5 (5-minute) timeframe, using advanced market microstructure analysis, regime detection, and risk management.

**Key Architecture**: Python-based event-driven trading bot that runs as an AppDaemon app, with thread-safe state management for WebSocket data and multi-symbol concurrent position handling.

## Core Configuration

- **src/apps.yaml**: Single source of truth for all configuration (trading hours, risk parameters, symbol specs, stop loss/take profit bands, auto-trading settings)
- No requirements.txt, setup.py, or pyproject.toml - dependencies managed externally
- Secrets referenced via `!secret` syntax (ws_uri, client_id, client_secret, access_token, etc.)

## Project Structure

**Development (macOS)**:
```
TAv70/
├── src/                    # 📦 DEPLOY FOLDER (→ HA)
│   ├── trading_assistant/  # Production code
│   └── apps.yaml          # Configuration
├── analytics/             # 📊 ANALYTICS (local only, NOT deployed)
│   ├── analyze_trades.py              # Simple: decision log only
│   ├── analyze_trades_with_ctrader.py # Advanced: match with cTrader
│   ├── statements/        # cTrader CSV exports
│   ├── logs/              # Synced from HA (/config/analytics/logs/)
│   └── reports/           # Generated CSV/Excel reports
├── docs/                  # 📚 DOCUMENTATION
├── deploy.sh              # 🚀 Deploy script
└── README.md              # Quick start guide
```

**Production (Home Assistant)**:
```
/config/appdaemon/
├── apps/
│   └── trading_assistant/  # ← Deployed from src/
└── apps.yaml              # ← Deployed from src/

/config/analytics/
└── logs/
    └── trade_decisions.jsonl  # ← Auto-generated
```

## Architecture Components

### Main Entry Point
- **main.py**: `TradingAssistant(hass.Hass)` - AppDaemon app class
  - `ThreadSafeAppState`: Thread-safe WebSocket data container (positions, prices, balance)
  - Orchestrates all modules via dependency injection
  - Runs on AppDaemon's main thread, coordinates WebSocket client in background thread

### Market Data & Execution
- **ctrader_client.py**: `CTraderClient` - WebSocket client for cTrader OpenAPI v2
  - JSON payloadType constants (PT_APPLICATION_AUTH_REQ, PT_SPOT_EVENT, etc.)
  - M5 bar aggregation from spot ticks
  - Full authentication flow: Application → Account → Subscription
  - Runs in background thread via asyncio event loop

- **ctrader_adapter.py**: Protocol adapter layer (if WebSocket protocol changes)

### Signal Generation Pipeline
1. **regime.py**: `RegimeDetector` - Ensemble voting (ADX + Linear Regression + optional Hurst)
   - Classifies market as TREND_UP/TREND_DOWN/RANGE/UNKNOWN
   - No NumPy dependency - pure Python math

2. **microstructure.py**: `MicrostructureAnalyzer` - Time-of-day normalized analysis
   - Volume profile, VWAP, liquidity scoring
   - Opening Range Breakout (ORB) detection with progressive updates
   - Falls back to **microstructure_lite.py** if NumPy unavailable

3. **pivots.py**: `PivotCalculator` - Daily/weekly pivot points
   - Standard pivots (R1/R2/R3, S1/S2/S3)
   - Pivot confluence detection for swing validation

4. **swings.py**: `SwingEngine` - ATR-based swing high/low detection
   - Multi-timeframe ATR multipliers (M1: 0.5, M5: 1.2, M15: 1.5)
   - Pivot-enhanced validation (use_pivot_validation: true)

5. **pullback_detector.py**: `PullbackDetector` - Fibonacci retracement analysis
   - Detects pullbacks to structure levels (swings, VWAP, pivots)
   - Confluence scoring with momentum divergence

6. **edges.py**: `EdgeDetector` - Primary signal generation
   - Pattern detection: PIN_BAR, ENGULFING, INSIDE_BAR, MOMENTUM
   - Wide stops strategy with dynamic SL/TP calculation
   - Swing-based, ATR-based, and static wide stop methods
   - Pivot interference handling (quality penalties, RRR adjustments)

7. **signal_manager.py**: `SignalManager` - Signal lifecycle management
   - States: PENDING → TRIGGERED → EXECUTED/EXPIRED/MISSED/CANCELLED
   - Validity periods (aggressive: 2 bars, normal: 4, patient: 6, limit: 12)
   - Signal history and notifications

### Risk Management & Execution
- **risk_manager.py**: `RiskManager` - Position sizing and portfolio risk
  - Flexible risk per trade: 0.4-0.6% based on signal quality (base: 0.5%)
  - Multiple adjustment factors: quality, regime, volatility, position scaling
  - Margin monitoring (max 80% usage)
  - Trading hours validation per symbol

- **position_sizer.py**: Legacy position sizing (may be deprecated)

- **simple_order_executor.py**: `SimpleOrderExecutor` - MVP auto-trading orchestrator
  - Coordinates time_manager, balance_tracker, risk_manager, daily_risk_tracker
  - Market orders only (no limit orders in MVP)
  - Per-trade risk: 0.5%, Daily limit: 4%
  - Max concurrent positions: 3

- **single_order_executor.py**: Alternative single-order executor

- **balance_tracker.py**: `BalanceTracker` - Real-time account balance tracking
  - `update_from_trader_res()`: Updates balance from PT_TRADER_RES (primary method)
  - `update_from_reconcile()`: Legacy support for RECONCILE_REQ responses
  - Automatically loads balance on every restart via PT_TRADER_RES callback

- **daily_risk_tracker.py**: `DailyRiskTracker` - Daily loss limit enforcement (5%)

- **account_state_monitor.py**: `AccountStateMonitor` - Event-driven account updates
  - update_on_execution_only: true (event-driven mode)
  - Fallback periodic updates if needed

- **time_based_manager.py**: `TimeBasedSymbolManager` - DAX/NASDAQ session switching
  - DAX: 09:00-15:30 CET
  - NASDAQ: 15:30-22:00 CET
  - Auto-closes positions on symbol switch

### Advanced Features
- **event_bridge.py**: `EventBridge` - Event bus for module communication

### Trade Decision Logging & Analytics
- **trade_decision_logger.py**: `TradeDecisionLogger` - Production logging component
  - **Daily log files**: `/config/analytics/logs/trade_decisions_YYYY-MM-DD.jsonl` (HA production)
  - Creates new log file each day automatically with date in filename
  - Captures: signal quality, market context, decision reasons, microstructure factors, risk metrics
  - JSONL format: One JSON object per line for easy streaming analysis
  - Automatically called by `SimpleOrderExecutor` after position opens

**Analytics (macOS development only)**:
1. **analyze_trades.py**: Simple analytics without cTrader matching
   - Quick overview of trade decisions from daily logs
   - Summary stats, breakdown by categories (trend, ORB, liquidity, etc.)
   - CSV export for basic analysis
   - Usage:
     ```bash
     python3 analytics/analyze_trades.py                    # Today's trades
     python3 analytics/analyze_trades.py 2025-10-08         # Specific date
     python3 analytics/analyze_trades.py --all --detailed   # All dates with details
     ```

2. **analyze_trades_with_ctrader.py**: Advanced analytics with P/L matching
   - Matches daily decision logs with cTrader export CSV
   - Auto-detects date from cTrader filename (e.g., `cT_xxx_2025-10-08.csv`)
   - Calculates win rates, profit factors, R-multiples
   - Finds optimal parameter thresholds for `apps.yaml`
   - Excel reports with performance by setup type, quality ranges, decision factors
   - Usage:
     ```bash
     # Auto-detect date from filename
     python3 analytics/analyze_trades_with_ctrader.py statements/cT_xxx_2025-10-08.csv

     # Explicit date
     python3 analytics/analyze_trades_with_ctrader.py statements/cT_xxx.csv 2025-10-08
     ```

**Workflow**:
1. **Production logging** (automatic): Trading system creates daily files on HA
   - Location: `/config/analytics/logs/trade_decisions_2025-10-08.jsonl`
   - New file each day with date in filename

2. **Manual log download** (user does this manually):
   ```bash
   # Option 1: If /Volumes mounted
   cp /Volumes/addon_configs/a0d7b954_appdaemon/analytics/logs/trade_decisions_*.jsonl \
      /Users/jirimerz/Projects/TAv70/analytics/logs/

   # Option 2: Via rsync/scp if needed
   rsync -av /Volumes/addon_configs/a0d7b954_appdaemon/analytics/logs/ \
             /Users/jirimerz/Projects/TAv70/analytics/logs/
   ```

3. **Export from cTrader** (manual):
   - History → Export CSV → save to `analytics/statements/cT_xxx_YYYY-MM-DD.csv`

4. **Run analytics** (local macOS only - NOT on HA RPi):
   ```bash
   # Simple analysis
   python3 analytics/analyze_trades.py 2025-10-08 --detailed

   # Advanced with cTrader matching (auto-detects date from filename)
   python3 analytics/analyze_trades_with_ctrader.py statements/cT_xxx_2025-10-08.csv
   ```

**IMPORTANT**: Analytics scripts read from LOCAL `analytics/logs/` directory only. They do NOT connect to HA directly. User must manually download logs first.

## Symbol Specifications

### DAX (GER40, symbol_id: 203)
- Pip position: 2 (100 pips per point)
- Pip value: 0.24 CZK per lot
- Margin: 29,062 CZK per lot
- Commission: 4.20 CZK per lot
- SL anchor: 4000 pips ± 25% (3000-5000 pips)
- TP target: 2.0 RRR
- Target position: 12 lots (range: 8-20)
- Max intraday TP: 50 points

### NASDAQ (US100, symbol_id: 208)
- Pip position: 2 (100 pips per point)
- Pip value: 0.20 CZK per lot
- Margin: 24,530 CZK per lot
- Commission: 4.20 CZK per lot
- SL anchor: 5000 pips ± 25% (3750-6250 pips)
- TP target: 2.0 RRR
- Target position: 10 lots (range: 8-20)
- Max intraday TP: 60 points

## Stop Loss/Take Profit Strategy

**Wide Stops with Band System** (replaces fixed limits):
1. **Swing-based** (priority 1): Stop below/above swing levels + buffer
2. **ATR-based** (priority 2): 2×ATR optimal (min: 1.5×ATR, max: 3×ATR)
3. **Static wide** (priority 3): Fallback to anchor ± band

All stops adjusted for:
- Pivot interference (±0.15 ATR buffer)
- Round number proximity (quality penalties)
- Market structure (pivot_influence: 0.3, atr_influence: 0.4, swing_influence: 0.3)

## Key Configuration Patterns

### Auto-Trading Control
```yaml
auto_trading:
  enabled: true
  per_trade_risk_pct: 0.005  # 0.5%
  daily_risk_limit_pct: 0.04  # 4%
  max_concurrent_positions: 3
```

### Position Conflict Strategy
```yaml
position_conflicts:
  strategy: "SAME_DIRECTION_ONLY"
  allow_same_direction_scaling: true
  block_opposite_direction: true
```

### Performance Tuning
```yaml
performance:
  enable_adaptive_dispatch: true
  base_dispatch_interval: 0.05  # 50ms
  max_queue_size: 300
  emergency_queue_size: 800
```

## Development Notes

### Deployment Workflow
This is an AppDaemon app deployed from `src/` to Home Assistant:

**IMPORTANT: User does manual deployment - DO NOT use deploy.sh script!**

```bash
# Edit code
code src/trading_assistant/edges.py

# User deploys manually (do NOT attempt automated deployment)
# After user confirms deployment:

# Restart AppDaemon on HA
ssh homeassistant
ha addons restart appdaemon
```

See [README.md](../README.md) for complete deployment guide.

### Testing Signals
Use test_signals configuration in apps.yaml:
```yaml
test_signals:
  default_quality: 75
  default_confidence: 75
  rrr_ratio: 2.0
  dax_sl_multiplier: 0.9
  nasdaq_sl_multiplier: 1.0
```

### Thread Safety
Always use `ThreadSafeAppState` locks when accessing WebSocket data from main thread:
- `_pos_lock` for positions
- `_px_lock` for prices
- `_bal_lock` for balance

### Module Dependencies
- **microstructure.py (FULL)**: Uses NumPy/Pandas for statistical calculations (mean, std, percentile)
- **microstructure_lite.py (LITE)**: Pure Python fallback using `statistics` module
- Try/except fallback automatically selects version based on NumPy availability
- Check `SPRINT2_VERSION` variable in main.py to see which loaded ("FULL" or "LITE")
- HA RPi AppDaemon typically runs LITE mode (NumPy not available in that environment)

### cTrader Message Types
Reference PT_* constants in ctrader_client.py for all WebSocket payloadType codes. JSON protocol uses:
- PT_TRADER_REQ/RES (2124/2125): Primary method for account balance, equity, margin, and positions
- PT_DEAL_LIST_REQ/RES (2133/2134): Daily deals for realized PnL verification
- Account balance is automatically fetched via PT_TRADER_REQ on every startup in `connect_and_stream()` → `_get_account_snapshot()`

### Time Handling
- All timestamps must be timezone-aware (use `timezone.utc`)
- Trading hours in CET (Europe/Prague)
- Use `ensure_datetime()` helper in microstructure.py for conversions

### Quality Thresholds
- Minimum swing quality: 25% (lowered for testing)
- Minimum signal quality: 60%
- Minimum confidence: 70%
- Minimum RRR: 0.2 (TESTING ONLY - production: 1.5)

### Historical Bootstrap
```yaml
use_historical_bootstrap: true
history_cache_dir: "./cache"
history_bars_count: 300
history_max_age_minutes: 60
```
Pre-loads 300 bars (25 hours of M5 data) for immediate analysis on startup.

## Debugging Tips

1. Check log_level in apps.yaml (INFO/DEBUG)
2. Monitor queue sizes for performance issues (emergency_queue_size: 800)
3. Verify symbol_id_overrides if WebSocket subscription fails
4. Review account_state_monitor events for execution tracking
5. Use signal_manager history (max_history: 100) to debug missed signals
