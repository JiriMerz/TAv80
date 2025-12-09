# Trading Assistant v8.0 - Refactoring Workspace

**Vytvořeno:** 2025-01-03  
**Zdroj:** TAv70  
**Účel:** Bezpečné testování refactoringu bez ovlivnění produkčního kódu

---

## 📁 Struktura projektu

```
TAv80/
├── src/                    # Hlavní kód (772K)
│   ├── apps.yaml          # Konfigurace
│   ├── secrets.yaml       # Secrets template
│   └── trading_assistant/ # 22 Python modulů (16,306 řádků)
├── docs/                   # Dokumentace (244K, 25 souborů)
│   └── REFACTORING_PRIORITIES.md  # Refactoring plán
├── deploy.sh               # Deployment script
├── claude.config.json     # Claude konfigurace
└── REFACTORING_STATUS.md   # Status refactoringu
```

---

## ✅ Ověření

- ✅ **22 Python souborů** zkopírovaných
- ✅ **16,306 řádků kódu** kompletních
- ✅ **25 dokumentačních souborů** včetně REFACTORING_PRIORITIES.md
- ✅ **Python syntax validní**
- ✅ **Konfigurační soubory** zkopírované

---

## 🎯 Refactoring plán

Postupuj podle **`docs/REFACTORING_PRIORITIES.md`**:

### Fáze 1: Rychlé výhry (začít zde)
1. Opravit duplicitní `position_conflicts` v `src/apps.yaml`
2. Odstranit SwingEngine z `src/trading_assistant/main.py`
3. Odstranit deprecated atributy

### Fáze 2: Optimalizace
4. Unifikovat microstructure
5. Dokončit TODO komentáře

### Fáze 3: Architektura (odložit)
6. Unifikovat threading
7. Rozdělit ctrader_client.py
8. Rozdělit main.py

---

## ⚠️ Důležité

- TAv80 je **pracovní kopie** - změny neovlivní TAv70
- Před deploy do produkce vždy otestovat
- Sledovat REFACTORING_PRIORITIES.md pro RPi-specifické úvahy

---

## 🚀 První kroky

1. Otevři `docs/REFACTORING_PRIORITIES.md` pro detailní plán
2. Začni s Fází 1 (rychlá výhra, nízké riziko)
3. Testuj lokálně na macOS
4. Po úspěchu můžeš změny aplikovat v TAv70

---

*Workspace připraven k refactoringu*
