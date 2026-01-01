#!/usr/bin/env python3
"""
Backtest s relaxovanými prahy - používá backtest_config.yaml
"""

import sys
from pathlib import Path

# Přidat src/ do Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# Import a spustit production backtest
from production_backtest import ProductionBacktestRunner

def main():
    """Hlavní funkce - spustí backtest s relaxovanou konfigurací"""
    config = {
        'data_dir': project_root / "backtesting" / "data",
        'results_dir': project_root / "backtesting" / "results",
        'initial_balance': 2000000.0
    }
    
    print("=" * 70)
    print("🚀 BACKTEST S RELAXOVANÝMI PRAHY")
    print("=" * 70)
    print("Používá: backtesting/config/backtest_config.yaml")
    print("(Pokud neexistuje, použije apps.yaml)")
    print()
    
    runner = ProductionBacktestRunner(config)
    symbols = ['GER40', 'US100']
    results = runner.run_backtest(symbols)
    
    if results:
        print("\n✅ Backtest dokončen!")
        print(f"\n💡 Pro zobrazení výsledků: python3 backtesting/view_results.py")
    else:
        print("\n❌ Backtest selhal!")

if __name__ == "__main__":
    main()

