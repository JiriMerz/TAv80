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
import appdaemon.plugins.hass.hassapi as hass
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional
from collections import deque
import traceback
from typing import Dict
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
            
            # Přidat pravidelné čištění každých 5 minut
            self.run_every(self.cleanup_old_entities, "now+300", 300)
            
            # Přidat rychlejší čištění pro kritické entity každou minutu
            self.run_every(self.quick_cleanup, "now+60", 60)
                    
            
            self.risk_manager = RiskManager({
            'account_balance': self.args.get('account_balance', 100000),
            'account_currency': self.args.get('account_currency', 'CZK'),
            'max_risk_per_trade': self.args.get('max_risk_per_trade', 0.01),
            'max_risk_total': self.args.get('max_risk_total', 0.03),
            'max_positions': self.args.get('max_positions', 3),
            'daily_loss_limit': self.args.get('daily_loss_limit', 0.02),
            'symbol_specs': self.args.get('symbol_specs', {}),
            'risk_adjustments': self.args.get('risk_adjustments', {}),
            'regime_adjustments': self.args.get('regime_adjustments', {}),
            'volatility_adjustments': self.args.get('volatility_adjustments', {})
            })
            
            self.listen_state(self.clear_all_signals, "input_boolean.clear_signals", new="on")
            
            # Analysis params
            self.pivot_calc   = PivotCalculator(self.args.get('pivots', {}))

            # Use SimpleSwingDetector for reliable swing detection
            swing_config = self.args.get('swings', {})
            self.swing_engine = SimpleSwingDetector(config={
                'lookback': 5,  # Bars on each side for local extrema
                'min_move_pct': 0.0015  # 0.15% minimum move between swings
            })
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
                    balance_tracker=self.balance_tracker
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

                self.log("[AUTO-TRADING] ✅ MVP auto-trading components initialized")
            else:
                self.log("[AUTO-TRADING] Auto-trading disabled in configuration")
                self.time_manager = None
                self.balance_tracker = None
                self.daily_risk_tracker = None
                self.order_executor = None

            # Listener pro zapnutí/vypnutí auto-tradingu (MUST be after auto_trading_enabled is initialized!)
            self.listen_state(self.toggle_auto_trading, "input_boolean.auto_trading_enabled")
            self.log("[AUTO-TRADING] ✅ Toggle listener registered")

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
                    balance_tracker=self.balance_tracker if self.auto_trading_enabled else None  # CRITICAL: Pass balance tracker
                )
                # CRITICAL: Give cTrader client reference to Account Monitor for balance fallback
                self.ctrader_client.account_state_monitor = self.account_monitor
                self.log("[ACCOUNT_MONITOR] Account monitoring initialized")
                self.log("[ACCOUNT_MONITOR] ✅ Account state monitor initialized")
                self.log("[ACCOUNT_MONITOR] ✅ Account monitor linked to cTrader client for balance fallback")
            else:
                self.log("[ACCOUNT_MONITOR] Account monitoring disabled in configuration")
            
            self.log(f"[TEST] CTrader client created: {self.ctrader_client}")  # PŘIDAT
            self.log(f"[TEST] Has start method: {hasattr(self.ctrader_client, 'start')}")  # P
            
            self._precreate_entities()

            # Wrap callbacks to use micro-dispatcher (from WS thread → main thread)
            def _bar_cb(raw_symbol, bar, *rest):
                history = rest[0] if rest else None
                self._enqueue_callback('bar', raw_symbol, bar, history)

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
            else:
                # Account monitoring disabled
                pass

            self.log("[TEST] About to call ctrader_client.start()")  # PŘIDAT
            self.ctrader_client.start(on_tick_callback=_tick_cb, on_bar_callback=_bar_cb, on_execution_callback=_execution_cb, on_account_callback=_account_cb)
            self.log(f"[TEST] Has start method: {hasattr(self.ctrader_client, 'start')}")  # PŘIDAT

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
            self.run_every(self._update_sprint2_entities_with_data, "now+30", 60)  # Update every minute

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

        Retry pattern: wait 0s, 1s, 2s before giving up
        """
        from aiohttp import ClientResponseError

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
                            self.log(f"[DISPATCH] Timer cancelled successfully")

                        # Create new timer with new interval
                        self._dispatch_timer_handle = self.run_every(self._process_dispatch_queue, f"now+{new_interval}", new_interval)
                        self.log(f"[DISPATCH] Adaptive interval: {new_interval*1000:.0f}ms (queue: {queue_size})")

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
                        self.log(f"[DISPATCH] Time limit reached, re-queued {len(remaining)} items")
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
                            self._on_bar_direct(*args, **kwargs)
                        elif callback_type == 'price':
                            self._on_price_direct(*args, **kwargs)
                        elif callback_type == 'execution':
                            self._on_execution_direct(*args, **kwargs)
                        elif callback_type == 'account':
                            self._on_account_direct(*args, **kwargs)
                        else:
                            self.log(f"[DISPATCH] Unknown callback type: {callback_type}")

                    except Exception as e:
                        self.log(f"[DISPATCH] Error processing {callback_type}: {e}")

                processing_time = (time.time() - start_time) * 1000  # ms
                if processed_count > 0:
                    coalesced_count = len(temp_queue) - len(all_items) if temp_queue else 0
                    # Callback processing completed

        except Exception as e:
            self.log(f"[DISPATCH] Critical error in queue processor: {e}")

            # EMERGENCY FALLBACK: Restart dispatcher if critical error
            try:
                if self._dispatch_timer_handle is not None:
                    self.cancel_timer(self._dispatch_timer_handle)

                # Restart with base interval (no adaptive)
                self._dispatch_timer_handle = self.run_every(self._process_dispatch_queue, f"now+{self._base_interval}", self._base_interval)
                self._adaptive_dispatch_enabled = False  # Disable adaptive after error
                self.log(f"[DISPATCH] EMERGENCY RESTART: Fixed {self._base_interval*1000:.0f}ms intervals, adaptive disabled")

            except Exception as restart_error:
                self.log(f"[DISPATCH] FATAL: Cannot restart dispatcher: {restart_error}")
                # Last resort: clear queue to prevent memory issues
                with self._dispatch_lock:
                    self._dispatch_queue.clear()
                self.log(f"[DISPATCH] Queue cleared due to fatal error")

    def _enqueue_callback(self, callback_type: str, *args, **kwargs):
        """Thread-safe callback enqueuer with adaptive priority-aware dropping"""
        with self._dispatch_lock:
            perf_config = self.args.get('performance', {})
            max_queue_size = perf_config.get('max_queue_size', 300) if self._queue_limiting_enabled else 800
            priority_queue_size = perf_config.get('priority_queue_size', 200) if self._queue_limiting_enabled else 700
            emergency_queue_size = perf_config.get('emergency_queue_size', 800)

            current_queue_size = len(self._dispatch_queue)

            # EMERGENCY: Clear queue if critically large
            if current_queue_size >= emergency_queue_size:
                self.log(f"[DISPATCH] EMERGENCY: Queue size {current_queue_size} >= {emergency_queue_size}, clearing all non-execution events")
                execution_events = [item for item in self._dispatch_queue if item[0] == 'execution']
                self._dispatch_queue.clear()
                for event in execution_events:
                    self._dispatch_queue.append(event)
                self.log(f"[DISPATCH] EMERGENCY: Queue cleared, kept {len(execution_events)} execution events")
                current_queue_size = len(self._dispatch_queue)

            # Enhanced queue size limiting
            if self._queue_limiting_enabled and current_queue_size >= max_queue_size:
                # Smart dropping - preserve execution events, drop old price events preferentially
                dropped_count = 0
                original_queue = list(self._dispatch_queue)
                self._dispatch_queue.clear()

                # Keep execution events and recent bar events
                for item in original_queue:
                    item_type = item[0]
                    if item_type == 'execution':
                        self._dispatch_queue.append(item)  # Always keep executions
                    elif item_type == 'bar':
                        self._dispatch_queue.append(item)  # Always keep bars
                    elif item_type == 'price' and len(self._dispatch_queue) < priority_queue_size:
                        self._dispatch_queue.append(item)  # Keep some recent prices
                    else:
                        dropped_count += 1

                if dropped_count > 0:
                    self.log(f"[DISPATCH] Smart drop: removed {dropped_count} old price events, "
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
            
            # Pokud dostáváme všechny bary (bootstrap), nahradit celou historii
            if all_bars and len(all_bars) > len(self.market_data[alias]):
                self.log(f"[BOOTSTRAP] Loading {len(all_bars)} historical bars for {alias}")
                self._bootstrap_in_progress = True  # Enable bootstrap timing mode
                self.market_data[alias] = deque(all_bars, maxlen=5000)
                
                # Okamžitě spustit analýzu
                if len(all_bars) >= self.analysis_min_bars:
                    self.process_market_data(alias)
                    self.log(f"[BOOTSTRAP] Immediate analysis started for {alias}")

                # After bootstrap analysis, switch back to normal timing
                self.run_in(lambda _: setattr(self, '_bootstrap_in_progress', False), 5)
            else:
                # Normální přidání nového baru
                self.market_data[alias].append(bar)

                # Update microstructure volume profile with new bar volume
                if hasattr(self, 'microstructure') and 'volume' in bar and bar['volume'] > 0:
                    bar_timestamp = bar.get('timestamp')
                    if isinstance(bar_timestamp, str):
                        bar_timestamp = datetime.fromisoformat(bar_timestamp.replace('Z', '+00:00'))
                    self.microstructure.update_volume_profile(alias, bar_timestamp, bar['volume'])

                if len(self.market_data[alias]) >= self.analysis_min_bars:
                    self.process_market_data(alias)
            
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
            self.error(f"_on_bar error: {e}")

    def log_status(self, _):
        """Periodic status logging with system state publishing"""
        risk_status = self.risk_manager.get_risk_status()
        parts = []
        
        # Stav připojení
        up = "on" if (self.ctrader_client and self.ctrader_client.is_connected()) else "off"
        self._safe_set_state("binary_sensor.ctrader_connected", state=up)
        
        # Publikovat hlavní stav systému
        self._safe_set_state(
            "sensor.trading_analysis_status",
            state="RUNNING" if up == "on" else "STOPPED",
            attributes={
                "friendly_name": "Trading Analysis Status",
                "last_update": datetime.now().isoformat(),
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
            in_hours = self._is_within_trading_hours(alias) if hasattr(self, '_is_within_trading_hours') else True
            has_data = n >= self.analysis_min_bars
            
            if up != "on":
                status = "DISCONNECTED"
            elif not has_data:
                status = "WARMING_UP"
            elif in_hours:
                status = "TRADING"
            else:
                status = "ANALYSIS_ONLY"
            
            # Publikovat stav symbolu
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
                self._startup_time = datetime.now(timezone.utc)
            
            time_since_startup = (datetime.now(timezone.utc) - self._startup_time).total_seconds()
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
        from datetime import datetime, timedelta
        
        # === KONTROLA STAVU SYSTÉMU PŘED ZPRACOVÁNÍM ===
        # Analýza se provádí jen když je cTrader Connected a Analysis Running
        ctrader_connected = self.get_state("binary_sensor.ctrader_connected")
        analysis_status = self.get_state("sensor.trading_analysis_status")
        
        if ctrader_connected != "on":
            # Throttle log - loguj max jednou za 5 minut
            if not hasattr(self, '_last_ctrader_check_log') or alias not in self._last_ctrader_check_log:
                if not hasattr(self, '_last_ctrader_check_log'):
                    self._last_ctrader_check_log = {}
                self._last_ctrader_check_log[alias] = datetime.now()
                self.log(f"[ANALYSIS] ⏸️ Skipping analysis for {alias} - cTrader not connected (status: {ctrader_connected})")
            elif (datetime.now() - self._last_ctrader_check_log.get(alias, datetime.now())).seconds > 300:
                self._last_ctrader_check_log[alias] = datetime.now()
                self.log(f"[ANALYSIS] ⏸️ Skipping analysis for {alias} - cTrader not connected (status: {ctrader_connected})")
            return
        
        if analysis_status != "RUNNING":
            # Throttle log - loguj max jednou za 5 minut
            if not hasattr(self, '_last_analysis_check_log') or alias not in self._last_analysis_check_log:
                if not hasattr(self, '_last_analysis_check_log'):
                    self._last_analysis_check_log = {}
                self._last_analysis_check_log[alias] = datetime.now()
                self.log(f"[ANALYSIS] ⏸️ Skipping analysis for {alias} - Analysis not running (status: {analysis_status})")
            elif (datetime.now() - self._last_analysis_check_log.get(alias, datetime.now())).seconds > 300:
                self._last_analysis_check_log[alias] = datetime.now()
                self.log(f"[ANALYSIS] ⏸️ Skipping analysis for {alias} - Analysis not running (status: {analysis_status})")
            return
        
        bars = list(self.market_data.get(alias, []))
        
        # Kontrola minimálního počtu barů
        if len(bars) < self.analysis_min_bars:
            now = datetime.now()
            last_log = self._last_insufficient_data_log.get(alias)
            if not last_log or (now - last_log).seconds > self.log_throttle_seconds:
                self.log(f"[MAIN] {alias}: Insufficient bars {len(bars)}/{self.analysis_min_bars}")
                self._last_insufficient_data_log[alias] = now
            return
        
        # === VŽDY SPOČÍTAT A PUBLIKOVAT ANALÝZU ===
        
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
        
        ## 2. Pivots calculation - VŽDY (NEW: Using PivotCalculator)
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
                
                # DEBUG - přidat tento log
                self.log(f"[PIVOTS] {alias}: PP={piv.get('pivot', 0):.2f}, "
                        f"R1={piv.get('r1', 0):.2f}, S1={piv.get('s1', 0):.2f}")

                # Store pivot data for market structure analysis
                self.current_pivots[alias] = piv

                self._publish_pivots(alias, piv, current_price=self._get_current_price(alias))
            else:
                # Fallback to simple calculation
                piv = self.calculate_simple_pivots(bars)
                self.log(f"[PIVOTS] {alias} (fallback): PP={piv.get('pivot', 0):.2f}")

                # Store fallback pivot data for market structure analysis
                self.current_pivots[alias] = piv

                self._publish_pivots(alias, piv, current_price=self._get_current_price(alias))
            
        except Exception as e:
            self.error(f"[ERROR] Pivot calculation failed for {alias}: {e}")
            self.error(traceback.format_exc())
        
        # 3. Swing detection - VŽDY
        try:
            timeframe = self.args.get('timeframe', 'M5')
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

            # Log swing detection for monitoring
            self.log(f"[SWING] {alias}: {len(swing_state.swings)} swings, trend={trend_value}, quality={swing_state.swing_quality:.0f}%")

        except Exception as e:
            self.error(f"[ERROR] Swing detection failed for {alias}: {e}")
            self.error(traceback.format_exc())
        
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
        
        # Kontrola cooldown
        if not hasattr(self, '_last_signal_time'):
            self._last_signal_time = {}
        
        now = datetime.now()
        last_signal = self._last_signal_time.get(alias)
        if last_signal and (now - last_signal).seconds < 1800:  # 30 minut
            return
        
        # Kontrola aktivních tiketů
        active_tickets = self._count_active_tickets(alias)
        if active_tickets > 0:
            return
        
        # Kontrola obchodních hodin
        in_hours = self._is_within_trading_hours(alias)
        if not in_hours:
            # DEBUG: Log why we're not trading
            if not hasattr(self, '_last_hours_log') or (datetime.now() - self._last_hours_log).seconds > 300:
                self._last_hours_log = datetime.now()
                self.log(f"[TRADING_HOURS] {alias} Outside trading hours at {datetime.now().strftime('%H:%M')} CET")
            return
        else:
            # DEBUG: Confirm we're in trading hours
            if not hasattr(self, '_hours_confirmed') or alias not in self._hours_confirmed:
                if not hasattr(self, '_hours_confirmed'):
                    self._hours_confirmed = set()
                self._hours_confirmed.add(alias)
                self.log(f"[TRADING_HOURS] {alias} Active trading hours confirmed at {datetime.now().strftime('%H:%M')} CET")
        
        # Kontrola risk manageru
        risk_status = self.risk_manager.get_risk_status()
        if not risk_status.can_trade:
            return
        
        # === MICROSTRUCTURE ANALYSIS ===
        micro_data = {}
        if hasattr(self, 'microstructure') and len(bars) >= 14:
            try:
                micro_data = self.microstructure.get_microstructure_summary(alias, bars)
                if micro_data:
                    self.log(f"[MICRO] {alias} Liquidity: {micro_data.get('liquidity_score', 0):.2f}, "
                            f"Vol Z-score: {micro_data.get('volume_zscore', 0):.2f}, "
                            f"VWAP dist: {micro_data.get('vwap_distance', 0):.2f}%")
                    
                    # Store for later use
                    if not hasattr(self, 'micro_data'):
                        self.micro_data = {}
                    self.micro_data[alias] = micro_data
                    
                    # Check if it's quality trading time
                    if not self.edge.is_quality_trading_time(alias, micro_data):
                        liquidity = micro_data.get('liquidity_score', 0)
                        is_high_quality = micro_data.get('is_high_quality_time', False)

                        min_liquidity_threshold = self.args.get('microstructure', {}).get('min_liquidity_score', 0.1)
                        if liquidity < min_liquidity_threshold:
                            self.log(f"[MICRO] {alias} Poor market conditions (liquidity {liquidity:.2f} < {min_liquidity_threshold}), skipping signal generation")
                        elif not is_high_quality:
                            self.log(f"[MICRO] {alias} Outside prime trading hours, skipping signal generation")
                        else:
                            self.log(f"[MICRO] {alias} Suboptimal trading conditions, skipping signal generation")
                        return
                        
            except Exception as e:
                self.error(f"[ERROR] Microstructure analysis failed for {alias}: {e}")
        
        # === EDGE DETECTION pro signály ===
        # (Kontrola stavu se provádí na začátku process_market_data, takže zde už není potřeba)
        try:
            signals = self.edge.detect_signals(
                bars=bars,
                regime_state=regime_data,  # Use new regime_data with trend_direction
                pivot_levels=piv,
                swing_state=swing,
                microstructure_data=micro_data  # ← PŘIDAT microstructure data
            )
            
            if signals:
                sig = signals[0]
                
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
                
                if position:
                    # Publikovat tiket
                    self._publish_single_trade_ticket(alias, position, sig)
                    self._last_signal_time[alias] = now
                    
                    # === AUTO-TRADING: Try to execute signal automatically ===
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
                
    # ---------------- publishers ----------------
    def _publish_regime(self, alias: str, regime: Dict[str, Any]):
        """Publish regime data - COMPLETE FIXED VERSION"""
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

        # Store full regime data for analytics (including ADX)
        self._last_regime_data_by_symbol[alias] = {
            'state': state,
            'adx': adx_float,
            'r2': r2_float
        }

        # Get trend direction if available
        trend_direction = regime.get("trend_direction")
        
        # Create enhanced state with direction
        enhanced_state = state
        if trend_direction and state == "TREND":
            enhanced_state = f"TREND_{trend_direction}"
        
        # Publikovat hlavní stav režimu
        self._safe_set_state(
            f"sensor.{alias.lower()}_m1_regime_state", 
            state=enhanced_state, 
            attributes={
                "adx": round(adx_float, 2),
                "r2": round(r2_float, 3),
                "trend_direction": trend_direction,
                "friendly_name": f"{alias} Regime",
                "icon": "mdi:chart-box-outline"
            }
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
            self._last_signal_time = {}
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
            
    def _is_within_trading_hours(self, alias: str) -> bool:
        """Kontrola zda jsme v obchodních hodinách"""
        config = self.args.get('trading_hours', {})
        if not config.get('enabled', False):
            return True
        
        from datetime import datetime
        import pytz
        
        tz = pytz.timezone(config.get('timezone', 'Europe/Prague'))
        now = datetime.now(tz)
        day = now.strftime('%A').lower()
        
        symbol_hours = config.get(alias, {})
        time_range = symbol_hours.get(day)
        
        if not time_range:
            return False
        
        try:
            start, end = time_range.split('-')
            start_time = datetime.strptime(start, '%H:%M').time()
            end_time = datetime.strptime(end, '%H:%M').time()
            return start_time <= now.time() <= end_time
        except:
            return True  # Při chybě povolit
    
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
        try:
            symbol = data.get('symbol')
            if not symbol:
                return
                
            alias = self.symbol_alias.get(symbol, symbol)
            bars = list(self.market_data.get(alias, []))
            
            if len(bars) < 20:
                return
            
            # KONTROLA: Pokud už máme aktivní tiket, negenerovat ORB
            if self._count_active_tickets(alias) > 0:
                return
            
            # Inicializovat ORB tracking
            if not hasattr(self, '_orb_triggered'):
                self._orb_triggered = {}
            
            # ORB pouze jednou denně a pouze pokud nemáme signál
            today_key = f"{alias}_{datetime.now().date()}"
            if today_key in self._orb_triggered:
                return  # Už bylo dnes
            
            # Detect Opening Range patterns
            or_data = self.microstructure.detect_opening_range(alias, bars)
            
            # ORB signal pouze pokud:
            # 1. Byl trigger
            # 2. Nemáme aktivní signál
            # 3. Jsme v obchodních hodinách
            # NOVĚ: Generovat ORB signál pokud byl trigger a nemáme aktivní pozici
            if or_data.get('orb_triggered') and not or_data.get('progressive_or'):
                if self._is_within_trading_hours(alias) and self._count_active_tickets(alias) == 0:
                    # Označit jako triggered
                    self._orb_triggered[today_key] = True

                    # NOVĚ: Skutečně vygenerovat signál
                    self._generate_orb_signal(alias, or_data, bars)
                    self.log(f"[{alias}] ORB signal generated after breakout detection")
                    
        except Exception as e:
            self.error(f"Error in bar handler: {e}")
    
    def _update_microstructure_entities(self, alias: str, micro_summary: Dict):
        """Update HA entities with microstructure data (v2 - new entity IDs to avoid corrupted entities)"""
        try:
            # Volume Z-score entity - use safe set_state to prevent HA internal attributes
            self._safe_set_state(f"sensor.{alias.lower()}_volume_zscore_v2",
                        state=round(micro_summary.get('volume_zscore', 0), 2),
                        attributes={
                            "friendly_name": f"{alias} Volume Z-Score",
                            "icon": "mdi:chart-bell-curve"
                        })

            # VWAP distance entity
            self._safe_set_state(f"sensor.{alias.lower()}_vwap_distance_v2",
                        state=round(micro_summary.get('vwap_distance', 0), 2),
                        attributes={
                            "friendly_name": f"{alias} VWAP Distance",
                            "vwap": micro_summary.get('vwap', 0)
                        })

            # Liquidity score entity
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
    
    def _generate_orb_signal(self, alias: str, or_data: Dict, bars: List[Dict]):
        """Generate signal from Opening Range Breakout with microstructure validation"""
        from datetime import datetime
        
        # === KONTROLA STAVU SYSTÉMU PŘED GENEROVÁNÍM ORB SIGNÁLU ===
        # ORB signály se generují jen když je cTrader Connected a Analysis Running
        ctrader_connected = self.get_state("binary_sensor.ctrader_connected")
        analysis_status = self.get_state("sensor.trading_analysis_status")
        
        if ctrader_connected != "on":
            # Throttle log - loguj max jednou za 5 minut
            if not hasattr(self, '_last_orb_ctrader_check_log') or alias not in self._last_orb_ctrader_check_log:
                if not hasattr(self, '_last_orb_ctrader_check_log'):
                    self._last_orb_ctrader_check_log = {}
                self._last_orb_ctrader_check_log[alias] = datetime.now()
                self.log(f"[ORB] ⏸️ Skipping ORB signal for {alias} - cTrader not connected (status: {ctrader_connected})")
            elif (datetime.now() - self._last_orb_ctrader_check_log.get(alias, datetime.now())).seconds > 300:
                self._last_orb_ctrader_check_log[alias] = datetime.now()
                self.log(f"[ORB] ⏸️ Skipping ORB signal for {alias} - cTrader not connected (status: {ctrader_connected})")
            return
        
        if analysis_status != "RUNNING":
            # Throttle log - loguj max jednou za 5 minut
            if not hasattr(self, '_last_orb_analysis_check_log') or alias not in self._last_orb_analysis_check_log:
                if not hasattr(self, '_last_orb_analysis_check_log'):
                    self._last_orb_analysis_check_log = {}
                self._last_orb_analysis_check_log[alias] = datetime.now()
                self.log(f"[ORB] ⏸️ Skipping ORB signal for {alias} - Analysis not running (status: {analysis_status})")
            elif (datetime.now() - self._last_orb_analysis_check_log.get(alias, datetime.now())).seconds > 300:
                self._last_orb_analysis_check_log[alias] = datetime.now()
                self.log(f"[ORB] ⏸️ Skipping ORB signal for {alias} - Analysis not running (status: {analysis_status})")
            return
        
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
                    return

                # Check high quality time
                is_high_quality = micro_data.get('is_high_quality_time', False)
                if not is_high_quality:
                    self.log(f"[ORB] {alias} Outside prime trading hours, rejecting ORB signal")
                    return

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
            
        except Exception as e:
            self.error(f"Error generating ORB signal: {e}")

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
                
                # Volume Z-score
                self._safe_set_state(f"sensor.{alias_lower}_volume_zscore_v2",
                              state=0.0,
                              attributes={
                                  "friendly_name": f"{alias} Volume Z-Score",
                                  "icon": "mdi:chart-bell-curve"
                              })
                
                # VWAP
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
                
                # VWAP distance
                self._safe_set_state(f"sensor.{alias_lower}_vwap_distance_v2",
                              state=0.0,
                              attributes={
                                  "friendly_name": f"{alias} VWAP Distance",
                                  "icon": "mdi:percent"
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
                
                # ATR profiles with debug info
                current_atr = self.current_atr.get(alias, 0)
                self._safe_set_state(f"sensor.{alias_lower}_atr_current_v2",
                              state=round(current_atr, 4),  # More precision for comparison
                              attributes={
                                  "friendly_name": f"{alias} ATR Current (Wilder's)",
                                  "unit_of_measurement": "pts",
                                  "icon": "mdi:pulse",
                                  "method": "Wilder's Smoothing",
                                  "period": 14,
                                  "description": "Compare with platform ATR(14)"
                              })
                
                self._safe_set_state(f"sensor.{alias_lower}_atr_expected_v2",
                              state=round(current_atr, 2),  # Start with same as current
                              attributes={
                                  "friendly_name": f"{alias} ATR Expected",
                                  "unit_of_measurement": "pts",
                                  "icon": "mdi:target"
                              })
                
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
        """Update Sprint 2 entities with real data from microstructure analysis"""
        try:
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
            
    def cleanup_old_entities(self, kwargs):
        """Odstranit staré entity - běží každých 5 minut"""
        try:
            all_states = self.get_state()
            removed_count = 0
            current_time = datetime.now()
            
            for entity_id in all_states:
                try:
                    state = self.get_state(entity_id)
                    
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
                    self.log(f"[CLEANUP] Error processing {entity_id}: {e}")
                    continue
            
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
        """Rychlé čištění unavailable entity každou minutu (optimized)"""
        try:
            all_states = self.get_state()
            unavailable_entities = []

            # Collect unavailable entities (limit to first 20 per run)
            count = 0
            for entity_id in all_states:
                if count >= 20:  # Limit processing to prevent timeouts
                    break
                if self.get_state(entity_id) == "unavailable":
                    unavailable_entities.append(entity_id)
                    count += 1

            # Batch purge if any found
            if unavailable_entities:
                try:
                    self.call_service("recorder/purge_entities", entity_id=unavailable_entities)
                    self.log(f"[CLEANUP] Removed {len(unavailable_entities)} old entities")
                except Exception as e:
                    self.log(f"[CLEANUP] Purge failed: {e}")

        except Exception as e:
            self.log(f"[CLEANUP] Error: {e}")      
        
        
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
    
    def _try_auto_execute_signal(self, signal_dict: Dict[str, Any], alias: str):
        """Try to auto-execute a signal if auto-trading is enabled"""
        if not self.auto_trading_enabled or not self.order_executor:
            return

        # POSITION CONFLICT CHECK - Configurable strategy (SAME_DIRECTION_ONLY or CLOSE_AND_REVERSE)
        conflict_config = self.args.get('position_conflicts', {})
        conflict_strategy = conflict_config.get('strategy', 'SAME_DIRECTION_ONLY')
        close_all_on_reverse = conflict_config.get('close_all_on_reverse', True)

        # Check for existing positions in BOTH risk_manager AND account_monitor
        # (risk_manager might not have position yet if order was just sent)
        existing_positions = [p for p in self.risk_manager.open_positions if p.symbol == alias]
        
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
            existing_pos = existing_positions[0]  # Get first position for this symbol

            # Determine directions
            new_direction = signal_dict.get('signal_type', signal_dict.get('direction', ''))
            existing_direction = getattr(existing_pos, 'direction', '')

            # Normalize direction strings
            new_dir_norm = 'BUY' if 'BUY' in str(new_direction).upper() else 'SELL'
            existing_dir_norm = 'BUY' if 'BUY' in str(existing_direction).upper() else 'SELL'

            if new_dir_norm == existing_dir_norm:
                # SAME DIRECTION: Allow scaling into trend
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
                        positions_to_close = list(self.risk_manager.open_positions)
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
                                # Remove from risk manager after successful close order
                                self.risk_manager.remove_position(pos_symbol, pnl_czk=0)
                                closed_count += 1
                                self.log(f"[AUTO-TRADING] ✅ Closed {pos_symbol} (close order sent)")
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
                        self.log(f"[AUTO-TRADING] 🔄 Opening REVERSE position: {alias} {new_dir_norm}")
                        # Continue to open new position...
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
