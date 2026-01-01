# Backtesting Design - Trading Assistant

**Datum:** 2025-12-25  
**Cíl:** Jednoduchý, ale funkční backtesting systém s minimálními změnami v existujícím kódu  
**Prostředí:** Standalone Python na lokálním počítači (např. macOS), **NENÍ potřeba Home Assistant ani AppDaemon**

## 🎯 Principy

1. **Použití stejných komponent** - EdgeDetector, RiskManager, regime detection, atd. zůstávají beze změny
2. **Minimální změny** - pouze abstrakce nad datovým zdrojem a exekucí
3. **Jednoduchost** - jeden nový modul `backtester.py` s jasnou strukturou
4. **Realističnost** - simulace spread, slippage, exekuce
5. **Standalone běh** - backtesting běží lokálně na Macu bez Home Assistant/AppDaemon

## 💻 Lokální běh na macOS

**Backtesting může běžet kompletně lokálně na Macu bez potřeby Home Assistant nebo Raspberry Pi.**

### ✅ Komponenty nezávislé na HA (použitelné přímo)

Všechny tyto komponenty jsou čistý Python bez závislosti na HA/AppDaemon:

- ✅ `edges.py` - EdgeDetector (detekce signálů)
- ✅ `regime.py` - RegimeDetector (detekce trhu)
- ✅ `risk_manager.py` - RiskManager (rizikový management)
- ✅ `pivots.py` - PivotCalculator (pivot body)
- ✅ `simple_swing_detector.py` - SimpleSwingDetector (swing detekce)
- ✅ `pullback_detector.py` - PullbackDetector (pullbacky)
- ✅ `microstructure*.py` - MicrostructureAnalyzer (mikrostruktura)
- ✅ `balance_tracker.py` - BalanceTracker (sledování zůstatku)
- ✅ `daily_risk_tracker.py` - DailyRiskTracker (denní risk)
- ✅ `time_based_manager.py` - TimeBasedSymbolManager (časové přepínání)
- ✅ `trade_decision_logger.py` - TradeDecisionLogger (logování)
- ✅ `performance_tracker.py` - PerformanceTracker (výkonnost)
- ✅ `logging_config.py` - LoggingConfig (logování)

### ⚠️ Komponenty závislé na HA (vyžadují mock/stub)

Tyto komponenty potřebují mock pro standalone běh:

- ⚠️ `main.py` - TradingAssistant (dědi z `hass.Hass`) → **má už MockHass fallback!**
- ⚠️ `simple_order_executor.py` - používá `hass_instance` → může být `None`
- ⚠️ `ctrader_client.py` - WebSocket komunikace → **není potřeba pro backtesting**
- ⚠️ `account_state_monitor.py` - HA entity → **není potřeba pro backtesting**
- ⚠️ `watchdog_manager.py` - HA entity → **není potřeba pro backtesting**
- ⚠️ `event_bridge.py` - může být použito bez HA

### 🔧 Co je potřeba pro lokální běh

1. **Python 3.10+** s potřebnými balíčky
2. **Historická data** (CSV/JSON s OHLCV bary)
3. **Backtest runner** (nový modul) - orchestruje celý proces
4. **Broker simulator** (nový modul) - simuluje exekuci

### 📦 Instalace pro lokální běh

```bash
# Na Macu - vytvořit virtuální prostředí
python3 -m venv venv
source venv/bin/activate

# Nainstalovat závislosti (bez HA/AppDaemon)
pip install numpy  # pokud používáš microstructure.py (ne lite verzi)
# ostatní moduly jsou pure Python bez externích závislostí
```

### 🎯 Struktura repository (oddělená pro HA a backtesting)

**Klíčový princip:** `src/trading_assistant/` zůstane **beze změny** jako obraz adresáře pro HA.

```
TAv80/
├── src/
│   ├── apps.yaml                    # AppDaemon konfigurace
│   ├── secrets.yaml                 # Credentials
│   └── trading_assistant/           # ✅ PRO HA (zůstane beze změny)
│       ├── __init__.py
│       ├── main.py                  # TradingAssistant(hass.Hass)
│       ├── edges.py                 # ✅ EdgeDetector
│       ├── regime.py                # ✅ RegimeDetector
│       ├── risk_manager.py          # ✅ RiskManager
│       ├── pivots.py                # ✅ PivotCalculator
│       ├── simple_swing_detector.py # ✅ SimpleSwingDetector
│       ├── pullback_detector.py     # ✅ PullbackDetector
│       ├── microstructure*.py       # ✅ MicrostructureAnalyzer
│       ├── balance_tracker.py       # ✅ BalanceTracker
│       ├── daily_risk_tracker.py    # ✅ DailyRiskTracker
│       ├── time_based_manager.py    # ✅ TimeBasedSymbolManager
│       ├── trade_decision_logger.py # ✅ TradeDecisionLogger
│       ├── performance_tracker.py   # ✅ PerformanceTracker
│       ├── logging_config.py        # ✅ LoggingConfig
│       ├── ctrader_client.py        # ⚠️ Pro HA (není potřeba pro backtesting)
│       ├── account_state_monitor.py # ⚠️ Pro HA (není potřeba pro backtesting)
│       ├── watchdog_manager.py      # ⚠️ Pro HA (není potřeba pro backtesting)
│       └── ... (ostatní HA komponenty)
│
└── backtesting/                      # 🆕 NOVÝ - pro backtesting (odděleno)
    ├── __init__.py
    ├── backtester.py                 # 🆕 BacktestRunner - orchestrátor
    ├── broker_simulator.py           # 🆕 BrokerSimulator - simulace exekuce
    ├── data_source.py                # 🆕 DataSource - abstrakce nad historickými daty
    ├── run_backtest.py               # 🆕 CLI spouštěcí skript
    ├── config/
    │   └── backtest_config.yaml      # 🆕 Konfigurace backtestu
    └── data/
        ├── NASDAQ_M5.csv             # Historická data
        └── DAX_M5.csv
```

### 📝 Importování komponent z `src/trading_assistant`

Backtesting moduly budou importovat komponenty z `src.trading_assistant`:

```python
# backtesting/backtester.py
import sys
from pathlib import Path

# Přidat src/ do Python path pro import trading_assistant modulů
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# Nyní můžeme importovat komponenty
from trading_assistant.edges import EdgeDetector
from trading_assistant.regime import RegimeDetector
from trading_assistant.risk_manager import RiskManager
from trading_assistant.pivots import PivotCalculator
# ... atd.
```

### 🚀 Spuštění backtestu

```bash
# Na Macu
cd TAv80
python backtesting/run_backtest.py --symbol NASDAQ --start-date 2025-01-01 --end-date 2025-12-25
```

### 📦 requirements.txt pro backtesting

Vytvoříme samostatný `backtesting/requirements.txt`:

```txt
# backtesting/requirements.txt
# Závislosti pouze pro backtesting (bez HA/AppDaemon)

numpy>=1.24.0  # Pokud používáš microstructure.py (ne lite verzi)
pandas>=2.0.0  # Pro práci s historickými daty (volitelné)
pyyaml>=6.0    # Pro konfigurační soubory
```

## 📐 Architektura

### Abstrakce potřebné

1. **Data Source Interface** - abstrakce nad cTrader klientem
   - `get_bar()` - vrátí další bar
   - `get_current_price()` - aktuální cena pro exekuci
   - `has_more_data()` - zda jsou ještě data

2. **Broker Simulator** - simulace exekuce
   - Spread (fixní nebo dynamický)
   - Slippage (volitelné)
   - Exekuce (okamžitá nebo s delay)
   - Pozice tracking (simulace cTrader pozic)

3. **Backtest Runner** - orchestrátor
   - Projde historické bary
   - Volá `process_market_data` s každým barem
   - Simuluje exekuci signálů
   - Sleduje výsledky

## 📁 Struktura souborů

**Backtesting soubory budou v samostatném adresáři `backtesting/` mimo `src/trading_assistant/`:**

```
backtesting/
├── __init__.py
├── backtester.py          # Nový modul - backtest runner
├── broker_simulator.py    # Nový modul - simulace brokeru
├── data_source.py         # Nový modul - abstrakce nad datovým zdrojem
├── run_backtest.py        # CLI spouštěcí skript
├── config/
│   └── backtest_config.yaml
└── data/
    ├── NASDAQ_M5.csv
    └── DAX_M5.csv
```

**`src/trading_assistant/` zůstane beze změny** - všechny komponenty pro HA zůstávají na svém místě.

## 🔧 Implementace

### 1. Data Source (`data_source.py`)

```python
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from datetime import datetime

class DataSource(ABC):
    """Abstrakce nad datovým zdrojem"""
    
    @abstractmethod
    def get_next_bar(self) -> Optional[Dict]:
        """Vrátí další bar nebo None pokud nejsou další data"""
        pass
    
    @abstractmethod
    def get_current_price(self, symbol: str) -> float:
        """Vrátí aktuální cenu symbolu"""
        pass
    
    @abstractmethod
    def get_all_bars(self, symbol: str) -> List[Dict]:
        """Vrátí všechny bary pro symbol (pro backtest)"""
        pass


class HistoricalDataSource(DataSource):
    """Historická data pro backtesting"""
    
    def __init__(self, bars: Dict[str, List[Dict]], start_index: int = 0):
        self.bars = bars  # {symbol: [bar1, bar2, ...]}
        self.current_index = {symbol: start_index for symbol in bars}
        self.current_bars = {}  # Aktuální stav pro každý symbol
        
    def get_next_bar(self, symbol: str) -> Optional[Dict]:
        """Vrátí další bar pro symbol"""
        if symbol not in self.bars:
            return None
            
        idx = self.current_index.get(symbol, 0)
        if idx >= len(self.bars[symbol]):
            return None
            
        bar = self.bars[symbol][idx]
        self.current_index[symbol] = idx + 1
        self.current_bars[symbol] = bar
        return bar
    
    def get_current_price(self, symbol: str) -> float:
        """Vrátí aktuální cenu z posledního baru"""
        if symbol in self.current_bars:
            return self.current_bars[symbol]['close']
        return 0.0
    
    def get_all_bars(self, symbol: str) -> List[Dict]:
        """Vrátí všechny bary pro symbol"""
        return self.bars.get(symbol, [])
```

### 2. Broker Simulator (`broker_simulator.py`)

```python
from typing import Dict, Optional
from datetime import datetime
from dataclasses import dataclass

@dataclass
class SimulatedPosition:
    """Simulovaná pozice"""
    position_id: str
    symbol: str
    direction: str  # BUY/SELL
    entry_price: float
    size: float  # lots
    stop_loss: float
    take_profit: float
    opened_at: datetime
    closed_at: Optional[datetime] = None
    close_price: Optional[float] = None
    pnl: float = 0.0


class BrokerSimulator:
    """Simulace brokeru pro backtesting"""
    
    def __init__(self, spread_pct: float = 0.001, slippage_pct: float = 0.0005):
        """
        Args:
            spread_pct: Spread v procentech (např. 0.001 = 0.1%)
            slippage_pct: Slippage v procentech (např. 0.0005 = 0.05%)
        """
        self.spread_pct = spread_pct
        self.slippage_pct = slippage_pct
        self.positions: Dict[str, SimulatedPosition] = {}
        self.balance = 0.0
        self.equity = 0.0
        self.next_position_id = 1
        
    def execute_order(self, symbol: str, direction: str, entry: float, 
                     size: float, sl: float, tp: float) -> SimulatedPosition:
        """
        Simuluje exekuci orderu
        
        Returns:
            SimulatedPosition objekt
        """
        # Aplikuj spread a slippage
        if direction == "BUY":
            # BUY: platíme ask (entry + spread)
            execution_price = entry * (1 + self.spread_pct)
            execution_price *= (1 + self.slippage_pct)  # Slippage
        else:  # SELL
            # SELL: dostáváme bid (entry - spread)
            execution_price = entry * (1 - self.spread_pct)
            execution_price *= (1 - self.slippage_pct)  # Slippage
        
        position_id = f"POS_{symbol}_{self.next_position_id}"
        self.next_position_id += 1
        
        position = SimulatedPosition(
            position_id=position_id,
            symbol=symbol,
            direction=direction,
            entry_price=execution_price,
            size=size,
            stop_loss=sl,
            take_profit=tp,
            opened_at=datetime.now()
        )
        
        self.positions[position_id] = position
        return position
    
    def update_positions(self, current_prices: Dict[str, float]):
        """
        Aktualizuje pozice s aktuálními cenami a kontroluje SL/TP
        
        Returns:
            List of closed positions
        """
        closed = []
        
        for position_id, position in list(self.positions.items()):
            if position.closed_at:
                continue
                
            current_price = current_prices.get(position.symbol, 0)
            if current_price == 0:
                continue
            
            # Kontrola SL/TP
            if position.direction == "BUY":
                if current_price <= position.stop_loss:
                    position.closed_at = datetime.now()
                    position.close_price = position.stop_loss
                    position.pnl = (position.stop_loss - position.entry_price) * position.size
                elif current_price >= position.take_profit:
                    position.closed_at = datetime.now()
                    position.close_price = position.take_profit
                    position.pnl = (position.take_profit - position.entry_price) * position.size
            else:  # SELL
                if current_price >= position.stop_loss:
                    position.closed_at = datetime.now()
                    position.close_price = position.stop_loss
                    position.pnl = (position.entry_price - position.stop_loss) * position.size
                elif current_price <= position.take_profit:
                    position.closed_at = datetime.now()
                    position.close_price = position.take_profit
                    position.pnl = (position.entry_price - position.take_profit) * position.size
            
            if position.closed_at:
                closed.append(position)
                # Aktualizuj balance
                self.balance += position.pnl
                self.equity = self.balance + sum(
                    (current_prices.get(p.symbol, 0) - p.entry_price) * p.size 
                    if p.direction == "BUY" else
                    (p.entry_price - current_prices.get(p.symbol, 0)) * p.size
                    for p in self.positions.values() if not p.closed_at
                )
        
        # Odstraň uzavřené pozice
        for position in closed:
            del self.positions[position.position_id]
            
        return closed
```

### 3. Backtest Runner (`backtester.py`)

```python
"""
Backtest Runner - jednoduchý backtesting systém
"""

from typing import Dict, List, Optional
from datetime import datetime
import json

import sys
from pathlib import Path

# Přidat src/ do Python path pro import trading_assistant modulů
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from .data_source import HistoricalDataSource
from .broker_simulator import BrokerSimulator

# Import komponent z trading_assistant (ze src/trading_assistant/)
from trading_assistant.edges import EdgeDetector
from trading_assistant.regime import RegimeDetector
from trading_assistant.pivots import PivotCalculator
from trading_assistant.simple_swing_detector import SimpleSwingDetector
from trading_assistant.microstructure_lite import MicrostructureAnalyzer
from trading_assistant.risk_manager import RiskManager
from trading_assistant.balance_tracker import BalanceTracker
from trading_assistant.daily_risk_tracker import DailyRiskTracker
from trading_assistant.time_based_manager import TimeBasedSymbolManager


class BacktestRunner:
    """Backtest runner - používá stejné komponenty jako live systém"""
    
    def __init__(self, config: Dict, initial_balance: float = 1000000.0):
        """
        Args:
            config: Konfigurace (stejná jako v apps.yaml)
            initial_balance: Počáteční balance v CZK
        """
        self.config = config
        self.initial_balance = initial_balance
        
        # Inicializuj komponenty (stejné jako v main.py)
        self.regime_detector = RegimeDetector(config.get('regime', {}))
        self.pivot_calc = PivotCalculator(config.get('pivots', {}))
        self.swing_engine = SimpleSwingDetector(config.get('swings', {}))
        self.edge = EdgeDetector(config.get('edges', {}))
        self.microstructure = MicrostructureAnalyzer(config.get('microstructure', {}))
        
        # Broker simulator
        spread = config.get('backtest', {}).get('spread_pct', 0.001)
        slippage = config.get('backtest', {}).get('slippage_pct', 0.0005)
        self.broker = BrokerSimulator(spread_pct=spread, slippage_pct=slippage)
        self.broker.balance = initial_balance
        self.broker.equity = initial_balance
        
        # Výsledky
        self.trades: List[Dict] = []
        self.equity_curve: List[Dict] = []
        
        # State
        self.market_data: Dict[str, List] = {}  # {symbol: [bar1, bar2, ...]}
        self.current_atr: Dict[str, float] = {}
        
    def run(self, bars: Dict[str, List[Dict]], symbols: List[str] = None) -> Dict:
        """
        Spustí backtest
        
        Args:
            bars: {symbol: [bar1, bar2, ...]}
            symbols: Seznam symbolů pro testování (None = všechny)
            
        Returns:
            Výsledky backtestu
        """
        if symbols is None:
            symbols = list(bars.keys())
        
        # Inicializuj market_data pro každý symbol
        for symbol in symbols:
            self.market_data[symbol] = bars[symbol][:100]  # Začni s 100 bary (warm-up)
        
        # Data source
        data_source = HistoricalDataSource(bars)
        
        # Projdi všechny bary
        bar_index = 100  # Začni po warm-up
        max_bars = max(len(bars[s]) for s in symbols)
        
        while bar_index < max_bars:
            # Získej bary pro aktuální index
            current_bars = {}
            for symbol in symbols:
                if bar_index < len(bars[symbol]):
                    bar = bars[symbol][bar_index]
                    self.market_data[symbol].append(bar)
                    current_bars[symbol] = bar
                    
                    # Aktualizuj microstructure
                    if 'volume' in bar and bar['volume'] > 0:
                        bar_timestamp = bar.get('timestamp')
                        if isinstance(bar_timestamp, str):
                            from datetime import datetime
                            bar_timestamp = datetime.fromisoformat(bar_timestamp.replace('Z', '+00:00'))
                        self.microstructure.update_volume_profile(symbol, bar_timestamp, bar['volume'])
            
            # Pro každý symbol proveď analýzu
            for symbol in symbols:
                if symbol not in current_bars:
                    continue
                
                symbol_bars = list(self.market_data[symbol])
                
                # 1. Regime detection
                regime_data = self.regime_detector.detect(symbol_bars)
                
                # 2. Pivots
                timeframe = self.config.get('timeframe', 'M5')
                pivot_sets = self.pivot_calc.calculate_pivots(symbol_bars, timeframe)
                piv = {}
                if pivot_sets.get('daily'):
                    daily = pivot_sets['daily']
                    piv = {
                        'pivot': daily.pivot,
                        'r1': daily.r1, 'r2': daily.r2,
                        's1': daily.s1, 's2': daily.s2
                    }
                
                # 3. Swings
                swing_state = self.swing_engine.detect_swings(symbol_bars, current_atr=self.current_atr.get(symbol, 0))
                swing = {
                    'trend': swing_state.trend.value if swing_state.trend else 'UNKNOWN',
                    'quality': swing_state.swing_quality,
                    'last_high': swing_state.last_high.price if swing_state.last_high else None,
                    'last_low': swing_state.last_low.price if swing_state.last_low else None,
                }
                
                # 4. Microstructure
                micro_data = {}
                if len(symbol_bars) >= 14:
                    micro_data = self.microstructure.get_microstructure_summary(symbol, symbol_bars)
                
                # 5. Signal detection
                signals = self.edge.detect_signals(
                    bars=symbol_bars,
                    regime_state=regime_data,
                    pivot_levels=piv,
                    swing_state=swing,
                    microstructure_data=micro_data
                )
                
                # 6. Execute signals (zjednodušeně - bez risk manageru, jen základní exekuce)
                if signals:
                    signal = signals[0]
                    self._execute_signal(symbol, signal, current_bars[symbol]['close'])
            
            # Aktualizuj pozice s aktuálními cenami
            current_prices = {s: current_bars[s]['close'] for s in symbols if s in current_bars}
            closed_positions = self.broker.update_positions(current_prices)
            
            # Sleduj equity curve
            self.equity_curve.append({
                'timestamp': current_bars[symbols[0]]['timestamp'] if symbols else None,
                'equity': self.broker.equity,
                'balance': self.broker.balance,
                'open_positions': len(self.broker.positions)
            })
            
            # Ulož uzavřené trades
            for position in closed_positions:
                self.trades.append({
                    'symbol': position.symbol,
                    'direction': position.direction,
                    'entry': position.entry_price,
                    'exit': position.close_price,
                    'size': position.size,
                    'pnl': position.pnl,
                    'opened_at': position.opened_at.isoformat(),
                    'closed_at': position.closed_at.isoformat()
                })
            
            bar_index += 1
        
        # Zavři všechny otevřené pozice na konci
        final_prices = {s: self.market_data[s][-1]['close'] for s in symbols}
        for position in list(self.broker.positions.values()):
            position.closed_at = datetime.now()
            position.close_price = final_prices[position.symbol]
            if position.direction == "BUY":
                position.pnl = (position.close_price - position.entry_price) * position.size
            else:
                position.pnl = (position.entry_price - position.close_price) * position.size
            self.broker.balance += position.pnl
            self.trades.append({
                'symbol': position.symbol,
                'direction': position.direction,
                'entry': position.entry_price,
                'exit': position.close_price,
                'size': position.size,
                'pnl': position.pnl,
                'opened_at': position.opened_at.isoformat(),
                'closed_at': position.closed_at.isoformat()
            })
        
        # Vypočti statistiky
        return self._calculate_statistics()
    
    def _execute_signal(self, symbol: str, signal, current_price: float):
        """Zjednodušená exekuce signálu (bez risk manageru pro jednoduchost)"""
        # Pro jednoduchost - fixní velikost pozice
        position_size = 1.0  # 1 lot
        
        # Execute order
        position = self.broker.execute_order(
            symbol=symbol,
            direction=signal.signal_type.value,
            entry=current_price,  # Použij current_price místo signal.entry
            size=position_size,
            sl=signal.stop_loss,
            tp=signal.take_profit
        )
    
    def _calculate_statistics(self) -> Dict:
        """Vypočti statistiky backtestu"""
        if not self.trades:
            return {
                'total_trades': 0,
                'win_rate': 0,
                'total_pnl': 0,
                'final_balance': self.broker.balance
            }
        
        winning_trades = [t for t in self.trades if t['pnl'] > 0]
        losing_trades = [t for t in self.trades if t['pnl'] < 0]
        
        total_pnl = sum(t['pnl'] for t in self.trades)
        win_rate = len(winning_trades) / len(self.trades) * 100 if self.trades else 0
        
        avg_win = sum(t['pnl'] for t in winning_trades) / len(winning_trades) if winning_trades else 0
        avg_loss = sum(t['pnl'] for t in losing_trades) / len(losing_trades) if losing_trades else 0
        profit_factor = abs(sum(t['pnl'] for t in winning_trades) / sum(t['pnl'] for t in losing_trades)) if losing_trades and sum(t['pnl'] for t in losing_trades) != 0 else 0
        
        return {
            'total_trades': len(self.trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'total_pnl_pct': (total_pnl / self.initial_balance) * 100,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'final_balance': self.broker.balance,
            'max_drawdown': self._calculate_max_drawdown(),
            'equity_curve': self.equity_curve,
            'trades': self.trades
        }
    
    def _calculate_max_drawdown(self) -> float:
        """Vypočti maximální drawdown"""
        if not self.equity_curve:
            return 0.0
        
        peak = self.initial_balance
        max_dd = 0.0
        
        for point in self.equity_curve:
            equity = point['equity']
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        
        return max_dd
```

## 🚀 Použití

```python
# backtesting/run_backtest.py
import json
import sys
from pathlib import Path

# Přidat src/ do Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from backtesting.backtester import BacktestRunner

# Načti historická data (např. z CSV nebo JSON)
with open('historical_bars.json', 'r') as f:
    bars_data = json.load(f)  # {symbol: [bar1, bar2, ...]}

# Konfigurace (stejná jako apps.yaml)
config = {
    'regime': {},
    'pivots': {},
    'swings': {},
    'edges': {},
    'microstructure': {},
    'timeframe': 'M5',
    'backtest': {
        'spread_pct': 0.001,  # 0.1% spread
        'slippage_pct': 0.0005  # 0.05% slippage
    }
}

# Spusť backtest
runner = BacktestRunner(config, initial_balance=1000000.0)
results = runner.run(bars_data, symbols=['US100', 'GER40'])

# Výsledky
print(f"Total trades: {results['total_trades']}")
print(f"Win rate: {results['win_rate']:.2f}%")
print(f"Total PnL: {results['total_pnl']:.2f} CZK ({results['total_pnl_pct']:.2f}%)")
print(f"Profit factor: {results['profit_factor']:.2f}")
print(f"Max drawdown: {results['max_drawdown']:.2f}%")

# Ulož výsledky
with open('backtest_results.json', 'w') as f:
    json.dump(results, f, indent=2)
```

## 📊 Výstup backtestu a prezentace výsledků

### 🎯 Struktura výsledků

Backtest vrátí komplexní objekt s výsledky v následující struktuře:

```python
{
    # === METADATA ===
    "metadata": {
        "backtest_id": "backtest_2025-12-25_143022",
        "start_date": "2025-01-01T00:00:00Z",
        "end_date": "2025-12-25T23:59:59Z",
        "initial_balance_czk": 1000000.0,
        "symbols": ["NASDAQ", "DAX"],
        "timeframe": "M5",
        "config": {...},  # Použitá konfigurace
        "duration_seconds": 1245.67,
        "total_bars_processed": 125000
    },
    
    # === VÝKONNOSTNÍ METRIKY ===
    "performance": {
        "total_trades": 145,
        "winning_trades": 87,
        "losing_trades": 58,
        "win_rate_pct": 60.0,
        "total_pnl_czk": 156789.50,
        "total_pnl_pct": 15.68,
        "final_balance_czk": 1156789.50,
        "profit_factor": 1.85,
        "expectancy_czk": 1081.31,
        
        # Average wins/losses
        "avg_win_czk": 2345.67,
        "avg_loss_czk": -1234.56,
        "avg_rrr": 1.90,  # Average Risk:Reward ratio
        
        # Largest wins/losses
        "largest_win_czk": 15234.56,
        "largest_loss_czk": -5678.90,
        
        # Drawdown metrics
        "max_drawdown_czk": -45678.90,
        "max_drawdown_pct": 4.57,
        "max_drawdown_start": "2025-03-15T10:30:00Z",
        "max_drawdown_end": "2025-03-20T14:15:00Z",
        "max_drawdown_duration_days": 5.16,
        
        # Risk metrics
        "sharpe_ratio": 1.42,
        "sortino_ratio": 1.89,
        "calmar_ratio": 3.43,  # Return / Max Drawdown
        
        # Consecutive wins/losses
        "max_consecutive_wins": 8,
        "max_consecutive_losses": 5,
        
        # Monthly breakdown
        "monthly_pnl": {
            "2025-01": {"pnl_czk": 12345.67, "trades": 12, "win_rate": 66.67},
            "2025-02": {"pnl_czk": 23456.78, "trades": 15, "win_rate": 60.00},
            # ...
        }
    },
    
    # === EQUITY CURVE ===
    "equity_curve": [
        {
            "timestamp": "2025-01-01T09:00:00Z",
            "balance_czk": 1000000.0,
            "equity_czk": 1000000.0,
            "drawdown_czk": 0.0,
            "drawdown_pct": 0.0,
            "open_positions": 0
        },
        # ... další body
    ],
    
    # === TRADES DETAIL ===
    "trades": [
        {
            "trade_id": "trade_001",
            "symbol": "NASDAQ",
            "direction": "BUY",
            "entry_price": 25540.18,
            "exit_price": 25590.18,
            "entry_time": "2025-01-15T09:30:00Z",
            "exit_time": "2025-01-15T14:45:00Z",
            "duration_minutes": 315,
            "size_lots": 12.0,
            "pnl_czk": 6000.0,
            "pnl_pct": 0.6,
            "commission_czk": -295.20,
            "net_pnl_czk": 5704.80,
            
            # Risk metrics
            "risk_czk": 3000.0,
            "sl_price": 25500.18,
            "tp_price": 25590.18,
            "planned_rrr": 2.0,
            "actual_rrr": 1.90,
            
            # Signal context
            "signal_quality": 75.5,
            "signal_confidence": 82.0,
            "regime": "TREND_UP",
            "setup_type": "PULLBACK",
            "patterns": ["FIB_618", "PIVOT_S1"],
            
            # Market context at entry
            "entry_atr": 11.4,
            "entry_volume_zscore": 1.2,
            "entry_vwap_distance": -0.15,  # % below VWAP
            
            # Exit reason
            "exit_reason": "TP_HIT"  # TP_HIT, SL_HIT, TRAILING_STOP, MANUAL
        },
        # ... další trades
    ],
    
    # === ANALYTIKA ===
    "analytics": {
        # Performance podle symbolu
        "by_symbol": {
            "NASDAQ": {
                "trades": 89,
                "win_rate": 62.92,
                "total_pnl_czk": 98765.43,
                "avg_pnl_czk": 1109.72
            },
            "DAX": {
                "trades": 56,
                "win_rate": 55.36,
                "total_pnl_czk": 58024.07,
                "avg_pnl_czk": 1036.14
            }
        },
        
        # Performance podle setupu
        "by_setup": {
            "PULLBACK": {
                "trades": 78,
                "win_rate": 64.10,
                "total_pnl_czk": 92345.67
            },
            "BREAKOUT": {
                "trades": 45,
                "win_rate": 55.56,
                "total_pnl_czk": 42345.78
            },
            "BREAKOUT_RETEST": {
                "trades": 22,
                "win_rate": 59.09,
                "total_pnl_czk": 22098.05
            }
        },
        
        # Performance podle regime
        "by_regime": {
            "TREND_UP": {
                "trades": 89,
                "win_rate": 65.17,
                "total_pnl_czk": 112345.67
            },
            "TREND_DOWN": {
                "trades": 34,
                "win_rate": 52.94,
                "total_pnl_czk": 23456.78
            },
            "RANGE": {
                "trades": 22,
                "win_rate": 45.45,
                "total_pnl_czk": 20987.05
            }
        },
        
        # Performance podle signal quality
        "by_quality": {
            "high": {  # >= 70
                "trades": 56,
                "win_rate": 71.43,
                "total_pnl_czk": 78901.23
            },
            "medium": {  # 50-69
                "trades": 67,
                "win_rate": 58.21,
                "total_pnl_czk": 56789.45
            },
            "low": {  # < 50
                "trades": 22,
                "win_rate": 40.91,
                "total_pnl_czk": 21098.82
            }
        },
        
        # Time of day analysis
        "by_time_of_day": {
            "09:00-12:00": {"trades": 45, "win_rate": 62.22, "pnl_czk": 52345.67},
            "12:00-15:30": {"trades": 67, "win_rate": 59.70, "pnl_czk": 61234.56},
            "15:30-18:00": {"trades": 23, "win_rate": 56.52, "pnl_czk": 23456.78},
            "18:00-22:00": {"trades": 10, "win_rate": 50.00, "pnl_czk": 9752.49}
        },
        
        # Monthly equity progression
        "monthly_equity": [
            {"month": "2025-01", "equity_start": 1000000.0, "equity_end": 1012345.67},
            {"month": "2025-02", "equity_start": 1012345.67, "equity_end": 1035802.45},
            # ...
        ]
    },
    
    # === WARNINGS & ERRORS ===
    "warnings": [
        "Low trade count - statistics may not be reliable",
        "Max drawdown exceeded 5% threshold"
    ],
    "errors": []
}
```

### 📁 Formáty výstupu

Backtest výsledky budou uloženy ve více formátech pro různé použití:

#### 1. JSON (Kompletní data)

```python
# backtesting/results/backtest_2025-12-25_143022.json
# Plná struktura výsledků pro programovou analýzu
```

**Použití:**
- Programová analýza výsledků
- Srovnání více backtestů
- Import do dalších nástrojů

#### 2. CSV (Trades detail)

```csv
# backtesting/results/backtest_2025-12-25_143022_trades.csv
trade_id,symbol,direction,entry_time,exit_time,duration_min,entry_price,exit_price,size_lots,pnl_czk,win_rate,setup_type,regime
trade_001,NASDAQ,BUY,2025-01-15 09:30:00,2025-01-15 14:45:00,315,25540.18,25590.18,12.0,5704.80,1,PULLBACK,TREND_UP
...
```

**Použití:**
- Import do Excel/Google Sheets
- Detailní analýza trades
- Vytváření vlastních reportů

#### 3. HTML Report (Vizuální přehled)

```html
<!-- backtesting/results/backtest_2025-12-25_143022.html -->
<!DOCTYPE html>
<html>
<head>
    <title>Backtest Results - 2025-12-25</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        /* Styling */
    </style>
</head>
<body>
    <h1>Backtest Results</h1>
    
    <!-- Summary Cards -->
    <div class="summary">
        <div class="card">
            <h3>Total PnL</h3>
            <p class="value positive">+156,789.50 CZK (+15.68%)</p>
        </div>
        <div class="card">
            <h3>Win Rate</h3>
            <p class="value">60.00%</p>
        </div>
        <div class="card">
            <h3>Profit Factor</h3>
            <p class="value">1.85</p>
        </div>
        <div class="card">
            <h3>Max Drawdown</h3>
            <p class="value negative">-4.57%</p>
        </div>
    </div>
    
    <!-- Equity Curve Chart -->
    <div id="equity-chart"></div>
    <script>
        Plotly.newPlot('equity-chart', equityData, layout);
    </script>
    
    <!-- Drawdown Chart -->
    <div id="drawdown-chart"></div>
    
    <!-- Monthly Performance Table -->
    <table>
        <thead>
            <tr>
                <th>Month</th>
                <th>Trades</th>
                <th>Win Rate</th>
                <th>PnL (CZK)</th>
            </tr>
        </thead>
        <tbody>
            <!-- Monthly data -->
        </tbody>
    </table>
    
    <!-- Trades Table -->
    <table>
        <!-- All trades -->
    </table>
</body>
</html>
```

**Použití:**
- Okamžitý vizuální přehled
- Sdílení výsledků s týmem
- Prezentace

#### 4. Markdown Summary (Textový přehled)

```markdown
# backtesting/results/backtest_2025-12-25_143022_summary.md

# Backtest Results

**Period:** 2025-01-01 to 2025-12-25  
**Initial Balance:** 1,000,000.00 CZK  
**Final Balance:** 1,156,789.50 CZK

## Performance Summary

| Metric | Value |
|--------|-------|
| Total Trades | 145 |
| Win Rate | 60.00% |
| Total PnL | +156,789.50 CZK (+15.68%) |
| Profit Factor | 1.85 |
| Max Drawdown | -4.57% |
| Sharpe Ratio | 1.42 |

## Top Performing Setups

1. PULLBACK: 78 trades, 64.10% win rate, +92,345.67 CZK
2. BREAKOUT: 45 trades, 55.56% win rate, +42,345.78 CZK
3. BREAKOUT_RETEST: 22 trades, 59.09% win rate, +22,098.05 CZK

## Monthly Breakdown

| Month | Trades | Win Rate | PnL (CZK) |
|-------|--------|----------|-----------|
| 2025-01 | 12 | 66.67% | +12,345.67 |
| 2025-02 | 15 | 60.00% | +23,456.78 |
...
```

### 📈 Grafické výstupy

#### 1. Equity Curve
- Graf vývoje equity v čase
- Zobrazení drawdown oblastí
- Srovnání s buy-and-hold (pokud k dispozici)

#### 2. Drawdown Chart
- Max drawdown v čase
- Délka recovery periodů

#### 3. Monthly PnL Bar Chart
- PnL po měsících
- Win rate overlay

#### 4. Setup Performance
- Srovnání výkonnosti různých setupů
- Win rate vs. avg PnL scatter

#### 5. Trade Distribution
- Histogram PnL distribuce
- Win/Loss rozložení

### 🔧 Implementace

```python
# backtesting/results_reporter.py

class BacktestResultsReporter:
    """Generuje různé formáty výsledků backtestu"""
    
    def __init__(self, results: Dict, output_dir: Path):
        self.results = results
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def save_all_formats(self):
        """Uloží všechny formáty výsledků"""
        self.save_json()
        self.save_csv()
        self.save_html()
        self.save_markdown()
    
    def save_json(self):
        """Uloží kompletní JSON"""
        json_path = self.output_dir / f"{self.results['metadata']['backtest_id']}.json"
        with open(json_path, 'w') as f:
            json.dump(self.results, f, indent=2, default=str)
    
    def save_csv(self):
        """Uloží trades do CSV"""
        csv_path = self.output_dir / f"{self.results['metadata']['backtest_id']}_trades.csv"
        df = pd.DataFrame(self.results['trades'])
        df.to_csv(csv_path, index=False)
    
    def save_html(self):
        """Vygeneruje HTML report s grafy"""
        html_path = self.output_dir / f"{self.results['metadata']['backtest_id']}.html"
        html_content = self._generate_html_report()
        with open(html_path, 'w') as f:
            f.write(html_content)
    
    def save_markdown(self):
        """Vygeneruje Markdown summary"""
        md_path = self.output_dir / f"{self.results['metadata']['backtest_id']}_summary.md"
        md_content = self._generate_markdown_summary()
        with md_path.open('w') as f:
            f.write(md_content)
```

### 🎯 Konzolový výstup

Při spuštění backtestu se zobrazí přehledný souhrn:

```bash
$ python backtesting/run_backtest.py --symbol NASDAQ --start-date 2025-01-01 --end-date 2025-12-25

🚀 Starting backtest...
📊 Processing 125,000 bars...
⏳ 45% complete... (56250/125000 bars)
⏳ 90% complete... (112500/125000 bars)
✅ Backtest completed in 20.5 seconds

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                    BACKTEST RESULTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📅 Period:        2025-01-01 to 2025-12-25
💰 Initial Balance: 1,000,000.00 CZK
💰 Final Balance:   1,156,789.50 CZK

📊 PERFORMANCE METRICS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total Trades:           145
Win Rate:               60.00%  (87 wins, 58 losses)
Total PnL:              +156,789.50 CZK  (+15.68%)
Profit Factor:          1.85
Expectancy:             +1,081.31 CZK per trade
Max Drawdown:           -4.57%  (-45,678.90 CZK)
Sharpe Ratio:           1.42

📈 BEST PERFORMERS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Best Setup:             PULLBACK  (64.10% WR, +92,345.67 CZK)
Best Symbol:            NASDAQ  (62.92% WR, +98,765.43 CZK)
Best Regime:            TREND_UP  (65.17% WR, +112,345.67 CZK)

📁 RESULTS SAVED TO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
JSON:    backtesting/results/backtest_2025-12-25_143022.json
CSV:     backtesting/results/backtest_2025-12-25_143022_trades.csv
HTML:    backtesting/results/backtest_2025-12-25_143022.html
Markdown: backtesting/results/backtest_2025-12-25_143022_summary.md
```

## 🔄 Integrace s existujícím kódem

### Možnost 1: Oddělený script (DOPORUČENO)
- Vytvoř `backtest_example.py` v root adresáři
- Importuje komponenty z `trading_assistant`
- Spustí se nezávisle na AppDaemon
- **Výhody:** Žádné změny v existujícím kódu, jednoduché

### Možnost 2: Přepínač v main.py
- Přidej `mode: backtest` do configu
- Pokud backtest mode, použij `BacktestRunner` místo `TradingAssistant`
- **Nevýhody:** Více změn, složitější

## 📊 Co je potřeba implementovat

1. ✅ **Data Source** - abstrakce nad daty
2. ✅ **Broker Simulator** - simulace exekuce
3. ✅ **Backtest Runner** - orchestrátor
4. ✅ **Results Reporter** - generování výstupů (JSON, CSV, HTML, Markdown)
5. ✅ **Performance Analytics** - výpočet metrik a analytiky
6. ⚠️ **Risk Manager integrace** - pro realističtější position sizing
7. ⚠️ **Trailing stops** - simulace trailing stop logiky
8. ⚠️ **Partial exits** - simulace částečných exitů
9. ⚠️ **Trading hours** - respektování trading hours
10. ⚠️ **Vizualizace** - grafy (equity curve, drawdown, atd.)

## 🎯 Fáze implementace

### Fáze 1: Základní MVP (1-2 dny)
- Data Source
- Broker Simulator (základní)
- Backtest Runner (bez risk manageru)
- Základní statistiky (win rate, PnL, profit factor)
- JSON výstup výsledků
- Konzolový přehled výsledků

### Fáze 2: Realističnost (2-3 dny)
- Integrace Risk Manageru
- Trailing stops
- Partial exits
- Trading hours
- CSV export trades
- Markdown summary report
- Základní analytika (by symbol, by setup, by regime)

### Fáze 3: Pokročilé funkce (3-5 dní)
- HTML report s grafy
- Equity curve vizualizace
- Drawdown charts
- Pokročilá analytika (by time of day, by quality, monthly breakdown)
- Walk-forward analýza
- Monte Carlo simulace
- Portfolio backtesting
- Optimalizace parametrů

## 💡 Tipy

1. **Začni jednoduše** - MVP bez risk manageru, jen základní exekuce
2. **Použij stejné komponenty** - EdgeDetector, RegimeDetector, atd. zůstávají beze změny
3. **Testuj na malých datech** - nejdřív 1 týden, pak měsíc, pak rok
4. **Loguj vše** - ukládej každý trade, equity curve, signály
5. **Vizualizace** - použij matplotlib pro equity curve, drawdown, atd.

## 🔍 Validace

1. **Porovnání s live** - backtest by měl dát podobné výsledky jako live trading (samozřejmě s ohledem na spread/slippage)
2. **Walk-forward** - testuj na různých obdobích
3. **Out-of-sample** - testuj na datech, která nebyla použita pro optimalizaci

