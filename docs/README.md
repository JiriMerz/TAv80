# Trading Assistant v2.0 - Sprint 2 Enhanced

Automatizovaný trading systém pro Home Assistant s cTrader integrací.

**Status:** ✅ Production Ready
**Datum:** 2025-10-28
**Platforma:** Home Assistant OS 16.2 + AppDaemon 4.5.12

---

## 🎯 Co to dělá

Trading Assistant automaticky:
- 📊 Analyzuje market data z cTrader (DAX, NASDAQ)
- 🎲 Generuje trading signály (edge detection, ORB, swings)
- 💰 Počítá position sizing s risk managementem
- 🤖 Exekuuje obchody automaticky (optional)
- 📈 Trackuje balance a daily PnL
- 🔔 Posílá notifikace do Home Assistant

---

## 📚 Dokumentace

### Quick Start:
1. **[APPDAEMON_SETUP.md](./APPDAEMON_SETUP.md)** - Kompletní setup guide
   - Instalace a konfigurace
   - Troubleshooting
   - Known issues
   - Quick fix commands

2. **[DEPLOY_README.md](./DEPLOY_README.md)** - Deployment workflow
   - Jak deployovat změny
   - Deploy script usage
   - Checklist

### Status & Features:
3. **[STATUS_REPORT.md](./STATUS_REPORT.md)** - Současný stav systému
   - Co funguje
   - Co bylo vyřešeno dnes
   - Testovací výsledky
   - Architecture overview
   - Next steps

4. **[FEATURES.md](./FEATURES.md)** - Feature dokumentace
   - Signal re-evaluation (🆕 2025-10-28)
   - Technical implementation
   - Use cases
   - Monitoring

---

## 🚀 Quick Start

### 1. Připoj Samba share
```bash
# Finder → Go → Connect to Server
smb://homeassistant.local/addon_configs
```

### 2. Udělaj změny lokálně
```bash
cd /Users/jirimerz/Projects/TAv70/src/trading_assistant
# Edit your Python files...
```

### 3. Deploy
```bash
cd /Users/jirimerz/Projects/TAv70

# First check what will be deployed
./deploy.sh --dry-run

# Deploy to Home Assistant
./deploy.sh
```

### 4. Restart AppDaemon
```
Settings → Add-ons → AppDaemon → RESTART
```

### 5. Check logs
```bash
tail -f /Volumes/addon_configs/a0d7b954_appdaemon/logs/appdaemon.log
```

---

## 📊 Current Status (28.10.2025)

### ✅ Fully Functional:
- cTrader WebSocket connection
- Real-time bar data (M5)
- Signal generation (Edge, ORB, Swings)
- Risk management & position sizing
- Auto-trading execution
- **🆕 Signal re-evaluation** (automatic retry of rejected signals)
- Account monitoring & PnL tracking

### ⚠️ Known Issues (Low Priority):
- ClientResponseError warnings (cosmetic, doesn't affect functionality)

---

## 🏗️ Architecture

```
Trading Assistant
├── cTrader WebSocket Client ──→ Market Data (bars, ticks)
├── Analysis Engine
│   ├── Regime Detection (ADX + regression)
│   ├── Swing Detection (local extrema)
│   ├── Pivot Calculator (daily levels)
│   └── Edge Detector (signal generation)
├── Risk Management
│   ├── Balance Tracker (from cTrader deals)
│   ├── Position Sizer (ATR-based, fixed sizing)
│   ├── Daily Risk Tracker (4% limit)
│   └── RiskManager (multi-position support)
├── Order Execution
│   ├── SimpleOrderExecutor (market orders)
│   ├── PositionCloser (close & reverse)
│   └── 🆕 Signal Re-evaluation (rejected signals retry)
└── Home Assistant Integration
    ├── Sensor entities (balance, PnL, signals)
    ├── Toggle controls (auto-trading enable/disable)
    └── Notifications (alerts, trade confirmations)
```

---

## 🔧 Configuration

### AppDaemon Config:
- **Location:** `/config/appdaemon.yaml`
- **Key settings:** Minimal configuration (no threading directives)

### Trading Config:
- **Location:** `/config/apps/apps.yaml`
- **Symbols:** DE40 (DAX), US100 (NASDAQ)
- **Timeframe:** M5
- **Auto-trading:** Enabled (but OFF by default after restart)

### cTrader:
- **Server:** demo.ctraderapi.com:5036
- **Account:** 42478187 (demo)
- **Balance:** 1,801,320.46 CZK

---

## 🆕 New Features (28.10.2025)

### Signal Re-evaluation
Automaticky re-evaluuje signály, které byly odmítnuty kvůli vypnutému auto-tradingu.

**Problém:**
```
Signal generated → Auto-trading OFF → Signal REJECTED → Lost forever ❌
```

**Řešení:**
```
Signal generated → Auto-trading OFF → Signal SAVED 💾
User enables toggle → Auto-trading ON → Signal RE-EVALUATED 🔄 → Executed ✅
```

**Features:**
- ✅ Automatic storage of rejected signals
- ✅ Re-evaluation when auto-trading enabled
- ✅ Age validation (max 30 minutes)
- ✅ Summary statistics & notifications
- ✅ Max 10 signals stored (FIFO)

**Documentation:** [FEATURES.md](./FEATURES.md)

---

## 📈 Performance

### Current Metrics:
- **Balance:** 1,801,320.46 CZK
- **Daily PnL:** +12,911.40 CZK
- **Signal latency:** < 2s
- **Bar processing:** < 1s per symbol

### Data Quality:
- **US100:** 480 bars loaded ✅
- **GER40:** 435 bars loaded ✅
- **WebSocket uptime:** 99%+

---

## 🐛 Troubleshooting

### AppDaemon won't start?
```bash
# Check if apps.yaml is in correct location
test -f /config/apps/apps.yaml && echo "✅ OK" || echo "❌ WRONG LOCATION"

# Check logs
tail -50 /config/logs/appdaemon.log
```

### Auto-trading not executing?
```bash
# Check toggle status
grep "AUTO-TRADING.*ENABLED\|DISABLED" /config/logs/appdaemon.log | tail -1

# Check rejected signals
grep "Signal saved for re-evaluation" /config/logs/appdaemon.log | tail -5
```

### Signals not generating?
```bash
# Check signal generation
grep "New signal:\|Signal.*status:" /config/logs/appdaemon.log | tail -10

# Check edge detection
grep "\[EDGE\]\|\[ORB\]" /config/logs/appdaemon.log | tail -20
```

**Full troubleshooting guide:** [APPDAEMON_SETUP.md](./APPDAEMON_SETUP.md)

---

## 🔮 Roadmap

### Completed:
- ✅ cTrader integration
- ✅ Signal generation (Edge, ORB, Swings)
- ✅ Risk management
- ✅ Auto-trading execution
- ✅ Multi-position support
- ✅ Signal re-evaluation 🆕

### Next Steps:
- [ ] Fix ClientResponseError warnings
- [ ] Enhanced signal filtering
- [ ] Trade journaling & analytics
- [ ] Backtesting framework
- [ ] Multi-timeframe analysis

---

## 🤝 Contributing

### Development Workflow:
1. Edit locally: `/Users/jirimerz/Projects/TAv70/src/trading_assistant/`
2. Test changes
3. Deploy: `./deploy.sh`
4. Restart AppDaemon
5. Verify in logs

### Code Style:
- Follow existing patterns
- Add logging for debugging
- Document complex logic
- Test edge cases

---

## 📝 Change Log

### 2025-10-28 (Evening - Phase 3):
- ✅ Signal re-evaluation mechanismus
- ✅ Automatické retry odmítnutých signálů při zapnutí auto-tradingu
- ✅ Age validation (30 min limit)
- ✅ Summary statistics & notifikace

### 2025-10-28 (Evening - Phase 2):
- ✅ Deployment workflow (deploy.sh)
- ✅ Race condition fix (toggle_auto_trading)
- ✅ Dokumentace

### 2025-10-28 (Morning):
- ✅ Critical bug fixes (apps.yaml location, thread config)
- ✅ Stabilní běh AppDaemonu
- ✅ Setup dokumentace

---

## 📞 Support

### Issues?
1. Check [APPDAEMON_SETUP.md](./APPDAEMON_SETUP.md)
2. Check logs: `tail -f /config/logs/appdaemon.log`
3. Check [STATUS_REPORT.md](./STATUS_REPORT.md) for known issues

### Questions?
- Technical details: [FEATURES.md](./FEATURES.md)
- Deployment: [DEPLOY_README.md](./DEPLOY_README.md)

---

## 📄 License

Private project - No public distribution.

---

## 🎯 Summary

**Trading Assistant v2.0** je plně funkční automatizovaný trading systém s:
- Real-time analýzou market dat
- Automatickým generováním signálů
- Risk managementem
- Automatickou exekucí obchodů
- 🆕 Inteligentním re-evaluation mechanismem

**Status:** Production ready, aktivně používáno v demo režimu.

**Připraveno pro další fázi vývoje!** 🚀
