#!/usr/bin/env python3
"""
Zobrazení výsledků backtestu v přehledném formátu
"""

import json
import sys
from pathlib import Path
from datetime import datetime

def view_results(results_file: Path):
    """Zobrazit výsledky backtestu"""
    if not results_file.exists():
        print(f"❌ Soubor neexistuje: {results_file}")
        return
    
    with open(results_file, 'r') as f:
        data = json.load(f)
    
    print("=" * 70)
    print("📊 VÝSLEDKY BACKTESTU")
    print("=" * 70)
    print()
    
    # Základní statistiky
    print("💰 FINANČNÍ VÝSLEDKY")
    print("-" * 70)
    initial = data['initial_balance']
    final = data['final_balance']
    pnl = data['total_pnl']
    pnl_pct = (pnl / initial) * 100
    
    print(f"Počáteční balance:     {initial:>15,.2f} CZK")
    print(f"Finální balance:       {final:>15,.2f} CZK")
    print(f"Celkový PnL:           {pnl:>15,.2f} CZK ({pnl_pct:>6.2f}%)")
    print()
    
    # Statistiky
    stats = data['statistics']
    print("📈 STATISTIKY OBCHODŮ")
    print("-" * 70)
    print(f"Celkem obchodů:        {stats['total_trades']:>15}")
    print(f"Výherních:             {stats['winning_trades']:>15} ({stats['win_rate']:.2f}%)")
    print(f"Ztrátových:            {stats['losing_trades']:>15} ({100-stats['win_rate']:.2f}%)")
    print()
    
    if stats['total_trades'] > 0:
        print("📊 PRŮMĚRNÉ HODNOTY")
        print("-" * 70)
        print(f"Průměrný zisk:        {stats['avg_win']:>15,.2f} CZK")
        print(f"Průměrná ztráta:      {stats['avg_loss']:>15,.2f} CZK")
        print(f"Profit Factor:        {stats['profit_factor']:>15,.2f}")
        print(f"Max Drawdown:         {stats['max_drawdown']:>15,.2f}%")
        print()
    
    # Rozdělení podle symbolů
    trades_by_symbol = {}
    for trade in data['trades']:
        symbol = trade['symbol']
        if symbol not in trades_by_symbol:
            trades_by_symbol[symbol] = {'total': 0, 'wins': 0, 'pnl': 0}
        trades_by_symbol[symbol]['total'] += 1
        # Podporovat oba formáty: 'is_win' nebo 'pnl' > 0
        is_win = trade.get('is_win', trade.get('pnl', 0) > 0)
        if is_win:
            trades_by_symbol[symbol]['wins'] += 1
        trades_by_symbol[symbol]['pnl'] += trade.get('pnl', 0)
    
    if trades_by_symbol:
        print("📊 ROZDĚLENÍ PODLE SYMBOLU")
        print("-" * 70)
        for symbol, stats_symbol in sorted(trades_by_symbol.items()):
            win_rate = (stats_symbol['wins'] / stats_symbol['total'] * 100) if stats_symbol['total'] > 0 else 0
            print(f"{symbol}:")
            print(f"  Obchodů: {stats_symbol['total']:>4} | Win Rate: {win_rate:>5.1f}% | PnL: {stats_symbol['pnl']:>10,.2f} CZK")
        print()
    
    # Top 5 nejlepších a nejhorších obchodů
    if data['trades']:
        sorted_trades = sorted(data['trades'], key=lambda t: t.get('pnl', 0), reverse=True)
        
        print("🏆 TOP 5 NEJLEPŠÍCH OBCHODŮ")
        print("-" * 70)
        for i, trade in enumerate(sorted_trades[:5], 1):
            entry_price = trade.get('entry_price', trade.get('entry', 0))
            pnl = trade.get('pnl', 0)
            direction = trade.get('direction', trade.get('signal_type', 'N/A'))
            timestamp = trade.get('timestamp', trade.get('opened_at', 'N/A'))
            print(f"{i}. {trade['symbol']:>6} {direction:>4} | "
                  f"Entry: {entry_price:>8.2f} | "
                  f"PnL: {pnl:>10,.2f} CZK | "
                  f"{str(timestamp)[:19]}")
        print()
        
        print("📉 TOP 5 NEJHORŠÍCH OBCHODŮ")
        print("-" * 70)
        for i, trade in enumerate(sorted_trades[-5:], 1):
            entry_price = trade.get('entry_price', trade.get('entry', 0))
            pnl = trade.get('pnl', 0)
            direction = trade.get('direction', trade.get('signal_type', 'N/A'))
            timestamp = trade.get('timestamp', trade.get('opened_at', 'N/A'))
            print(f"{i}. {trade['symbol']:>6} {direction:>4} | "
                  f"Entry: {entry_price:>8.2f} | "
                  f"PnL: {pnl:>10,.2f} CZK | "
                  f"{str(timestamp)[:19]}")
        print()
    
    print("=" * 70)
    print(f"📄 Výsledky uloženy: {results_file}")
    print("=" * 70)

def main():
    """Hlavní funkce"""
    if len(sys.argv) > 1:
        results_file = Path(sys.argv[1])
    else:
        # Najít nejnovější výsledky (priorita: production_backtest_ > backtest_)
        results_dir = Path(__file__).parent / "results"
        production_results = sorted(results_dir.glob("production_backtest_*.json"), reverse=True)
        simple_results = sorted(results_dir.glob("backtest_*.json"), reverse=True)
        results_files = production_results + simple_results
        if not results_files:
            print("❌ Žádné výsledky nenalezeny!")
            print(f"   Hledám v: {results_dir}")
            return
        results_file = results_files[0]
        print(f"📁 Používám nejnovější výsledky: {results_file.name}\n")
    
    view_results(results_file)

if __name__ == "__main__":
    main()

