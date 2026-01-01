"""
Trading Assistant - Sprint 3 (cTrader) - MAIN
- Proper cTrader client wiring (config + callbacks)
- ADX (Wilder) with per-symbol hysteresis
- Simple pivots & swings
- EdgeDetector + SignalManager integration

25-08-30 17:20
"""
import json
import hashlib
import os
import threading
import time
import logging
from datetime import datetime, timezone, timedelta
from datetime import time as dt_time
from typing import Dict, List, Any, Optional
from collections import deque
import traceback

# Module-level logger - same pattern as regime.py, pivots.py etc.
main_logger = logging.getLogger(__name__)

# AppDaemon import with fallback for development
try:
    import appdaemon.plugins.hass.hassapi as hass
except ImportError:
    # Mock class for development environments where AppDaemon is not installed
    class MockHass:
        """Mock AppDaemon Hass class for development."""
        def __init__(self):
            pass
        def log(self, message):
            print(f"[MockHass] {message}")
        def get_state(self, entity_id, attribute=None):
            return None
        def set_state(self, entity_id, **kwargs):
            pass
        def call_service(self, domain, service, **kwargs):
            pass
    
    class MockHassModule:
        class Hass(MockHass):
            pass
    
    hass = MockHassModule()
from .pivots import PivotCalculator
from .simple_swing_detector import SimpleSwingDetector  # Reliable swing detection
from .risk_manager import RiskManager

# Local modules (same package folder)
from .ctrader_client import CTraderClient
from .edges import EdgeDetector
from .signal_manager import SignalManager
from .regime import RegimeDetector

# Sprint 2 modules
from .event_bridge import EventBridge

# MVP Auto-Trading modules (Sprint 3)
from .time_based_manager import TimeBasedSymbolManager
from .balance_tracker import BalanceTracker
from .daily_risk_tracker import DailyRiskTracker
from .simple_order_executor import SimpleOrderExecutor
from .account_state_monitor import AccountStateMonitor

# Time synchronization (optional - may not exist)
try:
    from .time_sync import TimeSync
except ImportError:
    TimeSync = None

# Watchdog manager
from .watchdog_manager import WatchdogManager

# Try to import numpy-based version, fall back to lite version
try:
    from .microstructure import MicrostructureAnalyzer
    SPRINT2_VERSION = "FULL"
except ImportError:
    from .microstructure_lite import MicrostructureAnalyzer
    SPRINT2_VERSION = "LITE"


class ThreadSafeAppState:
    """Thread-safe state container for WebSocket data accessed from AppDaemon main thread."""

    def __init__(self):
        self._pos_lock = threading.RLock()
        self._px_lock = threading.RLock()
        self._bal_lock = threading.RLock()

        # Protected state
        self._positions = {}
        self._prices = {}
        self._balance = {}
        self._last_events = deque(maxlen=200)

    def update_position(self, symbol: str, position_data: dict):
        with self._pos_lock:
            self._positions[symbol] = position_data
            self._last_events.append(('position', symbol, time.time()))

    def update_price(self, symbol: str, price_data: dict):
        with self._px_lock:
            self._prices[symbol] = price_data
            self._last_events.append(('price', symbol, time.time()))

    def update_balance(self, balance_data: dict):
        with self._bal_lock:
            self._balance.update(balance_data)
            self._last_events.append(('balance', None, time.time()))

    def get_position(self, symbol: str) -> dict:
        with self._pos_lock:
            return self._positions.get(symbol, {}).copy()

    def get_price(self, symbol: str) -> dict:
        with self._px_lock:
            return self._prices.get(symbol, {}).copy()

    def get_balance(self) -> dict:
        with self._bal_lock:
            return self._balance.copy()

    def get_all_positions(self) -> dict:
        with self._pos_lock:
            return {k: v.copy() for k, v in self._positions.items()}


class TradingAssistant(hass.Hass):
    def _resync_time_wrapper(self, kwargs):
        """Wrapper pro automatickou resynchronizaci času s NTP serverem"""
        if hasattr(self, 'time_sync') and self.time_sync:
            self.time_sync.auto_resync()
    
    def get_synced_time(self) -> datetime:
        """
        Vrací synchronizovaný UTC čas (s NTP korekcí)
        
        Returns:
            datetime object s timezone.utc
        """
        if hasattr(self, 'time_sync') and self.time_sync.enabled:
            return self.time_sync.now()
        return datetime.now(timezone.utc)
    
    def initialize(self):
        try:
            self.log("=" * 50)
            self.log("Trading Assistant - Sprint 2 (Enhanced)")
            self.log(f"Version: 2.0.0 - {SPRINT2_VERSION} mode")
            self.log("=" * 50)
            
            # PŘIDEJ - Throttling pro logy
            self._last_insufficient_data_log = {}  # Pro každý symbol
            self._last_no_signal_log = {}          # Pro každý symbol
            self._last_analysis_log = {}           # Pro každý symbol
            
            # Live status tracking
            self._last_bar_time = {}  # {alias: datetime}
            self._last_analysis_time = {}  # {alias: datetime}
            self._last_signal_check_time = {}  # {alias: datetime}
            self._last_signal_check_result = {}  # {alias: str} - reason for no signal
            self.log_throttle_seconds = 60         # Loguj max jednou za minutu

            # Initialize thread-safe state and micro-dispatcher
            self.thread_safe_state = ThreadSafeAppState()
            self._dispatch_queue = deque(maxlen=1000)
            self._dispatch_lock = threading.Lock()

            # Performance configuration
            perf_config = self.args.get('performance', {})
            self._adaptive_dispatch_enabled = perf_config.get('enable_adaptive_dispatch', True)
            self._queue_limiting_enabled = perf_config.get('enable_queue_limiting', True)
            self._base_interval = perf_config.get('base_dispatch_interval', 0.05)
            self._fast_interval = perf_config.get('fast_dispatch_interval', 0.02)
            self._slow_interval = perf_config.get('slow_dispatch_interval', 0.10)
            self._queue_low_threshold = perf_config.get('queue_size_low_threshold', 50)
            self._queue_high_threshold = perf_config.get('queue_size_high_threshold', 200)
            self._current_interval = self._base_interval
            self._dispatch_timer_handle = None  # Store timer handle for safe cancellation

            # Start micro-dispatcher timer (process WS callbacks in main thread)
            self._dispatch_timer_handle = self.run_every(self._process_dispatch_queue, f"now+{self._current_interval}", self._current_interval)
            self.log(f"[THREADING] ✅ Micro-dispatcher initialized (adaptive: {self._adaptive_dispatch_enabled}, limiting: {self._queue_limiting_enabled})")

            # Rychlejší warm-up thresholds
            self.min_bars_ready_regime = 5   # místo 8
            self.min_bars_ready_swings = 5   # místo 8  
            self.min_bars_ready_pivots = 3
            self.min_bars_ready_signals = 5  # místo 8
        
            # --- Configuration -------------------------------------------------
            # Symbols from YAML (array of {name: "DE40"} OR simple strings)
            raw_symbols = [s.get("name", s) for s in (self.args.get("symbols") or [])]
            if not raw_symbols:
                raw_symbols = ["DE40", "US100"]

            # Alias mapping (what you want to show on dashboard)
            provided_alias: Dict[str, str] = self.args.get("symbol_alias") or {}
            self.symbol_alias: Dict[str, str] = {}
            for raw in raw_symbols:
                alias = provided_alias.get(raw)
                if not alias:
                    if raw.upper().startswith("DE"):
                        alias = "DAX"
                    elif raw.upper().startswith(("US", "NAS")):
                        alias = "NASDAQ"
                    else:
                        alias = raw
                self.symbol_alias[raw] = alias
            self.alias_to_raw = {alias: raw for raw, alias in self.symbol_alias.items()}
            
            # Symbol mapping configuration ready
            
            # Listeners pro test tlačítka
            self.listen_state(self.force_test_signal_dax, "input_boolean.force_signal_dax", new="on")
            self.listen_state(self.force_test_signal_nasdaq, "input_boolean.force_signal_nasdaq", new="on")

            # === CLEANUP PŘI STARTU - PŘIDAT TOTO ===
            self.log("[INIT] Cleaning up old tickets from previous session...")
            self._cleanup_on_startup()
            
            # === THREAD STARVATION PREVENTION ===
            # Snížena frekvence cleanup operací pro lepší výkon
            # cleanup_old_entities: každých 10 minut (místo 5)
            # quick_cleanup: každé 3 minuty (místo 1) 
            self.run_every(self.cleanup_old_entities, "now+600", 600)  # 10 minut
            self.run_every(self.quick_cleanup, "now+180", 180)  # 3 minuty
            
            # Tracking pro thread starvation prevention
            self._last_cleanup_time = 0
            self._cleanup_skip_count = 0
                    
            
            self.risk_manager = RiskManager({
            'account_balance': self.args.get('account_balance', 100000),
            'account_currency': self.args.get('account_currency', 'CZK'),
            'max_risk_per_trade': self.args.get('max_risk_per_trade', 0.01),
            'max_risk_total': self.args.get('max_risk_total', 0.03),
            'max_positions': self.args.get('max_positions', 1),  # CHANGED: Only 1 position at a time
            'daily_loss_limit': self.args.get('daily_loss_limit', 0.02),
            'symbol_specs': self.args.get('symbol_specs', {}),
            'risk_adjustments': self.args.get('risk_adjustments', {}),
            'regime_adjustments': self.args.get('regime_adjustments', {}),
            'volatility_adjustments': self.args.get('volatility_adjustments', {})
            })
            
            self.listen_state(self.clear_all_signals, "input_boolean.clear_signals", new="on")
            
            # === TIME SYNCHRONIZATION ===
            # Synchronizace s NTP serverem pro přesné časové značky (optional)
            self.time_sync = None
            if TimeSync is not None:
                try:
                    time_sync_config = self.args.get('time_sync', {
                        'enable_time_sync': True,
                        'sync_interval_seconds': 3600  # Sync každou hodinu
                    })
                    self.time_sync = TimeSync(time_sync_config)
                    
                    # Pravidelná resynchronizace každou hodinu
                    if self.time_sync and self.time_sync.enabled:
                        # Use lambda to avoid AttributeError if method not yet defined
                        self.run_every(self._resync_time_wrapper, "now+3600", 3600)
                except Exception as e:
                    self.log(f"[INIT] Time sync initialization failed: {e}, continuing without it")
                    self.time_sync = None
                self.log("[TIME_SYNC] ✅ Time synchronization enabled - will resync every hour")
            
            # Analysis params
            self.pivot_calc   = PivotCalculator(self.args.get('pivots', {}))

            # Use SimpleSwingDetector for reliable swing detection
            swing_config = self.args.get('swings', {})
            self.swing_engine = SimpleSwingDetector(
                config={
                    'lookback': 5,  # Bars on each side for local extrema
                    'min_move_pct': 0.0015,  # 0.15% minimum move between swings
                    'use_pivot_validation': swing_config.get('use_pivot_validation', True),
                    'pivot_confluence_atr': swing_config.get('pivot_confluence_atr', 0.3)
                },
                pivot_calculator=self.pivot_calc  # Pass pivot calculator for validation
            )
            self.log(f"[SWING] Using SimpleSwingDetector (lookback=5, min_move=0.15%)")
            self.regime_detector = RegimeDetector(self.args.get('regime', {}))
            
            # Sprint 2: Initialize EventBridge and MicrostructureAnalyzer
            self.event_bridge = EventBridge(self)
            self.microstructure = MicrostructureAnalyzer(self.args.get('microstructure', {
                'lookback_days': 20,
                'z_score_threshold': 2.0,
                'or_duration_minutes': 30
            }))
            
            # === MVP AUTO-TRADING INITIALIZATION ===
            self.auto_trading_enabled = self.args.get('auto_trading', {}).get('enabled', False)
            
            if self.auto_trading_enabled:
                self.log("[AUTO-TRADING] Initializing MVP auto-trading components...")
                
                # Initialize time-based symbol manager
                self.time_manager = TimeBasedSymbolManager()
                
                # Initialize balance tracker
                initial_balance = self.args.get('account_balance', 2000000)
                self.balance_tracker = BalanceTracker(initial_balance=initial_balance)

                # Connect balance tracker to risk manager
                self.risk_manager.balance_tracker = self.balance_tracker

                # Initialize daily risk tracker
                daily_limit = self.args.get('auto_trading', {}).get('daily_risk_limit_pct', 0.015)
                self.daily_risk_tracker = DailyRiskTracker(
                    daily_limit_percentage=daily_limit,
                    balance_tracker=self.balance_tracker,
                    config=self.args  # PHASE 2: Pass config for daily_loss_soft_cap
                )
                
                # Initialize simple order executor
                self.order_executor = SimpleOrderExecutor(
                    config=self.args,
                    time_manager=self.time_manager,
                    balance_tracker=self.balance_tracker,
                    risk_manager=self.risk_manager,
                    daily_risk_tracker=self.daily_risk_tracker,
                    create_task_fn=self.create_task,  # Pass AppDaemon's create_task method
                    ctrader_client=None,  # Will be set later
                    edge_detector=None,  # Will be set after EdgeDetector initialization
                    hass_instance=self  # Pass hass instance for notifications
                )

                # SAFETY: Check Home Assistant toggle state, or disable by default
                try:
                    toggle_state = self.get_state("input_boolean.auto_trading_enabled")
                    if toggle_state == "on":
                        self.order_executor.enabled = True
                        self.auto_trading_enabled = True
                        self.log("[AUTO-TRADING] ✅ Auto-trading ENABLED (toggle is ON)")
                    else:
                        self.order_executor.enabled = False
                        self.auto_trading_enabled = False
                        self.log("[AUTO-TRADING] ⚠️ Auto-trading DISABLED - toggle is OFF (use dashboard to enable)")
                except Exception as e:
                    # If toggle doesn't exist or error, disable for safety
                    self.order_executor.enabled = False
                    self.auto_trading_enabled = False
                    self.log(f"[AUTO-TRADING] ⚠️ Auto-trading DISABLED by default (toggle check failed: {e})")
                    self.log("[AUTO-TRADING] Create toggle in HA: Settings → Devices & Services → Helpers → Toggle")

                # Schedule periodic updates
                self.run_every(self._update_balance_from_ctrader, "now+30", 30)  # Every 30 seconds
                self.run_every(self._check_trading_session, "now+60", 60)        # Every minute
                self.run_every(self._update_performance_metrics, "now+10", 300)  # Every 5 minutes (start after 10s)
                self.run_every(self._check_trailing_stops, "now+30", 30)         # Every 30 seconds

                self.log("[AUTO-TRADING] ✅ MVP auto-trading components initialized")
            else:
                self.log("[AUTO-TRADING] Auto-trading disabled in configuration")
                self.time_manager = None
                self.balance_tracker = None
                self.daily_risk_tracker = None
                self.order_executor = None
            
            # Initialize performance tracker (for trade performance metrics) - BEFORE cTrader client
            from .performance_tracker import PerformanceTracker
            self.performance_tracker = PerformanceTracker()
            self.log("[PERFORMANCE] ✅ Performance tracker initialized")

            # Initialize trailing stop manager and partial exit manager (after order_executor is created)
            from .trailing_stop_manager import TrailingStopManager
            from .partial_exit_manager import PartialExitManager
            position_closer = None
            if self.auto_trading_enabled and self.order_executor:
                position_closer = self.order_executor.position_closer if hasattr(self.order_executor, 'position_closer') else None
            
            self.trailing_stop_manager = TrailingStopManager(
                config=self.args,
                ctrader_client=None,  # Will be set later
                create_task_fn=self.create_task,
                position_closer=position_closer  # Pass position closer if available
            )
            self.log("[TRAILING] ✅ Trailing stop manager initialized")
            
            # Initialize partial exit manager
            self.partial_exit_manager = PartialExitManager(
                config=self.args,
                position_closer=position_closer  # Pass position closer if available
            )
            self.log("[PARTIAL_EXIT] ✅ Partial exit manager initialized")

            # Listener pro zapnutí/vypnutí auto-tradingu (MUST be after auto_trading_enabled is initialized!)
            self.listen_state(self.toggle_auto_trading, "input_boolean.auto_trading_enabled")
            self.log("[AUTO-TRADING] ✅ Toggle listener registered")
            
            # CRITICAL: Listener pro Kill Switch (Dead Man's Switch)
            # Note: Will be registered after order_executor is initialized
            self.run_in(self._register_kill_switch_listener, 5)

            rcfg = self.args.get("regime") or {}
            self.adx_period = int(rcfg.get("adx_period", 14))
            self.adx_hi = float(rcfg.get("adx_hi", 28.0))
            self.adx_lo = float(rcfg.get("adx_lo", 22.0))

            self.edge = EdgeDetector({
                **self.args.get('edges', {}),
                'app': self,
                'main_config': self.args,
                'timeframe': self.args.get('timeframe', 'M5')
            })

            # Set EdgeDetector in order executor for trade logging context
            if self.order_executor:
                self.order_executor.edge = self.edge

            self.analysis_min_bars = int(self.args.get("analysis_min_bars", 30))
            self.bar_warmup = int(self.args.get("bar_warmup", 3))
            self.status_interval_sec = int(self.args.get("status_interval_sec", 60))

            # --- State ---------------------------------------------------------
            self.market_data: Dict[str, deque] = {alias: deque(maxlen=5000) for alias in self.alias_to_raw}
            self.current_atr: Dict[str, float] = {alias: 0.0 for alias in self.alias_to_raw}
            self.current_pivots: Dict[str, Dict] = {alias: {} for alias in self.alias_to_raw}
            self._last_regime_state_by_symbol: Dict[str, str] = {}
            self._last_regime_data_by_symbol: Dict[str, Dict] = {}  # Full regime data with ADX
            
            # NEW: Pending reverse signals (waiting for position close confirmation)
            self._pending_reverse_signals: Dict[str, Dict] = {}  # position_id -> signal_dict
            self._reverse_lock = threading.RLock()

            # Signal manager
           
            self.signal_manager = SignalManager(self, self.args.get('signal_manager', {
                "trigger_zone_atr": 0.2,
                "notify_on_new": False,  # Disabled - notify only when position is CONFIRMED opened
                "notify_on_trigger": False,  # Disabled - notify only when position is CONFIRMED opened
                "notify_on_expire": False,
                "max_history": 100
            }))

            # --- cTrader client -----------------------------------------------
            client_cfg = {
                "ws_uri": self.args.get("ws_uri"),
                "client_id": self.args.get("client_id"),
                "client_secret": self.args.get("client_secret"),
                "access_token": self.args.get("access_token"),
                "ctid_trader_account_id": self.args.get("ctid_trader_account_id"),
                "trader_login": self.args.get("trader_login"),
                "symbols": [{"name": s} for s in raw_symbols],
                "symbol_id_overrides": self.args.get("symbol_id_overrides", {}),
                "bar_warmup": self.bar_warmup,
                "use_historical_bootstrap": self.args.get("use_historical_bootstrap", True),
                "history_cache_dir": self.args.get("history_cache_dir", "./cache"),
                "history_bars_count": self.args.get("history_bars_count", 300),
                "account_balance": self.args.get("account_balance", 2000000),  # Fallback balance for PT_TRADER_RES failures
            }
            self.ctrader_client = CTraderClient(client_cfg)
            
            # Connect cTrader client to auto-trading components
            if self.auto_trading_enabled and self.order_executor:
                self.order_executor.ctrader_client = self.ctrader_client
                # Register execution callback now that client is available
                if hasattr(self.ctrader_client, 'add_execution_callback'):
                    self.ctrader_client.add_execution_callback(self.order_executor._handle_execution_event)
                    self.log("[AUTO-TRADING] ✅ Execution callback registered")
                self.log("[AUTO-TRADING] ✅ cTrader client connected to order executor")
            
            # Connect cTrader client to trailing stop manager
            if self.trailing_stop_manager:
                self.trailing_stop_manager.ctrader_client = self.ctrader_client
                # Also connect to position closer if available
                if self.order_executor and hasattr(self.order_executor, 'position_closer'):
                    # Trailing stop manager will use position_closer for SL updates
                    pass
                self.log("[TRAILING] ✅ cTrader client connected to trailing stop manager")

            # Initialize account state monitor
            self.account_monitor = None
            account_config = self.args.get('account_monitoring', {})
            account_enabled = account_config.get('enabled', False)
            # Account monitoring configuration loaded

            if account_enabled:
                self.account_monitor = AccountStateMonitor(
                    ctrader_client=self.ctrader_client,
                    app_instance=self,
                    config=self.args,
                    risk_manager=self.risk_manager,  # CRITICAL FIX: Pass risk manager
                    balance_tracker=self.balance_tracker if self.auto_trading_enabled else None,  # CRITICAL: Pass balance tracker
                    performance_tracker=self.performance_tracker,  # NEW: Pass performance tracker
                    trailing_stop_manager=self.trailing_stop_manager,  # NEW: Pass trailing stop manager
                    partial_exit_manager=self.partial_exit_manager  # NEW: Pass partial exit manager
                )
                # CRITICAL: Give cTrader client reference to Account Monitor for balance fallback
                self.ctrader_client.account_state_monitor = self.account_monitor
                self.log("[ACCOUNT_MONITOR] Account monitoring initialized")
                self.log("[ACCOUNT_MONITOR] ✅ Account state monitor initialized")
                self.log("[ACCOUNT_MONITOR] ✅ Account monitor linked to cTrader client for balance fallback")
            else:
                self.log("[ACCOUNT_MONITOR] Account monitoring disabled in configuration")
            
            
            # Initialize Watchdog Manager (Dead Man's Switch)
            watchdog_config = self.args.get('watchdog', {})
            self.watchdog_manager = WatchdogManager(self, watchdog_config)
            # Schedule watchdog updates every 60 seconds
            self.run_every(self.watchdog_manager.update, "now+60", 60)
            self.log("[WATCHDOG] ✅ Watchdog manager initialized and scheduled")
            
            self._precreate_entities()

            # Wrap callbacks to use micro-dispatcher (from WS thread → main thread)
            def _bar_cb(raw_symbol, bar, *rest):
                try:
                    history = rest[0] if rest else None
                    # USE MODULE LOGGER for thread safety!
                    main_logger.info(f"[_BAR_CB] ✅ Received bar for {raw_symbol}, history={history is not None}")
                    self.log(f"[_BAR_CB] Received bar for {raw_symbol}, history={history is not None}")
                    # Update broker timestamp in time manager
                    if hasattr(self, 'time_manager') and self.time_manager and bar:
                        bar_timestamp = bar.get('timestamp') or bar.get('utcTimestamp')
                        if bar_timestamp:
                            try:
                                from datetime import datetime, timezone
                                if isinstance(bar_timestamp, str):
                                    broker_dt = datetime.fromisoformat(bar_timestamp.replace('Z', '+00:00'))
                                elif isinstance(bar_timestamp, (int, float)):
                                    broker_dt = datetime.fromtimestamp(bar_timestamp / 1000, tz=timezone.utc)
                                else:
                                    broker_dt = bar_timestamp
                                self.time_manager.update_broker_timestamp(broker_dt)
                            except Exception as e:
                                pass  # Silently ignore timestamp parsing errors
                    self.log(f"[_BAR_CB] Enqueuing bar callback for {raw_symbol}")
                    self._enqueue_callback('bar', raw_symbol, bar, history)
                    self.log(f"[_BAR_CB] Bar callback enqueued for {raw_symbol}")
                except Exception as e:
                    import traceback
                    main_logger.error(f"[_BAR_CB] Error: {e}")
                    main_logger.error(traceback.format_exc())

            def _tick_cb(raw_symbol, price):
                self._enqueue_callback('price', raw_symbol, price)

            def _execution_cb(event_type, payload):
                self._enqueue_callback('execution', event_type, payload)

            def _account_cb(account_data):
                self._enqueue_callback('account', account_data)

            # CRITICAL FIX: Register AccountStateMonitor BEFORE starting cTrader client to ensure
            # account balance is available when auto-trading starts
            if self.account_monitor:
                self.log("[ACCOUNT_MONITOR] ✅ Registering account monitor callbacks...")
                try:
                    self.account_monitor.register_with_client()
                    self.log("[ACCOUNT_MONITOR] Callbacks registered successfully")
                except Exception as e:
                    self.log(f"[ACCOUNT_MONITOR] Registration failed: {e}")
                    # traceback already imported at top of file
                    self.log(f"[ACCOUNT_MONITOR] Traceback: {traceback.format_exc()}")

                self.log("[ACCOUNT_MONITOR] ✅ Starting account monitor updates early...")
                self.account_monitor.start_periodic_updates()
                self.log("[ACCOUNT_MONITOR] ✅ Account monitoring ready BEFORE auto-trading starts")
                
                # Update performance metrics immediately on startup
                self.run_in(self._update_performance_metrics, 5)  # After 5 seconds
            else:
                # Account monitoring disabled
                pass

            # Store callbacks as instance methods to ensure proper self binding
            self._bar_callback_func = _bar_cb
            self._tick_callback_func = _tick_cb
            self._execution_callback_func = _execution_cb
            self._account_callback_func = _account_cb
            self.ctrader_client.start(
                on_tick_callback=self._tick_callback_func, 
                on_bar_callback=self._bar_callback_func, 
                on_execution_callback=self._execution_callback_func, 
                on_account_callback=self._account_callback_func
            )
            self.log(f"[TEST] Callbacks registered, on_bar_callback type: {type(self.ctrader_client.on_bar_callback) if hasattr(self.ctrader_client, 'on_bar_callback') else 'NOT SET'}")

            # CRITICAL FIX: Update cTrader connected entity immediately after start
            # Schedule entity update after WebSocket is connected (2 seconds delay)
            self.run_in(self._update_ctrader_connected_entity, 2)
            self.log("[CTRADER] ✅ Connection status update scheduled for 2 seconds after startup")

            # CRITICAL FIX: Reconcile on startup - adopt existing positions and pending orders
            # Schedule reconcile after WebSocket is connected (5 seconds delay)
            self.run_in(self._reconcile_on_startup, 5)
            self.log("[RECONCILE] ✅ Reconcile scheduled for 5 seconds after startup")

            # Schedule additional account monitor start for redundancy (keep for safety)
            # Scheduling callback registration
            if self.account_monitor:
                # Will register callbacks after WebSocket connection
                # Delay both registration AND data requests until WebSocket is fully connected and authenticated
                self.run_in(self._start_account_monitoring, 5)  # 5 second delay for redundancy
            else:
                # Account monitoring not available for registration
                pass

            # Přidat diagnostiku
            self.run_in(self.diagnose_ctrader, 3)
            # Spustit diagnostiku obchodování po 10 sekundách (až se vše inicializuje)
            self.run_in(self.diagnose_trading, 10)
            
            # create HA entity upfront so the dash doesn't error before first update
            self._safe_set_state("binary_sensor.ctrader_connected", state="off",
                           attributes={"friendly_name": "cTrader Connected"})

            # Test že get_state funguje
            test_states = self.get_state()
            if test_states:
                self.log(f"[INIT] Found {len(test_states)} entities")
            else:
                self.log("[INIT] Warning: No entities found")
            
            if self.args.get('use_historical_bootstrap', True):
                self.analysis_min_bars = 12  # Místo 30
                self.bar_warmup = 3  # Místo 20
                self.log("Bootstrap mode: Reduced warmup requirements")
            
             # PŘIDAT TOTO - aktualizace cache každou hodinu
            if self.args.get('use_historical_bootstrap', True):
                self.run_every(self.update_history_cache, "now+3600", 3600)
                self.log("[INIT] History cache updater scheduled (every hour)")
        
            
            # Schedulers
            self.run_every(self.log_status, "now+30", self.status_interval_sec)
            self.run_every(self.update_signal_manager, "now+5", 15)  # Reduced from 10s to 15s
            
            # Sprint 2: Process event queue at 1Hz
            self.run_every(self.process_event_queue, "now+1", 1)

            # Sprint 2: Create entities for dashboard
            self.create_sprint2_entities()
            self.run_in(self.create_sprint2_entities, 5)  # Update after 5 seconds
            # THREAD STARVATION FIX: Snížena frekvence z 60s na 120s
            self.run_every(self._update_sprint2_entities_with_data, "now+60", 120)  # Update every 2 minutes

            self.log("[OK] initialize complete")

        except Exception:
            self.error("initialize() failed:\n" + traceback.format_exc())

    # ---------------- Helper: Safe set_state ----------------
    def _jsonify_attrs(self, attrs: dict) -> dict:
        """Convert non-JSON-serializable types (datetime, Decimal) to JSON-safe types."""
        def conv(v):
            if isinstance(v, (datetime, timezone)):
                return v.isoformat()
            elif hasattr(v, 'isoformat'):  # date, time objects
                return v.isoformat()
            # Add more conversions if needed (Decimal -> float, numpy -> int/float)
            return v

        return {k: conv(v) for k, v in (attrs or {}).items()}

    def _safe_set_state(self, entity_id: str, state=None, **kwargs):
        """
        Wrapper for set_state() with retry, serialization, and HA internal attribute filtering.

        Features:
        - Filters HA internal attributes (last_changed, last_reported, context, etc.)
        - Serializes datetime/Decimal objects to JSON-safe types
        - Retries on failure (useful when HA is not ready after restart)
        - Handles ClientResponseError from HA API
        - Uses replace=True to prevent AppDaemon auto-merging
        - Explicit namespace="hass" parameter
        - Skips corrupted entities (HTTP 400) to prevent system slowdown

        Retry pattern: wait 0s, 1s, 2s before giving up
        """
        from aiohttp import ClientResponseError

        # Blacklist of entities that cause HTTP 400 errors
        # These entities will be skipped to prevent system slowdown and log spam
        # Reasons: HASS 2024+ strict validation, entity doesn't exist in registry, or attribute issues
        CORRUPTED_ENTITIES_BLACKLIST = {
            'sensor.trading_open_positions',
            'sensor.trading_daily_pnl',
            'sensor.trading_daily_pnl_percent',
            # Sprint 2 entities that may fail on fresh HASS install
            'sensor.event_queue_metrics',
            'sensor.dax_volume_zscore_v2',
            'sensor.nasdaq_volume_zscore_v2',
            'sensor.dax_vwap_distance_v2',
            'sensor.nasdaq_vwap_distance_v2',
            'sensor.dax_atr_current_v2',
            'sensor.nasdaq_atr_current_v2',
            'sensor.dax_atr_expected_v2',
            'sensor.nasdaq_atr_expected_v2',
        }
        
        # Skip corrupted entities silently
        if entity_id in CORRUPTED_ENTITIES_BLACKLIST:
            return None

        # Get new attributes from kwargs
        new_attributes = kwargs.get('attributes', {})

        # 1. Serialize datetime/Decimal objects to JSON-safe types
        serialized_attributes = self._jsonify_attrs(new_attributes)

        # 2. Filter out any HA internal attributes
        HA_INTERNAL_ATTRS = {'last_changed', 'last_reported', 'last_updated', 'context', 'state'}
        clean_attributes = {
            k: v for k, v in serialized_attributes.items()
            if k not in HA_INTERNAL_ATTRS
        }

        # Update kwargs with clean attributes
        kwargs['attributes'] = clean_attributes

        # Use replace=True to prevent AppDaemon auto-merging
        kwargs['replace'] = True

        # 3. Retry pattern: attempt with 0s, 1s, 2s waits
        retries = [0, 1, 2]
        last_error = None

        for wait_seconds in retries:
            try:
                if wait_seconds > 0:
                    time.sleep(wait_seconds)

                # Call original set_state (NOT _safe_set_state to avoid recursion!)
                # namespace='hass' is default, no need to specify
                return self.set_state(entity_id, state=state, **kwargs)

            except ClientResponseError as e:
                # Convert to string immediately to avoid iteration issues
                last_error = f"ClientResponseError: {str(e)}"
                # Special handling for sensor entities that might not exist yet
                if "sensor." in entity_id and any(x in entity_id for x in ["zscore", "vwap", "atr", "liquidity"]):
                    self.log(f"[SAFE_SET_STATE] Creating new entity {entity_id} (initial failure expected)", level="DEBUG")
                    # Don't retry on sensor creation - they'll be created on next update
                    return None
                status = getattr(e, 'status', '')
                detail = str(e)
                self.log(f"[SAFE_SET_STATE] ClientResponseError {status} for {entity_id}: {detail}", level="ERROR")
                # Don't retry on ClientResponseError - it won't help
                break
            except TypeError as e:
                last_error = str(e)  # Convert to string
                # Check if this is the "not iterable" error from HA trying to check ClientResponseError
                if "not iterable" in str(e) and "sensor." in entity_id:
                    self.log(f"[SAFE_SET_STATE] Creating new sensor entity {entity_id}", level="DEBUG")
                    return None
                self.log(f"[SAFE_SET_STATE] TypeError for {entity_id} (bad serialization): {e}", level="ERROR")
                # Don't retry on TypeError - fix the data instead
                break
            except Exception as e:
                last_error = str(e)  # Convert to string
                self.log(f"[SAFE_SET_STATE] {entity_id} failed: {e!r}; retry in {wait_seconds}s", level="WARNING")

        # All retries exhausted or error type that won't benefit from retry
        self.error(f"[SAFE_SET_STATE] ❌ Giving up on {entity_id} after error: {last_error}")
        return None

    # ---------------- cTrader callbacks ----------------
    def _on_connected(self):
        self.log("[STATUS] cTrader connected")
        self._safe_set_state("binary_sensor.ctrader_connected", state="on")

    def _update_ctrader_connected_entity(self, _):
        """Update cTrader connected entity based on actual connection state.
        
        This is scheduled to run shortly after ctrader_client.start() to ensure
        the entity reflects the actual connection state before data processing begins.
        """
        try:
            is_connected = self.ctrader_client.is_connected() if self.ctrader_client else False
            state = "on" if is_connected else "off"
            
            self._safe_set_state("binary_sensor.ctrader_connected", state=state)
            self._safe_set_state(
                "sensor.trading_analysis_status",
                state="RUNNING" if is_connected else "STOPPED",
                attributes={
                    "friendly_name": "Trading Analysis Status",
                    "last_update": self.get_synced_time().isoformat(),
                    "symbols_tracked": len(self.alias_to_raw)
                }
            )
            
            self.log(f"[CTRADER] ✅ Connection entity updated: {state} (is_connected={is_connected})")
        except Exception as e:
            self.error(f"[CTRADER] ❌ Failed to update connection entity: {e}")

    def _on_price_direct(self, symbol: str, price: Dict[str, Any]):
        # Store price in thread-safe state and hook for future use - runs in main thread
        self.thread_safe_state.update_price(symbol, price)
        pass

    def _on_execution_direct(self, event_type: str, payload: dict):
        """Handle execution events in main thread"""
        try:
            # Forward execution events to order executor
            if self.auto_trading_enabled and self.order_executor:
                self.order_executor.on_execution_event(event_type, payload)
            else:
                self.log(f"[EXECUTION] Received {event_type} but no order executor available")
        except Exception as e:
            self.log(f"[EXECUTION] Error handling {event_type}: {e}")

    def _on_account_direct(self, account_data: dict):
        """Handle account updates in main thread - PRIORITY"""
        try:
            currency = account_data.get('currency', 'CZK')
            balance = account_data.get('balance', 0)

            # CRITICAL: Update BalanceTracker from trader payload FIRST (primary source)
            if self.balance_tracker and 'trader' in account_data:
                trader_payload = account_data['trader']
                success = self.balance_tracker.update_from_trader_res(trader_payload)
                if success:
                    # Get balance from tracker (authoritative source)
                    balance = self.balance_tracker.get_current_balance()
                    self.log(f"[ACCOUNT] ✅ BalanceTracker updated from PT_TRADER_RES: {balance:.2f} {currency}")
                else:
                    self.log(f"[ACCOUNT] ⚠️ Failed to update BalanceTracker from PT_TRADER_RES")
                    # Fall back to legacy balance if available
                    if balance <= 0:
                        self.log(f"[ACCOUNT] No valid balance from any source, skipping update")
                        return
            else:
                # No trader payload - use legacy balance (fallback)
                if balance > 0:
                    self.log(f"[ACCOUNT] Balance update (legacy): {balance:.2f} {currency}")
                else:
                    self.log(f"[ACCOUNT] ⚠️ Received invalid balance data ({balance}), skipping update")
                    return

            # Update risk manager with actual account balance
            if hasattr(self, 'risk_manager') and self.risk_manager:
                    self.risk_manager.account_balance = balance
                    self.log(f"[ACCOUNT] Risk manager balance updated to {balance:.2f}")

            # Immediately publish account info to Home Assistant (priority path)
            self._safe_set_state("sensor.account_balance",
                         state=round(balance, 2),
                         attributes={
                             "balance": balance,
                             "equity": account_data.get('equity', 0),
                             "margin_used": account_data.get('margin_used', 0),
                             "free_margin": account_data.get('free_margin', 0),
                             "currency": currency,
                             "last_update": account_data.get('timestamp', '').isoformat() if account_data.get('timestamp') else None,
                             "friendly_name": "Account Balance"
                         })

        except Exception as e:
            self.log(f"[ACCOUNT] Error handling account update: {e}")

    def _process_dispatch_queue(self, cb_data=None):
        """Optimized micro-dispatcher: Process WS callbacks with adaptive intervals and time-capping"""
        import time
        # Use module-level logger for proper AppDaemon integration
        logger = main_logger

        try:
            start_time = time.time()
            queue_size = len(self._dispatch_queue)

            # Adaptive dispatch interval adjustment - SAFE VERSION
            if self._adaptive_dispatch_enabled:
                new_interval = None
                if queue_size > self._queue_high_threshold:
                    new_interval = self._fast_interval  # Speed up processing
                elif queue_size < self._queue_low_threshold:
                    new_interval = self._slow_interval  # Slow down to save CPU
                else:
                    new_interval = self._base_interval  # Normal speed

                # Update interval if changed - USE STORED HANDLE
                if new_interval != self._current_interval:
                    self._current_interval = new_interval

                    # SAFE timer cancellation and recreation
                    try:
                        if self._dispatch_timer_handle is not None:
                            self.cancel_timer(self._dispatch_timer_handle)

                        # Create new timer with new interval
                        self._dispatch_timer_handle = self.run_every(self._process_dispatch_queue, f"now+{new_interval}", new_interval)

                    except Exception as e:
                        self.log(f"[DISPATCH] ERROR in timer management: {e}")
                        # Fallback: disable adaptive dispatch if timer fails
                        self._adaptive_dispatch_enabled = False
                        self.log(f"[DISPATCH] Adaptive dispatch DISABLED due to timer error")

            # During bootstrap, allow more time for heavy analysis
            is_bootstrap_phase = getattr(self, '_bootstrap_in_progress', False)
            max_processing_time = 0.100 if is_bootstrap_phase else (self._current_interval * 0.8)  # Use 80% of interval

            with self._dispatch_lock:
                processed_count = 0
                coalesced_prices = {}  # Symbol -> latest price data for coalescing
                priority_queue = []    # Execution events (high priority)
                regular_queue = []     # Bar and price events (normal priority)

                # Separate into priority queues and coalesce prices
                temp_queue = list(self._dispatch_queue)
                self._dispatch_queue.clear()

                for callback_type, args, kwargs in temp_queue:
                    if callback_type in ['execution', 'account']:
                        priority_queue.append((callback_type, args, kwargs))
                    elif callback_type == 'price':
                        # Coalesce price updates - keep only latest per symbol
                        symbol = args[0] if args else 'unknown'
                        coalesced_prices[symbol] = (callback_type, args, kwargs)
                    else:
                        regular_queue.append((callback_type, args, kwargs))

                # Add coalesced prices to regular queue
                regular_queue.extend(coalesced_prices.values())

                # Process priority items first (executions), then regular items
                all_items = priority_queue + regular_queue

                for callback_type, args, kwargs in all_items:
                    # Time-based exit condition (but not for critical execution events)
                    if callback_type != 'execution' and time.time() - start_time > max_processing_time:
                        # Re-queue remaining items
                        remaining = all_items[processed_count:]
                        for item in remaining:
                            self._dispatch_queue.append(item)
                        break

                    # Batch count limit
                    if processed_count >= 30:  # Increased from 20 to match 50ms time limit
                        remaining = all_items[processed_count:]
                        for item in remaining:
                            self._dispatch_queue.append(item)
                        break

                    try:
                        processed_count += 1

                        # Execute callback in main thread
                        if callback_type == 'bar':
                            symbol = args[0] if args else 'unknown'
                            logger.info(f"[DISPATCH] ✅ Processing bar callback for {symbol}")
                            self.log(f"[DISPATCH] Processing bar callback for {symbol}")
                            self._on_bar_direct(*args, **kwargs)
                            logger.info(f"[DISPATCH] ✅ Bar callback processed for {symbol}")
                            self.log(f"[DISPATCH] Bar callback processed for {symbol}")
                        elif callback_type == 'price':
                            self._on_price_direct(*args, **kwargs)
                        elif callback_type == 'execution':
                            self._on_execution_direct(*args, **kwargs)
                        elif callback_type == 'account':
                            self._on_account_direct(*args, **kwargs)

                    except Exception as e:
                        import traceback
                        logger.error(f"[DISPATCH] Error processing {callback_type}: {e}")
                        logger.error(traceback.format_exc())

                processing_time = (time.time() - start_time) * 1000  # ms
                if processed_count > 0:
                    coalesced_count = len(temp_queue) - len(all_items) if temp_queue else 0
                    # Callback processing completed

        except Exception as e:
            logger.error(f"[DISPATCH] Critical error in queue processor: {e}")

            # EMERGENCY FALLBACK: Restart dispatcher if critical error
            try:
                if self._dispatch_timer_handle is not None:
                    self.cancel_timer(self._dispatch_timer_handle)

                # Restart with base interval (no adaptive)
                self._dispatch_timer_handle = self.run_every(self._process_dispatch_queue, f"now+{self._base_interval}", self._base_interval)
                self._adaptive_dispatch_enabled = False  # Disable adaptive after error
                logger.error(f"[DISPATCH] EMERGENCY RESTART: Fixed {self._base_interval*1000:.0f}ms intervals, adaptive disabled")

            except Exception as restart_error:
                logger.error(f"[DISPATCH] FATAL: Cannot restart dispatcher: {restart_error}")
                # Last resort: clear queue to prevent memory issues
                with self._dispatch_lock:
                    self._dispatch_queue.clear()
                logger.error(f"[DISPATCH] Queue cleared due to fatal error")

    def _enqueue_callback(self, callback_type: str, *args, **kwargs):
        """Thread-safe callback enqueuer with adaptive priority-aware dropping"""
        with self._dispatch_lock:
            perf_config = self.args.get('performance', {})
            max_queue_size = perf_config.get('max_queue_size', 300) if self._queue_limiting_enabled else 800
            priority_queue_size = perf_config.get('priority_queue_size', 200) if self._queue_limiting_enabled else 700
            emergency_queue_size = perf_config.get('emergency_queue_size', 800)

            current_queue_size = len(self._dispatch_queue)
            if callback_type == 'bar':
                symbol = args[0] if args else 'unknown'
                # DIAGNOSTIC: Use module logger
                main_logger.info(f"[ENQUEUE] ✅ Bar callback for {symbol}, queue_size={current_queue_size}")
                self.log(f"[ENQUEUE] Enqueuing bar callback for {symbol}, queue_size={current_queue_size}")

            # EMERGENCY: Priority-based dropping if critically large (instead of clear all)
            if current_queue_size >= emergency_queue_size:
                self.log(f"[DISPATCH] EMERGENCY: Queue size {current_queue_size} >= {emergency_queue_size}, applying priority-based dropping")
                
                # Separate events by priority
                execution_events = []
                account_events = []
                bar_events = []
                price_events = []
                
                for item in self._dispatch_queue:
                    item_type = item[0]
                    if item_type == 'execution':
                        execution_events.append(item)
                    elif item_type == 'account':
                        account_events.append(item)
                    elif item_type == 'bar':
                        bar_events.append(item)
                    else:  # price and others
                        price_events.append(item)
                
                # Keep all execution and account events (critical)
                # Keep only latest 50% of bar events (sampling)
                # Drop all price events (lowest priority, already coalesced in processing)
                bar_keep_count = max(1, len(bar_events) // 2)  # Keep latest 50%
                bar_events_kept = bar_events[-bar_keep_count:] if bar_events else []
                
                # Rebuild queue with priority order
                self._dispatch_queue.clear()
                self._dispatch_queue.extend(execution_events)
                self._dispatch_queue.extend(account_events)
                self._dispatch_queue.extend(bar_events_kept)
                
                dropped_count = len(price_events) + (len(bar_events) - len(bar_events_kept))
                self.log(f"[DISPATCH] EMERGENCY: Priority drop - kept {len(execution_events)} execution, "
                        f"{len(account_events)} account, {len(bar_events_kept)}/{len(bar_events)} bars, "
                        f"dropped {dropped_count} events (all prices + {len(bar_events) - len(bar_events_kept)} old bars)")
                current_queue_size = len(self._dispatch_queue)

            # Enhanced queue size limiting with priority-based dropping
            if self._queue_limiting_enabled and current_queue_size >= max_queue_size:
                # Smart dropping - preserve execution/account events, sample bar events, drop old price events
                dropped_count = 0
                original_queue = list(self._dispatch_queue)
                
                # Separate by type
                execution_events = []
                account_events = []
                bar_events = []
                price_events = []
                
                for item in original_queue:
                    item_type = item[0]
                    if item_type == 'execution':
                        execution_events.append(item)
                    elif item_type == 'account':
                        account_events.append(item)
                    elif item_type == 'bar':
                        bar_events.append(item)
                    else:  # price and others
                        price_events.append(item)
                
                # Rebuild queue with priority: execution > account > bars (sampled) > prices (limited)
                self._dispatch_queue.clear()
                self._dispatch_queue.extend(execution_events)  # All execution events
                self._dispatch_queue.extend(account_events)   # All account events
                
                # Keep latest 75% of bar events (sampling to prevent signal loss)
                bar_keep_count = max(1, int(len(bar_events) * 0.75))
                bar_events_kept = bar_events[-bar_keep_count:] if bar_events else []
                self._dispatch_queue.extend(bar_events_kept)
                
                # Keep only latest price events if we have space
                remaining_slots = priority_queue_size - len(self._dispatch_queue)
                if remaining_slots > 0 and price_events:
                    price_events_kept = price_events[-remaining_slots:] if len(price_events) > remaining_slots else price_events
                    self._dispatch_queue.extend(price_events_kept)
                    dropped_count += len(price_events) - len(price_events_kept)
                else:
                    dropped_count += len(price_events)
                
                dropped_count += len(bar_events) - len(bar_events_kept)

                if dropped_count > 0:
                    self.log(f"[DISPATCH] Smart drop: removed {dropped_count} old events "
                           f"({len(price_events)} prices + {len(bar_events) - len(bar_events_kept)} old bars), "
                           f"kept {len(self._dispatch_queue)} priority events (limit: {max_queue_size})")

            # Add new callback (execution events skip queue size check)
            queue_limit = max_queue_size if self._queue_limiting_enabled else 1000
            if callback_type == 'execution' or len(self._dispatch_queue) < queue_limit:
                self._dispatch_queue.append((callback_type, args, kwargs))
            else:
                self.log(f"[DISPATCH] Dropping {callback_type} callback - queue full ({len(self._dispatch_queue)}/{queue_limit})")

    def _on_bar_direct(self, raw_symbol: str, bar: Dict[str, Any], all_bars: List = None):
        """Upravená metoda pro příjem barů s historií - runs in main thread"""
        try:
            alias = self.symbol_alias.get(raw_symbol, raw_symbol)
            
            # DIAGNOSTIC: Log entry IMMEDIATELY using module logger
            main_logger.info(f"[BAR_DIRECT] ✅ {alias}: ENTRY")
            
            # DIAGNOSTIC: Log entry to trace bar flow
            self.log(f"[BAR_DIRECT] {alias}: Entry - all_bars={all_bars is not None}, current_bars={len(self.market_data.get(alias, []))}")
            
            # Pokud dostáváme všechny bary (bootstrap), nahradit celou historii
            if all_bars and len(all_bars) > len(self.market_data[alias]):
                self.log(f"[BOOTSTRAP] Loading {len(all_bars)} historical bars for {alias}")
                self._bootstrap_in_progress = True  # Enable bootstrap timing mode
                self.market_data[alias] = deque(all_bars, maxlen=5000)
                
                # Okamžitě spustit analýzu
                if len(all_bars) >= self.analysis_min_bars:
                    self.log(f"[BOOTSTRAP] {alias}: Calling process_market_data immediately (bars: {len(all_bars)}, min: {self.analysis_min_bars})")
                    self.process_market_data(alias)
                    self.log(f"[BOOTSTRAP] Immediate analysis started for {alias}")

                # After bootstrap analysis, switch back to normal timing
                self.run_in(lambda _: setattr(self, '_bootstrap_in_progress', False), 5)
            else:
                # Normální přidání nového baru
                self.market_data[alias].append(bar)
                bars_count = len(self.market_data[alias])
                
                # Track last bar time for live status
                self._last_bar_time[alias] = datetime.now(timezone.utc)
                
                # Log entry (throttled - max once per minute per symbol)
                if not hasattr(self, '_last_bar_log') or alias not in self._last_bar_log or (datetime.now() - self._last_bar_log.get(alias, datetime.now())).seconds > 60:
                    if not hasattr(self, '_last_bar_log'):
                        self._last_bar_log = {}
                    self._last_bar_log[alias] = datetime.now()
                    self.log(f"[BAR] {alias}: Received bar, total={bars_count}, min_required={self.analysis_min_bars}")

                # Update microstructure volume profile with new bar volume
                if hasattr(self, 'microstructure') and 'volume' in bar and bar['volume'] > 0:
                    bar_timestamp = bar.get('timestamp')
                    if isinstance(bar_timestamp, str):
                        bar_timestamp = datetime.fromisoformat(bar_timestamp.replace('Z', '+00:00'))
                    
                    # CRITICAL FIX: Update broker timestamp in time manager
                    if hasattr(self, 'time_manager') and self.time_manager and bar_timestamp:
                        self.time_manager.update_broker_timestamp(bar_timestamp)
                    
                    self.microstructure.update_volume_profile(alias, bar_timestamp, bar['volume'])

                if bars_count >= self.analysis_min_bars:
                    self.log(f"[BAR] {alias}: Calling process_market_data (bars: {bars_count} >= {self.analysis_min_bars})")
                    try:
                        self.process_market_data(alias)
                        self.log(f"[BAR] {alias}: process_market_data completed")
                    except Exception as e:
                        import traceback
                        self.error(f"[BAR] {alias}: EXCEPTION in process_market_data: {e}")
                        self.error(f"[BAR] {alias}: Traceback: {traceback.format_exc()}")
                else:
                    # Log when we don't have enough bars (always log for visibility)
                    self.log(f"[BAR] {alias}: Not enough bars ({bars_count}/{self.analysis_min_bars}), skipping process_market_data")
            
            # Sprint 2: Push to EventBridge and handle microstructure
            if hasattr(self, 'event_bridge'):
                self.event_bridge.push_event('bar', {
                    'symbol': raw_symbol,
                    'bar': bar,
                    'alias': alias
                })
            
            # Sprint 2: Direct microstructure update
            if hasattr(self, 'handle_bar_data'):
                self.handle_bar_data({'symbol': raw_symbol, 'bar': bar})
                    
        except Exception as e:
            import traceback
            self.error(f"_on_bar error: {e}")
            self.error(f"_on_bar traceback: {traceback.format_exc()}")

    def log_status(self, _):
        """
        Periodic status logging with system state publishing
        
        OPTIMIZED pro thread starvation prevention:
        - Při přetížení přeskočí non-critical set_state volání
        - Vždy loguje status do konzole
        """
        # === THREAD STARVATION PREVENTION ===
        system_overloaded = self._is_system_overloaded()
        
        risk_status = self.risk_manager.get_risk_status()
        parts = []
        
        # Stav připojení - kritické, vždy publikovat
        up = "on" if (self.ctrader_client and self.ctrader_client.is_connected()) else "off"
        if not system_overloaded:
            self._safe_set_state("binary_sensor.ctrader_connected", state=up)
        
        # Publikovat hlavní stav systému - pouze pokud není přetížení
        if not system_overloaded:
            self._safe_set_state(
                "sensor.trading_analysis_status",
                state="RUNNING" if up == "on" else "STOPPED",
                attributes={
                    "friendly_name": "Trading Analysis Status",
                    "last_update": self.get_synced_time().isoformat(),
                    "symbols_tracked": len(self.alias_to_raw)
                }
            )
        
        # Pro každý symbol
        for alias, raw in self.alias_to_raw.items():
            n = len(self.market_data.get(alias, []))
            age = self._tick_age_minutes(raw)
            atr = self.current_atr.get(alias, 0)
            parts.append(f"{alias}={n}/{self.analysis_min_bars} (age:{age}, ATR:{atr:.2f})")
            
            # Určit stav pro každý symbol
            in_hours_result = self._is_within_trading_hours(alias) if hasattr(self, '_is_within_trading_hours') else (True, "open")
            in_hours = in_hours_result[0] if isinstance(in_hours_result, tuple) else in_hours_result
            hours_reason = in_hours_result[1] if isinstance(in_hours_result, tuple) else "unknown"
            has_data = n >= self.analysis_min_bars
            
            if up != "on":
                status = "DISCONNECTED"
            elif not in_hours:
                # Trhy jsou zavřené - jednotný status bez ohledu na množství dat
                status = "ANALYSIS_ONLY"
            elif not has_data:
                status = "WARMING_UP"
            else:
                status = "TRADING"
            
            # Log trading hours status pro každý symbol (jednou za restart nebo při změně)
            status_key = f"_last_hours_status_{alias}"
            current_hours_status = (in_hours, hours_reason)
            if not hasattr(self, status_key) or getattr(self, status_key) != current_hours_status:
                setattr(self, status_key, current_hours_status)
                if not in_hours:
                    if hours_reason == "holiday":
                        main_logger.info(f"[TRADING_HOURS] {alias}: ⛔ Market closed (holiday)")
                    elif hours_reason == "weekend":
                        main_logger.info(f"[TRADING_HOURS] {alias}: ⛔ Market closed (weekend)")
                    elif hours_reason == "early_close":
                        main_logger.info(f"[TRADING_HOURS] {alias}: ⛔ Market closed (early close)")
                    else:
                        main_logger.info(f"[TRADING_HOURS] {alias}: ⛔ Outside trading hours")
                else:
                    main_logger.info(f"[TRADING_HOURS] {alias}: ✅ Market open")
            
            # Publikovat stav symbolu - pouze pokud není přetížení
            if not system_overloaded:
                self._safe_set_state(
                    f"sensor.{alias.lower()}_trading_status",
                    state=status,
                    attributes={
                        "market_hours": in_hours,
                        "has_data": has_data,
                        "bars": n,
                        "min_bars": self.analysis_min_bars,
                        "signals_enabled": in_hours and has_data,
                        "atr": round(atr, 2),
                        "last_update": datetime.now().isoformat()
                    }
                )
        
        # Publikovat live status informace - pouze pokud není přetížení
        if not system_overloaded:
            self._publish_live_status()
        
        # Log pouze jednou za 5 minut
        if not hasattr(self, '_last_full_status') or \
        (datetime.now() - self._last_full_status).seconds > 300:
            self.log("[STATUS] " + " | ".join(parts))
            self._last_full_status = datetime.now()
            
            if risk_status.warnings:
                self.log(f"[RISK STATUS] Warnings: {', '.join(risk_status.warnings)}")
        
        # Check if Account Monitor is active to avoid overwriting daily PnL data
        current_entity = self.get_state("sensor.trading_risk_status", attribute="all")
        current_attributes = current_entity.get("attributes", {}) if current_entity else {}

        # Check for Account Monitor data first
        current_daily_pnl = current_attributes.get("daily_pnl_czk", None)
        account_monitor_last_update = current_attributes.get("account_monitor_last_update")
        account_monitor_active = current_attributes.get("account_monitor_active", False)

        # Prepare attributes for update
        # Preserve open_positions from Account Monitor if active
        account_monitor_open_positions = current_attributes.get("open_positions", 0) if account_monitor_active else risk_status.open_positions

        risk_attributes = {
            "open_positions": account_monitor_open_positions,
            "total_risk_czk": risk_status.total_risk_czk,
            "total_risk_pct": risk_status.total_risk_pct,
            "can_trade": risk_status.can_trade,
            "warnings": risk_status.warnings,  # Keep as list for dashboard
            "account_balance": risk_status.account_balance,
            "margin_used_czk": risk_status.margin_used_czk,
            "margin_used_pct": risk_status.margin_used_pct
        }

        # NO FALLBACKS - Only use Account Monitor data or show error
        if current_daily_pnl is not None:
            # Account Monitor has provided PnL data - use it (even if 0)
            risk_attributes.update({
                "daily_pnl_czk": current_daily_pnl,
                "daily_pnl_pct": current_attributes.get("daily_pnl_pct", 0),
                "daily_realized_pnl": current_attributes.get("daily_realized_pnl", 0),
                "daily_unrealized_pnl": current_attributes.get("daily_unrealized_pnl", 0),
            })
            self.log(f"[RISK STATUS] Using Account Monitor daily PnL data: {current_daily_pnl:.2f} CZK")
        else:
            # No data from Account Monitor - may be normal during startup
            # Only log as warning if we're past initial startup period (30 seconds)
            startup_time = getattr(self, '_startup_time', None)
            if startup_time is None:
                # Použít synchronizovaný čas
                self._startup_time = self.time_sync.now() if hasattr(self, 'time_sync') else datetime.now(timezone.utc)
            
            # Použít synchronizovaný čas
            current_time = self.time_sync.now() if hasattr(self, 'time_sync') else datetime.now(timezone.utc)
            time_since_startup = (current_time - self._startup_time).total_seconds()
            if time_since_startup > 30:
                # Past startup - this is a real issue
                self.log("[RISK STATUS] NO Account Monitor PnL data available - system may not be properly initialized!", level="WARNING")
            else:
                # During startup - this is normal
                self.log(f"[RISK STATUS] Account Monitor PnL data not yet available (startup: {time_since_startup:.0f}s)")
            
            risk_attributes.update({
                "daily_pnl_czk": None,  # Explicitly None, not some fake value
                "daily_pnl_pct": None,
                "error": "Account Monitor not providing data" if time_since_startup > 30 else "Initializing..."
            })

        # Update risk status with merged attributes
        self._safe_set_state(
            "sensor.trading_risk_status",
            state="ACTIVE" if risk_status.can_trade else "LOCKED",
            attributes=risk_attributes
        )

    def update_signal_manager(self, _):
        """Optimized signal manager updates with change detection"""
        if not self.ctrader_client:
            return

        # Fast path: Check if we have any price changes since last update
        has_changes = False
        current_prices = {}
        current_atrs = {}

        for alias, raw in self.alias_to_raw.items():
            cp = getattr(self.ctrader_client, "current_price", {}).get(raw)
            if not cp:
                continue
            bid = cp.get("bid"); ask = cp.get("ask")
            px = bid if bid is not None else ask
            if px is None:
                continue

            current_prices[alias] = float(px)
            current_atrs[alias] = float(self.current_atr.get(alias, 0.0))

            # Check for significant price change (0.01% threshold)
            last_price = getattr(self, '_last_signal_prices', {}).get(alias, 0)
            if abs(px - last_price) / max(last_price, 1) > 0.0001:  # 0.01% change
                has_changes = True

        # Only update if there are meaningful changes
        if has_changes and current_prices:
            self.signal_manager.update_signals(current_prices, current_atrs)
            # Cache current prices for next comparison
            self._last_signal_prices = current_prices.copy()
        elif not hasattr(self, '_last_signal_update_log'):
            # Log once that we're skipping updates due to no changes
            self.log("[PERF] Signal manager updates optimized - only updating on price changes")
            self._last_signal_update_log = True

    def _should_update_entity(self, entity_id: str, new_value, min_interval_sec: int = 5) -> bool:
        """Throttle entity updates to reduce HA load"""
        import time
        current_time = time.time()

        if not hasattr(self, '_entity_update_times'):
            self._entity_update_times = {}

        last_update = self._entity_update_times.get(entity_id, 0)
        if current_time - last_update >= min_interval_sec:
            self._entity_update_times[entity_id] = current_time
            return True
        return False

    def _get_cached_calculation(self, cache_key: str, calculation_func, cache_duration_sec: int = 30):
        """Generic caching mechanism for expensive calculations"""
        import time
        current_time = time.time()

        if not hasattr(self, '_calculation_cache'):
            self._calculation_cache = {}

        cache_entry = self._calculation_cache.get(cache_key)

        if cache_entry and (current_time - cache_entry['timestamp']) < cache_duration_sec:
            return cache_entry['result']

        # Calculate and cache
        result = calculation_func()
        self._calculation_cache[cache_key] = {
            'result': result,
            'timestamp': current_time
        }
        return result

    def process_market_data(self, alias: str):
        """Process market data - COMPLETE FIXED VERSION"""
        try:
            from datetime import datetime, timedelta
            
            # DIAGNOSTIC: Log IMMEDIATELY using module logger
            main_logger.info(f"[PROCESS_DATA] ✅ {alias}: ENTRY")
            
            # Always log entry (removed throttling for visibility)
            bars_count = len(self.market_data.get(alias, []))
            
            # Track last analysis time
            self._last_analysis_time[alias] = datetime.now(timezone.utc)
            
            # === KONTROLA STAVU SYSTÉMU PŘED ZPRACOVÁNÍM ===
            # CRITICAL FIX: Kontrolujeme přímo is_connected() místo HA entity (ta má zpoždění 30s)
            ctrader_connected = self.ctrader_client.is_connected() if self.ctrader_client else False
            ctrader_status = "on" if ctrader_connected else "off"
            
            main_logger.info(f"[SYSTEM_CHECK] {alias}: cTrader={ctrader_status}, bars={bars_count}")
            
            if not ctrader_connected:
                main_logger.info(f"[PROCESS_DATA] ⛔ {alias}: BLOCKED - cTrader not connected")
                return
            
            bars = list(self.market_data.get(alias, []))
            
            # Kontrola minimálního počtu barů
            if len(bars) < self.analysis_min_bars:
                main_logger.info(f"[PROCESS_DATA] ⛔ {alias}: BLOCKED - Insufficient bars {len(bars)}/{self.analysis_min_bars}")
                return
            
            main_logger.info(f"[PROCESS_DATA] ✅ {alias}: All pre-checks passed, starting analysis with {len(bars)} bars")
        
            # === VŽDY SPOČÍTAT A PUBLIKOVAT ANALÝZU ===
            
            # Initialize variables to ensure they're always defined
            regime_data = None
            piv = None
            swing = None
            
            # 1. Regime detection - VŽDY (using new RegimeDetector)
            try:
                regime_state = self.regime_detector.detect(bars)
                regime_data = self.regime_detector.get_state_summary()
                self._publish_regime(alias, regime_data)
            except Exception as e:
                self.error(f"[ERROR] Regime detection failed for {alias}: {e}")
                # Publikovat alespoň defaultní hodnoty a definovat regime_data
                regime_data = {"state": "ERROR", "adx": 0.0, "r2": 0.0, "trend_direction": None}
                self._publish_regime(alias, regime_data)
            
            # 2. Pivots calculation - VŽDY (NEW: Using PivotCalculator)
            try:
                # Calculate pivots using new PivotCalculator
                timeframe = self.args.get('timeframe', 'M5')
                pivot_sets = self.pivot_calc.calculate_pivots(bars, timeframe)
                
                # Extract daily pivots for publishing
                if pivot_sets.get('daily'):
                    daily = pivot_sets['daily']
                    piv = {
                        'pivot': daily.pivot,
                        'r1': daily.r1,
                        'r2': daily.r2,
                        's1': daily.s1,
                        's2': daily.s2
                    }
                    
                    # Store pivot data for market structure analysis
                    self.current_pivots[alias] = piv
                    self._publish_pivots(alias, piv, current_price=self._get_current_price(alias))
                else:
                    # Fallback to simple calculation
                    piv = self.calculate_simple_pivots(bars)
                    # Store fallback pivot data for market structure analysis
                    self.current_pivots[alias] = piv
                    self._publish_pivots(alias, piv, current_price=self._get_current_price(alias))
                    
            except Exception as e:
                self.error(f"[ERROR] Pivot calculation failed for {alias}: {e}")
                self.error(traceback.format_exc())
                # Ensure piv is defined even on error - use fallback
                if piv is None:
                    try:
                        piv = self.calculate_simple_pivots(bars)
                        self.log(f"[FALLBACK] Using simple pivots for {alias} due to calculation error")
                    except Exception as fallback_e:
                        self.error(f"[ERROR] Fallback pivot calculation also failed: {fallback_e}")
                        piv = {'pivot': 0, 'r1': 0, 'r2': 0, 's1': 0, 's2': 0}
            
            # 3. Swing detection - VŽDY
            try:
                timeframe = self.args.get('timeframe', 'M5')
                
                # Update ATR in swing detector for pivot validation
                # Use pivot calculator's ATR if available (calculated during pivot calculation)
                if hasattr(self.swing_engine, 'current_atr') and hasattr(self.pivot_calc, 'current_atr'):
                    if self.pivot_calc.current_atr > 0:
                        self.swing_engine.current_atr = self.pivot_calc.current_atr
                    elif len(bars) >= 15:
                        # Simple ATR calculation as fallback
                        tr_values = []
                        for i in range(1, min(15, len(bars))):
                            high = bars[i]['high']
                            low = bars[i]['low']
                            prev_close = bars[i-1]['close']
                            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
                            tr_values.append(tr)
                        if tr_values:
                            calculated_atr = sum(tr_values) / len(tr_values)
                            self.swing_engine.current_atr = calculated_atr
                            # Also update pivot calculator's ATR for consistency
                            self.pivot_calc.current_atr = calculated_atr
                
                swing_state = self.swing_engine.detect_swings(bars, timeframe)

                # Handle both Enum and string trend values (SimpleSwingDetector uses strings)
                trend_value = swing_state.trend.value if hasattr(swing_state.trend, 'value') else swing_state.trend

                swing = {
                    "trend": trend_value,
                    "quality": swing_state.swing_quality,
                    "last_high": swing_state.last_high.price if swing_state.last_high else None,
                    "last_low": swing_state.last_low.price if swing_state.last_low else None,
                    "swing_count": len(swing_state.swings)  # NEW: Add swing count for monitoring
                }
                self._publish_swings(alias, swing)

            except Exception as e:
                self.error(f"[ERROR] Swing detection failed for {alias}: {e}")
                self.error(traceback.format_exc())
                # Ensure swing is defined even on error
                if swing is None:
                    swing = {
                        "trend": "UNKNOWN",
                        "quality": 0,
                        "last_high": None,
                        "last_low": None,
                        "swing_count": 0
                    }
            
            # 4. ATR calculation - VŽDY
            try:
                atr_value = self._calculate_atr(bars, period=14)
                self.current_atr[alias] = atr_value

                # Test simple ATR calculation vs platform once per symbol startup
                if not hasattr(self, '_atr_tested') or alias not in self._atr_tested:
                    if not hasattr(self, '_atr_tested'):
                        self._atr_tested = set()
                    self._atr_tested.add(alias)

                    # Test with last 20 bars to see if calculation matches expected
                    if len(bars) >= 20:
                        simple_atr = self._test_atr_calculation(bars[-20:], alias)
                        if simple_atr != atr_value:
                            self.log(f"[ATR TEST] {alias}: Simple ATR (20 bars): {simple_atr:.4f} vs Full ATR: {atr_value:.4f}")

            except Exception as e:
                self.error(f"[ERROR] ATR calculation failed for {alias}: {e}")
                self.current_atr[alias] = 0.0
        
            # === KONTROLY PRO GENEROVÁNÍ SIGNÁLŮ ===
        
            # Enhanced cooldown check - direction-aware and market-change aware
            if not hasattr(self, '_last_signal_info'):
                self._last_signal_info = {}  # {alias: {'time': datetime, 'direction': 'BUY'|'SELL', 'price': float}}
            
            now = datetime.now()
            last_signal_info = self._last_signal_info.get(alias)
            
            last_signal_time = None
            last_direction = ''
            last_price = 0
            
            if last_signal_info:
                last_signal_time = last_signal_info.get('time')
                last_direction = last_signal_info.get('direction', '')
                last_price = last_signal_info.get('price', 0)
            
            time_since_signal = (now - last_signal_time).seconds if last_signal_time else 0
            base_cooldown = 1800  # 30 minut base cooldown
            
            # Get current price for market change detection
            current_price = self._get_current_price(alias)
            
            # Check if market changed significantly (new swing, pivot break, or large price move)
            market_changed = False
            # CRITICAL FIX: Handle None values for current_price and last_price
            if current_price is not None and last_price is not None and current_price > 0 and last_price > 0:
                price_change_pct = abs(current_price - last_price) / last_price if last_price > 0 else 0
                atr_value = self.current_atr.get(alias, 0)
                
                # Significant price move (2x ATR or 1% change)
                if atr_value > 0:
                    price_change_atr = abs(current_price - last_price) / atr_value if atr_value > 0 else 0
                    if price_change_atr >= 2.0 or price_change_pct >= 0.01:
                        market_changed = True
                elif price_change_pct >= 0.01:
                    market_changed = True
                
                # Check for new swing (if swing state changed significantly)
                if swing is not None and swing.get('last_high') and swing.get('last_low'):
                    # If new swing high/low detected, market structure changed
                    if last_signal_info.get('last_swing_high') != swing.get('last_high') or \
                       last_signal_info.get('last_swing_low') != swing.get('last_low'):
                        market_changed = True
            
            # Determine effective cooldown based on direction and market changes
            if market_changed:
                # Market changed significantly - reduce cooldown to 10 minutes
                effective_cooldown = 600  # 10 minutes
            else:
                effective_cooldown = base_cooldown
            
            # Direction-aware: Allow opposite direction signals sooner (15 minutes)
            # This allows BUY after SELL or vice versa without full cooldown
            # (We'll check direction later when we have the signal)
            
            if time_since_signal < effective_cooldown:
                # Still in cooldown - but we'll check direction when signal is generated
                # For now, just log and continue (direction check happens later in edge detection)
                if not hasattr(self, '_cooldown_log_throttle'):
                    self._cooldown_log_throttle = {}
                
                last_log = self._cooldown_log_throttle.get(alias, datetime.now() - timedelta(seconds=300))
                if (now - last_log).seconds > 300:  # Log max once per 5 minutes
                    self._cooldown_log_throttle[alias] = now
                    remaining = effective_cooldown - time_since_signal
                    self.log(f"[COOLDOWN] {alias}: Signal cooldown active ({remaining//60}min remaining, "
                            f"market_changed={market_changed}, last_direction={last_direction})")
                # Continue to edge detection - it will check direction and apply cooldown if needed
        
            # DIAGNOSTIC: Log checkpoint after analysis
            main_logger.info(f"[CHECKPOINT] ✅ {alias}: After regime/pivot/swing analysis")
            
            # Kontrola aktivních tiketů
            active_tickets = self._count_active_tickets(alias)
            main_logger.info(f"[CHECKPOINT] ✅ {alias}: active_tickets={active_tickets}")
            if active_tickets > 0:
                # Always log (removed throttling)
                main_logger.info(f"[PROCESS_DATA] ⛔ {alias}: BLOCKED - {active_tickets} active tickets")
                self.log(f"[PROCESS_DATA] {alias}: BLOCKED - {active_tickets} active tickets")
                return
            
            # Kontrola obchodních hodin
            in_hours, hours_reason = self._is_within_trading_hours(alias)
            main_logger.info(f"[CHECKPOINT] ✅ {alias}: in_hours={in_hours}")
            if not in_hours:
                # Zobrazit správnou zprávu podle důvodu
                current_time = datetime.now().strftime('%H:%M')
                if hours_reason == "holiday":
                    reason_msg = "Market closed (holiday)"
                elif hours_reason == "early_close":
                    reason_msg = "Market closed (early close)"
                elif hours_reason == "weekend":
                    reason_msg = "Market closed (weekend)"
                else:
                    reason_msg = f"Outside trading hours at {current_time}"
                main_logger.info(f"[PROCESS_DATA] ⛔ {alias}: BLOCKED - {reason_msg}")
                self.log(f"[PROCESS_DATA] {alias}: BLOCKED - {reason_msg}")
                return
            
            # Kontrola risk manageru
            risk_status = self.risk_manager.get_risk_status()
            main_logger.info(f"[CHECKPOINT] ✅ {alias}: risk can_trade={risk_status.can_trade}")
            if not risk_status.can_trade:
                # Always log (removed throttling)
                main_logger.info(f"[PROCESS_DATA] ⛔ {alias}: BLOCKED - Risk manager (can_trade=False)")
                self.log(f"[PROCESS_DATA] {alias}: BLOCKED - Risk manager (can_trade=False)")
                return
        
            main_logger.info(f"[PROCESS_DATA] ✅ {alias}: All system checks passed!")
            self.log(f"[PROCESS_DATA] {alias}: All system checks passed, proceeding with analysis")
        
            # === MICROSTRUCTURE ANALYSIS ===
            main_logger.info(f"[CHECKPOINT] ✅ {alias}: Starting microstructure analysis")
            micro_data = {}
            if hasattr(self, 'microstructure') and len(bars) >= 14:
                try:
                    micro_data = self.microstructure.get_microstructure_summary(alias, bars)
                    if micro_data:
                        # Store for later use
                        if not hasattr(self, 'micro_data'):
                            self.micro_data = {}
                        self.micro_data[alias] = micro_data
                        
                        liquidity = micro_data.get('liquidity_score', 0)
                        is_high_quality = micro_data.get('is_high_quality_time', False)
                        main_logger.info(f"[CHECKPOINT] ✅ {alias}: liquidity={liquidity:.2f}, is_high_quality={is_high_quality}")
                        
                        # Check if it's quality trading time
                        is_quality_time = self.edge.is_quality_trading_time(alias, micro_data)
                        main_logger.info(f"[CHECKPOINT] ✅ {alias}: is_quality_trading_time={is_quality_time}")
                        
                        if not is_quality_time:
                            min_liquidity_threshold = self.args.get('microstructure', {}).get('min_liquidity_score', 0.1)
                            if liquidity < min_liquidity_threshold:
                                main_logger.info(f"[PROCESS_DATA] ⛔ {alias}: BLOCKED - Poor liquidity ({liquidity:.2f} < {min_liquidity_threshold})")
                                self.log(f"[PROCESS_DATA] {alias}: BLOCKED - Poor market conditions (liquidity {liquidity:.2f} < {min_liquidity_threshold})")
                            elif not is_high_quality:
                                main_logger.info(f"[PROCESS_DATA] ⛔ {alias}: BLOCKED - Outside prime trading hours")
                                self.log(f"[PROCESS_DATA] {alias}: BLOCKED - Outside prime trading hours")
                            else:
                                main_logger.info(f"[PROCESS_DATA] ⛔ {alias}: BLOCKED - Suboptimal trading conditions")
                                self.log(f"[PROCESS_DATA] {alias}: BLOCKED - Suboptimal trading conditions")
                            return
                        
                except Exception as e:
                    main_logger.error(f"[ERROR] {alias}: Microstructure analysis failed: {e}")
                    self.error(f"[ERROR] Microstructure analysis failed for {alias}: {e}")
            
            # === EDGE DETECTION pro signály ===
            main_logger.info(f"[CHECKPOINT] ✅ {alias}: Starting edge detection")
            
            # Check if edge detector is initialized
            if not hasattr(self, 'edge') or self.edge is None:
                # Always log (removed throttling)
                main_logger.info(f"[PROCESS_DATA] ⛔ {alias}: BLOCKED - Edge detector not initialized")
                self.log(f"[PROCESS_DATA] {alias}: BLOCKED - Edge detector not initialized")
                return
            
            # Validate required data
            main_logger.info(f"[CHECKPOINT] ✅ {alias}: swing={swing is not None}, piv={piv is not None}, regime={regime_data is not None}")
            if not swing or not piv or not regime_data:
                # Always log (removed throttling)
                missing = []
                if not swing: missing.append('swing')
                if not piv: missing.append('pivots')
                if not regime_data: missing.append('regime')
                main_logger.info(f"[PROCESS_DATA] ⛔ {alias}: BLOCKED - Missing data: {', '.join(missing)}")
                self.log(f"[PROCESS_DATA] {alias}: BLOCKED - Missing data: {', '.join(missing)}")
                return
            
            # Always log signal detection attempt (removed throttling for visibility)
            regime_state = regime_data.get('state', 'UNKNOWN')
            swing_trend = swing.get('trend', 'UNKNOWN') if swing else 'N/A'
            main_logger.info(f"[SIGNAL_CHECK] ✅ {alias}: Calling detect_signals - regime={regime_state}, swing={swing_trend}")
            self.log(f"[SIGNAL_CHECK] {alias}: Calling detect_signals - regime={regime_state}, swing={swing_trend}, bars={len(bars)}")
            
            # Track last signal check time
            self._last_signal_check_time[alias] = datetime.now(timezone.utc)
            
            try:
                signals = self.edge.detect_signals(
                    bars=bars,
                    regime_state=regime_data,
                    pivot_levels=piv,
                    swing_state=swing,
                    microstructure_data=micro_data
                )
                
                # Always log signal detection result
                if signals:
                    self.log(f"✅ [SIGNAL] {alias}: {len(signals)} signal(s) generated and passed all filters")
                    self._last_signal_check_result[alias] = f"{len(signals)} signal(s) generated"
                else:
                    # Log that detection completed but no signals generated
                    self.log(f"⏸️ [SIGNAL] {alias}: Signal detection completed - no signals generated (check logs above for blocking reasons)")
                    # Store last blocking reason (will be updated by detect_signals if available)
                    if alias not in self._last_signal_check_result:
                        self._last_signal_check_result[alias] = "No signals (check filters)"
                
                if signals:
                    sig = signals[0]
                    
                    # Direction-aware cooldown check - allow opposite direction signals sooner
                    signal_direction = sig.signal_type.value if hasattr(sig.signal_type, 'value') else str(sig.signal_type)
                    last_signal_info = self._last_signal_info.get(alias)
                    
                    if last_signal_info:
                        last_direction = last_signal_info.get('direction', '')
                        last_signal_time = last_signal_info.get('time')
                        time_since_signal = (now - last_signal_time).seconds if last_signal_time else 0
                        
                        # If opposite direction, use shorter cooldown (15 minutes)
                        if last_direction and signal_direction != last_direction:
                            opposite_cooldown = 900  # 15 minutes for opposite direction
                            if time_since_signal < opposite_cooldown:
                                remaining = opposite_cooldown - time_since_signal
                                self.log(f"[COOLDOWN] {alias}: Skipping {signal_direction} signal - "
                                        f"opposite direction cooldown active ({remaining//60}min remaining, "
                                        f"last was {last_direction})")
                                return
                        else:
                            # Same direction - use full cooldown (already checked above, but double-check here)
                            base_cooldown = 1800  # 30 minutes
                            if time_since_signal < base_cooldown:
                                remaining = base_cooldown - time_since_signal
                                self.log(f"[COOLDOWN] {alias}: Skipping {signal_direction} signal - "
                                        f"same direction cooldown active ({remaining//60}min remaining)")
                                return
                    
                    # Position sizing with microstructure data
                    position = self.risk_manager.calculate_position_size(
                        symbol=alias,
                        entry=sig.entry,
                        stop_loss=sig.stop_loss,
                        take_profit=sig.take_profit,
                        regime=regime_data.get('state', 'UNKNOWN'),
                        signal_quality=sig.signal_quality,
                        atr=self.current_atr.get(alias, 0),
                        microstructure_data=micro_data  # Pass microstructure to risk manager
                    )
                    
                    self.log(f"[AUTO-TRADING] 🔍 Position sizing result for {alias}: position={'exists' if position else 'None'}")
                    
                    if position:
                        # Publikovat tiket
                        self._publish_single_trade_ticket(alias, position, sig)
                        
                        # Enhanced signal tracking - store direction, price, and swing state
                        signal_direction = sig.signal_type.value if hasattr(sig.signal_type, 'value') else str(sig.signal_type)
                        self._last_signal_info[alias] = {
                            'time': now,
                            'direction': signal_direction,
                            'price': sig.entry,
                            'last_swing_high': swing.get('last_high') if swing else None,
                            'last_swing_low': swing.get('last_low') if swing else None
                        }
                        
                        # === AUTO-TRADING: Try to execute signal automatically ===
                        self.log(f"[AUTO-TRADING] 🔍 Signal generated for {alias}: auto_trading_enabled={self.auto_trading_enabled}, order_executor={'exists' if self.order_executor else 'None'}")
                        if self.auto_trading_enabled:
                            signal_dict = {
                                'symbol': alias,
                                'signal_type': sig.signal_type,
                                'entry': sig.entry,
                                'stop_loss': sig.stop_loss,
                                'take_profit': sig.take_profit,
                                'signal_quality': sig.signal_quality,
                                'confidence': getattr(sig, 'confidence', 75),
                                'patterns': getattr(sig, 'patterns', ['EDGE']),
                                'risk_reward_ratio': getattr(sig, 'risk_reward', 2.0),
                                # Microstructure data for analytics
                                'liquidity_score': getattr(sig, 'liquidity_score', None),
                                'volume_zscore': getattr(sig, 'volume_zscore', None),
                                'vwap_distance_pct': getattr(sig, 'vwap_distance_pct', None),
                                'orb_triggered': getattr(sig, 'orb_triggered', False),
                                'high_quality_time': getattr(sig, 'high_quality_time', False),
                                # Swing context for analytics
                                'swing_quality_score': getattr(sig, 'swing_quality_score', None),
                                'pattern_type': sig.signal_type if hasattr(sig, 'signal_type') else None
                            }
                            self._try_auto_execute_signal(signal_dict, alias)
                    
            except Exception as e:
                self.error(f"[ERROR] Edge detection failed for {alias}: {e}")
                import traceback
                self.error(f"[ERROR] Edge detection traceback: {traceback.format_exc()}")
        except Exception as outer_e:
            # Catch any exception in process_market_data that wasn't caught by inner try-except blocks
            import traceback
            self.error(f"[PROCESS_DATA] {alias}: EXCEPTION in process_market_data: {outer_e}")
            self.error(f"[PROCESS_DATA] {alias}: Traceback: {traceback.format_exc()}")
                
    # ---------------- publishers ----------------
    def _publish_regime(self, alias: str, regime: Dict[str, Any]):
        """Publish regime data - COMPLETE FIXED VERSION with Multi-Timeframe support"""
        # Zajistit, že hodnoty nejsou None nebo NaN
        state = regime.get("state", "UNKNOWN")
        adx_value = regime.get("adx", 0.0)
        r2_value = regime.get("r2", 0.0)

        # Ověřit že hodnoty jsou čísla
        try:
            adx_float = float(adx_value) if adx_value is not None else 0.0
            r2_float = float(r2_value) if r2_value is not None else 0.0
        except (ValueError, TypeError):
            adx_float = 0.0
            r2_float = 0.0

        # Zajistit, že nejsou NaN
        if adx_float != adx_float:  # NaN check
            adx_float = 0.0
        if r2_float != r2_float:  # NaN check
            r2_float = 0.0

        # Store full regime data for analytics (including ADX and new fields)
        self._last_regime_data_by_symbol[alias] = {
            'state': state,
            'adx': adx_float,
            'r2': r2_float,
            'trend_direction': regime.get("trend_direction"),
            'confidence': regime.get("confidence", 0),
            'primary_regime': regime.get("primary_regime"),
            'secondary_regime': regime.get("secondary_regime"),
            'trend_change': regime.get("trend_change"),
            'ema34_trend': regime.get("ema34_trend"),
            'used_timeframe': regime.get("used_timeframe", "combined")
        }

        # Get trend direction if available
        trend_direction = regime.get("trend_direction")
        
        # Create enhanced state with direction (legacy support)
        enhanced_state = state
        if trend_direction and state in ["TREND_UP", "TREND_DOWN"]:
            # Already has direction
            enhanced_state = state
        elif trend_direction and state == "TREND":
            enhanced_state = f"TREND_{trend_direction}"
        
        # Build attributes with multi-timeframe info
        regime_attributes = {
            "adx": round(adx_float, 2),
            "r2": round(r2_float, 3),
            "trend_direction": trend_direction,
            "confidence": regime.get("confidence", 0),
            "friendly_name": f"{alias} Regime",
            "icon": "mdi:chart-box-outline"
        }
        
        # Add multi-timeframe fields to attributes
        if regime.get("used_timeframe"):
            regime_attributes["used_timeframe"] = regime.get("used_timeframe")
        if regime.get("primary_regime"):
            regime_attributes["primary_regime"] = regime.get("primary_regime")
        if regime.get("secondary_regime"):
            regime_attributes["secondary_regime"] = regime.get("secondary_regime")
        if regime.get("trend_change"):
            regime_attributes["trend_change"] = regime.get("trend_change")
        if regime.get("ema34_trend"):
            regime_attributes["ema34_trend"] = regime.get("ema34_trend")
        
        # Publikovat hlavní stav režimu (s multi-timeframe atributy)
        self._safe_set_state(
            f"sensor.{alias.lower()}_m1_regime_state", 
            state=enhanced_state, 
            attributes=regime_attributes
        )
        
        # Publikovat ADX samostatně
        self._safe_set_state(
            f"sensor.{alias.lower()}_m1_adx", 
            state=str(round(adx_float, 2)),
            attributes={
                "friendly_name": f"{alias} ADX",
                "unit_of_measurement": "",
                "icon": "mdi:sine-wave"
            }
        )
        
        # Publikovat R2 samostatně
        self._safe_set_state(
            f"sensor.{alias.lower()}_m1_r2", 
            state=str(round(r2_float, 3)),
            attributes={
                "friendly_name": f"{alias} R²",
                "unit_of_measurement": "",
                "icon": "mdi:chart-line-stacked"
            }
        )
        
        # Debug log
        self.log(f"[REGIME PUBLISHED] {alias}: State={state}, ADX={adx_float:.2f}, R2={r2_float:.3f}")

    def _publish_pivots(self, alias: str, piv: Dict[str, float], current_price: Optional[float] = None):
        """
        Publikuje:
        - základní P, R1, R2, S1, S2 do samostatných senzorů
        - a také 'nejbližší' R nad cenou do ..._pivot_r a S pod cenou do ..._pivot_s
        """
        base = f"sensor.{alias.lower()}_m1_pivot_"

        # 1) Základní úrovně vždy zvlášť
        if "pivot" in piv:
            self._safe_set_state(base + "p", state=round(float(piv["pivot"]), 2))
        if "r1" in piv:
            self._safe_set_state(base + "r1", state=round(float(piv["r1"]), 2))
        if "r2" in piv:
            self._safe_set_state(base + "r2", state=round(float(piv["r2"]), 2))
        if "s1" in piv:
            self._safe_set_state(base + "s1", state=round(float(piv["s1"]), 2))
        if "s2" in piv:
            self._safe_set_state(base + "s2", state=round(float(piv["s2"]), 2))

        # 2) Najdi nejbližší R nad a S pod aktuální cenou → zachováme původní entity _pivot_r / _pivot_s
        price = current_price if current_price is not None else self._get_current_price(alias)

        r_levels = [piv[k] for k in ("r1", "r2") if k in piv and piv[k] is not None]
        s_levels = [piv[k] for k in ("s1", "s2") if k in piv and piv[k] is not None]

        nearest_r = None
        nearest_s = None

        if price is not None:
            higher = [r for r in r_levels if r >= price]
            lower  = [s for s in s_levels if s <= price]
            nearest_r = min(higher) if higher else (min(r_levels) if r_levels else None)
            nearest_s = max(lower)  if lower  else (max(s_levels) if s_levels else None)
        else:
            # fallback: bez ceny – použij nejbližší „základní“ (R1/S1), případně P
            nearest_r = (piv.get("r1") or piv.get("r2") or piv.get("pivot"))
            nearest_s = (piv.get("s1") or piv.get("s2") or piv.get("pivot"))

        if nearest_r is not None:
            self._safe_set_state(base + "r", state=round(float(nearest_r), 2))
        if nearest_s is not None:
            self._safe_set_state(base + "s", state=round(float(nearest_s), 2))

    def _publish_swings(self, alias: str, swing: Dict[str, Any]):
        self._safe_set_state(f"sensor.{alias.lower()}_m1_swing_trend", state=swing.get("trend", "UNKNOWN"), attributes={
            "quality": swing.get("quality", 0.0)
        })
        self._safe_set_state(f"sensor.{alias.lower()}_m1_swing_quality", state=round(float(swing.get("quality", 0.0)), 1))
        
        # Publish swing count if available
        swing_count = swing.get("swing_count", 0)
        self._safe_set_state(f"sensor.{alias.lower()}_m1_swing_count", state=swing_count, attributes={
            "friendly_name": f"{alias} Swing Count",
            "icon": "mdi:counter"
        })

    def _publish_live_status(self):
        """Publish live system status information"""
        try:
            now = datetime.now(timezone.utc)
            
            # Calculate status for each symbol
            status_data = {}
            overall_status = "OK"
            
            for alias in self.alias_to_raw.keys():
                last_bar = self._last_bar_time.get(alias)
                last_analysis = self._last_analysis_time.get(alias)
                last_signal_check = self._last_signal_check_time.get(alias)
                last_result = self._last_signal_check_result.get(alias, "No data")
                
                # Check if markets are open for this symbol
                in_trading_hours_result = self._is_within_trading_hours(alias) if hasattr(self, '_is_within_trading_hours') else (True, "open")
                in_trading_hours = in_trading_hours_result[0] if isinstance(in_trading_hours_result, tuple) else in_trading_hours_result
                
                # Calculate ages - use None if no data available
                if last_bar:
                    bar_age_sec = (now - last_bar).total_seconds()
                    bar_ago = f"{int(bar_age_sec)}s" if bar_age_sec < 60 else f"{int(bar_age_sec/60)}m" if bar_age_sec < 3600 else f"{int(bar_age_sec/3600)}h"
                else:
                    bar_age_sec = None
                    bar_ago = "N/A"
                
                if last_analysis:
                    analysis_age_sec = (now - last_analysis).total_seconds()
                    analysis_ago = f"{int(analysis_age_sec)}s" if analysis_age_sec < 60 else f"{int(analysis_age_sec/60)}m" if analysis_age_sec < 3600 else f"{int(analysis_age_sec/3600)}h"
                else:
                    analysis_age_sec = None
                    analysis_ago = "N/A"
                
                if last_signal_check:
                    signal_check_age_sec = (now - last_signal_check).total_seconds()
                    signal_check_ago = f"{int(signal_check_age_sec)}s" if signal_check_age_sec < 60 else f"{int(signal_check_age_sec/60)}m" if signal_check_age_sec < 3600 else f"{int(signal_check_age_sec/3600)}h"
                else:
                    signal_check_age_sec = None
                    signal_check_ago = "N/A"
                
                # Determine status - only check for STALE if markets are open
                # When markets are closed, it's normal that no new bars arrive
                if in_trading_hours:
                    # Markets are open - check if data is fresh
                    if last_bar is None or bar_age_sec > 300:  # 5 minutes
                        status = "STALE"
                        overall_status = "WARNING" if overall_status == "OK" else overall_status
                    elif last_analysis is None or analysis_age_sec > 600:  # 10 minutes
                        status = "SLOW"
                        overall_status = "WARNING" if overall_status == "OK" else overall_status
                    else:
                        status = "OK"
                else:
                    # Markets are closed - this is expected, don't show warning
                    status = "CLOSED"
                
                status_data[alias] = {
                    "last_bar_ago": bar_ago,
                    "last_analysis_ago": analysis_ago,
                    "last_signal_check_ago": signal_check_ago,
                    "last_signal_result": last_result,
                    "status": status
                }
            
            # Get market status information
            market_status_info = self._get_market_status_info()
            
            # Publish overall system status
            self._safe_set_state(
                "sensor.trading_system_status",
                state=overall_status,
                attributes={
                    "friendly_name": "Trading System Status",
                    "last_update": now.isoformat(),
                    "symbols": status_data,
                    "ctrader_connected": "on" if (self.ctrader_client and self.ctrader_client.is_connected()) else "off",
                    **market_status_info
                }
            )
            
            # Publish market status as separate entity
            self._safe_set_state(
                "sensor.market_status",
                state=market_status_info.get("status", "UNKNOWN"),
                attributes={
                    "friendly_name": "Market Status",
                    "current_session": market_status_info.get("current_session", "UNKNOWN"),
                    "next_session": market_status_info.get("next_session", "N/A"),
                    "time_until_open": market_status_info.get("time_until_open", "N/A"),
                    "time_until_open_seconds": market_status_info.get("time_until_open_seconds", 0),
                    "is_open": market_status_info.get("is_open", False),
                    "next_change_time": market_status_info.get("next_change_time", "N/A"),
                    "last_update": now.isoformat()
                }
            )
            
            # Publish per-symbol status
            for alias, data in status_data.items():
                self._safe_set_state(
                    f"sensor.{alias.lower()}_live_status",
                    state=data["status"],
                    attributes={
                        "friendly_name": f"{alias} Live Status",
                        "last_bar_ago": data["last_bar_ago"],
                        "last_analysis_ago": data["last_analysis_ago"],
                        "last_signal_check_ago": data["last_signal_check_ago"],
                        "last_signal_result": data["last_signal_result"],
                        "last_update": now.isoformat()
                    }
                )
        except Exception as e:
            self.error(f"[LIVE_STATUS] Error publishing live status: {e}")
    
    def _get_market_status_info(self) -> Dict[str, Any]:
        """Get market status information (open/closed, time until open)"""
        try:
            now_utc = self.get_synced_time()
            
            # Convert UTC to Prague timezone
            import pytz
            prague_tz = pytz.timezone('Europe/Prague')
            now_prague = now_utc.astimezone(prague_tz) if now_utc.tzinfo else prague_tz.localize(now_utc)
            
            # Check if it's weekend (Saturday or Sunday) - markets are closed
            weekday = now_prague.weekday()  # 0=Monday, 6=Sunday
            is_weekend = weekday >= 5  # Saturday (5) or Sunday (6)
            
            if is_weekend:
                # Markets are closed on weekends
                # Calculate time until Monday 09:00
                from datetime import timedelta
                # If Saturday (5), next Monday is in 2 days
                # If Sunday (6), next Monday is in 1 day
                days_until_monday = 2 if weekday == 5 else 1
                
                # Calculate time until Monday 09:00
                next_monday = now_prague.replace(hour=9, minute=0, second=0, microsecond=0)
                # Move to next Monday
                next_monday = next_monday + timedelta(days=days_until_monday)
                
                time_until_open_seconds = (next_monday - now_prague).total_seconds()
                hours = int(time_until_open_seconds // 3600)
                minutes = int((time_until_open_seconds % 3600) // 60)
                seconds = int(time_until_open_seconds % 60)
                time_until_open = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                
                return {
                    "status": "CLOSED",
                    "current_session": "CLOSED",
                    "next_session": "DAX",
                    "time_until_open": time_until_open,
                    "time_until_open_seconds": int(time_until_open_seconds),
                    "is_open": False,
                    "next_change_time": "09:00 (Monday)"
                }
            
            # Use time_manager if available (only on weekdays)
            if hasattr(self, 'time_manager') and self.time_manager:
                session_info = self.time_manager.get_session_info(now_prague)
                current_session = session_info.get('session', 'CLOSED')
                trading_active = session_info.get('trading_active', False)
                next_change = session_info.get('next_change', None)
                minutes_to_change = session_info.get('minutes_to_change', None)
                
                # Calculate time until open
                if trading_active:
                    status = "OPEN"
                    time_until_open = "Now"
                    time_until_open_seconds = 0
                    next_session = "CLOSED" if current_session == "DAX" else "DAX"  # Next will be opposite or closed
                else:
                    status = "CLOSED"
                    # Calculate time until next open
                    if next_change and minutes_to_change is not None:
                        time_until_open_seconds = minutes_to_change * 60
                        hours = int(time_until_open_seconds // 3600)
                        minutes = int((time_until_open_seconds % 3600) // 60)
                        seconds = int(time_until_open_seconds % 60)
                        if hours > 0:
                            time_until_open = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                        else:
                            time_until_open = f"{minutes:02d}:{seconds:02d}"
                        
                        # Determine next session
                        if current_session == "CLOSED":
                            # Check if next is DAX (09:00) or NASDAQ (15:30)
                            current_time_only = now_prague.time()
                            if current_time_only < dt_time(9, 0) or current_time_only >= dt_time(22, 0):
                                next_session = "DAX"
                            else:
                                next_session = "NASDAQ"
                        else:
                            next_session = "CLOSED"
                    else:
                        time_until_open = "N/A"
                        time_until_open_seconds = 0
                        next_session = "N/A"
                
                return {
                    "status": status,
                    "current_session": current_session,
                    "next_session": next_session,
                    "time_until_open": time_until_open,
                    "time_until_open_seconds": time_until_open_seconds,
                    "is_open": trading_active,
                    "next_change_time": next_change or "N/A"
                }
            else:
                # Fallback: use trading hours check
                dax_result = self._is_within_trading_hours("DAX") if hasattr(self, '_is_within_trading_hours') else (False, "unknown")
                nasdaq_result = self._is_within_trading_hours("NASDAQ") if hasattr(self, '_is_within_trading_hours') else (False, "unknown")
                dax_open = dax_result[0] if isinstance(dax_result, tuple) else dax_result
                nasdaq_open = nasdaq_result[0] if isinstance(nasdaq_result, tuple) else nasdaq_result
                
                if dax_open:
                    return {
                        "status": "OPEN",
                        "current_session": "DAX",
                        "next_session": "NASDAQ",
                        "time_until_open": "Now",
                        "time_until_open_seconds": 0,
                        "is_open": True,
                        "next_change_time": "15:30"
                    }
                elif nasdaq_open:
                    return {
                        "status": "OPEN",
                        "current_session": "NASDAQ",
                        "next_session": "CLOSED",
                        "time_until_open": "Now",
                        "time_until_open_seconds": 0,
                        "is_open": True,
                        "next_change_time": "22:00"
                    }
                else:
                    return {
                        "status": "CLOSED",
                        "current_session": "CLOSED",
                        "next_session": "DAX",
                        "time_until_open": "N/A",
                        "time_until_open_seconds": 0,
                        "is_open": False,
                        "next_change_time": "09:00"
                    }
        except Exception as e:
            self.error(f"[MARKET_STATUS] Error getting market status: {e}")
            return {
                "status": "UNKNOWN",
                "current_session": "UNKNOWN",
                "next_session": "N/A",
                "time_until_open": "N/A",
                "time_until_open_seconds": 0,
                "is_open": False,
                "next_change_time": "N/A"
            }

    # ---------------- helpers ----------------
    def _tick_age_minutes(self, raw_symbol: str) -> str:
        try:
            price = getattr(self.ctrader_client, "current_price", {}).get(raw_symbol)
            ts = price and price.get("timestamp")
            if not ts:
                return "no-tick"
            if not isinstance(ts, datetime):
                return "n/a"
            return f"{int((datetime.now(timezone.utc)-ts).total_seconds()//60)}m"
        except Exception:
            return "n/a"

    def _calculate_atr(self, bars: List[Dict[str, Any]], period: int = 14) -> float:
        """
        Calculate ATR using Wilder's smoothing method
        This matches most trading platforms including TradingView
        """
        if len(bars) < period + 1:
            return 0.0
        
        # Calculate True Range values
        trs = []
        for i in range(1, len(bars)):
            h = bars[i]["high"]
            l = bars[i]["low"]
            pc = bars[i-1]["close"]
            
            # True Range = max(high-low, |high-prev_close|, |low-prev_close|)
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)
        
        if len(trs) < period:
            # Not enough data, return simple average
            return sum(trs) / len(trs) if trs else 0.0
        
        # Initial ATR = Simple average of first 'period' TR values
        atr = sum(trs[:period]) / period
        
        # Apply Wilder's smoothing for remaining values
        # ATR = ((ATR_prev * (period-1)) + TR_current) / period
        for i in range(period, len(trs)):
            atr = (atr * (period - 1) + trs[i]) / period

        # Debug log for comparison with platform
        if hasattr(self, '_last_atr_log') and (datetime.now() - self._last_atr_log).seconds > 300:  # Every 5 min
            self._last_atr_log = datetime.now()
            # Get symbol from calling context if possible
            try:
                import inspect
                frame = inspect.currentframe().f_back
                symbol = frame.f_locals.get('alias', 'UNKNOWN')

                # Show recent TRs and calculation details
                recent_trs = trs[-5:] if len(trs) >= 5 else trs
                self.log(f"[ATR DEBUG] {symbol}: Period={period}, Bars={len(bars)}, TRs={len(trs)}")
                self.log(f"[ATR DEBUG] {symbol}: Recent TRs: {[round(tr, 2) for tr in recent_trs]}")
                self.log(f"[ATR DEBUG] {symbol}: Final ATR: {atr:.4f} (compare with platform)")

                # Show last bar details for verification
                if len(bars) >= 2:
                    last_bar = bars[-1]
                    prev_bar = bars[-2]
                    last_tr = trs[-1]
                    self.log(f"[ATR DEBUG] {symbol}: Last bar H:{last_bar['high']:.2f} L:{last_bar['low']:.2f} C:{last_bar['close']:.2f}")
                    self.log(f"[ATR DEBUG] {symbol}: Prev close:{prev_bar['close']:.2f}, TR:{last_tr:.4f}")
            except:
                pass
        elif not hasattr(self, '_last_atr_log'):
            self._last_atr_log = datetime.now()

        return atr

    def _test_atr_calculation(self, bars: List[Dict], symbol: str) -> float:
        """Test ATR with simple approach for verification"""
        try:
            if len(bars) < 15:
                return 0.0

            # Calculate TRs for last 14 periods
            trs = []
            for i in range(1, len(bars)):
                h, l, pc = bars[i]['high'], bars[i]['low'], bars[i-1]['close']
                tr = max(h - l, abs(h - pc), abs(l - pc))
                trs.append(tr)

            if len(trs) < 14:
                return 0.0

            # Simple average for comparison
            simple_atr = sum(trs[-14:]) / 14
            self.log(f"[ATR TEST] {symbol}: Simple 14-period average ATR: {simple_atr:.4f}")
            return simple_atr
        except:
            return 0.0

    def calculate_simple_pivots(self, bars: List[Dict[str, Any]]) -> Dict[str, float]:
        """Calculate pivots - WITH DEBUG"""
        if len(bars) < 100:
            self.log(f"[PIVOTS] Not enough bars: {len(bars)}")
            return {"pivot": 0.0, "r1": 0.0, "r2": 0.0, "s1": 0.0, "s2": 0.0}

        # Processing historical data for pivots
        first_bar = bars[0]
        last_bar = bars[-1]

        # Použít jednoduchý přístup - posledních 24 hodin
        # Pro M5: 288 barů = 24 hodin
        lookback = min(288, len(bars) - 20)  # Vynechat posledních 20 barů (aktuální session)
        
        if lookback > 50:
            session_bars = bars[-lookback:-20]
        else:
            session_bars = bars[:len(bars)//2]
        
        if not session_bars:
            session_bars = bars[-100:]
        
        # Vypočítat H/L/C
        h = max(b["high"] for b in session_bars)
        l = min(b["low"] for b in session_bars)
        c = session_bars[-1]["close"]
        
        # Classical pivots
        p = (h + l + c) / 3.0
        
        r1 = (2 * p) - l
        r2 = p + (h - l)
        s1 = (2 * p) - h
        s2 = p - (h - l)
        
        # Pivot calculations completed
        
        return {
            "pivot": round(p, 2),
            "r1": round(r1, 2),
            "r2": round(r2, 2),
            "s1": round(s1, 2),
            "s2": round(s2, 2),
        }
        
    def detect_simple_swings(self, bars: List[Dict[str, Any]]) -> Dict[str, Any]:
        if len(bars) < 5:
            return {"trend": "UNKNOWN", "quality": 0.0}
        closes = [b["close"] for b in bars[-10:]]
        trend = "UP" if closes[-1] >= closes[0] else "DOWN"
        impulse = (closes[-1] - closes[-2]) / (abs(closes[-2]) or 1.0)
        qual = max(0.0, min(100.0, 50.0 + 100.0 * impulse))
        return {"trend": trend, "quality": round(qual, 1)}

    # ADX (Wilder) with hysteresis per symbol
    def detect_simple_regime(self, bars: List[Dict[str, Any]], period: int = 14, key: str = "GLOBAL") -> Dict[str, Any]:
        if len(bars) <= period:
            return {"state": "INIT", "adx": 0.0, "r2": 0.0}

        highs  = [b["high"]  for b in bars]
        lows   = [b["low"]   for b in bars]
        closes = [b["close"] for b in bars]

        TR, plusDM, minusDM = [], [], []
        for i in range(1, len(bars)):
            up = highs[i] - highs[i-1]
            dn = lows[i-1] - lows[i]
            tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
            TR.append(tr)
            plusDM.append(up if (up > 0 and up > dn) else 0.0)
            minusDM.append(dn if (dn > 0 and dn > up) else 0.0)

        if len(TR) < period:
            return {"state": "INIT", "adx": 0.0, "r2": 0.0}

        def wilder_smooth(vals: List[float], p: int) -> List[float]:
            n = len(vals)
            if n == 0: return [0.0]
            if n < p:  return [sum(vals)/n]
            inv = 1.0 / p
            avg = sum(vals[:p]) * inv
            out = [avg]
            for v in vals[p:]:
                avg = avg - avg * inv + v * inv
                out.append(avg)
            return out

        trN  = wilder_smooth(TR, period)
        pdmN = wilder_smooth(plusDM, period)
        mdmN = wilder_smooth(minusDM, period)

        m = min(len(trN), len(pdmN), len(mdmN))
        trN, pdmN, mdmN = trN[:m], pdmN[:m], mdmN[:m]

        DXs = []
        for t, p, m_ in zip(trN, pdmN, mdmN):
            if t == 0.0:
                DXs.append(0.0); continue
            pdi = 100.0 * (p / t)
            mdi = 100.0 * (m_ / t)
            s = pdi + mdi
            DXs.append(0.0 if s == 0.0 else 100.0 * abs(pdi - mdi) / s)

        if len(DXs) >= period:
            adx = wilder_smooth(DXs, period)[-1]
        elif DXs:
            adx = sum(DXs) / len(DXs)
        else:
            adx = 0.0

        if not (adx == adx and adx != float("inf")):
            adx = 0.0
        adx = max(0.0, min(100.0, adx))

        # R^2 over last N closes
        N = max(10, period)
        if len(closes) >= N:
            ys = closes[-N:]
            xs = list(range(N))
            xm = sum(xs)/N; ym = sum(ys)/N
            ss_tot = sum((y-ym)**2 for y in ys) or 1e-9
            num = sum((x-xm)*(y-ym) for x, y in zip(xs, ys))
            den = sum((x-xm)**2 for x in xs) or 1e-9
            slope = num / den
            yhat = [ym + slope*(x-xm) for x in xs]
            ss_res = sum((y - h)**2 for y, h in zip(ys, yhat))
            r2 = 1.0 - (ss_res / ss_tot)
            r2 = float(max(0.0, min(1.0, r2)))
        else:
            r2 = 0.0

        lo, hi = self.adx_lo, self.adx_hi
        prev = self._last_regime_state_by_symbol.get(key, "RANGE")
        state = "TREND" if (adx >= hi or (prev == "TREND" and adx >= lo)) else "RANGE"
        self._last_regime_state_by_symbol[key] = state

        # Store full regime data including ADX for analytics
        self._last_regime_data_by_symbol[key] = {
            'state': state,
            'adx': adx,
            'r2': r2
        }

        # Add trend direction if in TREND regime
        trend_direction = None
        if state == "TREND" and len(closes) >= 10:
            # Simple trend direction based on recent price action
            recent_closes = closes[-10:]
            trend_slope = (recent_closes[-1] - recent_closes[0]) / len(recent_closes)
            trend_direction = "UP" if trend_slope > 0 else "DOWN"

        return {
            "state": state, 
            "adx": float(adx), 
            "r2": r2,
            "trend_direction": trend_direction
        }

    # ---------------- shutdown ----------------
    def terminate(self):
        self.log("Stopping Trading Assistant...")
        try:
            if self.ctrader_client:
                self.ctrader_client.stop()
        except Exception:
            pass
        self.log("Stopped.")
        
    def _precreate_entities(self):
        """Precreate all entities - COMPLETE VERSION"""

        # Auto-trading toggle switch - Set to OFF after restart for safety
        # NOTE: This must be a Home Assistant Helper (input_boolean), not an AppDaemon entity
        # Create it in HA: Settings → Devices & Services → Helpers → Toggle
        try:
            current_state = self.get_state("input_boolean.auto_trading_enabled")
            if current_state is not None:
                # Helper exists - just log, DON'T change its state!
                # Changing state from AppDaemon prevents HA UI from controlling it
                self.log(f"[AUTO-TRADING] Helper found, current state: {current_state}")
                self.log("[AUTO-TRADING] ⚠️ Auto-trading will start in current Helper state")
                self.log("[AUTO-TRADING] Use dashboard or Helpers to change it")
            else:
                # Helper doesn't exist - warn user
                self.log("[AUTO-TRADING] ⚠️ WARNING: input_boolean.auto_trading_enabled not found!")
                self.log("[AUTO-TRADING] Create it in HA: Settings → Devices & Services → Helpers → Toggle")
        except Exception as e:
            self.log(f"[AUTO-TRADING] Error checking toggle state: {e}")

        # Stav spojení
        self._safe_set_state(
            "binary_sensor.ctrader_connected",
            state="off",
            attributes={"friendly_name": "cTrader Connected"}
        )

        # Hlavní status systému
        self._safe_set_state(
            "sensor.trading_analysis_status",
            state="INITIALIZING",
            attributes={
                "friendly_name": "Trading Analysis Status",
                "last_update": datetime.now().isoformat()
            }
        )
        
        # Market status
        self._safe_set_state(
            "sensor.market_status",
            state="UNKNOWN",
            attributes={
                "friendly_name": "Market Status",
                "current_session": "UNKNOWN",
                "next_session": "N/A",
                "time_until_open": "N/A",
                "time_until_open_seconds": 0,
                "is_open": False,
                "next_change_time": "N/A",
                "last_update": datetime.now().isoformat()
            }
        )
        
        # Risk status
        self._safe_set_state(
            "sensor.trading_risk_status",
            state="INITIALIZING",
            attributes={
                "friendly_name": "Trading Risk Status",
                "can_trade": False,
                "open_positions": 0,
                "total_risk_pct": 0.0
            }
        )
        
        # Performance metrics
        self._safe_set_state(
            "sensor.trading_performance",
            state="0.0%",
            attributes={
                "friendly_name": "Trading Performance",
                "icon": "mdi:chart-line",
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "expectancy_czk": 0.0,
                "average_win_czk": 0.0,
                "average_loss_czk": 0.0,
                "sharpe_ratio": 0.0,
                "max_drawdown_czk": 0.0,
                "max_drawdown_pct": 0.0,
                "average_rrr": 0.0,
                "last_updated": datetime.now().isoformat()
            }
        )
        
        self._safe_set_state(
            "sensor.trading_win_rate",
            state="0.0",
            attributes={
                "friendly_name": "Win Rate",
                "icon": "mdi:percent",
                "unit_of_measurement": "%"
            }
        )
        
        self._safe_set_state(
            "sensor.trading_profit_factor",
            state="0.00",
            attributes={
                "friendly_name": "Profit Factor",
                "icon": "mdi:chart-timeline-variant"
            }
        )
        
        # System status
        self._safe_set_state(
            "sensor.trading_system_status",
            state="INITIALIZING",
            attributes={
                "friendly_name": "Trading System Status",
                "last_update": datetime.now().isoformat(),
                "symbols": {}
            }
        )
        
        self._safe_set_state(
            "sensor.trading_expectancy",
            state="0",
            attributes={
                "friendly_name": "Expectancy",
                "icon": "mdi:currency-czk",
                "unit_of_measurement": "CZK"
            }
        )
        
        # Pro každý alias vytvoř všechny entity
        for alias in self.alias_to_raw:
            a = alias.lower()
            pref = f"sensor.{a}_m1"
            
            # Trading status
            self._safe_set_state(
                f"sensor.{a}_trading_status",
                state="INITIALIZING",
                attributes={
                    "friendly_name": f"{alias} Trading Status",
                    "market_hours": False,
                    "has_data": False,
                    "bars": 0,
                    "signals_enabled": False,
                    "atr": 0
                }
            )
            
            # Regime - s hodnotami místo N/A
            self._safe_set_state(
                f"{pref}_regime_state", 
                state="INIT",
                attributes={
                    "adx": 0.0,
                    "r2": 0.0,
                    "friendly_name": f"{alias} Regime"
                }
            )
            
            self._safe_set_state(
                f"{pref}_adx", 
                state="0.0",
                attributes={
                    "friendly_name": f"{alias} ADX",
                    "unit_of_measurement": ""
                }
            )
            
            self._safe_set_state(
                f"{pref}_r2", 
                state="0.0",
                attributes={
                    "friendly_name": f"{alias} R²",
                    "unit_of_measurement": ""
                }
            )
            
            # Pivots - s číselnými hodnotami
            self._safe_set_state(f"{pref}_pivot_p", state="0.0")
            self._safe_set_state(f"{pref}_pivot_r1", state="0.0")
            self._safe_set_state(f"{pref}_pivot_r2", state="0.0")
            self._safe_set_state(f"{pref}_pivot_s1", state="0.0")
            self._safe_set_state(f"{pref}_pivot_s2", state="0.0")
            self._safe_set_state(f"{pref}_pivot_r", state="0.0")
            self._safe_set_state(f"{pref}_pivot_s", state="0.0")
            
            # Swings
            self._safe_set_state(
                f"{pref}_swing_trend", 
                state="UNKNOWN",
                attributes={"quality": 0.0}
            )
            self._safe_set_state(f"{pref}_swing_quality", state="0.0")
            
            # Live status entity
            self._safe_set_state(
                f"sensor.{a}_live_status",
                state="INITIALIZING",
                attributes={
                    "friendly_name": f"{alias} Live Status",
                    "last_bar_ago": "N/A",
                    "last_analysis_ago": "N/A",
                    "last_signal_check_ago": "N/A",
                    "last_signal_result": "No data",
                    "last_update": datetime.now().isoformat()
                }
            )
            
            # Signal entity
            self._safe_set_state(
                f"sensor.signal_{a}",
                state="⏳ WAITING",
                attributes={
                    "status": "INIT",
                    "confidence": "0%",
                    "quality": "0%",
                    "rr": 0,
                    "entry": 0.0,
                    "current": 0.0
                }
            )
            
            # OR Range
            self._safe_set_state(
                f"sensor.{a}_or_range",
                state="0.0",
                attributes={
                    "friendly_name": f"{alias} OR Range",
                    "unit_of_measurement": "pts"
                }
            )
        
        self.log("[INIT] All entities pre-created with default values")
    
    def _get_current_price(self, alias: str) -> Optional[float]:
        """Vrátí poslední bid pro alias (DE40/US100)."""
        if not self.ctrader_client:
            return None
        raw = self.alias_to_raw.get(alias, alias)
        tick = self.ctrader_client.current_price.get(raw)
        if not tick:
            return None
        try:
            return float(tick.get("bid"))
        except Exception:
            return None

    def _schedule_countdown_updates(self, ticket_entity: str, total_seconds: int):
        """Schedule periodic countdown updates every 30 seconds"""
        
        def update_countdown(remaining_seconds):
            """Update ticket with remaining time"""
            if remaining_seconds <= 0:
                return  # Ticket expired
                
            # Get current ticket state
            try:
                current_state = self.get_state(ticket_entity)
                if not current_state or current_state == "expired":
                    return  # Ticket no longer exists or expired
                
                # Get attributes
                attributes = self.get_state(ticket_entity, attribute="all")["attributes"]
                
                # Calculate time remaining
                minutes = remaining_seconds // 60
                seconds = remaining_seconds % 60
                
                # Get original ticket text and update countdown
                original_ticket = attributes.get("ticket", "")
                
                # Find and replace the countdown part
                lines = original_ticket.split('\n')
                updated_lines = []
                
                for line in lines:
                    if line.strip().startswith("Expires:"):
                        # Update countdown line
                        expires_time = line.split("(")[0].strip()  # Keep original time
                        updated_line = f"{expires_time} ({minutes:02d}:{seconds:02d} min)"
                        updated_lines.append(updated_line)
                    else:
                        updated_lines.append(line)
                
                # Update ticket with new countdown
                attributes["ticket"] = '\n'.join(updated_lines)
                
                self._safe_set_state(
                    ticket_entity,
                    state=current_state,
                    attributes=attributes
                )
                
                # Schedule next update (if not last)
                if remaining_seconds > 30:
                    self.run_in(
                        lambda _: update_countdown(remaining_seconds - 30),
                        30  # Next update in 30 seconds
                    )
                    
            except Exception as e:
                self.log(f"[COUNTDOWN] Error updating {ticket_entity}: {e}")
        
        # Start countdown updates
        self.run_in(
            lambda _: update_countdown(total_seconds - 30),
            30  # First update after 30 seconds
        )

    def _publish_trade_ticket(self, alias: str, position, signal):
        """Publish trade ticket - CLEAN TEXT VERSION"""
        
        import hashlib
        from datetime import datetime, timedelta
        
        # Vyčistit staré tikety pro tento symbol PŘED vytvořením nového
        self._cleanup_symbol_tickets(alias)
        
        direction = signal.signal_type.value if hasattr(signal, 'signal_type') else "UNKNOWN"
        
        # Vypočítat vzdálenosti
        sl_points = abs(signal.entry - signal.stop_loss)
        tp_points = abs(signal.take_profit - signal.entry)
        sl_pips = sl_points * 100  # FIXED: 1 point = 100 pips for DAX/NASDAQ
        tp_pips = tp_points * 100  # FIXED: 1 point = 100 pips for DAX/NASDAQ
        
        # RRR
        rrr = tp_points / sl_points if sl_points > 0 else 0
        
        # Unikátní ID - kratší
        signal_id = hashlib.md5(
            f"{alias}{signal.entry}{datetime.now()}".encode()
        ).hexdigest()[:4]
        
        ticket_entity = f"sensor.trade_ticket_{alias.lower()}_{signal_id}"
        
        # Jednoduchý textový formát s většími mezerami pro čitelnost
        ticket_text = f"""
        TRADE TICKET - {alias}
        ==============================
        
        DIRECTION: {direction}
        
        ENTRY:     {signal.entry:.1f}
        STOP LOSS: {signal.stop_loss:.1f}
                (-{sl_pips:.0f} pips)
        TAKE PROF: {signal.take_profit:.1f}
                (+{tp_pips:.0f} pips)
        
        ------------------------------
        
        POSITION:  {position.lots:.2f} lots
        RISK:      {position.risk_amount_czk:.0f} CZK
        RRR:       {rrr:.1f}:1
        
        ------------------------------
        Ticket ID: {signal_id}
        Expires:   10 minutes
        """
        
        # Formátovaný čas
        now = datetime.now()
        created_time = now.strftime("%H:%M:%S")
        expires_time = (now + timedelta(minutes=10)).strftime("%H:%M:%S")
        
        # Alebo ešte jednoduchšia verzia:
        simple_ticket = f"""{alias} {direction}

Entry: {signal.entry:.1f}
SL: {signal.stop_loss:.1f} (-{sl_pips:.0f} pips)
TP: {signal.take_profit:.1f} (+{tp_pips:.0f} pips)

Size: {position.lots:.2f} lots
Risk: {position.risk_amount_czk:.0f} CZK
RRR: {rrr:.1f}:1

Created: {created_time}
Expires: {expires_time} (10:00 min)"""
        
        # Vytvořit sensor s jednoduchým textem
        self._safe_set_state(
            ticket_entity,
            state="READY",
            attributes={
                "symbol": alias,
                "direction": direction,
                "lots": position.lots,
                "entry": signal.entry,
                "stop_loss": signal.stop_loss,
                "take_profit": signal.take_profit,
                "sl_pips": sl_pips,
                "tp_pips": tp_pips,
                "risk_czk": position.risk_amount_czk,
                "rrr": rrr,
                "ticket": simple_ticket,  # Použít jednodušší verzi
                "created_at": datetime.now().isoformat(),
                "expires_at": (datetime.now() + timedelta(minutes=10)).isoformat(),
                "icon": "mdi:ticket-confirmation"
            }
        )
        
        # Nastavit countdown updater (každých 30 sekund)
        self._schedule_countdown_updates(ticket_entity, 600)  # 10 minut = 600 sekund
        
        # Nastavit auto-expiraci
        self.run_in(
            lambda _: self._fully_expire_ticket(ticket_entity),
            600  # 10 minut
        )
        
        # LOG - také jednodušší
        self.log("----------------------------------------")
        self.log(f"NEW TICKET: {alias} {direction}")
        self.log(f"Entry: {signal.entry:.1f} | SL: {signal.stop_loss:.1f} | TP: {signal.take_profit:.1f}")
        self.log(f"Size: {position.lots:.2f} lots | Risk: {position.risk_amount_czk:.0f} CZK")
        self.log(f"ID: {signal_id} | Expires in 10 min")
        self.log("----------------------------------------")
        
    def force_test_signal_dax(self, entity, attribute, old, new, kwargs):
        """Generate test signal for DAX on button press"""
        self._generate_test_signal("DAX")
        self._safe_set_state("input_boolean.force_signal_dax", state="off")
        
    def force_test_signal_nasdaq(self, entity, attribute, old, new, kwargs):
        """Generate test signal for NASDAQ on button press"""
        self._generate_test_signal("NASDAQ")
        self._safe_set_state("input_boolean.force_signal_nasdaq", state="off")

    def _register_kill_switch_listener(self, kwargs=None):
        """Register kill switch listener after order_executor is initialized"""
        try:
            if hasattr(self, 'order_executor') and self.order_executor:
                self.listen_state(self._handle_kill_switch, "input_boolean.trading_kill_switch")
                self.log("[KILL_SWITCH] ✅ Kill switch listener registered")
            else:
                self.log("[KILL_SWITCH] ⚠️ Order executor not yet available, will retry")
                self.run_in(self._register_kill_switch_listener, 5)
        except Exception as e:
            self.error(f"[KILL_SWITCH] ❌ Failed to register listener: {e}")
    
    def _handle_kill_switch(self, entity, attribute, old, new, kwargs):
        """
        CRITICAL: Handle kill switch activation - close all positions immediately
        
        This is called when input_boolean.trading_kill_switch is turned on
        """
        if new == 'on':
            self.log("[KILL_SWITCH] 🛑 KILL SWITCH ACTIVATED - Closing all positions immediately!")
            
            try:
                if hasattr(self, 'order_executor') and self.order_executor:
                    if hasattr(self, 'risk_manager') and self.risk_manager:
                        positions = self.risk_manager.open_positions
                        if positions:
                            self.log(f"[KILL_SWITCH] Closing {len(positions)} positions...")
                            result = self.order_executor.position_closer.close_all_positions(positions)
                            self.log(f"[KILL_SWITCH] ✅ Closed {result.get('closed', 0)}/{result.get('total', 0)} positions")
                        else:
                            self.log("[KILL_SWITCH] No positions to close")
                    else:
                        self.log("[KILL_SWITCH] ⚠️ Risk manager not available")
                else:
                    self.log("[KILL_SWITCH] ⚠️ Order executor not available")
            except Exception as e:
                self.error(f"[KILL_SWITCH] ❌ Error closing positions: {e}")
                import traceback
                self.error(traceback.format_exc())
    
    def toggle_auto_trading(self, entity, attribute, old, new, kwargs):
        """Toggle auto-trading execution on/off"""
        try:
            # Check if order_executor exists (not auto_trading_enabled!)
            if not self.order_executor:
                self.log("[AUTO-TRADING] ⚠️ Order executor not initialized - ignoring toggle change")
                return

            is_enabled = (new == "on")

            # Update BOTH the internal flag and the order executor
            self.auto_trading_enabled = is_enabled
            self.order_executor.enabled = is_enabled

            # Note: We don't need to call set_state() - the Helper entity is managed by HA
            # Just update the icon if needed (optional)
            # For HA Helpers, attributes like icon are set in the Helper configuration, not here

            if is_enabled:
                self.log("[AUTO-TRADING] ✅ Trade execution ENABLED - signals will be executed automatically")
                self.notify("Auto-trading ZAPNUT ✅ - obchody budou automaticky prováděny", "Auto Trading")

                # Discard previously rejected signals (do NOT execute old signals)
                try:
                    self.log("[AUTO-TRADING] 🗑️ Discarding old signals generated while auto-trading was OFF...")
                    result = self.order_executor.reevaluate_rejected_signals()
                    if result and result.get('discarded', 0) > 0:
                        self.notify(f"🗑️ Zahozeno {result['discarded']} starých signálů - pouze NOVÉ signály budou exekuovány", "Auto Trading")
                except Exception as e:
                    self.error(f"[AUTO-TRADING] Error discarding signals: {e}")
            else:
                self.log("[AUTO-TRADING] ⏸️ Trade execution DISABLED - signals will be generated but NOT executed")
                self.notify("Auto-trading VYPNUT ⏸️ - analýzy běží, obchody nebudou prováděny", "Auto Trading")

        except Exception as e:
            self.error(f"[AUTO-TRADING] Error toggling auto-trading: {e}")
            import traceback
            self.error(traceback.format_exc())

    def clear_all_signals(self, entity, attribute, old, new, kwargs):
        """Clear all signals and tickets + RESET RISK MANAGER"""
        try:
            # Clear signal manager
            self.signal_manager.active_signals.clear()
            
            # DŮLEŽITÉ: Clear risk manager kompletně
            self.risk_manager.open_positions.clear()
            self.log("[CLEAR] Risk manager positions cleared")
            
            # Získat všechny entity
            all_states = self.get_state()
            tickets_cleared = 0
            
            for entity_id in all_states:
                if 'trade_ticket_' in entity_id:
                    current_state = self.get_state(entity_id)
                    if current_state in ["READY", "PENDING"]:
                        self._safe_set_state(entity_id, state="CLEARED", attributes={})
                        tickets_cleared += 1
            
            # Clear signal entities
            for alias in self.alias_to_raw:
                a = alias.lower()
                self._safe_set_state(f"sensor.signal_{a}", state="WAITING", 
                            attributes={"status": "CLEARED"})
            
            # Clear signal queue
            if hasattr(self, 'signal_queue'):
                self.signal_queue.clear()
            
            self.log(f"[CLEAR] Total cleared: {tickets_cleared} tickets, risk manager reset")
            self.notify(f"Vymazáno: {tickets_cleared} tiketů, risk reset")
            
        except Exception as e:
            self.error(f"[CLEAR] Error: {e}")
        finally:
            self._safe_set_state("input_boolean.clear_signals", state="off")
        
        def notify(self, message, title="Trading Assistant"):
            """Send notification to UI"""
            from datetime import datetime
            self.call_service("persistent_notification/create",
                            title=title,
                            message=message,
                            notification_id=f"trading_{datetime.now().timestamp()}")
         
    def _generate_test_signal(self, alias: str):
        """Generate test signal using REAL signal detection logic"""
        from types import SimpleNamespace
        
        bars = list(self.market_data.get(alias, []))

        if len(bars) < 20:  # Reálná edge detection potřebuje více dat
            self.log(f"[TEST] Not enough bars for real signal detection: {len(bars)}/20")
            self.notify(f"Nedostatek dat pro reálnou detekci ({len(bars)}/20 barů)")
            return
        
        risk_status = self.risk_manager.get_risk_status()
        if not risk_status.can_trade:
            self.log(f"[TEST] Cannot generate - risk limits: {', '.join(risk_status.warnings)}")
            self.notify(f"Nelze generovat - {risk_status.warnings[0] if risk_status.warnings else 'risk limit'}")
            return

        # === POUŽÍT REÁLNOU EDGE DETECTION LOGIKU ===
        try:
            # Získat všechna potřebná data pro reálnou detekci
            regime_state = {
                'current_regime': self._last_regime_state_by_symbol.get(alias, 'TREND'),
                'regime_strength': 0.7,  # Default
                'trend_direction': 'UP'   # Default
            }

            pivot_levels = self.current_pivots.get(alias, {})

            # Získat swing state ze swing engine
            swing_state = {}
            if hasattr(self, 'swing_engine'):
                try:
                    swing_state = self.swing_engine.get_swing_state(alias) or {}
                except:
                    swing_state = {}

            # Získat mikrostrukturu pokud je k dispozici
            micro_data = {}
            if hasattr(self, 'microstructure') and len(bars) >= 14:
                try:
                    micro_data = self.microstructure.get_microstructure_summary(alias, bars) or {}
                except:
                    micro_data = {}

            # VOLAT REÁLNOU EDGE DETECTION! 🎯
            self.log(f"[TEST] Calling real edge detection for {alias}...")
            detected_signals = self.edge_detector.detect_signals(
                bars=bars,
                regime_state=regime_state,
                pivot_levels=pivot_levels,
                swing_state=swing_state,
                microstructure_data=micro_data
            )

            if detected_signals:
                # Použít první/nejlepší signál
                real_signal = detected_signals[0]
                self.log(f"[TEST] Real signal detected! Quality: {real_signal.signal_quality:.1f}%, "
                        f"Confidence: {real_signal.confidence:.1f}%, Patterns: {real_signal.patterns}")

                # Převést reálný signál na formát pro auto-execution
                test_signal = {
                    "symbol": alias,
                    "signal_type": real_signal.signal_type.value,
                    "entry": real_signal.entry,
                    "stop_loss": real_signal.stop_loss,
                    "take_profit": real_signal.take_profit,
                    "risk_reward": real_signal.risk_reward_ratio,
                    "confidence": real_signal.confidence,
                    "signal_quality": real_signal.signal_quality,
                    "patterns": real_signal.patterns,
                    "atr": real_signal.atr,
                    "timestamp": real_signal.timestamp
                }

            else:
                self.log(f"[TEST] No real signals detected by edge detector for {alias}")
                self.notify(f"Žádný signál detekován reálnou logikou pro {alias}")
                return

        except Exception as e:
            self.log(f"[TEST] Error in real signal detection: {e}")
            self.log(f"[TEST] Falling back to simple signal generation...")

            # FALLBACK na současnou jednoduchou logiku
            current_price = bars[-1]['close']
            atr = self.current_atr.get(alias, 10)
            direction = 'BUY' if bars[-1]['close'] > bars[-2]['close'] else 'SELL'

            # [Zde by byla stará logika pro fallback]
            self.notify(f"Fallback signál pro {alias} - reálná detekce selhala")
            return

        # === POKRAČOVAT S REÁLNÝM SIGNÁLEM ===
        # Použít position sizing pro reálný signál
        position = self.risk_manager.calculate_position_size(
            symbol=alias,
            entry=test_signal['entry'],
            stop_loss=test_signal['stop_loss'],
            take_profit=test_signal['take_profit'],
            regime=regime_state.get('current_regime', 'TREND'),
            signal_quality=test_signal['signal_quality'],
            atr=test_signal.get('atr', 0)
        )

        if not position:
            self.log(f"[TEST] Position sizing failed for real signal on {alias}")
            self.notify(f"Nelze vypočítat pozici pro reálný signál {alias}")
            return

        # Aktualizovat signál s finálními hodnotami z risk manageru
        test_signal.update({
            'stop_loss': position.stop_loss,
            'take_profit': position.take_profit,
            'position_size': position.lots,
            'risk_amount': position.risk_amount_czk,
            'margin_required': position.margin_required_czk
        })

        # Přidat signál do manageru
        self.signal_manager.add_signal(test_signal, test_signal['entry'], test_signal.get('atr', 0))

        # Vytvořit ticket pro Home Assistant
        test_sig = SimpleNamespace(
            entry=test_signal['entry'],
            stop_loss=test_signal['stop_loss'],
            take_profit=test_signal['take_profit'],
            signal_type=SimpleNamespace(value=test_signal['signal_type'])
        )

        # Publikovat trade ticket
        self._publish_trade_ticket(alias, position, test_sig)

        self.log(f"[TEST REAL SIGNAL] {alias} {test_signal['signal_type']}: {position.lots:.2f} lots")
        self.log(f"  Patterns: {test_signal['patterns']}")
        self.log(f"  Quality: {test_signal['signal_quality']:.1f}%, Confidence: {test_signal['confidence']:.1f}%")
        self.log(f"  Risk: {position.risk_amount_czk:.0f} CZK, RRR: {test_signal['risk_reward']:.2f}")

        # AUTO-EXECUTE if auto-trading is enabled
        self.log(f"[TEST] Attempting auto-execution for real signal...")
        self._try_auto_execute_signal(test_signal, alias)
        return  # Konec funkce

        # === STARÝ KÓD PO TOMTO BODĚ SE UŽ NEPOUŽIJE ===
        symbol_spec = self.risk_manager._get_symbol_spec(alias)
        
        # Získat limity SL z konfigurace
        min_sl_points = symbol_spec.get('min_sl_points', 150.0)
        max_sl_points = symbol_spec.get('max_sl_points', 400.0)
        
        # Vypočítat základní SL vzdálenost (jako v edges.py)
        if atr < 30:
            base_sl = 150  # Low volatility
        elif atr < 50:
            base_sl = 200  # Medium volatility
        elif atr < 80:
            base_sl = 250  # Higher volatility
        else:
            base_sl = 300  # High volatility
        
        # Upravit pro režim trhu
        current_regime = self._last_regime_state_by_symbol.get(alias, 'TREND')
        if current_regime == 'TREND':
            sl_distance = base_sl * 1.2
        elif current_regime == 'RANGE':
            sl_distance = base_sl * 0.8
        else:
            sl_distance = base_sl
        
        # Upravit pro symbol (z konfigurace)
        test_config = self.args.get('test_signals', {})
        if alias == 'DAX':
            multiplier = test_config.get('dax_sl_multiplier', 0.9)
            sl_distance = sl_distance * multiplier
        elif alias == 'NASDAQ':
            multiplier = test_config.get('nasdaq_sl_multiplier', 1.0)
            sl_distance = sl_distance * multiplier
        
        # Aplikovat limity
        sl_distance = max(min_sl_points, min(sl_distance, max_sl_points))
        
        # Vypočítat SL/TP ceny (z konfigurace)
        rrr_ratio = test_config.get('rrr_ratio', 2.0)
        if direction == 'BUY':
            test_sl = current_price - sl_distance
            test_tp = current_price + (sl_distance * rrr_ratio)
        else:  # SELL
            test_sl = current_price + sl_distance
            test_tp = current_price - (sl_distance * rrr_ratio)
        
        # === POUŽÍT RISK MANAGER PRO POSITION SIZING ===
        
        position = self.risk_manager.calculate_position_size(
            symbol=alias,
            entry=current_price,
            stop_loss=test_sl,
            take_profit=test_tp,
            regime=current_regime,
            signal_quality=test_config.get('default_quality', 75),
            atr=atr
        )
        
        if not position:
            self.log(f"[TEST] Position sizing failed for {alias}")
            self.notify(f"Nelze vypočítat pozici pro {alias}")
            return
        
        # Risk manager již upravil SL/TP pokud bylo potřeba
        # Použít finální hodnoty z position objektu
        test_sl = position.stop_loss
        test_tp = position.take_profit
        
        # Vytvořit test signál
        test_signal = {
            "symbol": alias,
            "signal_type": direction,
            "entry": current_price,
            "stop_loss": test_sl,
            "take_profit": test_tp,
            "risk_reward": abs(test_tp - current_price) / abs(current_price - test_sl),
            "confidence": test_config.get('default_confidence', 75),
            "signal_quality": test_config.get('default_quality', 75),
            "patterns": ["TEST_SIGNAL"],
            "position_size": position.lots,
            "risk_amount": position.risk_amount_czk,
            "margin_required": position.margin_required_czk,
            "breakeven": position.breakeven_points
        }
        
        # Přidat signál do manageru
        self.signal_manager.add_signal(test_signal, current_price, atr)
        
        # Vytvořit SimpleNamespace pro ticket
        test_sig = SimpleNamespace(
            entry=current_price,
            stop_loss=test_sl,
            take_profit=test_tp,
            signal_type=SimpleNamespace(value=direction)
        )
        
        # Publikovat trade ticket
        self._publish_trade_ticket(alias, position, test_sig)
        
        # Přidat pozici do risk manageru (pro tracking)
        self.risk_manager.add_position(position)
        
        # Log výsledek
        sl_distance = abs(current_price - test_sl)
        tp_distance = abs(test_tp - current_price)
        
        self.log(f"[TEST SIGNAL] {alias} {direction}: {position.lots:.2f} lots")
        self.log(f"  Entry: {current_price:.1f}, SL: {test_sl:.1f} (-{sl_distance:.1f}), TP: {test_tp:.1f} (+{tp_distance:.1f})")
        self.log(f"  Risk: {position.risk_amount_czk:.0f} CZK ({position.risk_percent:.1f}%), RR: {test_signal['risk_reward']:.2f}")
        
        # Notifikace
        self.notify(f"Test signál: {alias} {direction}\n"
                    f"Velikost: {position.lots:.2f} lots\n"
                    f"Risk: {position.risk_amount_czk:.0f} CZK")
        
        # AUTO-EXECUTE TEST SIGNAL if auto-trading is enabled
        self.log(f"[TEST] Attempting auto-execution for {alias} signal...")
        self._try_auto_execute_signal(test_signal, alias)
        
    def diagnose_ctrader(self, _):
        """Diagnostika cTrader připojení"""
        self.log("[DIAG] === cTrader Diagnostics ===")
        self.log(f"[DIAG] Is connected: {self.ctrader_client.is_connected()}")
        self.log(f"[DIAG] Has WS: {hasattr(self.ctrader_client, 'ws')}")
        
        # Zkusit manuálně zavolat connect pokud není připojeno
        if not self.ctrader_client.is_connected():
            self.log("[DIAG] Attempting manual reconnect...")
            try:
                self.ctrader_client._connect()  # nebo jakákoliv connect metoda
            except Exception as e:
                self.log(f"[DIAG] Reconnect failed: {e}")
    
    def diagnose_trading(self, _):
        """Diagnostika proč se negenerují obchody"""
        self.log("=" * 60)
        self.log("[DIAG] === Trading Diagnostics ===")
        self.log("=" * 60)
        
        # 1. Auto-trading toggle state
        try:
            toggle_state = self.get_state("input_boolean.auto_trading_enabled")
            self.log(f"[DIAG] 1. Auto-trading toggle: {toggle_state}")
            if toggle_state != "on":
                self.log(f"[DIAG]    ⚠️ Toggle is OFF - obchody se nebudou provádět!")
        except Exception as e:
            self.log(f"[DIAG]    ❌ Error reading toggle: {e}")
        
        # 2. Auto-trading enabled state
        self.log(f"[DIAG] 2. auto_trading_enabled: {self.auto_trading_enabled}")
        if not self.auto_trading_enabled:
            self.log(f"[DIAG]    ⚠️ Auto-trading is DISABLED in code!")
        
        # 3. Order executor state
        if self.order_executor:
            self.log(f"[DIAG] 3. Order executor enabled: {self.order_executor.enabled}")
            if not self.order_executor.enabled:
                self.log(f"[DIAG]    ⚠️ Order executor is DISABLED!")
            
            # Check rejected signals
            rejected_count = len(self.order_executor.rejected_signals) if hasattr(self.order_executor, 'rejected_signals') else 0
            self.log(f"[DIAG] 4. Rejected signals (waiting): {rejected_count}")
        else:
            self.log(f"[DIAG] 3. Order executor: ❌ NOT INITIALIZED")
        
        # 5. Signal detection status for each symbol
        self.log(f"[DIAG] 5. Signal detection status:")
        for alias in ['DAX', 'NASDAQ']:
            last_check = self._last_signal_check_time.get(alias)
            last_result = self._last_signal_check_result.get(alias, "No check yet")
            if last_check:
                time_since = (datetime.now(timezone.utc) - last_check).total_seconds() / 60
                self.log(f"[DIAG]    {alias}: Last check {time_since:.1f} min ago - {last_result}")
            else:
                self.log(f"[DIAG]    {alias}: No signal check yet")
        
        # 6. Risk manager status
        if hasattr(self, 'risk_manager') and self.risk_manager:
            risk_status = self.risk_manager.get_risk_status()
            self.log(f"[DIAG] 6. Risk manager:")
            self.log(f"[DIAG]    Can trade: {risk_status.can_trade}")
            if risk_status.warnings:
                self.log(f"[DIAG]    ⚠️ Warnings: {', '.join(risk_status.warnings)}")
            self.log(f"[DIAG]    Open positions: {len(self.risk_manager.open_positions)}")
            self.log(f"[DIAG]    Max positions: {self.risk_manager.max_positions}")
        
        # 7. Regime state
        self.log(f"[DIAG] 7. Current regime state:")
        for alias in ['DAX', 'NASDAQ']:
            regime = self._last_regime_state_by_symbol.get(alias, 'UNKNOWN')
            self.log(f"[DIAG]    {alias}: {regime}")
        
        # 8. Pattern detection hints
        self.log(f"[DIAG] 8. Pattern detection:")
        self.log(f"[DIAG]    Edge detector initialized: {hasattr(self, 'edge') and self.edge is not None}")
        if hasattr(self, 'edge') and self.edge:
            self.log(f"[DIAG]    Min bars between signals: {self.edge.min_bars_between_signals}")
            self.log(f"[DIAG]    Last signal bar index: {self.edge._last_signal_bar_index}")
        
        self.log("=" * 60)
        self.log("[DIAG] === End Diagnostics ===")
        self.log("=" * 60)
                
    def _count_active_tickets(self, alias: str) -> int:
        """Spočítat aktivní tikety pro symbol - OPRAVENÁ PRO APPDAEMON"""
        try:
            all_states = self.get_state()  # Získat všechny entity
            count = 0
            
            for entity_id in all_states:
                if f'trade_ticket_{alias.lower()}_' in entity_id:
                    if self.get_state(entity_id) == "READY":
                        count += 1
            
            return count
        except Exception as e:
            self.error(f"[COUNT] Error counting tickets: {e}")
            return 0

    def _save_to_signal_queue(self, alias: str, signal):
        """Uložit signál do fronty pro pozdější použití"""
        if not hasattr(self, 'signal_queue'):
            self.signal_queue = {}
        
        if alias not in self.signal_queue:
            self.signal_queue[alias] = []
        
        self.signal_queue[alias].append({
            'signal': signal,
            'timestamp': datetime.now(),
            'expires': datetime.now() + timedelta(minutes=15)
        })
        
        # Omezit frontu na 5 signálů
        self.signal_queue[alias] = self.signal_queue[alias][-5:]
        
        self.log(f"[QUEUE] Saved signal to queue, total queued: {len(self.signal_queue[alias])}")

    def _expire_ticket(self, ticket_entity: str):
        """Automaticky expirovat starý tiket A VYČISTIT Z RISK MANAGERU"""
        current_state = self.get_state(ticket_entity)
        if current_state == "READY":
            # Získat symbol z tiketu
            ticket_attrs = self.get_state(ticket_entity, attribute="all")
            if ticket_attrs and ticket_attrs.get("attributes"):
                symbol = ticket_attrs["attributes"].get("symbol")
                entry_price = ticket_attrs["attributes"].get("entry")
                
                # Odstranit odpovídající pozici z risk manageru
                if symbol and hasattr(self, 'risk_manager'):
                    original_count = len(self.risk_manager.open_positions)
                    # Filtrovat pozice - ponechat jen ty, které neodpovídají
                    self.risk_manager.open_positions = [
                        pos for pos in self.risk_manager.open_positions 
                        if not (pos.symbol == symbol and abs(pos.entry_price - entry_price) < 0.1)
                    ]
                    removed = original_count - len(self.risk_manager.open_positions)
                    if removed > 0:
                        self.log(f"[EXPIRE] Removed {removed} position(s) for {symbol} from risk manager")
            
            # Změnit stav tiketu
            self._safe_set_state(ticket_entity, state="EXPIRED", attributes={
                "reason": "timeout",
                "expired_at": datetime.now().isoformat()
            })
            self.log(f"[TICKET] Auto-expired: {ticket_entity}")
            
    def _cleanup_on_startup(self):
        """Vyčistit VŠECHNY staré tikety a signály při startu - COMPLETE VERSION"""
        try:
            # Set auto trading toggle based on config value
            auto_trading_config = self.args.get('auto_trading', {}).get('enabled', False)
            initial_state = "on" if auto_trading_config else "off"
            self.log(f"[CLEANUP] Setting auto trading toggle to {initial_state.upper()} based on config...")
            try:
                self._safe_set_state("input_boolean.auto_trading_enabled", state=initial_state)
                self.log(f"[CLEANUP] ✅ Auto trading toggle set to {initial_state.upper()} (config value: {auto_trading_config})")
            except Exception as e:
                self.log(f"[CLEANUP] ⚠️ Failed to reset auto trading toggle: {e}")

            all_states = self.get_state()
            if not all_states:
                self.log("[CLEANUP] No entities found")
                return

            tickets_removed = 0
            signals_removed = 0
            entities_to_remove = []
            
            for entity_id in all_states:
                # Odstranit VŠECHNY trade tikety
                if 'trade_ticket_' in entity_id:
                    entities_to_remove.append(entity_id)
                    tickets_removed += 1
                
                # Odstranit staré signal entity (ne hlavní)
                elif entity_id.startswith('sensor.signal_'):
                    # Ponechat pouze hlavní signal entity pro každý symbol
                    keep_entities = [
                        'sensor.signal_dax',
                        'sensor.signal_nasdaq', 
                        'sensor.signal_dax_headline',
                        'sensor.signal_nasdaq_headline'
                    ]
                    if entity_id not in keep_entities:
                        entities_to_remove.append(entity_id)
                        signals_removed += 1
            
            # Odstranit entity
            for entity_id in entities_to_remove:
                try:
                    # AppDaemon má omezení s remove_entity, použít set_state s unavailable
                    self._safe_set_state(entity_id, state="unavailable", attributes={})
                except:
                    pass
            
            # Reset hlavních signal entity
            for alias in self.alias_to_raw:
                alias_lower = alias.lower()
                
                # Hlavní signal entity
                self._safe_set_state(
                    f"sensor.signal_{alias_lower}",
                    state="⏳ WAITING",
                    attributes={
                        "status": "INIT",
                        "confidence": "0%",
                        "quality": "0%",
                        "rr": 0,
                        "entry": 0.0,
                        "current": 0.0,
                        "icon": "mdi:bell-off"
                    }
                )
                
                # Headline entity (pokud používáte)
                self._safe_set_state(
                    f"sensor.signal_{alias_lower}_headline",
                    state="NO SIGNAL",
                    attributes={
                        "status": "WAITING",
                        "last_signal": None,
                        "icon": "mdi:bell-sleep"
                    }
                )
            
            # Clear všechny managery
            if hasattr(self, 'risk_manager'):
                self.risk_manager.open_positions.clear()
                self.risk_manager.daily_pnl = 0
                
            if hasattr(self, 'signal_manager'):
                self.signal_manager.active_signals.clear()
                self.signal_manager.signal_history.clear()
                
            if hasattr(self, 'signal_queue'):
                self.signal_queue.clear()
            
            # Reset tracking proměnných
            self._last_signal_info = {}  # Updated to use enhanced signal tracking
            self._last_insufficient_data_log = {}
            self._last_no_signal_log = {}
            self._last_analysis_log = {}
            self._orb_triggered = {}
            
            self.log(f"[CLEANUP] Startup cleanup: {tickets_removed} tickets, {signals_removed} signals removed")
            
        except Exception as e:
            self.error(f"[CLEANUP] Startup cleanup error: {e}")
            self.error(traceback.format_exc())
            
    def clear_dax_signals(self, entity, attribute, old, new, kwargs):
        """Clear pouze DAX signály"""
        self._clear_symbol_signals("DAX")
        self._safe_set_state("input_boolean.clear_dax_signals", state="off")
    
    def clear_nasdaq_signals(self, entity, attribute, old, new, kwargs):
        """Clear pouze NASDAQ signály"""
        self._clear_symbol_signals("NASDAQ")
        self._safe_set_state("input_boolean.clear_nasdaq_signals", state="off")
    
    def _clear_symbol_signals(self, symbol: str):
        """Clear signály pro konkrétní symbol + VYČISTIT Z RISK MANAGERU"""
        all_states = self.get_state()
        cleared = 0
        
        # Odstranit pozice pro tento symbol z risk manageru
        if hasattr(self, 'risk_manager'):
            original_count = len(self.risk_manager.open_positions)
            self.risk_manager.open_positions = [
                pos for pos in self.risk_manager.open_positions 
                if pos.symbol != symbol
            ]
            removed = original_count - len(self.risk_manager.open_positions)
            if removed > 0:
                self.log(f"[CLEAR] Removed {removed} {symbol} position(s) from risk manager")
        
        # Clear tikety
        for entity_id in all_states:
            if f'trade_ticket_{symbol.lower()}_' in entity_id:
                self._safe_set_state(entity_id, state="CLEARED", attributes={})
                cleared += 1
        
        # Clear signal entity
        self._safe_set_state(f"sensor.signal_{symbol.lower()}", state="WAITING", 
                      attributes={"status": "CLEARED"})
        
        self.log(f"[CLEAR] Cleared {cleared} {symbol} tickets")
        self.notify(f"Smazáno {cleared} {symbol} tiketů")
        
    def update_history_cache(self, kwargs):
        """Pravidelná aktualizace cache historických dat"""
        try:
            # Kontrola připojení
            if not self.ctrader_client or not self.ctrader_client.is_connected():
                self.log("[CACHE] Skip update - cTrader not connected")
                return
            
            self.log("[CACHE] Starting historical data cache update")
            
            # Pro každý symbol vytvořit update request
            for alias, raw_symbol in self.alias_to_raw.items():
                try:
                    # Zkontrolovat stáří současných dat
                    current_bars = list(self.market_data.get(alias, []))
                    
                    if current_bars:
                        # Máme data - zkontrolovat stáří
                        last_bar = current_bars[-1]
                        if 'timestamp' in last_bar:
                            # Neaktualizovat pokud máme čerstvá data (< 10 minut)
                            try:
                                # Import ensure_datetime function for robust timestamp parsing
                                from .microstructure_lite import ensure_datetime
                                last_time = ensure_datetime(last_bar['timestamp'])
                                age_minutes = (datetime.now(timezone.utc) - last_time).total_seconds() / 60
                            except Exception as e:
                                self.log(f"[CACHE] Error parsing timestamp for {alias}: {e}")
                                # If timestamp parsing fails, force update
                                age_minutes = 999
                            
                            if age_minutes < 10:
                                self.log(f"[CACHE] {alias} data is fresh ({age_minutes:.1f} min), skipping")
                                continue
                    
                    # Uložit současná data do cache
                    cache_dir = self.args.get('history_cache_dir', './cache')
                    os.makedirs(cache_dir, exist_ok=True)
                    
                    cache_file = os.path.join(cache_dir, f"{raw_symbol}_M5.jsonl")
                    
                    # Získat poslední data z cTrader clienta
                    if hasattr(self.ctrader_client, 'bars'):
                        client_bars = list(self.ctrader_client.bars.get(raw_symbol, []))
                        
                        if client_bars and len(client_bars) > 50:
                            # Uložit do souboru
                            with open(cache_file, 'w') as f:
                                for bar in client_bars:
                                    f.write(json.dumps(bar) + '\n')
                            
                            self.log(f"[CACHE] Saved {len(client_bars)} bars for {alias} to {cache_file}")
                            
                            # Aktualizovat i market_data pokud máme více dat
                            if len(client_bars) > len(current_bars):
                                self.market_data[alias] = deque(client_bars, maxlen=5000)
                                self.log(f"[CACHE] Updated market_data for {alias} with {len(client_bars)} bars")
                        else:
                            self.log(f"[CACHE] Insufficient bars for {alias} ({len(client_bars)}), skipping")
                    else:
                        self.log(f"[CACHE] No bars structure in ctrader_client")
                        
                except Exception as e:
                    self.log(f"[CACHE] Failed to update {alias}: {e}")
                    continue
            
            # Vyčistit staré cache soubory (starší než 7 dní)
            try:
                cache_dir = self.args.get('history_cache_dir', './cache')
                if os.path.exists(cache_dir):
                    now = datetime.now()
                    for filename in os.listdir(cache_dir):
                        filepath = os.path.join(cache_dir, filename)
                        if filename.endswith('.jsonl'):
                            file_age = datetime.fromtimestamp(os.path.getmtime(filepath))
                            if (now - file_age).days > 7:
                                os.remove(filepath)
                                self.log(f"[CACHE] Removed old cache file: {filename}")
            except Exception as e:
                self.error(f"[CACHE] Cleanup error: {e}")
            
            self.log("[CACHE] Update complete")
            
            # Volitelně: vynutit garbage collection po velkých operacích
            import gc
            gc.collect()
            
        except Exception as e:
            self.error(f"[CACHE] Update failed: {e}")
            self.error(traceback.format_exc())
            
    def _is_within_trading_hours(self, alias: str) -> tuple:
        """
        Kontrola zda jsme v obchodních hodinách
        
        Kontroluje:
        1. Zda není svátek (market_holidays)
        2. Zda není early close den (early_close_days)
        3. Zda jsme v rámci denních obchodních hodin
        
        Returns:
            tuple: (is_open: bool, reason: str)
                - (True, "open") - trh je otevřený
                - (False, "holiday") - zavřeno kvůli svátku
                - (False, "early_close") - zavřeno kvůli early close
                - (False, "outside_hours") - mimo obchodní hodiny
                - (False, "weekend") - víkend (žádné hodiny pro tento den)
        """
        config = self.args.get('trading_hours', {})
        if not config.get('enabled', False):
            return (True, "open")
        
        from datetime import datetime
        import pytz
        
        tz = pytz.timezone(config.get('timezone', 'Europe/Prague'))
        # Použít synchronizovaný čas
        now = self.get_synced_time()
        # Převést na Prague timezone
        if now.tzinfo != tz:
            now = now.astimezone(tz)
        
        today_str = now.strftime('%Y-%m-%d')
        day = now.strftime('%A').lower()
        
        # 1. Kontrola svátků (market_holidays)
        holidays_config = self.args.get('market_holidays', {})
        symbol_holidays = holidays_config.get(alias, [])
        if today_str in symbol_holidays:
            if not hasattr(self, '_holiday_logged') or self._holiday_logged.get(alias) != today_str:
                self.log(f"[TRADING_HOURS] {alias}: CLOSED - Market holiday ({today_str})")
                if not hasattr(self, '_holiday_logged'):
                    self._holiday_logged = {}
                self._holiday_logged[alias] = today_str
            return (False, "holiday")
        
        # 2. Kontrola early close dnů
        early_close_config = self.args.get('early_close_days', {})
        symbol_early_close = early_close_config.get(alias, [])
        early_close_time = None
        for ec in symbol_early_close:
            if isinstance(ec, dict) and ec.get('date') == today_str:
                early_close_time = ec.get('close_time')
                break
        
        # 3. Získání standardních obchodních hodin
        symbol_hours = config.get(alias, {})
        time_range = symbol_hours.get(day)
        
        if not time_range:
            return (False, "weekend")
        
        try:
            start, end = time_range.split('-')
            start_time = datetime.strptime(start, '%H:%M').time()
            end_time = datetime.strptime(end, '%H:%M').time()
            
            # Pokud je early close den, použít dřívější close time
            if early_close_time:
                early_close = datetime.strptime(early_close_time, '%H:%M').time()
                if early_close < end_time:
                    end_time = early_close
                    if not hasattr(self, '_early_close_logged') or self._early_close_logged.get(alias) != today_str:
                        self.log(f"[TRADING_HOURS] {alias}: Early close today at {early_close_time}")
                        if not hasattr(self, '_early_close_logged'):
                            self._early_close_logged = {}
                        self._early_close_logged[alias] = today_str
            
            is_open = start_time <= now.time() <= end_time
            if is_open:
                return (True, "open")
            elif early_close_time and now.time() > end_time:
                return (False, "early_close")
            else:
                return (False, "outside_hours")
        except Exception as e:
            self.error(f"[TRADING_HOURS] Error parsing time for {alias}: {e}")
            return (True, "open")  # Při chybě povolit
    
    # ============== SPRINT 2 METHODS ==============
    
    def process_event_queue(self, kwargs):
        """Process events from EventBridge queue (called at 1Hz)"""
        try:
            if hasattr(self, 'event_bridge'):
                self.event_bridge.process_events()
                
                # Log metrics periodically
                metrics = self.event_bridge.get_metrics()
                if metrics.get('events_dropped', 0) > 0:
                    self.log(f"[EventBridge] Warning: {metrics['events_dropped']} events dropped")
                    
        except Exception as e:
            self.error(f"Error processing event queue: {e}")
    
    def handle_tick_data(self, data: Dict[str, Any]):
        """Enhanced tick handler with microstructure analysis"""
        try:
            symbol = data.get('symbol')
            if not symbol:
                return
                
            alias = self.symbol_alias.get(symbol, symbol)
            
            # Update microstructure spread profile from tick data (volume comes from bars only)
            if 'spread' in data and data['spread'] > 0:
                if hasattr(self.microstructure, 'update_spread_profile'):
                    # Use current timestamp for tick-based spread data
                    current_timestamp = datetime.now()
                    self.microstructure.update_spread_profile(alias, current_timestamp, data['spread'])
            elif 'bid' in data and 'ask' in data:
                # Calculate spread from bid/ask if available
                calculated_spread = data['ask'] - data['bid']
                if calculated_spread > 0 and hasattr(self.microstructure, 'update_spread_profile'):
                    current_timestamp = datetime.now()
                    self.microstructure.update_spread_profile(alias, current_timestamp, calculated_spread)
            else:
                # TESTING: Use estimated spread for liquidity calculation
                estimated_spread = 2.0 if alias == 'DAX' else 1.5  # Typical spreads
                if hasattr(self.microstructure, 'update_spread_profile'):
                    current_timestamp = datetime.now()
                    self.microstructure.update_spread_profile(alias, current_timestamp, estimated_spread)
            
            # Get microstructure summary for enhanced analysis
            bars = list(self.market_data.get(alias, []))
            if len(bars) >= 14:  # Need minimum bars for analysis
                micro_summary = self.microstructure.get_microstructure_summary(alias, bars)
                
                # Store for later use in signal generation
                if not hasattr(self, 'micro_data'):
                    self.micro_data = {}
                self.micro_data[alias] = micro_summary
                
                # Update HA entities with microstructure data
                self._update_microstructure_entities(alias, micro_summary)
                
        except Exception as e:
            self.error(f"Error in enhanced tick handler: {e}")
    
    def handle_bar_data(self, data: Dict[str, Any]):
        """Enhanced bar handler - FIXED to prevent duplicate ORB signals"""
        # ============================================================
        # ORB SIGNALS DISABLED - Strategy focuses on PULLBACK entries
        # We are swing trading in clear trends, entering on pullback bottoms
        # ============================================================
        return  # ORB disabled - pullback-only strategy
        
        try:
            symbol = data.get('symbol')
            if not symbol:
                return
                
            alias = self.symbol_alias.get(symbol, symbol)
            self.log(f"[ORB_CHECK] {alias}: handle_bar_data called")
            bars = list(self.market_data.get(alias, []))
            
            if len(bars) < 20:
                self.log(f"[ORB_CHECK] {alias}: Insufficient bars ({len(bars)}/20)")
                return
            
            # Inicializovat ORB tracking
            if not hasattr(self, '_orb_triggered'):
                self._orb_triggered = {}
            
            # KONTROLA: Pokud už máme aktivní tiket, negenerovat ORB
            active_tickets = self._count_active_tickets(alias)
            if active_tickets > 0:
                self.log(f"[ORB_CHECK] {alias}: Active tickets exist ({active_tickets}), skipping")
                return
            
            # Detect Opening Range patterns FIRST
            or_data = self.microstructure.detect_opening_range(alias, bars)
            orb_triggered = or_data.get('orb_triggered', False)
            progressive_or = or_data.get('progressive_or', False)
            
            self.log(f"[ORB_CHECK] {alias}: ORB triggered={orb_triggered}, progressive={progressive_or}")
            
            if not orb_triggered:
                return  # ORB not triggered yet
            
            if progressive_or:
                self.log(f"[ORB_CHECK] {alias}: Still in progressive OR phase")
                return
            
            # Check if already triggered today (AFTER detecting ORB)
            today_key = f"{alias}_{datetime.now().date()}"
            if today_key in self._orb_triggered:
                self.log(f"[ORB_CHECK] {alias}: Already triggered today, skipping")
                return
            
            # Check trading hours
            in_hours, hours_reason = self._is_within_trading_hours(alias)
            self.log(f"[ORB_CHECK] {alias}: Within trading hours={in_hours}")
            if not in_hours:
                if hours_reason == "holiday":
                    self.log(f"[ORB_CHECK] {alias}: Market closed (holiday), skipping")
                elif hours_reason == "weekend":
                    self.log(f"[ORB_CHECK] {alias}: Market closed (weekend), skipping")
                else:
                    self.log(f"[ORB_CHECK] {alias}: Outside trading hours, skipping")
                return
            
            # All checks passed - try to generate signal
            self.log(f"[ORB_CHECK] {alias}: ✅ All checks passed, generating ORB signal...")
            signal_generated = self._generate_orb_signal(alias, or_data, bars)
            
            # CRITICAL FIX: Only mark as triggered if signal was ACTUALLY generated
            if signal_generated:
                self._orb_triggered[today_key] = True
                self.log(f"[ORB_CHECK] {alias}: ✅ ORB signal generated and marked as triggered")
            else:
                self.log(f"[ORB_CHECK] {alias}: ⚠️ Signal generation failed (see logs above)")
                    
        except Exception as e:
            self.error(f"Error in bar handler: {e}")
    
    def _update_microstructure_entities(self, alias: str, micro_summary: Dict):
        """
        Update HA entities with microstructure data
        
        NOTE: Most Sprint 2 entities (Volume Z-Score, VWAP Distance, ATR v2) are DISABLED
        because HASS 2024+ has strict entity validation that causes HTTP 400 errors.
        
        Microstructure data is still calculated and used internally for signal generation,
        but not published to HA entities to avoid log spam.
        """
        try:
            # === DISABLED ENTITIES (HASS 2024+ strict validation) ===
            # Volume Z-score, VWAP distance - cause HTTP 400 errors
            # These are non-critical display entities
            
            # Liquidity score - keep this one as it's useful for dashboard
            self._safe_set_state(f"sensor.{alias.lower()}_liquidity_score_v2",
                        state=round(micro_summary.get('liquidity_score', 0), 2),
                        attributes={
                            "friendly_name": f"{alias} Liquidity Score",
                            "min": 0,
                            "max": 1,
                            "is_high_quality": micro_summary.get('is_high_quality_time', False)
                        })
            
            # Opening Range entities
            or_data = micro_summary.get('opening_range', {})
            if or_data:
                # OR High
                or_high = or_data.get('or_high', 0)
                if or_high:
                    self._safe_set_state(f"sensor.{alias.lower()}_or_high",
                                state=round(or_high, 2),
                                attributes={"friendly_name": f"{alias} OR High"})

                # OR Low
                or_low = or_data.get('or_low', 0)
                if or_low:
                    self._safe_set_state(f"sensor.{alias.lower()}_or_low",
                                state=round(or_low, 2),
                                attributes={"friendly_name": f"{alias} OR Low"})

                # OR Range - OPRAVENO
                or_range = or_data.get('or_range', 0)
                if or_range:
                    self._safe_set_state(f"sensor.{alias.lower()}_or_range",
                                state=round(or_range, 2),
                                attributes={
                                    "friendly_name": f"{alias} OR Range",
                                    "unit_of_measurement": "pts"
                                })
                else:
                    # Pokud není range, vypočítat z high/low
                    if or_high and or_low:
                        calculated_range = abs(or_high - or_low)
                        self._safe_set_state(f"sensor.{alias.lower()}_or_range",
                                    state=round(calculated_range, 2),
                                    attributes={
                                        "friendly_name": f"{alias} OR Range",
                                        "unit_of_measurement": "pts"
                                    })

                # NOVĚ: OR Status (progressive vs complete)
                is_progressive = or_data.get('progressive_or', False)
                if is_progressive:
                    # Progressive OR entities
                    bars_collected = or_data.get('bars_collected', 0)
                    bars_needed = or_data.get('bars_needed', 6)
                    progress_pct = round((bars_collected / bars_needed) * 100, 1) if bars_needed > 0 else 0

                    self._safe_set_state(f"sensor.{alias.lower()}_or_status",
                                state="building",
                                attributes={
                                    "friendly_name": f"{alias} OR Status",
                                    "bars_collected": bars_collected,
                                    "bars_needed": bars_needed,
                                    "progress_pct": progress_pct,
                                    "session_start": or_data.get('session_start_utc', '').isoformat() if or_data.get('session_start_utc') else None
                                })

                    # self.log(f"[{alias}] Progressive OR: {bars_collected}/{bars_needed} bars ({progress_pct}%)")  # Disabled to reduce log noise
                else:
                    # Final OR entities (existing logic)
                    self._safe_set_state(f"sensor.{alias.lower()}_or_status",
                                state="complete",
                                attributes={
                                    "friendly_name": f"{alias} OR Status",
                                    "orb_ready": True,
                                    "bars_collected": or_data.get('bars_collected', 6),
                                    "bars_needed": or_data.get('bars_needed', 6),
                                    "progress_pct": 100,
                                    "session_start": or_data.get('session_start_utc', '').isoformat() if or_data.get('session_start_utc') else None
                                })

                # ORB Triggered
                if or_data.get('orb_triggered'):
                    self._safe_set_state(f"binary_sensor.{alias.lower()}_orb_triggered",
                                state="on",
                                attributes={
                                    "direction": or_data.get('orb_direction'),
                                    "timestamp": or_data.get('orb_timestamp')
                                })
                else:
                    self._safe_set_state(f"binary_sensor.{alias.lower()}_orb_triggered",
                                state="off",
                                attributes={"friendly_name": f"{alias} ORB Triggered"})
            else:
                # Pokud nemáme OR data (mimo session), nastavit na inactive s prázdnými hodnotami
                self._safe_set_state(f"sensor.{alias.lower()}_or_high",
                            state="---",
                            attributes={
                                "friendly_name": f"{alias} OR High",
                                "status": "Outside session"
                            })

                self._safe_set_state(f"sensor.{alias.lower()}_or_low",
                            state="---",
                            attributes={
                                "friendly_name": f"{alias} OR Low",
                                "status": "Outside session"
                            })

                self._safe_set_state(f"sensor.{alias.lower()}_or_range",
                            state="---",
                            attributes={
                                "friendly_name": f"{alias} OR Range",
                                "status": "Outside session"
                            })

                # Set OR status to inactive when outside session
                self._safe_set_state(f"sensor.{alias.lower()}_or_status",
                            state="inactive",
                            attributes={
                                "friendly_name": f"{alias} OR Status",
                                "reason": "Outside trading session",
                                "session_hours": self._get_session_hours(alias)
                            })

                self._safe_set_state(f"binary_sensor.{alias.lower()}_orb_triggered",
                            state="off",
                            attributes={"friendly_name": f"{alias} ORB Triggered"})
            
            # ATR analysis entities
            atr_data = micro_summary.get('atr_analysis', {})
            if atr_data:
                # Current ATR
                current_atr = atr_data.get('current', 0)
                if current_atr:
                    self._safe_set_state(f"sensor.{alias.lower()}_atr_current_v2",
                                state=round(current_atr, 2),
                                attributes={
                                    "friendly_name": f"{alias} ATR Current",
                                    "unit_of_measurement": "pts"
                                })

                # Expected ATR
                expected_atr = atr_data.get('expected', 0)
                if expected_atr:
                    self._safe_set_state(f"sensor.{alias.lower()}_atr_expected_v2",
                                state=round(expected_atr, 2),
                                attributes={
                                    "friendly_name": f"{alias} ATR Expected",
                                    "unit_of_measurement": "pts"
                                })

                # ATR Percentile
                percentile = atr_data.get('percentile', 50)
                self._safe_set_state(f"sensor.{alias.lower()}_atr_percentile",
                            state=round(percentile, 0),
                            attributes={
                                "friendly_name": f"{alias} ATR Percentile",
                                "is_elevated": atr_data.get('is_elevated', False)
                            })

            # VWAP entity
            vwap_value = micro_summary.get('vwap', 0)
            if vwap_value:
                self._safe_set_state(f"sensor.{alias.lower()}_vwap",
                            state=round(vwap_value, 2),
                            attributes={
                                "friendly_name": f"{alias} VWAP",
                                "unit_of_measurement": "pts"
                            })
            
        except Exception as e:
            self.error(f"Error updating microstructure entities for {alias}: {e}")
    
    def _generate_orb_signal(self, alias: str, or_data: Dict, bars: List[Dict]) -> bool:
        """
        Generate signal from Opening Range Breakout with microstructure validation.
        Returns True if signal was successfully generated, False otherwise.
        """
        from datetime import datetime
        
        # === KONTROLA STAVU SYSTÉMU PŘED GENEROVÁNÍM ORB SIGNÁLU ===
        # CRITICAL FIX: Kontrolujeme přímo is_connected() místo HA entity (ta má zpoždění)
        ctrader_connected = self.ctrader_client.is_connected() if self.ctrader_client else False
        ctrader_status = "on" if ctrader_connected else "off"
        
        self.log(f"[ORB] {alias}: cTrader={ctrader_status}")
        
        if not ctrader_connected:
            self.log(f"[ORB] ⏸️ {alias} - cTrader not connected")
            return False
        
        try:
            current_bar = bars[-1]
            current_price = current_bar['close']

            # === MIKROSTRUKTURNÍ VALIDACE (same as wide-stops) ===
            try:
                micro_data = self.microstructure.get_microstructure_summary(alias, bars)

                # Check liquidity threshold
                liquidity = micro_data.get('liquidity_score', 0)
                min_liquidity_threshold = self.args.get('microstructure', {}).get('min_liquidity_score', 0.1)

                if liquidity < min_liquidity_threshold:
                    self.log(f"[ORB] {alias} Poor market conditions (liquidity {liquidity:.2f} < {min_liquidity_threshold}), rejecting ORB signal")
                    return False

                # Check high quality time (DISABLED - always allow ORB signals)
                is_high_quality = micro_data.get('is_high_quality_time', False)
                self.log(f"[ORB] {alias}: is_high_quality_time={is_high_quality}")
                # NOTE: We don't block on is_high_quality_time for ORB signals anymore
                # ORB signals are time-sensitive and should be generated when triggered

                # Extract microstructure metrics for signal enhancement
                volume_zscore = micro_data.get('volume_zscore', 0)
                vwap_distance = abs(micro_data.get('vwap_distance', 0))

                self.log(f"[ORB] {alias} Microstructure OK - Liquidity: {liquidity:.2f}, Vol Z-score: {volume_zscore:.2f}")

            except Exception as e:
                self.log(f"[ORB] {alias} Microstructure analysis failed: {e}, using defaults")
                micro_data = {}
                liquidity = 0.5
                volume_zscore = 0
                vwap_distance = 0

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
            
            # === MIKROSTRUKTURNÍ BONUSY (same as wide-stops) ===
            base_confidence = 75
            base_quality = 70

            # Volume bonus
            if volume_zscore > 1.5:
                base_confidence += 10
                self.log(f"[ORB] High volume Z-score bonus: +10% confidence")

            # VWAP confluence bonus
            vwap_confluence_distance = self.args.get('microstructure', {}).get('vwap_confluence_distance', 0.3)
            if vwap_distance < vwap_confluence_distance:
                base_quality += 10
                self.log(f"[ORB] VWAP confluence bonus: +10% quality")

            # High quality time bonus
            if is_high_quality:
                base_confidence += 5
                self.log(f"[ORB] High quality time bonus: +5% confidence")

            # Create ORB signal with microstructure enhancements (flat structure for consistency)
            signal = {
                'symbol': alias,
                'signal_type': direction,  # Změna z 'type' na 'signal_type'
                'direction': direction,
                'entry': entry,
                'stop_loss': stop,  # Změna z 'stop' na 'stop_loss'
                'take_profit': target,  # Změna z 'target' na 'take_profit'
                'confidence': min(100, base_confidence),  # Cap at 100%
                'signal_quality': min(100, base_quality),  # Cap at 100%
                'patterns': ['ORB'],
                'risk_reward_ratio': 2.0,
                'pattern_type': 'ORB',
                # Flat microstructure data for consistency with EdgeDetector signals
                'liquidity_score': liquidity,
                'volume_zscore': volume_zscore,
                'vwap_distance_pct': vwap_distance,
                'orb_triggered': True,
                'high_quality_time': is_high_quality,
                'metadata': {
                    'pattern': 'Opening Range Breakout',
                    'or_high': or_data['or_high'],
                    'or_low': or_data['or_low'],
                    'or_range': or_range
                }
            }
            
            # Add to signal manager s current_price a atr
            atr_value = self.current_atr.get(alias, 20.0)
            self.signal_manager.add_signal(signal, current_price, atr_value)

            self.log(f"[{alias}] ORB Signal: {direction} @ {entry:.2f}, Stop: {stop:.2f}, Target: {target:.2f}")

            # Try auto-execute ORB signal (same as wide-stops signals)
            self._try_auto_execute_signal(signal, alias)
            
            return True  # Signal successfully generated
            
        except Exception as e:
            self.error(f"Error generating ORB signal: {e}")
            return False

    def _get_session_hours(self, alias: str) -> str:
        """Get trading session hours for display"""
        try:
            if alias == 'DAX':
                return "09:00-14:30 CET"
            elif alias == 'NASDAQ':
                return "14:30-22:00 CET"
            else:
                return "Unknown"
        except Exception:
            return "Unknown"
    
    def create_sprint2_entities(self, kwargs=None):
        """Create all Sprint 2 entities for dashboard"""
        try:
            self.log("[SPRINT2] Creating microstructure entities...")
            
            for alias in self.symbol_alias.values():
                alias_lower = alias.lower()
                
                # Liquidity score
                self._safe_set_state(f"sensor.{alias_lower}_liquidity_score_v2",
                              state=0.5,
                              attributes={
                                  "friendly_name": f"{alias} Liquidity Score",
                                  "unit_of_measurement": "",
                                  "min": 0,
                                  "max": 1,
                                  "icon": "mdi:water"
                              })
                
                # === DISABLED ENTITIES (HASS 2024+ strict validation causes HTTP 400) ===
                # Volume Z-score, VWAP Distance, ATR entities are non-critical
                # and cause repeated errors. Keeping only essential entities.
                
                # VWAP - essential for trading display
                current_price = 0
                bars = list(self.market_data.get(alias, []))
                if bars and len(bars) > 0:
                    current_price = bars[-1].get('close', 0)
                
                self._safe_set_state(f"sensor.{alias_lower}_vwap",
                              state=current_price if current_price > 0 else "unknown",
                              attributes={
                                  "friendly_name": f"{alias} VWAP",
                                  "unit_of_measurement": "pts",
                                  "icon": "mdi:chart-line"
                              })
                
                # Opening Range entities
                self._safe_set_state(f"sensor.{alias_lower}_or_high",
                              state="unknown",
                              attributes={
                                  "friendly_name": f"{alias} OR High",
                                  "unit_of_measurement": "pts",
                                  "icon": "mdi:arrow-up-bold"
                              })
                
                self._safe_set_state(f"sensor.{alias_lower}_or_low",
                              state="unknown",
                              attributes={
                                  "friendly_name": f"{alias} OR Low",
                                  "unit_of_measurement": "pts",
                                  "icon": "mdi:arrow-down-bold"
                              })
                
                self._safe_set_state(f"sensor.{alias_lower}_or_range",
                              state="unknown",
                              attributes={
                                  "friendly_name": f"{alias} OR Range",
                                  "unit_of_measurement": "pts",
                                  "icon": "mdi:arrow-expand-vertical"
                              })
                
                self._safe_set_state(f"binary_sensor.{alias_lower}_orb_triggered",
                              state="off",
                              attributes={
                                  "friendly_name": f"{alias} ORB Triggered",
                                  "device_class": "signal",
                                  "icon": "mdi:alert-circle"
                              })
                
                # ATR entities - DISABLED (cause HTTP 400 on HASS 2024+)
                # ATR is still calculated and used internally, just not published to HA
                # current_atr = self.current_atr.get(alias, 0)
                # ATR values are available via sensor.{alias}_trading_status attributes
                
                # Additional Sprint 2 metrics
                self._safe_set_state(f"sensor.sprint2_mode",
                              state=SPRINT2_VERSION,
                              attributes={
                                  "friendly_name": "Sprint 2 Mode",
                                  "icon": "mdi:rocket-launch"
                              })
                
                # Expectancy thresholds placeholder
                self._safe_set_state(f"sensor.expectancy_thresholds",
                              state="active",
                              attributes={
                                  "friendly_name": "Expectancy Thresholds",
                                  f"{alias}_ORB_quality": 70,
                                  f"{alias}_ORB_confidence": 60,
                                  f"{alias}_ORB_samples": 0,
                                  f"{alias}_SWING_quality": 70,
                                  f"{alias}_SWING_confidence": 60,
                                  f"{alias}_SWING_samples": 0,
                                  "icon": "mdi:target"
                              })
            
            self.log(f"[SPRINT2] Created entities for {len(self.symbol_alias)} symbols")
            
            # Update with real data if available
            self._update_sprint2_entities_with_data()
            
        except Exception as e:
            self.error(f"[SPRINT2] Error creating entities: {e}")
    
    def _update_sprint2_entities_with_data(self, kwargs=None):
        """
        Update Sprint 2 entities with real data from microstructure analysis
        
        OPTIMIZED pro thread starvation prevention:
        - Přeskočí pokud je systém přetížený
        """
        try:
            # === THREAD STARVATION PREVENTION ===
            if self._is_system_overloaded():
                return  # Přeskočit - non-critical operace
            
            for alias in self.symbol_alias.values():
                bars = list(self.market_data.get(alias, []))
                
                if len(bars) >= 14:  # Need minimum bars
                    # Convert timestamp strings to datetime if needed
                    for bar in bars:
                        if isinstance(bar.get('timestamp'), str):
                            from datetime import datetime
                            bar['timestamp'] = datetime.fromisoformat(bar['timestamp'].replace('Z', '+00:00'))
                    
                    # Calculate real microstructure data
                    micro_summary = self.microstructure.get_microstructure_summary(alias, bars)
                    
                    if micro_summary:
                        # Update entities with real values
                        self._update_microstructure_entities(alias, micro_summary)
                        self.log(f"[SPRINT2] Updated {alias} entities with real data")
            
        except Exception as e:
            self.log(f"[SPRINT2] Could not update with real data: {e}")
            
    def _expire_and_remove_ticket(self, ticket_entity: str):
        """Expirovat a označit tiket jako REMOVED"""
        try:
            current_state = self.get_state(ticket_entity)
            if current_state == "READY":
                # Získat informace z tiketu před expirací
                ticket_attrs = self.get_state(ticket_entity, attribute="all")
                if ticket_attrs and ticket_attrs.get("attributes"):
                    symbol = ticket_attrs["attributes"].get("symbol")
                    entry_price = ticket_attrs["attributes"].get("entry")
                    
                    # Odstranit odpovídající pozici z risk manageru
                    if symbol and hasattr(self, 'risk_manager'):
                        original_count = len(self.risk_manager.open_positions)
                        # Filtrovat pozice - ponechat jen ty, které neodpovídají
                        self.risk_manager.open_positions = [
                            pos for pos in self.risk_manager.open_positions 
                            if not (pos.symbol == symbol and abs(pos.entry_price - entry_price) < 0.1)
                        ]
                        removed = original_count - len(self.risk_manager.open_positions)
                        if removed > 0:
                            self.log(f"[EXPIRE] Removed {removed} position(s) for {symbol} from risk manager")
                    
                    # Odstranit ze signal manageru pokud existuje
                    if hasattr(self, 'signal_manager'):
                        # Najít a odstranit odpovídající signál
                        for signal_id in list(self.signal_manager.active_signals.keys()):
                            signal = self.signal_manager.active_signals[signal_id]
                            if signal.symbol == symbol and abs(signal.entry_price - entry_price) < 0.1:
                                del self.signal_manager.active_signals[signal_id]
                                self.log(f"[EXPIRE] Removed signal {signal_id} from signal manager")
                                break
            
            # Označit tiket jako REMOVED
            self._safe_set_state(ticket_entity, 
                        state="REMOVED",
                        attributes={
                            "expired": True,
                            "expired_at": datetime.now().isoformat(),
                            "reason": "timeout_10min"
                        })
            
            self.log(f"[TICKET] Expired and marked as REMOVED: {ticket_entity}")
            
        except Exception as e:
            self.error(f"[EXPIRE] Error expiring ticket {ticket_entity}: {e}")
            self.error(traceback.format_exc())
            
    def _is_system_overloaded(self) -> bool:
        """
        Kontrola zda je systém přetížený (thread starvation prevention)
        
        Returns:
            True pokud je queue příliš velká a měli bychom přeskočit non-critical operace
        """
        try:
            with self._dispatch_lock:
                queue_size = len(self._dispatch_queue)
            
            # Přetížení pokud queue > 500 položek
            overload_threshold = self.args.get('performance', {}).get('overload_threshold', 500)
            return queue_size > overload_threshold
        except:
            return False
    
    def _get_trading_entities_fast(self) -> list:
        """
        Rychlé získání pouze trading-related entit (thread starvation prevention)
        
        Místo get_state() pro všechny entity, získáme pouze naše entity
        pomocí specifických prefixů.
        """
        trading_entities = []
        try:
            # Definované prefixy pro naše entity
            prefixes = [
                'sensor.signal_',
                'sensor.trade_ticket_',
                'sensor.trading_',
                'sensor.dax_',
                'sensor.nasdaq_',
            ]
            
            all_states = self.get_state()
            if all_states:
                for entity_id in all_states:
                    for prefix in prefixes:
                        if entity_id.startswith(prefix):
                            trading_entities.append(entity_id)
                            break
        except Exception as e:
            self.error(f"[CLEANUP] Error getting trading entities: {e}")
        
        return trading_entities

    def cleanup_old_entities(self, kwargs):
        """
        Odstranit staré entity - běží každých 10 minut
        
        OPTIMIZED pro thread starvation prevention:
        - Přeskočí pokud je systém přetížený
        - Zpracuje max 30 entit per run
        - Používá specifické entity namísto všech
        """
        import time
        
        try:
            # === THREAD STARVATION PREVENTION ===
            if self._is_system_overloaded():
                self._cleanup_skip_count = getattr(self, '_cleanup_skip_count', 0) + 1
                if self._cleanup_skip_count <= 3:  # Log pouze prvních 3 skip
                    self.log(f"[CLEANUP] Skipped - system overloaded (skip #{self._cleanup_skip_count})")
                return
            
            self._cleanup_skip_count = 0
            start_time = time.time()
            
            # Získat pouze trading entity (rychlejší než get_state() pro všechny)
            trading_entities = self._get_trading_entities_fast()
            
            removed_count = 0
            processed_count = 0
            current_time = datetime.now()
            max_entities_per_run = 30  # Limit pro prevenci timeout
            
            for entity_id in trading_entities:
                # Limit zpracování per run
                if processed_count >= max_entities_per_run:
                    break
                    
                # Time limit - max 2 sekundy
                if time.time() - start_time > 2.0:
                    self.log(f"[CLEANUP] Time limit reached after {processed_count} entities")
                    break
                
                try:
                    state = self.get_state(entity_id)
                    processed_count += 1
                    
                    # Skip hlavní entity
                    if entity_id in ['sensor.signal_dax', 'sensor.signal_nasdaq', 
                                'sensor.signal_dax_headline', 'sensor.signal_nasdaq_headline']:
                        continue
                    
                    # Odstranit staré tikety
                    if 'trade_ticket_' in entity_id:
                        if state in ["REMOVED", "EXPIRED", "CLEARED", "unavailable"]:
                            self._safe_set_state(entity_id, state="unavailable", attributes={})
                            removed_count += 1
                        elif state == "READY":
                            # Zkontrolovat stáří READY tiketů
                            attrs = self.get_state(entity_id, attribute="all")
                            if attrs and attrs.get("attributes"):
                                created_str = attrs["attributes"].get("created_at")
                                if created_str:
                                    try:
                                        created = datetime.fromisoformat(created_str)
                                        age_minutes = (current_time - created).seconds / 60
                                        if age_minutes > 15:  # Starší než 15 minut
                                            self._safe_set_state(entity_id, state="unavailable", attributes={})
                                            removed_count += 1
                                    except:
                                        pass
                    
                    # Odstranit staré signály
                    elif entity_id.startswith('sensor.signal_') and state in ["REMOVED", "MISSED", "EXPIRED"]:
                        self._safe_set_state(entity_id, state="unavailable", attributes={})
                        removed_count += 1
                        
                except Exception as e:
                    continue  # Tiše přeskočit chyby jednotlivých entit
            
            if removed_count > 0:
                self.log(f"[CLEANUP] Removed {removed_count} old entities")
                
        except Exception as e:
            self.error(f"[CLEANUP] Periodic cleanup error: {e}")      
            
    def _cleanup_symbol_tickets(self, alias: str):
        """Vyčistit všechny staré tikety pro daný symbol"""
        try:
            all_states = self.get_state()
            cleaned = 0
            
            for entity_id in all_states:
                if f'trade_ticket_{alias.lower()}_' in entity_id:
                    state = self.get_state(entity_id)
                    # Odstranit všechny kromě READY
                    if state != "READY":
                        self._safe_set_state(entity_id, state="unavailable", attributes={})
                        cleaned += 1
            
            if cleaned > 0:
                self.log(f"[CLEANUP] Removed {cleaned} old tickets for {alias}")
                
        except Exception as e:
            self.error(f"[CLEANUP] Error cleaning {alias} tickets: {e}")

    def _fully_expire_ticket(self, ticket_entity: str):
        """Kompletně expirovat a odstranit tiket"""
        try:
            current_state = self.get_state(ticket_entity)
            if current_state == "READY":
                # Získat info pro cleanup risk manageru
                ticket_attrs = self.get_state(ticket_entity, attribute="all")
                if ticket_attrs and ticket_attrs.get("attributes"):
                    symbol = ticket_attrs["attributes"].get("symbol")
                    entry_price = ticket_attrs["attributes"].get("entry")
                    
                    # Odstranit z risk manageru
                    if symbol and hasattr(self, 'risk_manager'):
                        self.risk_manager.open_positions = [
                            pos for pos in self.risk_manager.open_positions 
                            if not (pos.symbol == symbol and abs(pos.entry_price - entry_price) < 0.1)
                        ]
            
            # Nastavit jako unavailable (skryje se v dashboardu)
            self._safe_set_state(ticket_entity, state="unavailable", attributes={})
            self.log(f"[EXPIRE] Ticket {ticket_entity} fully expired")
            
        except Exception as e:
            self.error(f"[EXPIRE] Error expiring ticket: {e}") 
            
            
    def quick_cleanup(self, kwargs):
        """
        Rychlé čištění unavailable entity každé 3 minuty
        
        OPTIMIZED pro thread starvation prevention:
        - Přeskočí pokud je systém přetížený
        - Zpracuje pouze trading-related entity
        - Max 10 entit per run
        """
        try:
            # === THREAD STARVATION PREVENTION ===
            if self._is_system_overloaded():
                return  # Tiše přeskočit - non-critical operace
            
            # Získat pouze trading entity
            trading_entities = self._get_trading_entities_fast()
            unavailable_entities = []

            # Collect unavailable entities (limit to first 10 per run)
            count = 0
            for entity_id in trading_entities:
                if count >= 10:  # Snížený limit pro rychlejší průběh
                    break
                try:
                    if self.get_state(entity_id) == "unavailable":
                        unavailable_entities.append(entity_id)
                        count += 1
                except:
                    continue

            # Batch purge if any found
            if unavailable_entities:
                try:
                    self.call_service("recorder/purge_entities", entity_id=unavailable_entities)
                    self.log(f"[CLEANUP] Removed {len(unavailable_entities)} old entities")
                except Exception as e:
                    pass  # Tiše ignorovat chyby purge

        except Exception as e:
            pass  # Tiše ignorovat - non-critical operace      
        
        
    def _publish_single_trade_ticket(self, alias: str, position, signal):
        """Publish single trade ticket - no duplicates"""
        import hashlib
        from datetime import datetime, timedelta

        # Vyčistit VŠECHNY staré tikety tohoto symbolu
        all_states = self.get_state()
        for entity_id in all_states:
            if f'trade_ticket_{alias.lower()}_' in entity_id:
                self._safe_set_state(entity_id, state="unavailable", attributes={})

        direction = signal.signal_type.value if hasattr(signal, 'signal_type') else "UNKNOWN"

        # NOVINKA: Aplikovat SL/TP band system pro přesné zobrazení
        original_sl_points = abs(signal.entry - signal.stop_loss)
        original_tp_points = abs(signal.take_profit - signal.entry)

        # Získat band-adjusted hodnoty z RiskManager
        sl_final_pts, sl_diag = self.risk_manager.apply_structural_sl_band(alias, original_sl_points)
        tp_final_pts, tp_diag = self.risk_manager.apply_structural_tp_band(alias, sl_final_pts, original_tp_points)

        # Spočítat finální hodnoty pro ticket (odpovídá skutečným orderům)
        sl_pips = sl_final_pts * 100  # Band-adjusted SL pips
        tp_pips = tp_final_pts * 100  # Band-adjusted TP pips
        rrr = tp_final_pts / sl_final_pts if sl_final_pts > 0 else 0

        # Spočítat finální SL/TP ceny pro zobrazení
        if signal.signal_type.value == "BUY":
            final_sl_price = signal.entry - sl_final_pts
            final_tp_price = signal.entry + tp_final_pts
        else:  # SELL
            final_sl_price = signal.entry + sl_final_pts
            final_tp_price = signal.entry - tp_final_pts
        
        # ID
        signal_id = hashlib.md5(
            f"{alias}{signal.entry}{datetime.now()}".encode()
        ).hexdigest()[:4]
        
        ticket_entity = f"sensor.trade_ticket_{alias.lower()}_{signal_id}"
        
        # Formátované časy
        now = datetime.now()
        created_time = now.strftime("%H:%M:%S")
        expires_time = (now + timedelta(minutes=10)).strftime("%H:%M:%S")
        
        # Ticket text s band-adjusted hodnotami (odpovídá skutečným orderům)
        ticket_text = f"""{alias} {direction}
Entry: {signal.entry:.1f}
SL: {final_sl_price:.1f} (-{sl_pips:.0f} pips)
TP: {final_tp_price:.1f} (+{tp_pips:.0f} pips)
Size: {position.lots:.2f} lots
Risk: {position.risk_amount_czk:.0f} CZK
RRR: {rrr:.1f}:1
Created: {created_time}
Expires: {expires_time} (10:00 min)"""
        
        # Vytvořit JEDINÝ sensor s band-adjusted hodnotami
        self._safe_set_state(
            ticket_entity,
            state="READY",
            attributes={
                "symbol": alias,
                "direction": direction,
                "lots": position.lots,
                "entry": signal.entry,
                "stop_loss": final_sl_price,  # Band-adjusted SL cena
                "take_profit": final_tp_price,  # Band-adjusted TP cena
                "sl_pips": sl_pips,  # Band-adjusted SL pips
                "tp_pips": tp_pips,  # Band-adjusted TP pips
                "risk_czk": position.risk_amount_czk,
                "rrr": rrr,  # Band-adjusted RRR
                "ticket": ticket_text,
                "created_at": datetime.now().isoformat(),
                "expires_at": (datetime.now() + timedelta(minutes=10)).isoformat(),
                # Debug info pro srovnání
                "original_sl": signal.stop_loss,
                "original_tp": signal.take_profit,
                "sl_band_applied": sl_diag.get('clamped', False),
                "tp_band_applied": tp_diag.get('clamped', False)
            }
        )
        
        # Auto-expire
        self.run_in(
            lambda _: self._safe_set_state(ticket_entity, state="unavailable", attributes={}),
            600
        )
        
        # Naplánovat countdown updates (každých 30 sekúnd)
        total_seconds = 10 * 60  # 10 minút
        self._schedule_countdown_updates(ticket_entity, total_seconds)
        
        # === PŘIDAT SIGNÁL DO SIGNAL MANAGERU (BEZ NOTIFIKACE) ===
        # Notifikace se posílá až při potvrzení otevření pozice (EXECUTION_EVENT type 3)
        # Signal manager má notify_on_new=False, takže notifikaci nepošle
        signal_dict = {
            'symbol': alias,
            'signal_type': direction,
            'entry': signal.entry,
            'stop_loss': signal.stop_loss,
            'take_profit': signal.take_profit,
            'risk_reward': rrr,
            'confidence': 75,
            'signal_quality': 70,
            'patterns': ['SIGNAL']
        }
        
        # Přidat signál do signal manageru (pro tracking), ale bez notifikace
        current_price = self._get_current_price(alias) or signal.entry
        atr = self.current_atr.get(alias, 10)
        self.signal_manager.add_signal(signal_dict, current_price, atr)
        
        self.log(f"[TICKET] Created {ticket_entity}")
    
    # === MVP AUTO-TRADING HELPER METHODS ===
    
    def _reconcile_on_startup(self, kwargs=None):
        """
        CRITICAL: Reconcile bot state with broker on startup
        Adopts existing positions and pending orders
        """
        try:
            self.log("[RECONCILE] 🔄 Starting startup reconcile...")
            
            # Use existing _update_balance_from_ctrader method
            if hasattr(self, '_update_balance_from_ctrader'):
                self._update_balance_from_ctrader(kwargs)
                self.log("[RECONCILE] ✅ Startup reconcile complete")
            else:
                self.log("[RECONCILE] ⚠️ _update_balance_from_ctrader not available")
        except Exception as e:
            self.error(f"[RECONCILE] ❌ Error during startup reconcile: {e}")
            import traceback
            self.error(traceback.format_exc())
    
    def _update_balance_from_ctrader(self, _=None):
        """Update balance tracker from cTrader reconcile data"""
        if not self.auto_trading_enabled or not self.balance_tracker or not self.ctrader_client:
            return
            
        # Get reconcile data from cTrader client
        if hasattr(self.ctrader_client, 'reconcile_data') and self.ctrader_client.reconcile_data:
            reconcile_data = self.ctrader_client.reconcile_data
            success = self.balance_tracker.update_from_reconcile(reconcile_data)
            
            if success:
                current_balance = self.balance_tracker.get_current_balance()
                balance_info = self.balance_tracker.get_balance_info()
                
                # Update Home Assistant sensor
                self._safe_set_state(
                    "sensor.trading_account_balance",
                    state=int(current_balance),
                    attributes={
                        "balance": current_balance,
                        "free_margin": balance_info.get('free_margin', 0),
                        "margin_used": balance_info.get('margin_used', 0),
                        "equity": balance_info.get('equity', 0),
                        "last_update": datetime.now().isoformat()
                    }
                )
    
    def _check_trading_session(self, _=None):
        """Check current trading session and update status"""
        if not self.auto_trading_enabled or not self.time_manager:
            return
            
        current_session = self.time_manager.get_active_session()
        
        # Update Home Assistant sensor
        self._safe_set_state(
            "sensor.trading_active_session",
            state=current_session.value,
            attributes={
                "session": current_session.value,
                "session_info": self.time_manager.get_session_info(),
                "last_update": datetime.now().isoformat()
            }
        )
    
    def _update_performance_metrics(self, _=None):
        """Update performance metrics in Home Assistant"""
        try:
            if self.account_monitor and hasattr(self.account_monitor, '_update_performance_metrics'):
                self.account_monitor._update_performance_metrics()
        except Exception as e:
            self.log(f"[PERFORMANCE] Error updating metrics: {e}", level="ERROR")
    
    def _check_trailing_stops(self, _=None):
        """Periodically check and update trailing stops"""
        try:
            if self.account_monitor and hasattr(self.account_monitor, '_check_trailing_stops'):
                self.account_monitor._check_trailing_stops()
        except Exception as e:
            self.log(f"[TRAILING] Error checking trailing stops: {e}", level="ERROR")
    
    def _check_pending_reverse(self, position_id: str, symbol: str):
        """
        Check if there's a pending reverse signal for this position and execute it
        
        Called from account_state_monitor when position is confirmed closed
        """
        try:
            with self._reverse_lock:
                if position_id not in self._pending_reverse_signals:
                    return
                
                reverse_data = self._pending_reverse_signals.pop(position_id)
                signal_dict = reverse_data['signal']
                alias = reverse_data['alias']
                direction = reverse_data['direction']
                
                self.log(f"[AUTO-TRADING] ✅ Position {position_id} closed - executing pending reverse: {alias} {direction}")
                
                # Verify no positions are open (safety check)
                open_positions = self.risk_manager.get_open_positions_copy()
                if open_positions:
                    self.log(f"[AUTO-TRADING] ⚠️ Warning: {len(open_positions)} positions still open, but proceeding with reverse")
                
                # Also check account_monitor
                if self.account_monitor:
                    with self.account_monitor._lock:
                        account_positions = self.account_monitor._account_state.get('open_positions', [])
                        if account_positions:
                            self.log(f"[AUTO-TRADING] ⚠️ Warning: {len(account_positions)} positions in account_monitor, but proceeding with reverse")
                
                # Execute reverse signal (recursive call to _try_auto_execute_signal)
                # But skip conflict check since we just closed the position
                self.log(f"[AUTO-TRADING] 🚀 Executing reverse signal: {alias} {direction}")
                self._execute_reverse_signal(signal_dict, alias)
                
        except Exception as e:
            self.log(f"[AUTO-TRADING] ❌ Error checking pending reverse: {e}", level="ERROR")
            import traceback
            self.log(traceback.format_exc())
    
    def _execute_reverse_signal(self, signal_dict: Dict[str, Any], alias: str):
        """
        Execute reverse signal after position close confirmation
        This bypasses conflict check since we just closed the position
        """
        try:
            if not self.auto_trading_enabled or not self.order_executor:
                return
            
            self.log(f"[AUTO-TRADING] 🔄 Executing reverse signal for {alias}")
            
            # Convert signal format (same as in _try_auto_execute_signal)
            entry_price = signal_dict.get('entry', 0)
            stop_loss = signal_dict.get('stop_loss', 0)
            take_profit = signal_dict.get('take_profit', 0)
            
            # Check if using fixed SL/TP strategy
            use_fixed_sl_tp = self.args.get('use_fixed_sl_tp', False)
            
            if use_fixed_sl_tp:
                # Advanced SL/TP strategy with market structure adjustment
                base_sl_pips = self.args.get('base_sl_pips', 4000)
                fixed_rrr = self.args.get('fixed_rrr', 2.0)
                sl_flexibility = self.args.get('sl_flexibility_percent', 25)
                
                # Calculate flexible risk
                min_risk = self.args.get('min_risk_per_trade', 0.004)
                max_risk = self.args.get('max_risk_per_trade', 0.006)
                base_risk = self.args.get('base_risk_per_trade', 0.005)
                
                signal_quality = signal_dict.get('signal_quality', 70)
                if signal_quality >= 85:
                    risk_multiplier = max_risk / base_risk
                elif signal_quality >= 75:
                    risk_multiplier = 1.0
                else:
                    risk_multiplier = min_risk / base_risk
                
                # Market structure adjustment
                use_market_structure = self.args.get('use_market_structure_sl', True)
                adjusted_sl_pips = base_sl_pips
                
                if use_market_structure:
                    adjustment_factor = self._calculate_sl_market_structure_adjustment(
                        alias, entry_price, signal_dict
                    )
                    max_adjustment = sl_flexibility / 100.0
                    bounded_adjustment = max(-max_adjustment, min(max_adjustment, adjustment_factor))
                    adjusted_sl_pips = base_sl_pips * (1 + bounded_adjustment)
                
                sl_distance_points = adjusted_sl_pips / 100.0
                tp_distance_points = sl_distance_points * fixed_rrr
            else:
                # Use original dynamic calculation
                sl_distance_points = abs(entry_price - stop_loss)
                tp_distance_points = abs(take_profit - entry_price)
            
            # Get regime data
            regime_data = self._last_regime_data_by_symbol.get(alias, {'state': 'RANGE', 'adx': 0, 'r2': 0})
            
            # Prepare signal for order executor
            auto_signal = {
                'symbol': alias,
                'direction': str(signal_dict.get('signal_type', '')).upper(),
                'entry_price': entry_price,
                'sl_distance_points': sl_distance_points,
                'tp_distance_points': tp_distance_points,
                'quality': signal_dict.get('signal_quality', 70),
                'regime': regime_data.get('state', 'RANGE'),
                'adx': regime_data.get('adx', 0),
                'confidence': signal_dict.get('confidence'),
                'risk_reward_ratio': signal_dict.get('risk_reward_ratio'),
                'pattern_type': signal_dict.get('pattern_type'),
                'liquidity_score': signal_dict.get('liquidity_score'),
                'volume_zscore': signal_dict.get('volume_zscore'),
                'vwap_distance_pct': signal_dict.get('vwap_distance_pct'),
                'orb_triggered': signal_dict.get('orb_triggered', False),
                'high_quality_time': signal_dict.get('high_quality_time', False),
                'swing_quality_score': signal_dict.get('swing_quality_score')
            }
            
            # Execute via order executor
            self.log(f"[AUTO-TRADING] 🚀 Opening reverse position: {alias} {auto_signal['direction']}")
            result = self.order_executor.execute_signal(auto_signal)
            
            if result.get('success'):
                self.log(f"[AUTO-TRADING] ✅ Reverse position opened successfully: {result.get('position_id', 'unknown')}")
            else:
                error = result.get('error', 'Unknown error')
                self.log(f"[AUTO-TRADING] ❌ Failed to open reverse position: {error}")
                
        except Exception as e:
            self.log(f"[AUTO-TRADING] ❌ Error executing reverse signal: {e}", level="ERROR")
            import traceback
            self.log(traceback.format_exc())
    
    def _calculate_ema(self, bars: List[Dict], period: int) -> float:
        """
        Calculate Exponential Moving Average (EMA) on close prices
        
        Args:
            bars: List of bar dictionaries with 'close' key
            period: EMA period (e.g., 34)
            
        Returns:
            EMA value as float
        """
        if not bars or len(bars) == 0:
            return 0.0
            
        if len(bars) < period:
            # Not enough bars - return simple average
            return sum(bar.get('close', 0) for bar in bars) / len(bars) if bars else 0.0
        
        # Calculate EMA
        multiplier = 2.0 / (period + 1.0)
        
        # Start with SMA of first 'period' bars
        ema = sum(bar.get('close', 0) for bar in bars[:period]) / period
        
        # Apply EMA formula to remaining bars
        for bar in bars[period:]:
            close = bar.get('close', 0)
            ema = (close * multiplier) + (ema * (1.0 - multiplier))
        
        return ema
    
    def _get_trend_from_ema34(self, alias: str) -> Optional[str]:
        """
        Determine trend direction using EMA(34) on close price
        
        Args:
            alias: Symbol alias (DAX, NASDAQ)
            
        Returns:
            'UP' if price > EMA(34) (uptrend), 'DOWN' if price < EMA(34) (downtrend), None if insufficient data
        """
        try:
            if alias not in self.market_data:
                return None
                
            bars = list(self.market_data[alias])
            if len(bars) < 34:
                return None
            
            # Get current price (last bar close)
            current_price = bars[-1].get('close', 0)
            if current_price == 0:
                return None
            
            # Calculate EMA(34)
            ema34 = self._calculate_ema(bars, 34)
            if ema34 == 0:
                return None
            
            # Determine trend
            if current_price > ema34:
                return 'UP'
            elif current_price < ema34:
                return 'DOWN'
            else:
                return None  # Price exactly at EMA - unclear trend
                
        except Exception as e:
            self.log(f"[TREND] Error calculating EMA(34) trend for {alias}: {e}", level="ERROR")
            return None

    def _try_auto_execute_signal(self, signal_dict: Dict[str, Any], alias: str):
        """Try to auto-execute a signal if auto-trading is enabled"""
        self.log(f"[AUTO-TRADING] 🔍 _try_auto_execute_signal called: {alias} {signal_dict.get('signal_type', 'UNKNOWN')} (auto_trading_enabled={self.auto_trading_enabled}, order_executor={'exists' if self.order_executor else 'None'})")
        
        if not self.auto_trading_enabled or not self.order_executor:
            self.log(f"[AUTO-TRADING] ❌ Early return: auto_trading_enabled={self.auto_trading_enabled}, order_executor={'exists' if self.order_executor else 'None'}")
            return

        self.log(f"[AUTO-TRADING] 🔍 Checking signal: {alias} {signal_dict.get('signal_type', 'UNKNOWN')} (max_positions={self.risk_manager.max_positions})")
        
        # ====================================================================
        # TREND FILTER: EMA(34) - Only trade WITH the trend, never against it
        # ====================================================================
        trend_direction = self._get_trend_from_ema34(alias)
        
        # Extract signal direction - handle both SignalType enum and string
        signal_type_raw = signal_dict.get('signal_type', signal_dict.get('direction', ''))
        if hasattr(signal_type_raw, 'value'):
            # SignalType enum object
            signal_direction = str(signal_type_raw.value).upper()
        elif hasattr(signal_type_raw, 'upper'):
            # String
            signal_direction = signal_type_raw.upper()
        else:
            # Fallback - convert to string
            signal_direction = str(signal_type_raw).upper()
        
        if trend_direction:
            # Trend is clear - enforce trend alignment
            if trend_direction == 'UP':
                # Uptrend: Only allow BUY signals
                if 'SELL' in signal_direction:
                    self.log(f"[AUTO-TRADING] ❌ BLOCKED: Protitrend signal detected")
                    self.log(f"[AUTO-TRADING] 📊 Trend: {trend_direction} (Price > EMA34), Signal: {signal_direction}")
                    self.log(f"[AUTO-TRADING] 🛡️ Only BUY signals allowed in uptrend - blocking SELL signal")
                    return
                else:
                    self.log(f"[AUTO-TRADING] ✅ Trend aligned: {trend_direction} trend, {signal_direction} signal")
            elif trend_direction == 'DOWN':
                # Downtrend: Only allow SELL signals
                if 'BUY' in signal_direction:
                    self.log(f"[AUTO-TRADING] ❌ BLOCKED: Protitrend signal detected")
                    self.log(f"[AUTO-TRADING] 📊 Trend: {trend_direction} (Price < EMA34), Signal: {signal_direction}")
                    self.log(f"[AUTO-TRADING] 🛡️ Only SELL signals allowed in downtrend - blocking BUY signal")
                    return
                else:
                    self.log(f"[AUTO-TRADING] ✅ Trend aligned: {trend_direction} trend, {signal_direction} signal")
        else:
            # Trend unclear (insufficient data or price at EMA) - allow both directions
            self.log(f"[AUTO-TRADING] ⚠️ Trend unclear (insufficient data or price at EMA34) - allowing signal")

        # ====================================================================
        # SIMPLE CHECK: Is there already an open position?
        # ====================================================================
        # Check account_monitor first (most reliable source of truth)
        open_positions_count = 0
        existing_position = None
        
        if self.account_monitor:
            with self.account_monitor._lock:
                account_positions = self.account_monitor._account_state.get('open_positions', [])
                open_positions_count = len([p for p in account_positions 
                                          if p.get('positionStatus') == 1 and p.get('tradeData', {}).get('volume', 0) > 0])
                
                if open_positions_count > 0:
                    # Get first open position
                    for acc_pos in account_positions:
                        if acc_pos.get('positionStatus') == 1 and acc_pos.get('tradeData', {}).get('volume', 0) > 0:
                            trade_data = acc_pos.get('tradeData', {})
                            symbol_id = trade_data.get('symbolId', 0)
                            position_alias = 'NASDAQ' if symbol_id == 208 else ('DAX' if symbol_id == 203 else f'SYMBOL_{symbol_id}')
                            trade_side = trade_data.get('tradeSide', 0)
                            direction_str = 'BUY' if trade_side == 2 else 'SELL'
                            
                            existing_position = {
                                'symbol': position_alias,
                                'direction': direction_str,
                                'position_id': acc_pos.get('positionId', 0),
                                'volume': trade_data.get('volume', 0)
                            }
                            break
        
        self.log(f"[AUTO-TRADING] 🔍 Found {open_positions_count} open position(s) in account_monitor")
        
        # CRITICAL FIX: Always check for existing positions on the same symbol
        # regardless of max_positions setting - we should never have multiple positions
        # on the same symbol unless explicitly allowed by position_conflicts strategy
        skip_duplicate_check = False
        all_positions = []
        
        # Check for existing positions on the SAME symbol (always, regardless of max_positions)
        existing_position_same_symbol = None
        if self.account_monitor:
            with self.account_monitor._lock:
                account_positions = self.account_monitor._account_state.get('open_positions', [])
                for acc_pos in account_positions:
                    if acc_pos.get('positionStatus') == 1 and acc_pos.get('tradeData', {}).get('volume', 0) > 0:
                        trade_data = acc_pos.get('tradeData', {})
                        symbol_id = trade_data.get('symbolId', 0)
                        # Map symbol_id to alias
                        position_alias = 'NASDAQ' if symbol_id == 208 else ('DAX' if symbol_id == 203 else f'SYMBOL_{symbol_id}')
                        if position_alias == alias:
                            trade_side = trade_data.get('tradeSide', 0)
                            direction_str = 'BUY' if trade_side == 1 else 'SELL'
                            existing_position_same_symbol = {
                                'symbol': position_alias,
                                'direction': direction_str,
                                'position_id': acc_pos.get('positionId', 0),
                                'volume': trade_data.get('volume', 0)
                            }
                            break
        
        # If max_positions = 1 and we have an open position, handle it
        if self.risk_manager.max_positions == 1 and open_positions_count > 0:
            if existing_position:
                existing_symbol = existing_position['symbol']
                existing_direction = existing_position['direction']
                existing_id = existing_position['position_id']
                
                self.log(f"[AUTO-TRADING] 🚫 MAX_POSITIONS=1: Found existing position: {existing_symbol} {existing_direction} (ID: {existing_id})")
                
                new_direction = signal_dict.get('signal_type', signal_dict.get('direction', ''))
                new_dir_norm = 'BUY' if 'BUY' in str(new_direction).upper() else 'SELL'
                existing_dir_norm = existing_direction
                
                self.log(f"[AUTO-TRADING] 🔍 New signal: {alias} {new_dir_norm}")
                
                # Same symbol, same direction - BLOCK
                if existing_symbol == alias and new_dir_norm == existing_dir_norm:
                    self.log(f"[AUTO-TRADING] ❌ BLOCKED: Position already open in same direction")
                    self.log(f"[AUTO-TRADING] 🛡️ Max positions = 1 - no scaling allowed")
                    return
                
                # Same symbol, opposite direction - CLOSE AND REVERSE
                if existing_symbol == alias and new_dir_norm != existing_dir_norm:
                    self.log(f"[AUTO-TRADING] 🔄 REVERSE: Closing {existing_symbol} {existing_dir_norm} to open {new_dir_norm}")
                    skip_duplicate_check = True
                    # Prepare position list for closing
                    from dataclasses import dataclass
                    @dataclass
                    class TempPosition:
                        symbol: str
                        direction: str
                        lots: float
                        entry_price: float
                        position_id: int
                    
                    all_positions = [TempPosition(
                        symbol=existing_symbol,
                        direction=existing_direction,
                        lots=existing_position['volume'] / 100.0,
                        entry_price=0,
                        position_id=existing_id
                    )]
                else:
                    # Different symbol - BLOCK (only 1 position allowed globally)
                    self.log(f"[AUTO-TRADING] ❌ BLOCKED: Position already open on {existing_symbol}")
                    self.log(f"[AUTO-TRADING] 🛡️ Max positions = 1 - only one position allowed at a time")
                    return
        elif existing_position_same_symbol:
            # CRITICAL FIX: Even if max_positions > 1, we should check for same symbol positions
            # and apply position_conflicts strategy
            existing_symbol = existing_position_same_symbol['symbol']
            existing_direction = existing_position_same_symbol['direction']
            existing_id = existing_position_same_symbol['position_id']
            
            self.log(f"[AUTO-TRADING] 🔍 Found existing position on same symbol: {existing_symbol} {existing_direction} (ID: {existing_id})")
            
            new_direction = signal_dict.get('signal_type', signal_dict.get('direction', ''))
            new_dir_norm = 'BUY' if 'BUY' in str(new_direction).upper() else 'SELL'
            existing_dir_norm = existing_direction
            
            self.log(f"[AUTO-TRADING] 🔍 New signal: {alias} {new_dir_norm}, Existing: {existing_symbol} {existing_dir_norm}")
            
            # Same symbol, same direction - BLOCK (no scaling allowed)
            if existing_symbol == alias and new_dir_norm == existing_dir_norm:
                self.log(f"[AUTO-TRADING] ❌ BLOCKED: Position already open in same direction on {alias}")
                self.log(f"[AUTO-TRADING] 🛡️ No scaling allowed - one position per symbol per direction")
                return
            
            # Same symbol, opposite direction - CLOSE AND REVERSE
            if existing_symbol == alias and new_dir_norm != existing_dir_norm:
                self.log(f"[AUTO-TRADING] 🔄 REVERSE: Closing {existing_symbol} {existing_dir_norm} to open {new_dir_norm}")
                skip_duplicate_check = True
                # Prepare position list for closing
                from dataclasses import dataclass
                @dataclass
                class TempPosition:
                    symbol: str
                    direction: str
                    lots: float
                    entry_price: float
                    position_id: int
                
                all_positions = [TempPosition(
                    symbol=existing_symbol,
                    direction=existing_direction,
                    lots=existing_position_same_symbol['volume'] / 100.0,
                    entry_price=0,
                    position_id=existing_id
                )]
        else:
            self.log(f"[AUTO-TRADING] ✅ No existing positions on {alias} - proceeding with signal")

        # POSITION CONFLICT CHECK - Configurable strategy (SAME_DIRECTION_ONLY or CLOSE_AND_REVERSE)
        conflict_config = self.args.get('position_conflicts', {})
        conflict_strategy = conflict_config.get('strategy', 'CLOSE_AND_REVERSE')  # Default to CLOSE_AND_REVERSE
        close_all_on_reverse = conflict_config.get('close_all_on_reverse', True)

        # Skip duplicate check if we already handled it above (max_positions=1 case)
        if skip_duplicate_check:
            self.log(f"[AUTO-TRADING] ⏭️ Skipping duplicate position check (already handled above)")
            # We already have all_positions from above, use that
            existing_positions = all_positions if 'all_positions' in locals() else []
            conflict_config = self.args.get('position_conflicts', {})
            conflict_strategy = conflict_config.get('strategy', 'CLOSE_AND_REVERSE')
            close_all_on_reverse = conflict_config.get('close_all_on_reverse', True)
            self.log(f"[AUTO-TRADING] ⏭️ Using positions from max_positions=1 check: {len(existing_positions)}")
        else:
            # Check for existing positions in BOTH risk_manager AND account_monitor
            # (risk_manager might not have position yet if order was just sent)
            # CRITICAL FIX: Use thread-safe getter to prevent race condition
            existing_positions = self.risk_manager.get_open_positions_copy(symbol=alias)
            self.log(f"[AUTO-TRADING] 🔍 Checking for existing {alias} positions: {len(existing_positions)} found in risk_manager")
            
            # Also check account_monitor for real positions from account
            if self.account_monitor:
                with self.account_monitor._lock:
                    account_positions = self.account_monitor._account_state.get('open_positions', [])
                    # Convert account positions to match risk_manager format
                    for acc_pos in account_positions:
                        trade_data = acc_pos.get('tradeData', {})
                        symbol_id = trade_data.get('symbolId')
                        volume = trade_data.get('volume', 0)
                        trade_side = trade_data.get('tradeSide', 0)  # 1=BUY, 2=SELL
                        status = acc_pos.get('positionStatus', 0)
                        
                        # Only consider open positions (status 1, volume > 0)
                        if status == 1 and volume > 0:
                            # Map symbol_id to alias using symbol_id_overrides and symbol_alias
                            position_alias = None
                            symbol_id_overrides = self.args.get('symbol_id_overrides', {})
                            symbol_alias_map = self.symbol_alias  # raw -> alias mapping
                            
                            # Find raw symbol name by symbol_id
                            raw_symbol = None
                            for raw, sym_id in symbol_id_overrides.items():
                                if sym_id == symbol_id:
                                    raw_symbol = raw
                                    break
                            
                            # Convert raw symbol to alias
                            if raw_symbol:
                                position_alias = symbol_alias_map.get(raw_symbol, raw_symbol)
                            
                            # If this position is for the same symbol, add to existing_positions check
                            if position_alias == alias:
                                # Check if already in risk_manager
                                already_tracked = any(
                                    p.symbol == alias and 
                                    getattr(p, 'position_id', None) == acc_pos.get('positionId')
                                    for p in existing_positions
                                )
                                
                                if not already_tracked:
                                    # Create a temporary position object for conflict checking
                                    from dataclasses import dataclass
                                    @dataclass
                                    class TempPosition:
                                        symbol: str
                                        direction: str
                                        lots: float
                                        entry_price: float
                                        position_id: int
                                    
                                    direction_str = 'BUY' if trade_side == 1 else 'SELL'
                                    price = acc_pos.get('price', 0)
                                    
                                    temp_pos = TempPosition(
                                        symbol=alias,
                                        direction=direction_str,
                                        lots=volume / 100.0,  # Convert volume to lots
                                        entry_price=price,
                                        position_id=acc_pos.get('positionId', 0)
                                    )
                                    existing_positions.append(temp_pos)
                                    self.log(f"[AUTO-TRADING] 🔍 Found position in account (not yet in risk_manager): {alias} {direction_str} {temp_pos.lots:.2f} lots")
            
            if existing_positions:
                self.log(f"[AUTO-TRADING] 🔍 Total existing positions for {alias}: {len(existing_positions)}")
            
            # Get conflict config for regular check
            conflict_config = self.args.get('position_conflicts', {})
            conflict_strategy = conflict_config.get('strategy', 'CLOSE_AND_REVERSE')
            close_all_on_reverse = conflict_config.get('close_all_on_reverse', True)
        
        if existing_positions:
            existing_pos = existing_positions[0]  # Get first position for this symbol

            # Determine directions
            new_direction = signal_dict.get('signal_type', signal_dict.get('direction', ''))
            existing_direction = getattr(existing_pos, 'direction', '')

            # Normalize direction strings
            new_dir_norm = 'BUY' if 'BUY' in str(new_direction).upper() else 'SELL'
            existing_dir_norm = 'BUY' if 'BUY' in str(existing_direction).upper() else 'SELL'

            if new_dir_norm == existing_dir_norm:
                # SAME DIRECTION: Block if max_positions = 1 (no scaling allowed)
                if self.risk_manager.max_positions == 1:
                    self.log(f"[AUTO-TRADING] ❌ Signal blocked - position already open in same direction ({new_dir_norm})")
                    self.log(f"[AUTO-TRADING] 🔄 Existing: {existing_dir_norm} @ {existing_pos.entry_price} | New: {new_dir_norm} @ {signal_dict.get('entry', 'N/A')}")
                    self.log(f"[AUTO-TRADING] 🛡️ Max positions = 1 - no scaling allowed")
                    return
                else:
                    # SAME DIRECTION: Allow scaling into trend (only if max_positions > 1)
                    self.log(f"[AUTO-TRADING] ✅ Scaling {alias} position - Same direction ({new_dir_norm})")
                    self.log(f"[AUTO-TRADING] 📊 Existing: {len(existing_positions)} positions, Entry: {existing_pos.entry_price}")
                    # Continue with execution...
            else:
                # OPPOSITE DIRECTION - handle based on strategy
                if conflict_strategy == "CLOSE_AND_REVERSE":
                    # CLOSE & REVERSE strategy
                    self.log(f"[AUTO-TRADING] 🔄 REVERSE signal detected: {alias} {existing_dir_norm} → {new_dir_norm}")

                    # Decide what to close
                    if close_all_on_reverse:
                        # Close ALL positions (more conservative)
                        # CRITICAL FIX: Use thread-safe getter
                        positions_to_close = self.risk_manager.get_open_positions_copy()
                        self.log(f"[AUTO-TRADING] Closing ALL {len(positions_to_close)} positions before reverse")
                    else:
                        # Close only positions for this symbol
                        positions_to_close = existing_positions
                        self.log(f"[AUTO-TRADING] Closing {len(positions_to_close)} {alias} positions before reverse")

                    # Close positions using PositionCloser
                    closed_count = 0
                    failed_count = 0

                    for pos in positions_to_close:
                        try:
                            pos_symbol = getattr(pos, 'symbol', 'unknown')
                            pos_lots = getattr(pos, 'lots', 0)
                            pos_direction = getattr(pos, 'direction', '')
                            pos_id = getattr(pos, 'position_id', 'unknown')

                            self.log(f"[AUTO-TRADING] Closing: {pos_symbol} {pos_direction} {pos_lots:.2f} lots (ID: {pos_id})")

                            # Prepare position dict for PositionCloser
                            position_data = {
                                'symbol': pos_symbol,
                                'lots': pos_lots,
                                'direction': pos_direction,
                                'position_id': pos_id
                            }

                            # Close position via order executor's position_closer
                            close_result = self.order_executor.position_closer.close_position(position_data)

                            if close_result.get('success'):
                                # CRITICAL FIX: Do NOT remove from risk_manager here!
                                # Wait for EXECUTION_EVENT confirmation (status 2 or 3) before removing.
                                # AccountStateMonitor will handle removal in _handle_position_close_for_risk_manager()
                                # when it receives EXECUTION_EVENT with closed position status.
                                # This prevents race condition where position is removed but close order fails on server.
                                closed_count += 1
                                self.log(f"[AUTO-TRADING] ✅ Close order sent for {pos_symbol} (waiting for EXECUTION_EVENT confirmation)")
                                self.log(f"[AUTO-TRADING] 📋 Position will be removed from risk_manager when EXECUTION_EVENT confirms close")
                            else:
                                failed_count += 1
                                error = close_result.get('error', 'Unknown error')
                                self.log(f"[AUTO-TRADING] ⚠️ Failed to close {pos_symbol}: {error}")

                        except Exception as close_error:
                            failed_count += 1
                            self.log(f"[AUTO-TRADING] ⚠️ Exception closing {pos_symbol}: {close_error}")
                            import traceback
                            self.log(f"[AUTO-TRADING] {traceback.format_exc()}")

                    self.log(f"[AUTO-TRADING] ✅ Closed {closed_count}/{len(positions_to_close)} positions (failed: {failed_count})")

                    if closed_count > 0:
                        # CRITICAL FIX: Store reverse signal and wait for close confirmation
                        # Don't open new position immediately - wait for EXECUTION_EVENT
                        for pos in positions_to_close:
                            pos_id = getattr(pos, 'position_id', None)
                            if pos_id:
                                with self._reverse_lock:
                                    self._pending_reverse_signals[str(pos_id)] = {
                                        'signal': signal_dict,
                                        'alias': alias,
                                        'direction': new_dir_norm,
                                        'timestamp': datetime.now().isoformat()
                                    }
                                self.log(f"[AUTO-TRADING] 📋 Stored pending reverse signal for position {pos_id}: {alias} {new_dir_norm}")
                        
                        self.log(f"[AUTO-TRADING] ⏳ Waiting for position close confirmation before opening reverse...")
                        self.log(f"[AUTO-TRADING] 🔄 Reverse position will open after EXECUTION_EVENT confirms close")
                        return  # Don't continue - wait for close confirmation
                    else:
                        self.log(f"[AUTO-TRADING] ❌ No positions closed - aborting reverse")
                        return

                else:
                    # SAME_DIRECTION_ONLY strategy (default behavior)
                    self.log(f"[AUTO-TRADING] ❌ Signal blocked - {alias} opposite direction conflict")
                    self.log(f"[AUTO-TRADING] 🔄 Existing: {existing_dir_norm} @ {existing_pos.entry_price} | New: {new_dir_norm} @ {signal_dict.get('entry', 'N/A')}")
                    self.log(f"[AUTO-TRADING] 🛡️ Protection: No hedge positions allowed (strategy: {conflict_strategy})")
                    return
        
        # Convert signal format (keep alias for order executor)
        entry_price = signal_dict.get('entry', 0)
        stop_loss = signal_dict.get('stop_loss', 0)
        take_profit = signal_dict.get('take_profit', 0)
        
        # Check if using fixed SL/TP strategy
        use_fixed_sl_tp = self.args.get('use_fixed_sl_tp', False)

        if use_fixed_sl_tp:
            # Advanced SL/TP strategy with market structure adjustment
            base_sl_pips = self.args.get('base_sl_pips', 4000)
            fixed_rrr = self.args.get('fixed_rrr', 2.0)
            sl_flexibility = self.args.get('sl_flexibility_percent', 25)

            # Calculate flexible risk (0.4-0.6% based on signal quality)
            min_risk = self.args.get('min_risk_per_trade', 0.004)
            max_risk = self.args.get('max_risk_per_trade', 0.006)
            base_risk = self.args.get('base_risk_per_trade', 0.005)

            signal_quality = signal_dict.get('signal_quality', 70)
            if signal_quality >= 85:
                risk_multiplier = max_risk / base_risk  # 1.2 (0.6%)
            elif signal_quality >= 75:
                risk_multiplier = 1.0  # Base risk (0.5%)
            else:
                risk_multiplier = min_risk / base_risk  # 0.8 (0.4%)

            # Market structure adjustment for SL
            use_market_structure = self.args.get('use_market_structure_sl', True)
            adjusted_sl_pips = base_sl_pips

            if use_market_structure:
                adjustment_factor = self._calculate_sl_market_structure_adjustment(
                    alias, entry_price, signal_dict
                )
                # Apply ±25% flexibility based on market structure
                max_adjustment = sl_flexibility / 100.0  # 0.25
                bounded_adjustment = max(-max_adjustment, min(max_adjustment, adjustment_factor))
                adjusted_sl_pips = base_sl_pips * (1 + bounded_adjustment)

                self.log(f"[AUTO-TRADING] Market structure adjustment: {bounded_adjustment*100:+.1f}% (SL: {base_sl_pips} → {adjusted_sl_pips:.0f} pips)")

            # Convert pips to points (for indices: 1 point = 100 pips)
            sl_distance_points = adjusted_sl_pips / 100.0
            tp_distance_points = sl_distance_points * fixed_rrr

            self.log(f"[AUTO-TRADING] Using ADVANCED SL/TP strategy for {alias}:")
            self.log(f"  Entry: {entry_price}")
            self.log(f"  Base SL: {base_sl_pips} pips, Adjusted SL: {adjusted_sl_pips:.0f} pips = {sl_distance_points:.1f} points")
            self.log(f"  TP: {adjusted_sl_pips * fixed_rrr:.0f} pips = {tp_distance_points:.1f} points (RRR: {fixed_rrr}:1)")
            self.log(f"  Risk multiplier: {risk_multiplier:.2f}x (Quality: {signal_quality}%)")
        else:
            # Use original dynamic calculation
            sl_distance_points = abs(entry_price - stop_loss)
            tp_distance_points = abs(take_profit - entry_price)
            
            self.log(f"[AUTO-TRADING] Using DYNAMIC SL/TP strategy for {alias}:")
            self.log(f"  Entry: {entry_price}, SL: {stop_loss}, TP: {take_profit}")
            self.log(f"  SL distance: {sl_distance_points:.1f} points, TP distance: {tp_distance_points:.1f} points")
        
        # Get regime data with ADX
        regime_data = self._last_regime_data_by_symbol.get(alias, {'state': 'RANGE', 'adx': 0, 'r2': 0})

        auto_signal = {
            'symbol': alias,  # Keep alias (DAX, NASDAQ) for order executor
            'direction': str(signal_dict.get('signal_type', '')).upper(),
            'entry_price': entry_price,
            'sl_distance_points': sl_distance_points,
            'tp_distance_points': tp_distance_points,
            'quality': signal_dict.get('signal_quality', 70),
            'regime': regime_data.get('state', 'RANGE'),
            'adx': regime_data.get('adx', 0),
            # Add all signal data for trade logger
            'confidence': signal_dict.get('confidence'),
            'risk_reward_ratio': signal_dict.get('risk_reward_ratio'),
            'pattern_type': signal_dict.get('pattern_type'),
            # Microstructure data
            'liquidity_score': signal_dict.get('liquidity_score'),
            'volume_zscore': signal_dict.get('volume_zscore'),
            'vwap_distance_pct': signal_dict.get('vwap_distance_pct'),
            'orb_triggered': signal_dict.get('orb_triggered', False),
            'high_quality_time': signal_dict.get('high_quality_time', False),
            # Swing context
            'swing_quality_score': signal_dict.get('swing_quality_score')
        }

        # Add swing state if available
        swing_state = None
        if hasattr(self, 'swing_engine') and self.swing_engine.current_state:
            swing_state = self.swing_engine.get_swing_summary()
            if swing_state:
                auto_signal['last_swing_high'] = swing_state.get('last_swing_high')
                auto_signal['last_swing_low'] = swing_state.get('last_swing_low')

        # Add ATR if available
        atr = self.current_atr.get(alias, 0)
        if atr > 0:
            auto_signal['atr'] = atr

        # === NEW: Apply SL/TP Band System ===
        # IMPORTANT: Skip band adjustment when sl_flexibility_percent is 0 (fixed SL/TP mode)
        sl_flexibility = self.args.get('sl_flexibility_percent', 25)

        if sl_flexibility > 0:
            # Band adjustment enabled - apply flexible bands
            try:
                # 1) Apply SL band to structural SL
                sl_struct_pts = float(auto_signal["sl_distance_points"])
                sl_final_pts, sl_diag = self.risk_manager.apply_structural_sl_band(alias, sl_struct_pts)

                if abs(sl_final_pts - sl_struct_pts) > 1e-6:
                    self.log(
                        f"[AUTO-TRADING] SL adjusted by band: "
                        f"{sl_struct_pts:.1f}pt ({int(sl_diag['structural_pips'])} pips) → "
                        f"{sl_final_pts:.1f}pt ({sl_diag['clamped_pips']} pips) | "
                        f"band: {sl_diag['lo_pips']}-{sl_diag['hi_pips']} pips"
                    )
                else:
                    self.log(
                        f"[AUTO-TRADING] SL within band: {sl_final_pts:.1f}pt "
                        f"({sl_diag['clamped_pips']} pips) | "
                        f"band: {sl_diag['lo_pips']}-{sl_diag['hi_pips']} pips, anchor: {sl_diag['anchor_pips']}"
                    )

                # 2) Apply TP band to structural TP
                tp_struct_pts = float(auto_signal["tp_distance_points"])
                tp_final_pts, tp_diag = self.risk_manager.apply_structural_tp_band(alias, sl_final_pts, tp_struct_pts)

                if abs(tp_final_pts - tp_struct_pts) > 1e-6 or tp_diag["source"] != "structural":
                    src_desc = "structural" if tp_diag["source"] == "structural" else f"RRR {float(tp_diag.get('tp_anchor_pips', 8000) / sl_diag.get('anchor_pips', 4000)):.1f}x"
                    self.log(
                        f"[AUTO-TRADING] TP adjusted by band: "
                        f"{tp_struct_pts:.1f}pt ({src_desc}) → "
                        f"{tp_final_pts:.1f}pt ({tp_diag['clamped_pips']} pips) | "
                        f"band: {tp_diag['lo_pips']}-{tp_diag['hi_pips']} pips"
                    )
                else:
                    self.log(
                        f"[AUTO-TRADING] TP within band: {tp_final_pts:.1f}pt "
                        f"({tp_diag['clamped_pips']} pips) | "
                        f"band: {tp_diag['lo_pips']}-{tp_diag['hi_pips']} pips, anchor: {tp_diag['tp_anchor_pips']}"
                    )

                # 3) CRITICAL: Update signal with band-adjusted values
                auto_signal["sl_distance_points"] = sl_final_pts
                auto_signal["tp_distance_points"] = tp_final_pts

            except Exception as e:
                self.log(f"[ERROR] SL/TP band application failed: {e}")
                # Continue with original values
        else:
            # Fixed SL/TP mode - no band adjustments
            self.log(f"[AUTO-TRADING] Fixed SL/TP mode (sl_flexibility_percent=0) - using structural values without band adjustment")

        try:
            self.log(f"[AUTO-TRADING] Checking signal for auto-execution: {alias} {auto_signal['direction']}")
            
            # Check if signal can be executed
            check_result = self.order_executor.can_execute_trade(auto_signal)
            
            if check_result['can_execute']:
                self.log(f"[AUTO-TRADING] Signal validated, executing...")
                self.log(f"[AUTO-TRADING] 🎯 About to call order_executor.execute_signal()")
                self.log(f"[AUTO-TRADING] 📋 Signal data: {auto_signal}")
                
                # Execute the signal
                result = self.order_executor.execute_signal(auto_signal)
                
                self.log(f"[AUTO-TRADING] 📊 Execution result: {result}")
                
                if result['executed']:
                    self.log(f"[AUTO-TRADING] ✅ Signal executed successfully: {result['position_id']}")
                    
                    # Update Home Assistant with execution status
                    self._safe_set_state(
                        f"sensor.auto_trading_{alias.lower()}_last_trade",
                        state="EXECUTED",
                        attributes={
                            "position_id": result['position_id'],
                            "symbol": auto_signal['symbol'],
                            "direction": auto_signal['direction'],
                            "position_size": result['position_data']['position_size'],
                            "entry_price": result['position_data']['entry_price'],
                            "sl_price": result['position_data']['sl_price'],
                            "tp_price": result['position_data']['tp_price'],
                            "risk_amount": result['position_data']['risk_amount'],
                            "executed_at": datetime.now().isoformat()
                        }
                    )
                else:
                    self.log(f"[AUTO-TRADING] ❌ Signal execution failed: {result.get('reason', 'Unknown error')}")
            else:
                issues = ', '.join(check_result.get('issues', []))
                self.log(f"[AUTO-TRADING] Signal rejected: {issues}")
                
        except Exception as e:
            self.log(f"[AUTO-TRADING] Error during auto-execution: {e}")
            self.log(f"[AUTO-TRADING] Traceback: {traceback.format_exc()}")

    def _calculate_sl_market_structure_adjustment(self, alias: str, entry_price: float, signal_dict: dict) -> float:
        """Calculate SL adjustment factor based on market structure"""
        try:
            adjustment_factor = 0.0
            pivot_weight = self.args.get('pivot_influence_weight', 0.3)
            atr_weight = self.args.get('atr_influence_weight', 0.4)
            swing_weight = self.args.get('swing_influence_weight', 0.3)

            # 1. PIVOT LEVELS INFLUENCE
            current_atr = self.current_atr.get(alias, 0)
            if hasattr(self, 'pivot_calc') and self.pivot_calc:
                pivot_data = self.current_pivots.get(alias, {})
                if pivot_data:
                    pivot_adjustment = self._get_pivot_sl_adjustment(entry_price, pivot_data, current_atr, alias)
                    adjustment_factor += pivot_adjustment * pivot_weight

            # 2. ATR VOLATILITY INFLUENCE
            if current_atr > 0:
                atr_adjustment = self._get_atr_sl_adjustment(current_atr, alias)
                adjustment_factor += atr_adjustment * atr_weight

            # 3. SWING LEVELS INFLUENCE
            if hasattr(self, 'swing_engine') and self.swing_engine:
                swing_summary = self.swing_engine.get_swing_summary()
                if swing_summary:
                    swing_adjustment = self._get_swing_sl_adjustment(entry_price, swing_summary, signal_dict)
                    adjustment_factor += swing_adjustment * swing_weight

            # 4. ROUND NUMBERS INFLUENCE
            round_adjustment = self._get_round_number_adjustment(entry_price, current_atr, alias)
            adjustment_factor += round_adjustment * 0.1

            return adjustment_factor
        except Exception as e:
            self.log(f"[ERROR] Market structure adjustment failed: {e}")
            return 0.0

    def _get_pivot_sl_adjustment(self, entry_price: float, pivot_data: dict, atr: float = None, symbol_alias: str = None) -> float:
        """Calculate SL adjustment based on proximity to pivot levels - ATR normalized"""
        try:
            pp = pivot_data.get('PP', entry_price)
            r1 = pivot_data.get('R1', entry_price + 50)
            s1 = pivot_data.get('S1', entry_price - 50)
            distances = [abs(entry_price - level) for level in [pp, r1, s1]]
            min_distance = min(distances)

            # ATR normalization - use symbol specs if available
            if atr and atr > 0:
                symbol_spec = self.args.get('symbol_specs', {}).get(symbol_alias, {})
                pivot_close_atr = symbol_spec.get('pivot_close_atr', 0.2)
                pivot_far_atr = symbol_spec.get('pivot_far_atr', 0.8)

                min_distance_atr = min_distance / atr

                if min_distance_atr < pivot_close_atr:
                    adjustment = -0.10
                    if hasattr(self, 'log'):
                        self.log(f"[PIVOT_SL] Penalizing close pivot: {min_distance:.1f} ({min_distance_atr:.2f} ATR) < {pivot_close_atr} ATR → {adjustment:.1%}")
                    return adjustment
                elif min_distance_atr > pivot_far_atr:
                    adjustment = 0.10
                    if hasattr(self, 'log'):
                        self.log(f"[PIVOT_SL] Rewarding distant pivot: {min_distance:.1f} ({min_distance_atr:.2f} ATR) > {pivot_far_atr} ATR → {adjustment:.1%}")
                    return adjustment
                else:
                    if hasattr(self, 'log'):
                        self.log(f"[PIVOT_SL] Neutral pivot distance: {min_distance:.1f} ({min_distance_atr:.2f} ATR)")
                    return 0.0
            else:
                # Fallback to old hardcoded values when ATR not available
                if min_distance < 20:
                    return -0.10
                elif min_distance > 80:
                    return 0.10
                return 0.0
        except Exception as e:
            if hasattr(self, 'log'):
                self.log(f"[PIVOT_SL] Error in pivot SL adjustment: {e}")
            return 0.0

    def _get_atr_sl_adjustment(self, atr: float, alias: str) -> float:
        """Calculate SL adjustment based on ATR volatility"""
        try:
            ranges = {'DAX': {'low': 8, 'high': 15}, 'NASDAQ': {'low': 10, 'high': 20}}.get(alias, {'low': 10, 'high': 20})
            if atr < ranges['low']:
                return -0.15
            elif atr > ranges['high']:
                return 0.15
            return 0.0
        except Exception:
            return 0.0

    def _get_swing_sl_adjustment(self, entry_price: float, swing_summary: dict, signal_dict: dict) -> float:
        """Calculate SL adjustment based on swing structure"""
        try:
            direction = signal_dict.get('signal_type', '')
            last_high = swing_summary.get('last_high', {})
            last_low = swing_summary.get('last_low', {})

            if str(direction).upper() in ['SELL', 'SHORT'] and last_high:
                distance = abs(entry_price - last_high.get('price', entry_price))
                return -0.12 if distance < 30 else 0.12 if distance > 100 else 0.0
            elif str(direction).upper() in ['BUY', 'LONG'] and last_low:
                distance = abs(entry_price - last_low.get('price', entry_price))
                return -0.12 if distance < 30 else 0.12 if distance > 100 else 0.0
            return 0.0
        except Exception:
            return 0.0

    def _get_round_number_adjustment(self, price: float, atr: float = None, symbol_alias: str = None) -> float:
        """Calculate SL adjustment based on proximity to round numbers - ATR normalized"""
        try:
            # Get round number thresholds from symbol specs or use defaults
            symbol_spec = self.args.get('symbol_specs', {}).get(symbol_alias, {}) if symbol_alias else {}
            round_close_atr = symbol_spec.get('round_close_atr', 0.1)  # Default: within 0.1 ATR
            round_medium_atr = symbol_spec.get('round_medium_atr', 0.05)  # Default: within 0.05 ATR

            # Calculate distances to round numbers
            price_int = int(price)
            remainder_100 = price_int % 100
            remainder_50 = price_int % 50

            # Distance to nearest 100-level
            dist_100 = min(remainder_100, 100 - remainder_100)
            # Distance to nearest 50-level
            dist_50 = min(remainder_50, 50 - remainder_50)

            if atr and atr > 0:
                # ATR-normalized distances
                dist_100_atr = dist_100 / atr
                dist_50_atr = dist_50 / atr

                if dist_100_atr <= round_medium_atr:
                    adjustment = -0.08
                    if hasattr(self, 'log'):
                        self.log(f"[ROUND_SL] Major round level {price_int}: dist={dist_100} ({dist_100_atr:.3f} ATR) → {adjustment:.1%}")
                    return adjustment
                elif dist_50_atr <= round_close_atr:
                    adjustment = -0.05
                    if hasattr(self, 'log'):
                        self.log(f"[ROUND_SL] Minor round level {price_int}: dist={dist_50} ({dist_50_atr:.3f} ATR) → {adjustment:.1%}")
                    return adjustment
                else:
                    return 0.0
            else:
                # Fallback to old hardcoded logic when ATR not available
                if remainder_100 <= 5 or remainder_100 >= 95:
                    return -0.08
                elif remainder_50 <= 3 or remainder_50 >= 47:
                    return -0.05
                return 0.0
        except Exception as e:
            if hasattr(self, 'log'):
                self.log(f"[ROUND_SL] Error in round number adjustment: {e}")
            return 0.0

    def _start_account_monitoring(self, kwargs):
        """Start account monitoring after WebSocket is connected"""
        try:
            self.log("[ACCOUNT_MONITOR] 🚀 Starting delayed account monitoring...")
            if self.account_monitor and hasattr(self.ctrader_client, 'is_connected'):
                if self.ctrader_client.is_connected():
                    self.log("[ACCOUNT_MONITOR] ✅ WebSocket connected, registering callbacks...")
                    # First register callbacks when WebSocket is ready
                    self.account_monitor.register_with_client()
                    self.log("[ACCOUNT_MONITOR] ✅ Callbacks registered, starting periodic updates...")
                    # Then start periodic updates
                    self.account_monitor.start_periodic_updates()
                    self.log("[ACCOUNT_MONITOR] ✅ Account monitoring started successfully")
                else:
                    self.log("[ACCOUNT_MONITOR] ⚠️ WebSocket not connected yet, retrying in 3 seconds...")
                    self.run_in(self._start_account_monitoring, 3)
            else:
                self.log("[ACCOUNT_MONITOR] ❌ Account monitor not available")
        except Exception as e:
            self.log(f"[ACCOUNT_MONITOR] ❌ Error starting account monitoring: {e}")
            # Retry once more
            self.run_in(self._start_account_monitoring, 5)
