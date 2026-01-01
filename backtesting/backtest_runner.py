#!/usr/bin/env python3
"""
Backtest Runner - Spouští backtest na historických datech
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from collections import defaultdict

# Přidat src/ do Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

def load_historical_data(symbol: str, data_dir: Path) -> List[Dict]:
    """Načíst historická data z cache souboru"""
    cache_file = data_dir / f"{symbol}_M5.jsonl"
    
    if not cache_file.exists():
        print(f"❌ Cache soubor neexistuje: {cache_file}")
        return []
    
    bars = []
    with open(cache_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    bar = json.loads(line)
                    bars.append(bar)
                except json.JSONDecodeError as e:
                    print(f"⚠️  Chyba při parsování řádku: {e}")
                    continue
    
    print(f"✅ Načteno {len(bars)} barů pro {symbol}")
    return bars

def parse_timestamp(ts: str) -> datetime:
    """Parsovat ISO timestamp do datetime objektu"""
    try:
        if 'T' in ts:
            # ISO format
            if ts.endswith('Z'):
                ts = ts.replace('Z', '+00:00')
            return datetime.fromisoformat(ts.replace('Z', '+00:00'))
        else:
            # Unix timestamp
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except Exception as e:
        print(f"⚠️  Chyba při parsování timestamp '{ts}': {e}")
        return datetime.now(timezone.utc)

class SimpleBacktestRunner:
    """
    Jednoduchý backtest runner - MVP verze
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.data_dir = Path(config.get('data_dir', 'backtesting/data'))
        self.results_dir = Path(config.get('results_dir', 'backtesting/results'))
        self.results_dir.mkdir(parents=True, exist_ok=True)
        
        # Trade tracking
        self.trades = []
        self.equity_curve = []
        self.initial_balance = config.get('initial_balance', 2000000.0)
        self.current_balance = self.initial_balance
        
        # Statistics
        self.stats = {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'total_pnl': 0.0,
            'max_drawdown': 0.0,
            'win_rate': 0.0,
            'profit_factor': 0.0,
            'avg_win': 0.0,
            'avg_loss': 0.0,
        }
        
        # Mock signal generator (prozatím jednoduchý)
        self.last_price = {}
        self.price_history = defaultdict(list)
    
    def run_backtest(self, symbols: List[str]):
        """Spustit backtest pro dané symboly"""
        print("=" * 60)
        print("🚀 SPOUŠTÍM BACKTEST")
        print("=" * 60)
        print(f"Počáteční balance: {self.initial_balance:,.2f} CZK")
        print(f"Symboly: {', '.join(symbols)}")
        print()
        
        all_bars = {}
        
        # Načíst data pro všechny symboly
        for symbol in symbols:
            bars = load_historical_data(symbol, self.data_dir)
            if bars:
                # Seřadit podle timestampu
                bars.sort(key=lambda b: parse_timestamp(b['timestamp']))
                all_bars[symbol] = bars
                print(f"📊 {symbol}: {len(bars)} barů")
                if bars:
                    first = parse_timestamp(bars[0]['timestamp'])
                    last = parse_timestamp(bars[-1]['timestamp'])
                    print(f"   Rozsah: {first.strftime('%Y-%m-%d %H:%M')} - {last.strftime('%Y-%m-%d %H:%M')}")
            else:
                print(f"⚠️  Žádná data pro {symbol}")
        
        if not all_bars:
            print("❌ Nenačtena žádná data!")
            return None
        
        # Pro jednoduchost - zpracovat každý symbol zvlášť
        for symbol, bars in all_bars.items():
            print(f"\n📈 Zpracovávám {symbol}...")
            self._process_symbol(symbol, bars)
        
        # Vypočítat finální statistiky
        self._calculate_statistics()
        
        # Zobrazit výsledky
        self._display_results()
        
        # Uložit výsledky
        results = self._save_results()
        
        return results
    
    def _process_symbol(self, symbol: str, bars: List[Dict]):
        """Zpracovat bary pro jeden symbol"""
        # Pro MVP: Jednoduchá strategie - buy když cena roste, sell když klesá
        # TODO: Integrovat skutečnou logiku z TradingAssistant
        
        lookback = 10  # Počet barů pro rozhodnutí
        
        for i in range(lookback, len(bars)):
            bar = bars[i]
            timestamp = parse_timestamp(bar['timestamp'])
            price = bar['close']
            
            # Uložit cenu do historie
            self.price_history[symbol].append(price)
            if len(self.price_history[symbol]) > 100:
                self.price_history[symbol].pop(0)
            
            # Jednoduchá strategie: trend following
            if len(self.price_history[symbol]) >= lookback:
                recent_prices = self.price_history[symbol][-lookback:]
                avg_price = sum(recent_prices) / len(recent_prices)
                
                # BUY signál: cena nad průměrem a rostoucí
                if price > avg_price and recent_prices[-1] > recent_prices[0]:
                    self._execute_trade(symbol, 'BUY', price, timestamp, bar)
                # SELL signál: cena pod průměrem a klesající
                elif price < avg_price and recent_prices[-1] < recent_prices[0]:
                    self._execute_trade(symbol, 'SELL', price, timestamp, bar)
            
            # Aktualizovat equity curve
            self.equity_curve.append({
                'timestamp': timestamp.isoformat(),
                'balance': self.current_balance,
                'pnl': self.current_balance - self.initial_balance
            })
    
    def _execute_trade(self, symbol: str, direction: str, price: float, timestamp: datetime, bar: Dict):
        """Simulovat exekuci obchodu"""
        # Pro MVP: Jednoduchá simulace
        # TODO: Integrovat skutečnou logiku z RiskManager a OrderExecutor
        
        # Zjednodušená logika - malé pozice pro test
        position_size = 1.0  # 1 lot
        risk_amount = self.current_balance * 0.01  # 1% risk
        
        # Jednoduchý SL/TP (2% vzdálenost)
        if direction == 'BUY':
            entry = price
            sl = entry * 0.98
            tp = entry * 1.02
        else:
            entry = price
            sl = entry * 1.02
            tp = entry * 0.98
        
        # Simulovat výsledek (pro MVP: 50% win rate)
        import random
        is_win = random.random() > 0.5
        
        if is_win:
            pnl = abs(tp - entry) * position_size * 10  # Zjednodušený výpočet
        else:
            pnl = -abs(entry - sl) * position_size * 10
        
        # Uložit trade
        trade = {
            'symbol': symbol,
            'direction': direction,
            'entry_price': entry,
            'sl_price': sl,
            'tp_price': tp,
            'exit_price': tp if is_win else sl,
            'timestamp': timestamp.isoformat(),
            'pnl': pnl,
            'is_win': is_win,
            'position_size': position_size
        }
        
        self.trades.append(trade)
        self.current_balance += pnl
        self.stats['total_trades'] += 1
        
        if is_win:
            self.stats['winning_trades'] += 1
        else:
            self.stats['losing_trades'] += 1
    
    def _calculate_statistics(self):
        """Vypočítat statistiky"""
        if not self.trades:
            return
        
        wins = [t['pnl'] for t in self.trades if t['is_win']]
        losses = [abs(t['pnl']) for t in self.trades if not t['is_win']]
        
        self.stats['total_pnl'] = sum(t['pnl'] for t in self.trades)
        self.stats['win_rate'] = (self.stats['winning_trades'] / self.stats['total_trades'] * 100) if self.stats['total_trades'] > 0 else 0
        self.stats['avg_win'] = sum(wins) / len(wins) if wins else 0
        self.stats['avg_loss'] = sum(losses) / len(losses) if losses else 0
        
        if losses and sum(losses) > 0:
            self.stats['profit_factor'] = sum(wins) / sum(losses) if wins else 0
        
        # Vypočítat max drawdown
        peak = self.initial_balance
        max_dd = 0
        for point in self.equity_curve:
            balance = point['balance']
            if balance > peak:
                peak = balance
            dd = (peak - balance) / peak * 100
            if dd > max_dd:
                max_dd = dd
        
        self.stats['max_drawdown'] = max_dd
    
    def _display_results(self):
        """Zobrazit výsledky backtestu"""
        print()
        print("=" * 60)
        print("📊 VÝSLEDKY BACKTESTU")
        print("=" * 60)
        print()
        
        print(f"💰 Finální balance: {self.current_balance:,.2f} CZK")
        print(f"📈 Celkový PnL: {self.stats['total_pnl']:,.2f} CZK ({self.stats['total_pnl']/self.initial_balance*100:.2f}%)")
        print(f"📉 Max Drawdown: {self.stats['max_drawdown']:.2f}%")
        print()
        
        print("📊 Obchody:")
        print(f"   Celkem: {self.stats['total_trades']}")
        print(f"   Výherních: {self.stats['winning_trades']}")
        print(f"   Ztrátových: {self.stats['losing_trades']}")
        print(f"   Win Rate: {self.stats['win_rate']:.2f}%")
        print()
        
        if self.stats['total_trades'] > 0:
            print("📈 Průměry:")
            print(f"   Průměrný zisk: {self.stats['avg_win']:,.2f} CZK")
            print(f"   Průměrná ztráta: {self.stats['avg_loss']:,.2f} CZK")
            print(f"   Profit Factor: {self.stats['profit_factor']:.2f}")
            print()
    
    def _save_results(self) -> Dict:
        """Uložit výsledky do souboru"""
        results = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'initial_balance': self.initial_balance,
            'final_balance': self.current_balance,
            'total_pnl': self.stats['total_pnl'],
            'statistics': self.stats,
            'trades': self.trades,
            'equity_curve': self.equity_curve
        }
        
        # Uložit JSON
        results_file = self.results_dir / f"backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(results_file, 'w') as f:
            json.dump(results, f, indent=2)
        
        print(f"💾 Výsledky uloženy do: {results_file}")
        
        return results

def main():
    """Hlavní funkce"""
    config = {
        'data_dir': project_root / "backtesting" / "data",
        'results_dir': project_root / "backtesting" / "results",
        'initial_balance': 2000000.0
    }
    
    runner = SimpleBacktestRunner(config)
    
    # Spustit backtest pro dostupné symboly
    symbols = ['GER40', 'US100']
    results = runner.run_backtest(symbols)
    
    if results:
        print("\n✅ Backtest dokončen!")
    else:
        print("\n❌ Backtest selhal!")

if __name__ == "__main__":
    main()

