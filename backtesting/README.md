# Backtesting - Návod

## 📊 Načítání historických dat

### 1. Když jsou trhy otevřené (doporučeno)
Použij `load_ger40_data.py` nebo `load_historical_data.py` - načte skutečná data z cTrader API:
```bash
python3 backtesting/load_ger40_data.py
```

**Výhody:**
- Skutečná historická data z cTrader
- Automaticky uložená do cache
- 400+ barů během obchodních hodin

**Kdy použít:**
- Během obchodních hodin (Po-Pá, 09:00-22:00 CET)
- Ne během svátků/víkendů

### 2. Pro testování (když jsou trhy zavřené)
Použij `load_test_data.py` - vygeneruje mock data pro rychlé testování:
```bash
python3 backtesting/load_test_data.py
```

**Výhody:**
- Funguje kdykoliv (i když jsou trhy zavřené)
- Rychlé pro testování
- Vytvoří 500 barů pro GER40 i US100

**Nevýhody:**
- Mock data (ne skutečná)
- Pouze pro testování, ne pro skutečný backtest

**Co skript dělá:**
1. Zkusí stáhnout data z Yahoo Finance (pokud jsou dostupná)
2. Pokud to nefunguje, vygeneruje realistická mock data
3. Uloží data do `backtesting/data/` ve správném formátu

## 📁 Struktura adresářů

```
backtesting/
├── data/           # Cache historických dat (JSONL formát)
│   ├── GER40_M5.jsonl
│   └── US100_M5.jsonl
├── results/        # Výsledky backtestů (bude přidáno)
└── config/         # Konfigurační soubory (bude přidáno)
```

## 📋 Formát dat

Data jsou uložena v JSONL formátu (jeden JSON objekt na řádek):

```json
{
  "timestamp": "2025-12-25T20:00:00+00:00",
  "open": 24331.22,
  "high": 24331.45,
  "low": 24331.10,
  "close": 24331.35,
  "volume": 150,
  "spread": 2.5
}
```

## 🚀 Další kroky

1. ✅ Načíst historická data
2. ⏳ Implementovat backtesting runner
3. ⏳ Implementovat broker simulator
4. ⏳ Implementovat výsledky a reporty
