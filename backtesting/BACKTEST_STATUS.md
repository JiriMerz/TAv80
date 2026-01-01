# Status Produkčního Backtestu

**Datum:** 2025-12-25  
**Verze:** Production Backtest Runner (MVP)

## ✅ Implementováno

### 1. Produkční komponenty integrované
- ✅ `RegimeDetector` - detekce režimu trhu (ADX, Linear Regression)
- ✅ `EdgeDetector` - detekce signálů (stejná logika jako v produkci)
- ✅ `RiskManager` - výpočet pozic, risk management
- ✅ `PivotCalculator` - výpočet pivot bodů
- ✅ `SimpleSwingDetector` - detekce swingů
- ✅ `BalanceTracker` - sledování zůstatku
- ✅ `DailyRiskTracker` - denní risk limity

### 2. Broker Simulator
- ✅ Simulace exekuce s spreadem
- ✅ SL/TP kontrola
- ✅ Tracking pozic a PnL
- ✅ Equity curve

### 3. Backtest Runner
- ✅ Zpracování historických barů
- ✅ Volání produkční logiky (`_process_market_data`)
- ✅ Exekuce signálů přes broker simulator
- ✅ Statistiky a výsledky

## ⚠️ Poznámky

### Žádné obchody
Backtest běží bez chyb, ale nevytváří žádné obchody. Možné příčiny:

1. **Příliš přísné filtry v EdgeDetector:**
   - STRICT regime filter vyžaduje TREND_UP/DOWN + EMA34 souhlas
   - Microstructure checks (quality trading time)
   - Swing extreme checks
   - Pullback zone validation

2. **Regime detection:**
   - Mock data mohou mít špatné režimy (RANGE místo TREND)
   - ADX může být nízký

3. **Chybějící konfigurace:**
   - Některé komponenty potřebují konfiguraci z `apps.yaml`
   - Microstructure data nejsou použita (None)

### Co dělat dál

1. **Přidat debug logování:**
   - Kolik signálů je generováno?
   - Kolik je odmítnuto a proč?
   - Jaký je regime na mock datech?

2. **Relaxovat filtry pro test:**
   - Dočasně vypnout STRICT regime filter
   - Vypnout microstructure checks
   - Zkusit na skutečných datech z cTrader

3. **Použít skutečná data:**
   - Načíst data z cache (když jsou trhy otevřené)
   - Použít data z cTrader API

## 📊 Výsledky (Mock Data)

```
Počáteční balance: 2,000,000.00 CZK
Finální balance: 2,000,000.00 CZK
Celkový PnL: 0.00 CZK (0.00%)
Obchody: 0
Win Rate: 0.00%
```

## 🔧 Použití

```bash
# Spustit backtest
python3 backtesting/production_backtest.py

# Zobrazit výsledky
python3 backtesting/view_results.py
```

## 📝 TODO

- [ ] Přidat debug logování signálů
- [ ] Testovat na skutečných datech z cTrader
- [ ] Přidat více statistik (equity curve, drawdown, atd.)
- [ ] HTML report s grafy
- [ ] Porovnání s jednoduchým backtestem

