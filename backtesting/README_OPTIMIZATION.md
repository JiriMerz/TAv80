# Optimalizace parametrů

Skript `optimize_params.py` testuje různé kombinace parametrů pro maximalizaci profit na daném datasetu.

## Použití

```bash
cd backtesting
python3 optimize_params.py
```

## Co dělá

1. **Grid Search**: Testuje různé kombinace parametrů:
   - `min_signal_quality`: 50, 60, 70
   - `min_confidence`: 60, 70
   - `min_rrr`: 1.2, 1.5, 2.0
   - `min_bars_between_signals`: 3, 6
   - `adx_threshold`: 20, 25
   - `regression_r2_threshold`: 0.4, 0.5, 0.6
   - `strict_regime_filter`: False

2. **Hodnocení**: Každá kombinace je ohodnocena kombinovaným skóre:
   - PnL % (váha 40%)
   - Profit Factor (váha 25%)
   - Win Rate (váha 15%)
   - Sharpe Ratio (váha 10%)
   - Max Drawdown - penalizace (váha 10%)

3. **Výsledky**: 
   - Zobrazí TOP 10 nejlepších kombinací
   - Uloží všechny výsledky do JSON souboru
   - Vytvoří optimální konfigurační soubor `optimized_config.yaml`

## Výstup

```
🏆 TOP 10 NEJLEPŠÍCH KOMBINACÍ PARAMETRŮ
==========================================

1. Score: 0.8234
   Parametry: {'min_signal_quality': 60, 'min_confidence': 70, ...}
   PnL: +2.34% (+46,800 CZK)
   Trades: 15 | WR: 66.7% | PF: 1.85 | DD: 1.2% | Sharpe: 1.45
```

## Optimalizované parametry

Po dokončení optimalizace se vytvoří `config/optimized_config.yaml` s nejlepšími parametry.

Pro použití zkopírujte:
```bash
cp backtesting/config/optimized_config.yaml backtesting/config/backtest_config.yaml
```

## Poznámky

- Optimalizace může trvat 5-15 minut (závisí na počtu kombinací)
- Každý backtest běží na stejném datasetu (GER40 + US100 z Yahoo Finance)
- Výsledky jsou specifické pro daný dataset a časové období
- Pro produkci doporučuji použít produkční prahy z `apps.yaml`

