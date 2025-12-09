# Trading Assistant - Deployment Guide

## 🚀 Quick Start

### 1. Připoj Samba share
```bash
# Finder → Go → Connect to Server
smb://homeassistant.local/addon_configs
```

### 2. Udělej změny lokálně
```bash
cd /Users/jirimerz/Projects/TAv70/src/trading_assistant
# Edit your Python files...
```

### 3. Deploy
```bash
cd /Users/jirimerz/Projects/TAv70

# First check what will be deployed (dry-run)
./deploy.sh --dry-run

# Deploy to Home Assistant
./deploy.sh
```

### 4. Restart AppDaemon
- Home Assistant UI: Settings → Add-ons → AppDaemon → RESTART
- Or via SSH: `ha addons restart a0d7b954_appdaemon`

### 5. Check logs
```bash
tail -f /Volumes/addon_configs/a0d7b954_appdaemon/logs/appdaemon.log
```

---

## 📋 Deploy Script Options

```bash
./deploy.sh              # Normal deployment
./deploy.sh --dry-run    # Simulation only (no actual deployment)
./deploy.sh --restart    # Deploy + auto-restart AppDaemon (requires SSH)
./deploy.sh --help       # Show help
```

---

## 🔍 What Gets Deployed

- **Source:** `/Users/jirimerz/Projects/TAv70/src/trading_assistant/`
- **Target:** `/Volumes/addon_configs/a0d7b954_appdaemon/apps/trading_assistant/`
- **Includes:** All `.py` files
- **Excludes:** `.DS_Store`, `__pycache__`, `*.pyc`

---

## ✅ Checklist Before Deploy

- [ ] Samba share mounted at `/Volumes/addon_configs/`
- [ ] Local changes tested (if applicable)
- [ ] Run `./deploy.sh --dry-run` first
- [ ] Review what files will be changed
- [ ] Deploy with `./deploy.sh`
- [ ] Restart AppDaemon manually
- [ ] Check logs for errors

---

## ⚠️ Important Notes

1. **Always test first:** Use `--dry-run` to see what will change
2. **Restart required:** AppDaemon won't reload code until restarted
3. **Check logs:** Always verify successful startup after deploy
4. **Backup:** Current config is backed up automatically:
   - `appdaemon.yaml.backup`
   - `apps/apps.yaml.backup`

---

## 🐛 Troubleshooting

### Samba share not mounted
```bash
# Mount via Finder
open smb://homeassistant.local/addon_configs

# Or check if already mounted
ls -la /Volumes/addon_configs/
```

### Deploy failed
```bash
# Check if target directory exists
ls -la /Volumes/addon_configs/a0d7b954_appdaemon/apps/trading_assistant/

# Manual sync as fallback
rsync -av --exclude='.DS_Store' \
  /Users/jirimerz/Projects/TAv70/src/trading_assistant/ \
  /Volumes/addon_configs/a0d7b954_appdaemon/apps/trading_assistant/
```

### AppDaemon not starting after deploy
```bash
# Check logs
tail -100 /Volumes/addon_configs/a0d7b954_appdaemon/logs/appdaemon.log

# Look for Python syntax errors or import errors
grep -i "error\|traceback" /Volumes/addon_configs/a0d7b954_appdaemon/logs/appdaemon.log | tail -20
```

---

## 📚 Full Documentation

See [APPDAEMON_SETUP.md](./APPDAEMON_SETUP.md) for complete setup and troubleshooting guide.
