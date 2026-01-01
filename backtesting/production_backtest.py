#!/usr/bin/env python3
"""
Production Backtest Runner - Používá skutečnou logiku z TradingAssistant
"""

import sys
import json
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional
from collections import defaultdict, deque

# Přidat src/ do Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# Nastavit logging
logging.basicConfig(level=logging.WARNING)  # Potlačit verbose logy

# Mock pro AppDaemon
class MockHass:
    """Mock pro hass.Hass - umožní použít TradingAssistant komponenty"""
    
    def __init__(self):
        self.states = {}
        self.logs = []
        self.debug_mode = True  # Enable debug logging for backtest
    
    def log(self, message: str, level: str = "INFO"):
        """Mock log - uložit do seznamu a tisknout důležité zprávy"""
        self.logs.append((level, message))
        # Tisknout rejection důvody a důležité informace
        if any(keyword in message for keyword in [
            "SIGNAL REJECTED", "STRICT Regime filter", "Low swing quality",
            "Signal cooldown", "Insufficient bars", "Quality:", "Confidence:",
            "EMA34", "regime_is_trend", "directions_match"
        ]):
            print(f"[{level}] {message}")
        elif level == "ERROR":
            print(f"[{level}] {message}")
    
    def error(self, message: str):
        self.log(message, "ERROR")
    
    def get_state(self, entity_id: str = None, attribute: str = None):
        """Mock get_state"""
        if entity_id is None:
            return self.states
        if entity_id in self.states:
            state_data = self.states[entity_id]
            if attribute == "all":
                return state_data
            if isinstance(state_data, dict):
                if attribute:
                    return state_data.get("attributes", {}).get(attribute)
                return state_data.get("state")
            return state_data
        return None
    
    def set_state(self, entity_id: str, state: str = None, attributes: dict = None):
        """Mock set_state"""
        self.states[entity_id] = {
            "state": state,
            "attributes": attributes or {}
        }
    
    def create_task(self, coro):
        """Mock create_task - není potřeba pro backtest"""
        pass
    
    def run_in(self, callback, delay: float):
        """Mock run_in - není potřeba pro backtest"""
        pass
    
    def run_every(self, callback, start_time: str, interval: float):
        """Mock run_every - není potřeba pro backtest"""
        pass
    
    def cancel_timer(self, handle):
        """Mock cancel_timer"""
        pass
    
    def notify(self, message: str, title: str = None):
        """Mock notify"""
        pass

def load_historical_data(symbol: str, data_dir: Path) -> List[Dict]:
    """Načíst historická data z cache souboru"""
    cache_file = data_dir / f"{symbol}_M5.jsonl"
    
    if not cache_file.exists():
        return []
    
    bars = []
    with open(cache_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    bar = json.loads(line)
                    bars.append(bar)
                except json.JSONDecodeError:
                    continue
    
    return bars

def parse_timestamp(ts: str) -> datetime:
    """Parsovat ISO timestamp"""
    try:
        if 'T' in ts:
            if ts.endswith('Z'):
                ts = ts.replace('Z', '+00:00')
            return datetime.fromisoformat(ts.replace('Z', '+00:00'))
        else:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)

class BrokerSimulator:
    """Simulace brokeru pro backtesting"""
    
    def __init__(self, initial_balance: float = 2000000.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.positions = {}  # position_id -> position dict
        self.next_position_id = 1
        self.closed_trades = []
        
    def execute_order(self, symbol: str, direction: str, entry: float, 
                     size: float, sl: float, tp: float, timestamp: datetime) -> Dict:
        """Simulovat exekuci orderu"""
        position_id = f"POS_{symbol}_{self.next_position_id}"
        self.next_position_id += 1
        
        # Spread (realistický pro indexy: ~2-3 points)
        spread = 2.5 if symbol == 'GER40' else 2.0
        
        # Aplikovat spread
        if direction == "BUY":
            execution_price = entry + spread
        else:
            execution_price = entry - spread
        
        position = {
            'position_id': position_id,
            'symbol': symbol,
            'direction': direction,
            'entry_price': execution_price,
            'size': size,
            'stop_loss': sl,
            'take_profit': tp,
            'opened_at': timestamp,
            'closed_at': None,
            'close_price': None,
            'pnl': 0.0
        }
        
        self.positions[position_id] = position
        return position
    
    def update_positions(self, current_prices: Dict[str, float], timestamp: datetime) -> List[Dict]:
        """Aktualizovat pozice a kontrolovat SL/TP"""
        closed = []
        
        for position_id, position in list(self.positions.items()):
            if position['closed_at']:
                continue
            
            current_price = current_prices.get(position['symbol'])
            if current_price is None:
                continue
            
            # Kontrola SL/TP
            should_close = False
            close_price = None
            
            if position['direction'] == "BUY":
                if current_price <= position['stop_loss']:
                    should_close = True
                    close_price = position['stop_loss']
                elif current_price >= position['take_profit']:
                    should_close = True
                    close_price = position['take_profit']
            else:  # SELL
                if current_price >= position['stop_loss']:
                    should_close = True
                    close_price = position['stop_loss']
                elif current_price <= position['take_profit']:
                    should_close = True
                    close_price = position['take_profit']
            
            if should_close:
                position['closed_at'] = timestamp
                position['close_price'] = close_price
                
                # Vypočítat PnL
                if position['direction'] == "BUY":
                    pnl = (close_price - position['entry_price']) * position['size'] * 10  # Zjednodušený výpočet
                else:
                    pnl = (position['entry_price'] - close_price) * position['size'] * 10
                
                position['pnl'] = pnl
                self.balance += pnl
                closed.append(position)
                
                # Přesunout do closed trades
                self.closed_trades.append(position)
                del self.positions[position_id]
        
        return closed

class ProductionBacktestRunner:
    """Backtest runner používající skutečnou produkční logiku"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.data_dir = Path(config.get('data_dir', 'backtesting/data'))
        self.results_dir = Path(config.get('results_dir', 'backtesting/results'))
        self.results_dir.mkdir(parents=True, exist_ok=True)
        
        # Mock hass
        self.mock_hass = MockHass()
        
        # Initialize components
        self._initialize_components()
        
        # Broker simulator
        self.broker = BrokerSimulator(config.get('initial_balance', 2000000.0))
        
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
        
        # Equity curve
        self.equity_curve = []
    
    def _load_production_config(self) -> dict:
        """Načíst konfiguraci z apps.yaml nebo backtest_config.yaml"""
        try:
            import yaml
            
            # Zkusit načíst backtest-specifickou konfiguraci
            backtest_config_path = project_root / "backtesting" / "config" / "backtest_config.yaml"
            if backtest_config_path.exists():
                print("📋 Používám backtest-specifickou konfiguraci (relaxované prahy)")
                with open(backtest_config_path, 'r') as f:
                    return yaml.safe_load(f)
            
            # Fallback na apps.yaml
            config_path = project_root / "src" / "apps.yaml"
            print("📋 Používám produkční konfiguraci z apps.yaml")
            
            with open(config_path, 'r') as f:
                content = f.read()
                # Nahradit !secret referencí (nejsou potřeba pro backtesting)
                lines = []
                for line in content.split('\n'):
                    if '!secret' in line:
                        # Nahradit !secret hodnotami z defaultů nebo None
                        key = line.split(':')[0].strip()
                        if 'ws_uri' in key or 'access_token' in key or 'trader_login' in key or 'client_id' in key or 'client_secret' in key:
                            lines.append(f'  {key}: ""')
                        elif 'ctid_trader_account_id' in key:
                            lines.append('  ctid_trader_account_id: 0')
                        else:
                            lines.append(f'  {key}: ""')
                    else:
                        lines.append(line)
                content = '\n'.join(lines)
                
                data = yaml.safe_load(content)
                return data.get('trading_assistant', {})
        except Exception as e:
            print(f"⚠️  Chyba při načítání apps.yaml: {e}, používám defaultní hodnoty")
            return {}
    
    def _initialize_components(self):
        """Inicializovat produkční komponenty s konfigurací z apps.yaml"""
        # Načíst konfiguraci z apps.yaml
        self.prod_config = self._load_production_config()
        
        from trading_assistant.regime import RegimeDetector
        from trading_assistant.edges import EdgeDetector
        from trading_assistant.risk_manager import RiskManager
        from trading_assistant.pivots import PivotCalculator
        from trading_assistant.simple_swing_detector import SimpleSwingDetector
        from trading_assistant.microstructure_lite import MicrostructureAnalyzer
        from trading_assistant.balance_tracker import BalanceTracker
        from trading_assistant.daily_risk_tracker import DailyRiskTracker
        
        # Mock Hass pro komponenty, které potřebují app
        self.mock_hass = MockHass()
        
        # Initialize components s konfigurací z apps.yaml nebo backtest config
        regime_config = self.prod_config.get('regime', {})
        self.regime_detector = RegimeDetector(regime_config)
        
        edges_config = self.prod_config.get('edges', {})
        # Pro backtest: pokud je require_regime_alignment: false, použijeme relaxovanější režim
        # Přidat app do config pro logování
        edges_config['app'] = self.mock_hass
        edges_config['main_config'] = self.prod_config
        self.edge_detector = EdgeDetector(edges_config)
        
        # Poznámka: STRICT regime filter je hardcoded v edges.py
        # Pokud chceme ho vypnout, museli bychom upravit edges.py nebo vytvořit wrapper
        
        # RiskManager - použít kompletní konfiguraci z apps.yaml
        account_balance = self.prod_config.get('account_balance', 2000000)
        
        # Načíst symbol_specs z apps.yaml (mapovat GER40 -> DAX, US100 -> NASDAQ)
        symbol_specs_from_yaml = self.prod_config.get('symbol_specs', {})
        symbol_specs = {}
        
        # Mapovat podle aliasů z apps.yaml
        if 'DAX' in symbol_specs_from_yaml:
            symbol_specs['DAX'] = symbol_specs_from_yaml['DAX']
            symbol_specs['GER40'] = symbol_specs_from_yaml['DAX'].copy()  # GER40 používá stejné spec jako DAX
        if 'NASDAQ' in symbol_specs_from_yaml:
            symbol_specs['NASDAQ'] = symbol_specs_from_yaml['NASDAQ']
            symbol_specs['US100'] = symbol_specs_from_yaml['NASDAQ'].copy()  # US100 používá stejné spec jako NASDAQ
        
        risk_config = {
            'account_balance': account_balance,
            'account_currency': self.prod_config.get('account_currency', 'CZK'),
            'max_risk_per_trade': self.prod_config.get('base_risk_per_trade', 0.005),
            'max_risk_total': self.prod_config.get('max_risk_total', 0.03),
            'max_positions': self.prod_config.get('max_positions', 1),
            'daily_loss_limit': self.prod_config.get('daily_loss_limit', 0.02),
            'max_margin_usage': self.prod_config.get('max_margin_usage', 80.0),
            'symbol_specs': symbol_specs,
            'risk_adjustments': self.prod_config.get('risk_adjustments', {}),
            'regime_adjustments': self.prod_config.get('regime_adjustments', {}),
            'volatility_adjustments': self.prod_config.get('volatility_adjustments', {}),
            # Position sizing parametry
            'use_wide_stops': self.prod_config.get('use_wide_stops', True),
            'target_position_lots': self.prod_config.get('target_position_lots', 12.0),
            'min_position_lots': self.prod_config.get('min_position_lots', 8.0),
            'max_position_lots': self.prod_config.get('max_position_lots', 20.0),
        }
        
        self.balance_tracker = BalanceTracker(initial_balance=account_balance)
        self.risk_manager = RiskManager(config=risk_config, balance_tracker=self.balance_tracker)
        
        # PivotCalculator
        pivots_config = self.prod_config.get('pivots', {})
        self.pivot_calc = PivotCalculator(pivots_config)
        
        # SimpleSwingDetector - použít konfiguraci z apps.yaml
        swings_config = self.prod_config.get('swings', {})
        self.swing_engine = SimpleSwingDetector(
            config={
                'lookback': 5,
                'min_move_pct': 0.0015,
                'use_pivot_validation': swings_config.get('use_pivot_validation', True),
                'pivot_confluence_atr': swings_config.get('pivot_confluence_atr', 0.3),
                'atr_multiplier_m5': swings_config.get('atr_multiplier_m5', 0.5),
                'min_bars_between': swings_config.get('min_bars_between', 2),
                'min_swing_quality': swings_config.get('min_swing_quality', 20),
            },
            pivot_calculator=self.pivot_calc
        )
        
        # MicrostructureAnalyzer
        microstructure_config = self.prod_config.get('microstructure', {})
        self.microstructure = MicrostructureAnalyzer(microstructure_config)
        
        # DailyRiskTracker
        daily_risk_limit = self.prod_config.get('auto_trading', {}).get('daily_risk_limit_pct', 0.04)
        self.daily_risk_tracker = DailyRiskTracker(
            daily_limit_percentage=daily_risk_limit,
            balance_tracker=self.balance_tracker,
            config=self.prod_config
        )
        
        # Connect
        self.risk_manager.balance_tracker = self.balance_tracker
        
        # Market data storage
        self.market_data = defaultdict(lambda: deque(maxlen=5000))
        
        # ORB tracking (jako v produkci)
        self._orb_triggered = {}  # {symbol_date: True}
        self.current_atr = {}  # {symbol: atr_value}
    
    def run_backtest(self, symbols: List[str]):
        """Spustit backtest"""
        print("=" * 70)
        print("🚀 PRODUKČNÍ BACKTEST")
        print("=" * 70)
        print(f"Počáteční balance: {self.broker.initial_balance:,.2f} CZK")
        print(f"Symboly: {', '.join(symbols)}")
        print()
        
        # Načíst data
        all_bars = {}
        for symbol in symbols:
            bars = load_historical_data(symbol, self.data_dir)
            if bars:
                bars.sort(key=lambda b: parse_timestamp(b['timestamp']))
                all_bars[symbol] = bars
                print(f"✅ {symbol}: {len(bars)} barů")
            else:
                print(f"❌ Žádná data pro {symbol}")
                return None
        
        # Spustit backtest - zpracovat každý bar
        for symbol, bars in all_bars.items():
            print(f"\n📈 Zpracovávám {symbol}...")
            self._process_symbol(symbol, bars)
        
        # Vypočítat statistiky
        self._calculate_statistics()
        
        # Zobrazit výsledky
        self._display_results()
        
        # Uložit výsledky
        return self._save_results()
    
    def _process_symbol(self, symbol: str, bars: List[Dict]):
        """Zpracovat bary pro symbol - používá produkční logiku"""
        min_bars = 100  # Minimální počet barů pro analýzu
        
        for i, bar in enumerate(bars):
            timestamp = parse_timestamp(bar['timestamp'])
            
            # Přidat bar do historie
            self.market_data[symbol].append(bar)
            bars_list = list(self.market_data[symbol])
            
            # Potřebujeme minimální počet barů
            if len(bars_list) < min_bars:
                continue
            
            # Aktualizovat pozice v broker simulatoru
            current_price = bar['close']
            self.broker.update_positions({symbol: current_price}, timestamp)
            
            # Aktualizovat equity curve
            self.equity_curve.append({
                'timestamp': timestamp.isoformat(),
                'balance': self.broker.balance,
                'pnl': self.broker.balance - self.broker.initial_balance
            })
            
            # Použít produkční logiku - process_market_data
            try:
                # 1. EdgeDetector signály (swing trading)
                signals = self._process_market_data(symbol, bars_list)
                
                # Debug: Kolik signálů generuje EdgeDetector?
                if signals:
                    print(f"🔍 [{symbol}] EdgeDetector generoval {len(signals)} signálů")
                    for sig in signals:
                        print(f"   • {sig.signal_type.value}: Entry={sig.entry:.2f}, SL={sig.stop_loss:.2f}, TP={sig.take_profit:.2f}, Quality={sig.quality:.1f}%, Confidence={sig.confidence:.1f}%")
                
                # Zpracovat EdgeDetector signály
                executed_count = 0
                for signal in signals:
                    print(f"🔍 [{symbol}] Zkouším exekuovat signál: {signal.signal_type.value} @ {signal.entry:.2f}")
                    try:
                        self._execute_signal(symbol, signal, current_price, timestamp)
                        executed_count += 1
                        print(f"✅ [{symbol}] Signál exekuován ({executed_count}/{len(signals)})")
                    except Exception as e:
                        print(f"❌ [{symbol}] Chyba při exekuci signálu: {e}")
                        import traceback
                        traceback.print_exc()
                
                # 2. ORB signály (Opening Range Breakout) - NOVĚ!
                if len(bars_list) >= 20:
                    orb_signals = self._detect_orb_signals(symbol, bars_list, timestamp)
                    if orb_signals:
                        print(f"🔍 [{symbol}] Detekováno {len(orb_signals)} ORB signálů")
                        for orb_signal in orb_signals:
                            print(f"🔍 [{symbol}] Zkouším exekuovat ORB signál")
                            try:
                                self._execute_signal(symbol, orb_signal, current_price, timestamp)
                                print(f"✅ [{symbol}] ORB signál exekuován")
                            except Exception as e:
                                print(f"❌ [{symbol}] Chyba při exekuci ORB signálu: {e}")
                                import traceback
                                traceback.print_exc()
                    
            except Exception as e:
                print(f"⚠️  Chyba při zpracování baru {i}: {e}")
                import traceback
                traceback.print_exc()
                continue
    
    def _process_market_data(self, symbol: str, bars: List[Dict]) -> List[Dict]:
        """Použít produkční logiku pro detekci signálů"""
        # 1. Regime detection
        regime_state = self.regime_detector.detect(bars)
        regime_dict = {
            'state': regime_state.regime.value,
            'confidence': regime_state.confidence,
            'trend_direction': regime_state.trend_direction
        }
        
        # 2. Pivot calculation - vrátí dict s 'daily' a možná 'weekly' PivotSet
        pivot_sets = self.pivot_calc.calculate_pivots(bars, timeframe='M5')
        # Extrahovat daily pivots do dict formátu
        if pivot_sets.get('daily'):
            daily = pivot_sets['daily']
            pivot_levels = {
                'pivot': daily.pivot,
                'r1': daily.r1,
                'r2': daily.r2,
                's1': daily.s1,
                's2': daily.s2
            }
        else:
            pivot_levels = {}  # Fallback
        
        # 3. Swing detection - nejdřív nastavit ATR
        if hasattr(self.pivot_calc, 'current_atr') and self.pivot_calc.current_atr > 0:
            self.swing_engine.current_atr = self.pivot_calc.current_atr
            self.current_atr[symbol] = self.pivot_calc.current_atr  # Uložit pro ORB
        swing_state = self.swing_engine.detect_swings(bars, timeframe='M5')
        
        # 4. Microstructure (pro ORB a EdgeDetector)
        microstructure_data = None  # Pro EdgeDetector zatím zjednodušeně
        
        # 5. Edge detection (detekce signálů)
        # Převést swing_state (SimpleSwingState) na dict formát pro edge detector
        swing_dict_for_edge = {
            'trend': swing_state.trend if isinstance(swing_state.trend, str) else swing_state.trend.value,
            'last_high_price': swing_state.last_high.price if swing_state.last_high else None,
            'last_low_price': swing_state.last_low.price if swing_state.last_low else None,
            'swing_count': len(swing_state.swings),
            'quality': swing_state.swing_quality
        }
        
        # Debug: Logovat detailní informace před detekcí
        if len(bars) % 50 == 0:  # Každých 50 barů (častěji pro debug)
            print(f"\n{'='*70}")
            print(f"🔍 [{symbol}] SIGNAL DETECTION CHECK (bar {len(bars)})")
            print(f"{'='*70}")
            print(f"Regime: {regime_dict.get('state')} | Trend: {regime_dict.get('trend_direction')}")
            print(f"Swing: {swing_dict_for_edge.get('trend')} | Quality: {swing_dict_for_edge.get('quality', 0):.1f}%")
            print(f"ADX: {regime_dict.get('adx', 0):.1f} | Confidence: {regime_dict.get('confidence', 0):.1f}%")
            
            # Zkontrolovat EMA34 trend
            try:
                ema34_trend = self.edge_detector._get_ema34_trend(bars)
                print(f"EMA34 Trend: {ema34_trend}")
            except:
                print(f"EMA34 Trend: N/A")
            
            # Zkontrolovat strict regime filter
            if self.edge_detector.strict_regime_filter:
                regime_type = regime_dict.get('state', 'UNKNOWN')
                regime_is_trend = regime_type.upper() in ['TREND_UP', 'TREND_DOWN']
                ema34_has_trend = ema34_trend and ema34_trend.upper() in ['UP', 'DOWN'] if 'ema34_trend' in locals() else False
                print(f"STRICT FILTER: regime_is_trend={regime_is_trend}, ema34_has_trend={ema34_has_trend}")
        
        signals = self.edge_detector.detect_signals(
            bars=bars,
            regime_state=regime_dict,
            pivot_levels=pivot_levels,
            swing_state=swing_dict_for_edge,
            microstructure_data=microstructure_data
        )
        
        # Debug: Logovat výsledky
        if len(bars) % 50 == 0:
            print(f"✅ Signals generated: {len(signals)}")
            for sig in signals:
                print(f"   • {sig.signal_type.value}: Quality={sig.quality:.1f}%, Confidence={sig.confidence:.1f}%, RRR={sig.risk_reward:.2f}")
            print(f"{'='*70}\n")
        
        return signals
    
    def _detect_orb_signals(self, symbol: str, bars: List[Dict], timestamp: datetime) -> List[Dict]:
        """Detekce ORB signálů (jako v produkci)"""
        signals = []
        
        # Kontrola: ORB pouze jednou denně
        today_key = f"{symbol}_{timestamp.date()}"
        if today_key in self._orb_triggered:
            return signals  # Už bylo dnes
        
        # Kontrola: minimální počet barů
        if len(bars) < 20:
            return signals
        
        try:
            # Detect Opening Range
            or_data = self.microstructure.detect_opening_range(symbol, bars)
            
            # ORB signal pouze pokud byl trigger a není progressive
            if or_data.get('orb_triggered') and not or_data.get('progressive_or'):
                # Označit jako triggered
                self._orb_triggered[today_key] = True
                
                # Vytvořit ORB signál (zjednodušená verze produkční logiky)
                current_bar = bars[-1]
                current_price = current_bar['close']
                
                # Calculate stop and target based on OR range
                or_range = or_data['or_range']
                
                if or_data['orb_direction'] == 'LONG':
                    entry = or_data['or_high']
                    stop = or_data['or_low']
                    target = entry + (or_range * 2)  # 2:1 R:R
                    direction = 'BUY'
                else:
                    entry = or_data['or_low']
                    stop = or_data['or_high']
                    target = entry - (or_range * 2)
                    direction = 'SELL'
                
                # Vytvořit signál (kompatibilní s TradingSignal formátem)
                # Použijeme dict formát, který lze převést na TradingSignal
                orb_signal_dict = {
                    'signal_type': direction,
                    'entry': entry,
                    'stop_loss': stop,
                    'take_profit': target,
                    'confidence': 75,
                    'quality': 70,
                    'atr': self.current_atr.get(symbol, 20.0),
                    'pattern_type': 'ORB',
                    'metadata': {
                        'pattern': 'Opening Range Breakout',
                        'or_high': or_data['or_high'],
                        'or_low': or_data['or_low'],
                        'or_range': or_range
                    }
                }
                
                # Převést na TradingSignal objekt (pokud je potřeba)
                from trading_assistant.edges import TradingSignal, SignalType
                signal_type = SignalType.BUY if direction == 'BUY' else SignalType.SELL
                
                orb_signal = TradingSignal(
                    signal_type=signal_type,
                    entry=entry,
                    stop_loss=stop,
                    take_profit=target,
                    confidence=75,
                    quality=70,
                    atr=self.current_atr.get(symbol, 20.0),
                    pattern_type='ORB',
                    metadata=orb_signal_dict['metadata']
                )
                
                signals.append(orb_signal)
                print(f"✅ [{symbol}] ORB {direction} signal detected: Entry={entry:.2f}, SL={stop:.2f}, TP={target:.2f}")
                
        except Exception as e:
            print(f"⚠️  Chyba při ORB detekci pro {symbol}: {e}")
            import traceback
            traceback.print_exc()
        
        return signals
    
    def _execute_signal(self, symbol: str, signal, current_price: float, timestamp: datetime):
        """Simulovat exekuci signálu - POUŽÍVÁ STEJNOU LOGIKU JAKO PRODUKCE"""
        try:
            # Získat signal direction a prices
            signal_direction = signal.signal_type.value if hasattr(signal.signal_type, 'value') else str(signal.signal_type)
            entry_price = signal.entry if hasattr(signal, 'entry') else current_price
            stop_loss = signal.stop_loss
            take_profit = signal.take_profit
            signal_quality = signal.quality if hasattr(signal, 'quality') else 50.0
            atr_value = signal.atr if hasattr(signal, 'atr') else 0.0
            
            # === PRODUKČNÍ LOGIKA: Přepočet SL/TP distances ===
            # Stejná logika jako v main.py _try_auto_execute_signal
            
            # Check if using fixed SL/TP strategy
            use_fixed_sl_tp = self.prod_config.get('use_fixed_sl_tp', False)
            
            if use_fixed_sl_tp:
                # Advanced SL/TP strategy with market structure adjustment
                base_sl_pips = self.prod_config.get('base_sl_pips', 4000)
                fixed_rrr = self.prod_config.get('fixed_rrr', 2.0)
                sl_flexibility = self.prod_config.get('sl_flexibility_percent', 25)
                
                # Calculate flexible risk (0.4-0.6% based on signal quality)
                min_risk = self.prod_config.get('min_risk_per_trade', 0.004)
                max_risk = self.prod_config.get('max_risk_per_trade', 0.006)
                base_risk = self.prod_config.get('base_risk_per_trade', 0.005)
                
                if signal_quality >= 85:
                    risk_multiplier = max_risk / base_risk  # 1.2 (0.6%)
                elif signal_quality >= 75:
                    risk_multiplier = 1.0  # Base risk (0.5%)
                else:
                    risk_multiplier = min_risk / base_risk  # 0.8 (0.4%)
                
                # Market structure adjustment for SL (zjednodušeně - bez _calculate_sl_market_structure_adjustment)
                use_market_structure = self.prod_config.get('use_market_structure_sl', True)
                adjusted_sl_pips = base_sl_pips
                
                if use_market_structure:
                    # Zjednodušený market structure adjustment (bez full implementace)
                    # V produkci by se volal _calculate_sl_market_structure_adjustment
                    adjustment_factor = 0.0  # Pro backtest zjednodušeně
                    max_adjustment = sl_flexibility / 100.0  # 0.25
                    bounded_adjustment = max(-max_adjustment, min(max_adjustment, adjustment_factor))
                    adjusted_sl_pips = base_sl_pips * (1 + bounded_adjustment)
                
                # Convert pips to points (for indices: 1 point = 100 pips)
                sl_distance_points = adjusted_sl_pips / 100.0
                tp_distance_points = sl_distance_points * fixed_rrr
            else:
                # Use original dynamic calculation (jako produkce)
                sl_distance_points = abs(entry_price - stop_loss)
                tp_distance_points = abs(take_profit - entry_price)
            
            # === PRODUKČNÍ LOGIKA: SL/TP Band System ===
            # Stejná logika jako v main.py
            sl_flexibility = self.prod_config.get('sl_flexibility_percent', 25)
            
            if sl_flexibility > 0:
                # Band adjustment enabled - apply flexible bands
                try:
                    # 1) Apply SL band to structural SL
                    sl_struct_pts = float(sl_distance_points)
                    sl_final_pts, sl_diag = self.risk_manager.apply_structural_sl_band(symbol, sl_struct_pts)
                    
                    # 2) Apply TP band to structural TP
                    tp_struct_pts = float(tp_distance_points)
                    tp_final_pts, tp_diag = self.risk_manager.apply_structural_tp_band(symbol, sl_final_pts, tp_struct_pts)
                    
                    # 3) Update distances with band-adjusted values
                    sl_distance_points = sl_final_pts
                    tp_distance_points = tp_final_pts
                except Exception as e:
                    print(f"⚠️  SL/TP band application failed: {e}")
                    # Continue with original values
            
            # === PRODUKČNÍ LOGIKA: Znovu vypočítat SL/TP ceny z distances ===
            # Stejná logika jako v simple_order_executor.py can_execute_trade
            if signal_direction.upper() == 'BUY':
                stop_loss_price = entry_price - sl_distance_points
                take_profit_price = entry_price + tp_distance_points
            else:  # SELL
                stop_loss_price = entry_price + sl_distance_points
                take_profit_price = entry_price - tp_distance_points
            
            # === Risk manager - vypočítat pozici s PŘEPOČÍTANÝMI cenami ===
            # Stejná logika jako v produkci
            print(f"   [RISK] Volám calculate_position_size pro {symbol}: entry={entry_price:.2f}, SL={stop_loss_price:.2f}, TP={take_profit_price:.2f}")
            position = self.risk_manager.calculate_position_size(
                symbol=symbol,
                entry=entry_price,
                stop_loss=stop_loss_price,  # ← PŘEPOČÍTANÁ cena!
                take_profit=take_profit_price,  # ← PŘEPOČÍTANÁ cena!
                regime="UNKNOWN",  # Pro backtest zjednodušeně
                signal_quality=signal_quality,
                atr=atr_value,
                microstructure_data=None,
                swing_state=None
            )
            
            if not position:
                print(f"   [RISK] ❌ Risk manager odmítl pozici pro {symbol}")
                return  # Risk manager odmítl
            
            print(f"   [RISK] ✅ Risk manager schválil: {position.lots:.2f} lots, risk={position.risk_amount_czk:.0f} CZK")
            
            # Zkontrolovat daily risk
            daily_check = self.daily_risk_tracker.can_trade(position.risk_amount_czk)
            if not daily_check:
                print(f"   [DAILY_RISK] ❌ Daily risk limit: {position.risk_amount_czk:.0f} CZK")
                return  # Daily limit
            print(f"   [DAILY_RISK] ✅ Daily risk OK: {position.risk_amount_czk:.0f} CZK")
            
            # Exekuce přes broker simulator
            broker_position = self.broker.execute_order(
                symbol=symbol,
                direction=signal_direction,
                entry=entry_price,
                size=position.lots,
                sl=position.stop_loss,  # ← FINÁLNÍ SL z risk_manager (může být dále upraveno)
                tp=position.take_profit,  # ← FINÁLNÍ TP z risk_manager (může být dále upraveno)
                timestamp=timestamp
            )
            
            # Přidat do risk manageru
            self.risk_manager.add_position(position)
            # Balance tracker se aktualizuje automaticky přes risk_manager.balance_tracker
            
        except Exception as e:
            import traceback
            print(f"⚠️  Chyba při exekuci signálu: {e}")
            traceback.print_exc()
    
    def _calculate_statistics(self):
        """Vypočítat statistiky z closed trades"""
        trades = self.broker.closed_trades
        
        if not trades:
            return
        
        wins = [t['pnl'] for t in trades if t['pnl'] > 0]
        losses = [abs(t['pnl']) for t in trades if t['pnl'] < 0]
        
        self.stats['total_trades'] = len(trades)
        self.stats['winning_trades'] = len(wins)
        self.stats['losing_trades'] = len(losses)
        self.stats['total_pnl'] = sum(t['pnl'] for t in trades)
        self.stats['win_rate'] = (len(wins) / len(trades) * 100) if trades else 0
        self.stats['avg_win'] = sum(wins) / len(wins) if wins else 0
        self.stats['avg_loss'] = sum(losses) / len(losses) if losses else 0
        
        if losses and sum(losses) > 0:
            self.stats['profit_factor'] = sum(wins) / sum(losses) if wins else 0
        
        # Max drawdown
        peak = self.broker.initial_balance
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
        """Zobrazit výsledky"""
        print()
        print("=" * 70)
        print("📊 VÝSLEDKY PRODUKČNÍHO BACKTESTU")
        print("=" * 70)
        print()
        
        print(f"💰 Finální balance: {self.broker.balance:,.2f} CZK")
        print(f"📈 Celkový PnL: {self.stats['total_pnl']:,.2f} CZK ({self.stats['total_pnl']/self.broker.initial_balance*100:.2f}%)")
        print(f"📉 Max Drawdown: {self.stats['max_drawdown']:.2f}%")
        print()
        
        print("📊 Obchody:")
        print(f"   Celkem: {self.stats['total_trades']}")
        print(f"   Výherních: {self.stats['winning_trades']}")
        print(f"   Ztrátových: {self.stats['losing_trades']}")
        print(f"   Win Rate: {self.stats['win_rate']:.2f}%")
        
        if self.stats['total_trades'] > 0:
            print()
            print("📈 Průměry:")
            print(f"   Průměrný zisk: {self.stats['avg_win']:,.2f} CZK")
            print(f"   Průměrná ztráta: {self.stats['avg_loss']:,.2f} CZK")
            print(f"   Profit Factor: {self.stats['profit_factor']:.2f}")
        print()
    
    def _save_results(self) -> Dict:
        """Uložit výsledky"""
        # Konvertovat datetime na ISO string pro JSON serializaci
        trades_serializable = []
        for trade in self.broker.closed_trades:
            trade_copy = trade.copy()
            if 'opened_at' in trade_copy and isinstance(trade_copy['opened_at'], datetime):
                trade_copy['opened_at'] = trade_copy['opened_at'].isoformat()
            if 'closed_at' in trade_copy and isinstance(trade_copy['closed_at'], datetime):
                trade_copy['closed_at'] = trade_copy['closed_at'].isoformat()
            trades_serializable.append(trade_copy)
        
        results = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'initial_balance': self.broker.initial_balance,
            'final_balance': self.broker.balance,
            'total_pnl': self.stats['total_pnl'],
            'statistics': self.stats,
            'trades': trades_serializable,
            'equity_curve': self.equity_curve
        }
        
        results_file = self.results_dir / f"production_backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(results_file, 'w') as f:
            json.dump(results, f, indent=2)
        
        print(f"💾 Výsledky uloženy: {results_file}")
        return results

def main():
    """Hlavní funkce"""
    print("=" * 70)
    print("📊 PRODUKČNÍ BACKTEST - POUŽÍVÁ DATA Z CTRADER")
    print("=" * 70)
    print()
    
    # Zkontrolovat, zda existují data
    data_dir = project_root / "backtesting" / "data"
    ger40_file = data_dir / "GER40_M5.jsonl"
    us100_file = data_dir / "US100_M5.jsonl"
    
    missing_data = []
    if not ger40_file.exists():
        missing_data.append("GER40")
    if not us100_file.exists():
        missing_data.append("US100")
    
    if missing_data:
        print(f"⚠️  Chybí data pro: {', '.join(missing_data)}")
        print()
        print("💡 Spusť nejdřív:")
        print("   python3 backtesting/download_ctrader_data.py")
        print()
        return
    
    # Zkontrolovat, zda jsou data dostatečná
    ger40_bars = load_historical_data('GER40', data_dir)
    us100_bars = load_historical_data('US100', data_dir)
    
    if len(ger40_bars) < 100:
        print(f"⚠️  GER40 má pouze {len(ger40_bars)} barů (doporučeno: 500+)")
    if len(us100_bars) < 100:
        print(f"⚠️  US100 má pouze {len(us100_bars)} barů (doporučeno: 500+)")
    
    print(f"✅ GER40: {len(ger40_bars)} barů")
    print(f"✅ US100: {len(us100_bars)} barů")
    print()
    
    config = {
        'data_dir': data_dir,
        'results_dir': project_root / "backtesting" / "results",
        'initial_balance': 2000000.0
    }
    
    runner = ProductionBacktestRunner(config)
    symbols = ['GER40', 'US100']
    results = runner.run_backtest(symbols)
    
    if results:
        print("\n✅ Produkční backtest dokončen!")
    else:
        print("\n❌ Backtest selhal!")

if __name__ == "__main__":
    main()

