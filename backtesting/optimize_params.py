#!/usr/bin/env python3
"""
Optimalizace parametrů pro maximalizaci profit na daném datasetu
Používá grid search nebo random search
"""

import sys
import json
import itertools
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Any
import yaml
from dataclasses import dataclass, asdict

# Přidat src/ do Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from production_backtest import ProductionBacktestRunner, load_historical_data

@dataclass
class OptimizationResult:
    """Výsledek jedné kombinace parametrů"""
    params: Dict[str, Any]
    total_pnl: float
    pnl_pct: float
    total_trades: int
    win_rate: float
    profit_factor: float
    max_drawdown: float
    avg_win: float
    avg_loss: float
    sharpe_ratio: float = 0.0
    score: float = 0.0  # Kombinované skóre pro řazení

def calculate_sharpe_ratio(returns: List[float], risk_free_rate: float = 0.0) -> float:
    """Vypočítat Sharpe ratio z listu returns"""
    if not returns or len(returns) < 2:
        return 0.0
    
    import numpy as np
    returns_array = np.array(returns)
    
    if returns_array.std() == 0:
        return 0.0
    
    excess_returns = returns_array - risk_free_rate
    return np.mean(excess_returns) / returns_array.std() * np.sqrt(252)  # Annualized

def calculate_score(result: OptimizationResult, weights: Dict[str, float] = None) -> float:
    """
    Vypočítat kombinované skóre pro řazení výsledků
    
    Defaultní váhy:
    - PnL %: 40%
    - Profit Factor: 25%
    - Win Rate: 15%
    - Sharpe Ratio: 10%
    - Max Drawdown: 10% (penalizace)
    """
    if weights is None:
        weights = {
            'pnl_pct': 0.40,
            'profit_factor': 0.25,
            'win_rate': 0.15,
            'sharpe_ratio': 0.10,
            'max_drawdown': 0.10  # Penalizace
        }
    
    # Normalizovat metriky na škálu 0-1
    # PnL % - očekáváme -5% až +10%
    pnl_score = max(0, min(1, (result.pnl_pct + 5) / 15))
    
    # Profit Factor - očekáváme 0 až 3
    pf_score = max(0, min(1, result.profit_factor / 3))
    
    # Win Rate - očekáváme 40% až 80%
    wr_score = max(0, min(1, (result.win_rate - 40) / 40))
    
    # Sharpe Ratio - očekáváme -2 až 3
    sharpe_score = max(0, min(1, (result.sharpe_ratio + 2) / 5))
    
    # Max Drawdown - penalizace (menší = lepší)
    dd_score = max(0, min(1, 1 - result.max_drawdown / 10))  # 0% DD = 1.0, 10% DD = 0.0
    
    score = (
        pnl_score * weights['pnl_pct'] +
        pf_score * weights['profit_factor'] +
        wr_score * weights['win_rate'] +
        sharpe_score * weights['sharpe_ratio'] +
        dd_score * weights['max_drawdown']
    )
    
    return score

def run_single_backtest(params: Dict[str, Any], data_dir: Path) -> OptimizationResult:
    """Spustit jeden backtest s danými parametry"""
    
    # Vytvořit dočasnou konfiguraci
    temp_config = {
        'data_dir': data_dir,
        'results_dir': project_root / "backtesting" / "results",
        'initial_balance': 2000000.0
    }
    
    runner = ProductionBacktestRunner(temp_config)
    
    # Načíst základní konfiguraci a přepsat parametry
    # Použít backtest_config.yaml jako základ (pokud existuje)
    base_config_path = project_root / "backtesting" / "config" / "backtest_config.yaml"
    if base_config_path.exists():
        try:
            with open(base_config_path, 'r') as f:
                prod_config = yaml.safe_load(f)
        except:
            prod_config = runner._load_production_config()
    else:
        # Fallback na apps.yaml
        prod_config = runner._load_production_config()
    
    # Zajistit, že máme všechny sekce
    if 'edges' not in prod_config:
        prod_config['edges'] = {}
    if 'regime' not in prod_config:
        prod_config['regime'] = {}
    if 'microstructure' not in prod_config:
        prod_config['microstructure'] = {}
    
    # Aktualizovat edges parametry
    for key, value in params.items():
        if key in ['min_signal_quality', 'min_confidence', 'min_rrr', 'min_bars_between_signals', 
                   'strict_regime_filter', 'min_swing_quality']:
            prod_config['edges'][key] = value
        elif key in ['adx_threshold', 'regression_r2_threshold']:
            prod_config['regime'][key] = value
        elif key in ['min_liquidity_score', 'use_time_filter']:
            prod_config['microstructure'][key] = value
    
    # Re-inicializovat komponenty s novými parametry
    from trading_assistant.regime import RegimeDetector
    from trading_assistant.edges import EdgeDetector
    from trading_assistant.risk_manager import RiskManager
    from trading_assistant.pivots import PivotCalculator
    from trading_assistant.simple_swing_detector import SimpleSwingDetector
    from trading_assistant.microstructure_lite import MicrostructureAnalyzer
    from trading_assistant.balance_tracker import BalanceTracker
    from trading_assistant.daily_risk_tracker import DailyRiskTracker
    
    regime_config = prod_config.get('regime', {})
    runner.regime_detector = RegimeDetector(regime_config)
    
    edges_config = prod_config.get('edges', {})
    runner.edge_detector = EdgeDetector(edges_config)
    
    # RiskManager a ostatní zůstávají stejné
    account_balance = prod_config.get('account_balance', 2000000)
    symbol_specs_from_yaml = prod_config.get('symbol_specs', {})
    symbol_specs = {}
    
    if 'DAX' in symbol_specs_from_yaml:
        symbol_specs['DAX'] = symbol_specs_from_yaml['DAX']
        symbol_specs['GER40'] = symbol_specs_from_yaml['DAX'].copy()
    if 'NASDAQ' in symbol_specs_from_yaml:
        symbol_specs['NASDAQ'] = symbol_specs_from_yaml['NASDAQ']
        symbol_specs['US100'] = symbol_specs_from_yaml['NASDAQ'].copy()
    
    risk_config = {
        'account_balance': account_balance,
        'account_currency': prod_config.get('account_currency', 'CZK'),
        'max_risk_per_trade': prod_config.get('base_risk_per_trade', 0.005),
        'max_risk_total': prod_config.get('max_risk_total', 0.03),
        'max_positions': prod_config.get('max_positions', 1),
        'daily_loss_limit': prod_config.get('daily_loss_limit', 0.02),
        'max_margin_usage': prod_config.get('max_margin_usage', 80.0),
        'symbol_specs': symbol_specs,
        'risk_adjustments': prod_config.get('risk_adjustments', {}),
        'regime_adjustments': prod_config.get('regime_adjustments', {}),
        'volatility_adjustments': prod_config.get('volatility_adjustments', {}),
        'use_wide_stops': prod_config.get('use_wide_stops', True),
        'target_position_lots': prod_config.get('target_position_lots', 12.0),
        'min_position_lots': prod_config.get('min_position_lots', 8.0),
        'max_position_lots': prod_config.get('max_position_lots', 20.0),
    }
    
    runner.balance_tracker = BalanceTracker(initial_balance=account_balance)
    runner.risk_manager = RiskManager(config=risk_config, balance_tracker=runner.balance_tracker)
    
    pivots_config = prod_config.get('pivots', {})
    runner.pivot_calc = PivotCalculator(pivots_config)
    
    swings_config = prod_config.get('swings', {})
    runner.swing_engine = SimpleSwingDetector(
        config={
            'lookback': 5,
            'min_move_pct': 0.0015,
            'use_pivot_validation': swings_config.get('use_pivot_validation', True),
            'pivot_confluence_atr': swings_config.get('pivot_confluence_atr', 0.3),
            'atr_multiplier_m5': swings_config.get('atr_multiplier_m5', 0.5),
            'min_bars_between': swings_config.get('min_bars_between', 2),
            'min_swing_quality': prod_config.get('edges', {}).get('min_swing_quality', 20),
        },
        pivot_calculator=runner.pivot_calc
    )
    
    microstructure_config = prod_config.get('microstructure', {})
    runner.microstructure = MicrostructureAnalyzer(microstructure_config)
    
    daily_risk_limit = prod_config.get('auto_trading', {}).get('daily_risk_limit_pct', 0.04)
    runner.daily_risk_tracker = DailyRiskTracker(
        daily_limit_percentage=daily_risk_limit,
        balance_tracker=runner.balance_tracker,
        config=prod_config
    )
    
    # Spustit backtest
    symbols = ['GER40', 'US100']
    results_dict = runner.run_backtest(symbols)
    
    if not results_dict:
        return OptimizationResult(
            params=params,
            total_pnl=0.0,
            pnl_pct=0.0,
            total_trades=0,
            win_rate=0.0,
            profit_factor=0.0,
            max_drawdown=0.0,
            avg_win=0.0,
            avg_loss=0.0,
            score=0.0
        )
    
    stats = results_dict.get('statistics', {})
    
    # Vypočítat Sharpe ratio z equity curve
    equity_curve = results_dict.get('equity_curve', [])
    returns = []
    if len(equity_curve) > 1:
        for i in range(1, len(equity_curve)):
            prev_balance = equity_curve[i-1].get('balance', 2000000)
            curr_balance = equity_curve[i].get('balance', 2000000)
            if prev_balance > 0:
                returns.append((curr_balance - prev_balance) / prev_balance)
    
    sharpe = calculate_sharpe_ratio(returns) if returns else 0.0
    
    result = OptimizationResult(
        params=params,
        total_pnl=stats.get('total_pnl', 0.0),
        pnl_pct=(stats.get('total_pnl', 0.0) / 2000000.0 * 100) if stats.get('total_pnl') else 0.0,
        total_trades=stats.get('total_trades', 0),
        win_rate=stats.get('win_rate', 0.0),
        profit_factor=stats.get('profit_factor', 0.0),
        max_drawdown=stats.get('max_drawdown', 0.0),
        avg_win=stats.get('avg_win', 0.0),
        avg_loss=stats.get('avg_loss', 0.0),
        sharpe_ratio=sharpe
    )
    
    result.score = calculate_score(result)
    
    return result

def grid_search(param_grid: Dict[str, List[Any]], data_dir: Path, max_combinations: int = None) -> List[OptimizationResult]:
    """Grid search přes všechny kombinace parametrů"""
    
    # Vytvořit všechny kombinace
    keys = list(param_grid.keys())
    values = list(param_grid.values())
    all_combinations = list(itertools.product(*values))
    
    if max_combinations and len(all_combinations) > max_combinations:
        print(f"⚠️  Příliš mnoho kombinací ({len(all_combinations)}), omezuji na {max_combinations} náhodných")
        import random
        random.shuffle(all_combinations)
        all_combinations = all_combinations[:max_combinations]
    
    print(f"🔍 Testuji {len(all_combinations)} kombinací parametrů...")
    print(f"   (Každý backtest může trvat 10-30 sekund)")
    print()
    
    results = []
    
    for i, combination in enumerate(all_combinations, 1):
        params = dict(zip(keys, combination))
        
        print(f"[{i}/{len(all_combinations)}] Testuji: {params}")
        
        try:
            result = run_single_backtest(params, data_dir)
            results.append(result)
            
            print(f"    → PnL: {result.pnl_pct:+.2f}%, Trades: {result.total_trades}, "
                  f"WR: {result.win_rate:.1f}%, PF: {result.profit_factor:.2f}, "
                  f"Score: {result.score:.3f}")
        except Exception as e:
            print(f"    ❌ Chyba: {e}")
            continue
        
        print()
    
    return results

def main():
    """Hlavní funkce optimalizace"""
    
    print("=" * 70)
    print("🎯 OPTIMALIZACE PARAMETRŮ PRO MAXIMALIZACI PROFIT")
    print("=" * 70)
    print()
    
    data_dir = project_root / "backtesting" / "data"
    
    # Definovat grid parametrů k testování
    # Začneme s menším počtem hodnot pro rychlejší optimalizaci
    param_grid = {
        # Edge Detection parametry - klíčové parametry
        'min_signal_quality': [50, 60, 70],  # 3 hodnoty
        'min_confidence': [60, 70],          # 2 hodnoty (zúženo)
        'min_rrr': [1.2, 1.5, 2.0],         # 3 hodnoty
        'min_bars_between_signals': [3, 6],  # 2 hodnoty (zúženo)
        
        # Regime parametry
        'adx_threshold': [20, 25],           # 2 hodnoty (zúženo)
        'regression_r2_threshold': [0.4, 0.5, 0.6],  # 3 hodnoty
        
        # STRICT filter
        'strict_regime_filter': [False],     # Vypnuto pro více signálů
    }
    
    # Celkem: 3 × 2 × 3 × 2 × 2 × 3 × 1 = 216 kombinací
    # Omezíme na 30 náhodných kombinací pro rychlejší běh (lze zvýšit)
    print(f"📊 Grid parametrů:")
    for key, values in param_grid.items():
        print(f"   {key}: {values}")
    print()
    
    # Spustit grid search (omezený)
    # Zvětšit na 30 kombinací pro lepší pokrytí
    results = grid_search(param_grid, data_dir, max_combinations=30)
    
    if not results:
        print("❌ Žádné výsledky!")
        return
    
    # Seřadit podle skóre
    results.sort(key=lambda r: r.score, reverse=True)
    
    # Zobrazit top 10
    print("=" * 70)
    print("🏆 TOP 10 NEJLEPŠÍCH KOMBINACÍ PARAMETRŮ")
    print("=" * 70)
    print()
    
    for i, result in enumerate(results[:10], 1):
        print(f"{i}. Score: {result.score:.4f}")
        print(f"   Parametry: {result.params}")
        print(f"   PnL: {result.pnl_pct:+.2f}% ({result.total_pnl:+,.0f} CZK)")
        print(f"   Trades: {result.total_trades} | WR: {result.win_rate:.1f}% | "
              f"PF: {result.profit_factor:.2f} | DD: {result.max_drawdown:.2f}% | "
              f"Sharpe: {result.sharpe_ratio:.2f}")
        print()
    
    # Uložit všechny výsledky
    output_file = project_root / "backtesting" / "results" / f"optimization_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w') as f:
        json.dump([asdict(r) for r in results], f, indent=2, default=str)
    
    print(f"💾 Všechny výsledky uloženy: {output_file}")
    
    # Vytvořit optimální konfigurační soubor
    best_params = results[0].params
    print()
    print("=" * 70)
    print("✅ NEJLEPŠÍ PARAMETRY:")
    print("=" * 70)
    print(json.dumps(best_params, indent=2))
    
    # Uložit do YAML
    optimal_config_file = project_root / "backtesting" / "config" / "optimized_config.yaml"
    
    # Načíst základní config a přepsat parametry
    base_config_path = project_root / "backtesting" / "config" / "backtest_config.yaml"
    if base_config_path.exists():
        with open(base_config_path, 'r') as f:
            optimal_config = yaml.safe_load(f)
    else:
        optimal_config = {}
    
    # Aktualizovat parametry
    if 'edges' not in optimal_config:
        optimal_config['edges'] = {}
    if 'regime' not in optimal_config:
        optimal_config['regime'] = {}
    
    for key, value in best_params.items():
        if key in ['min_signal_quality', 'min_confidence', 'min_rrr', 'min_bars_between_signals', 
                   'strict_regime_filter', 'min_swing_quality']:
            optimal_config['edges'][key] = value
        elif key in ['adx_threshold', 'regression_r2_threshold']:
            optimal_config['regime'][key] = value
    
    with open(optimal_config_file, 'w') as f:
        yaml.dump(optimal_config, f, default_flow_style=False, sort_keys=False)
    
    print(f"\n💾 Optimální konfigurace uložena: {optimal_config_file}")
    print(f"\n💡 Pro použití: zkopíruj {optimal_config_file} jako backtest_config.yaml")

if __name__ == "__main__":
    main()

