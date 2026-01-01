# Analýza rozdílů: Backtest vs. Reálné obchodování

**Datum:** 2025-12-26  
**Období:** Prosinec 2025

## 📊 Porovnání výsledků

### Backtest (Yahoo Finance data)
- **Obchodů:** 4
- **Win Rate:** 75.0%
- **PnL:** -1,200 CZK (-0.06%)
- **Profit Factor:** 0.93
- **Období:** 01.10.2025 - 23.12.2025 (6,121 barů)

### Reálné obchodování (cTrader)
- **Obchodů:** ~130
- **Win Rate:** ~XX% (bude vypočteno)
- **PnL:** ~XX CZK (~XX%)
- **Profit Factor:** ~XX
- **Období:** 01.12.2025 - 23.12.2025

## 🔍 Možné příčiny rozdílů

### 1. **Počet signálů (KRITICKÝ ROZDÍL!)**

**Backtest:** Pouze 4 obchody  
**Realita:** ~130 obchodů

**Příčina:**
- Backtest používá **jiné parametry** (testoval různé kombinace)
- Produkční systém používá **parametry z apps.yaml** (přísnější filtry)
- Možná chyba v implementaci backtestu nebo jiné podmínky

### 2. **Parametry**

**Backtest:** 
- Použil optimalizované parametry z `backtest_config.yaml`
- `strict_regime_filter: false`
- Relaxované prahy (`min_signal_quality: 50-70`, `min_confidence: 60-70`)

**Produkce:**
- Používá parametry z `apps.yaml`
- `strict_regime_filter: true` (pravděpodobně - nutné ověřit)
- Přísnější prahy (`min_signal_quality: 75`, `min_confidence: 80`)

### 3. **Dataset**

**Backtest:**
- Yahoo Finance 5-min data
- Možné rozdíly v datech (ohlc, volume)
- Simulovaný spread

**Realita:**
- cTrader live data
- Reálný spread
- Reálný slippage

### 4. **Execution**

**Backtest:**
- Idealizovaná exekuce
- Bez slippage
- Bez poplatků

**Realita:**
- Skutečná exekuce
- Slippage
- Poplatky (commission)

### 5. **Market conditions**

**Backtest:**
- Testuje na historických datech (říjen-prosinec 2025)

**Realita:**
- Prosinec 2025 (1.12 - 23.12)
- Možné rozdíly v tržních podmínkách

### 6. **Implementace backtestu**

**Možné problémy:**
- Backtest možná nepoužívá všechny komponenty správně
- Chybí některé filtry (trading hours, risk manager, atd.)
- Různé inicializace komponent

## 💡 Doporučení

### 1. **Ověřit parametry produkce**
```bash
# Zkontrolovat, jaké parametry skutečně používá produkce
grep -A 20 "edges:" src/apps.yaml
```

### 2. **Spustit backtest s produkčními parametry**
```bash
# Použít apps.yaml místo backtest_config.yaml
cp src/apps.yaml backtesting/config/backtest_config.yaml
python3 backtesting/production_backtest.py
```

### 3. **Debug logování**
- Přidat logování, kolik signálů je generováno vs. kolik je blokováno
- Porovnat důvody blokování signálů mezi backtestem a produkcí

### 4. **Porovnat konkrétní obchody**
- Zjistit, kdy byly reálné obchody otevřeny
- Porovnat s backtestem - zda by byly tyto signály generovány

### 5. **Ověřit data**
- Porovnat ceny z Yahoo Finance s reálnými daty z cTrader
- Zkontrolovat, zda jsou data synchronizovaná

## ⚠️ Kritické zjištění

**Backtest generuje pouze 4 obchody, zatímco produkce ~130 obchodů!**

To znamená, že:
- Buď backtest má chybu v implementaci
- Nebo produkce používá jiné parametry
- Nebo backtest data nejsou reprezentativní

**Musíme to prozkoumat!**

