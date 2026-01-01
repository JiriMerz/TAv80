# Stažení historických dat z Yahoo Finance

## 📥 Skript pro stahování dat

Skript `download_yahoo_data.py` stahuje historická data z Yahoo Finance pro backtesting.

### Instalace závislostí

```bash
pip install yfinance pandas
```

### Použití

```bash
python3 backtesting/download_yahoo_data.py
```

### Co skript dělá

1. **Stahuje 5-minutová data** z Yahoo Finance:
   - GER40 (DAX): `^GDAXI`
   - US100 (NASDAQ-100): `^NDX`

2. **Period a interval:**
   - Period: `60d` (60 dní historie - max pro intraday data)
   - Interval: `5m` (5-minutové bary)

3. **Převod formátu:**
   - Konvertuje Yahoo Finance data do našeho JSONL formátu
   - Přidává simulovaný spread (2.5 pro GER40, 2.0 pro US100)
   - Ukládá do `backtesting/data/{SYMBOL}_M5.jsonl`

### Limity Yahoo Finance

⚠️ **Důležité:** Yahoo Finance má omezení pro intraday data:
- **5-minutová data:** Max ~60 dní historie
- **1-minutová data:** Max ~7 dní historie
- Data jsou dostupná pouze když jsou trhy otevřené (pro intraday)

### Alternativy

Pokud Yahoo Finance nefunguje nebo potřebujete více historických dat:

1. **Použít cTrader cache:**
   - Spustit `load_ger40_data.py` když jsou trhy otevřené
   - Data se uloží do cache a lze je použít pro backtesting

2. **Mock data:**
   - `load_test_data.py` generuje realistická mock data
   - Použitelné pro testování když jsou trhy zavřené

### Po stažení dat

```bash
# Spustit backtest na stažených datech
python3 backtesting/production_backtest.py

# Zobrazit výsledky
python3 backtesting/view_results.py
```

