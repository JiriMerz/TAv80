# ================================
# /config/apps/ctrader_client.py
# ================================
"""
cTrader WebSocket Client – M5 Version with Wide Stops
- M5 bar aggregation (5-minute candles)
- Full authentication and subscription flow
- Proper error handling

2025-01-03
"""

from __future__ import annotations  # volitelné, ale pomáhá do budoucna

from typing import List, Dict, Deque, Optional, Callable, Any  # <<< DŮLEŽITÉ
from collections import deque
import os
from datetime import datetime, timezone, timedelta
import asyncio
import json
import threading
import logging
import websockets

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # PŘIDAT - zajistí že logy projdou

# PŘIDAT TOTO - zajistí že logy se dostanou ven
import sys
# Module loading complete

# --- cTrader JSON payloadType constants (OFFICIAL OpenAPI v2) ---
# Core authentication and connection
PT_APPLICATION_AUTH_REQ     = 2100  # PROTO_OA_APPLICATION_AUTH_REQ
PT_APPLICATION_AUTH_RES     = 2101  # PROTO_OA_APPLICATION_AUTH_RES
PT_ACCOUNT_AUTH_REQ         = 2102  # PROTO_OA_ACCOUNT_AUTH_REQ (FIXED: was 2113!)
PT_ACCOUNT_AUTH_RES         = 2103  # PROTO_OA_ACCOUNT_AUTH_RES (FIXED: was 2114!)
PT_GET_ACCS_BY_TOKEN_REQ    = 2149  # PROTO_OA_GET_ACCOUNTS_BY_ACCESS_TOKEN_REQ
PT_GET_ACCS_BY_TOKEN_RES    = 2150  # PROTO_OA_GET_ACCOUNTS_BY_ACCESS_TOKEN_RES
PT_ERROR_RES                = 2142
PT_PING_REQ                 = 50
PT_PONG_RES                 = 51

# Market data subscriptions
PT_SUBSCRIBE_SPOTS_REQ      = 2127  # PROTO_OA_SUBSCRIBE_SPOTS_REQ
PT_SUBSCRIBE_SPOTS_RES      = 2128  # PROTO_OA_SUBSCRIBE_SPOTS_RES
PT_UNSUBSCRIBE_SPOTS_REQ    = 2129  # PROTO_OA_UNSUBSCRIBE_SPOTS_REQ
# PT_RECONCILE removed - JSON protocol uses only PT_TRADER_REQ/RES for positions
PT_SPOT_EVENT               = 2131  # PROTO_OA_SPOT_EVENT
PT_GET_TRENDBARS_REQ        = 2137
PT_GET_TRENDBARS_RES        = 2138

# Trading operations
PT_NEW_ORDER_REQ            = 2106
PT_NEW_ORDER_RES            = 2107
PT_EXECUTION_EVENT          = 2126
PT_ORDER_ERROR_EVENT        = 2132

# Account information
PT_TRADER_REQ               = 2124  # PROTO_OA_TRADER_REQ (JSON protocol)
PT_TRADER_RES               = 2125  # PROTO_OA_TRADER_RES (JSON protocol)
PT_DEAL_LIST_REQ            = 2133  # PROTO_OA_DEAL_LIST_REQ (for account balance and PnL)
PT_DEAL_LIST_RES            = 2134  # PROTO_OA_DEAL_LIST_RES (for account balance and PnL)
# PT_POSITIONS_REQ/RES REMOVED - caused collision with GET_ACCS_BY_TOKEN (2149/2150)
PT_POSITION_STATUS_EVENT    = 2151

# Timeframe constants
PERIOD_M5                   = 3          


class CTraderClient:
    def __init__(self, config: Dict):

        logger.info("[CTRADER] Starting client...")  # PŘIDAT

        # Store full config for fallback values
        self.config = config or {}

        # Connection credentials
        self.ws_uri = config.get('ws_uri', 'wss://demo.ctraderapi.com:5036')
        self.client_id = config.get('client_id')
        self.client_secret = config.get('client_secret')
        self.access_token = config.get('access_token')
        self.ctid_trader_account_id = config.get('ctid_trader_account_id')
        self.trader_login = config.get('trader_login')

        # Account ID configuration validation
        if str(self.client_id).startswith(str(self.ctid_trader_account_id) or ""):
            logger.warning(f"[CONFIG] ctid_trader_account_id might be set to client_id!")

        if self.ctid_trader_account_id == 16612:
            logger.error(f"[CONFIG] ctid_trader_account_id is set to client_id! Should be trader account ID")


        # Symbols configuration
        self.requested_symbols = [s.get("name", s) for s in (config.get("symbols") or [])]
        self.symbol_id_overrides = config.get('symbol_id_overrides', {})
        self.bar_warmup = int(config.get('bar_warmup', 20))

        # Runtime state
        self.ws = None
        self._msg_id = 0
        self._loop = None
        self._ws_thread = None
        self._running = True

        self.symbol_to_id: Dict[str, int] = {}
        self.id_to_symbol: Dict[int, str] = {}

        # CENTRALIZED MESSAGE PUMP - Request/Response pairing system
        self._pending_requests: Dict[str, Dict] = {}  # clientMsgId -> {payload_type, symbol_id, future}
        self._response_futures: Dict[str, asyncio.Future] = {}  # msgId -> Future for responses

        # THREAD-SAFE COMMAND QUEUE for cross-thread operations (order execution, etc.)
        self._command_queue = None  # Will be initialized when loop starts
        self._command_processor_task = None

        # Market data storage
        self.bars: Dict[str, deque] = {}
        self.current_price: Dict[str, Dict] = {}
        self.last_bar_block: Dict[str, datetime] = {}  # For M5 aggregation

        # Callbacks
        self.on_tick_callback: Optional[Callable] = None
        self.on_bar_callback: Optional[Callable] = None
        self.on_account_callback: Optional[Callable] = None
        self.on_execution_callback: Optional[Callable] = None

        # Account monitoring callbacks (multiple subscribers)
        self._account_callbacks = []
        self._price_callbacks = []
        self._execution_callbacks = []

        # Account state tracking
        # Initialize with configured balance (fallback if PT_TRADER_RES fails)
        logger.debug(f"[ACCOUNT] Config keys at init: {list(config.keys())}")
        configured_balance = float(config.get('account_balance', 0))
        logger.info(f"[ACCOUNT] Configured balance from config: {configured_balance}")

        self.account_balance: float = configured_balance
        self.account_equity: float = configured_balance
        self.account_margin_used: float = 0.0
        self.account_free_margin: float = configured_balance
        self.account_currency: str = "CZK"

        if configured_balance > 0:
            logger.info(f"[ACCOUNT] Initialized with configured balance: {configured_balance:,.2f} CZK")
        else:
            logger.error(f"[ACCOUNT] ❌ No account_balance in config! Will use 0 until execution events")

        # Position storage for reference
        self.current_positions: List[Dict] = []

        self.use_historical_bootstrap = config.get('use_historical_bootstrap', True)
        self.history_cache_dir = config.get('history_cache_dir', './cache')
        self.history_bars_count = config.get('history_bars_count', 300)

        logger.info(f"CTrader client initialized for {self.ws_uri}")

    # ------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------
    
    def start(self, on_tick_callback=None, on_bar_callback=None, on_execution_callback=None, on_account_callback=None):
        """Start the WebSocket client"""
        import sys
        # Starting with callbacks registered
        logger.info("[CTRADER] Starting client...")

        self.on_tick_callback = on_tick_callback
        self.on_bar_callback = on_bar_callback
        self.on_execution_callback = on_execution_callback
        self.on_account_callback = on_account_callback
        self._running = True
        
        # Creating WebSocket thread
        self._ws_thread = threading.Thread(target=self._run_loop, daemon=True)
        
        # Starting WebSocket thread
        self._ws_thread.start()

        # WebSocket thread started
        logger.info(f"[CTRADER] Thread started: {self._ws_thread.is_alive()}")

    def stop(self):
        """Stop the WebSocket client"""
        self._running = False
        try:
            if self.ws:
                asyncio.run_coroutine_threadsafe(self.ws.close(), self._loop)
        except Exception:
            pass

    def is_connected(self) -> bool:
        """Check if WebSocket is connected"""
        return self.ws is not None

    # ------------------------------------------------------------
    # Communication helpers
    # ------------------------------------------------------------
    
    async def _send(self, payload_type: int, payload: Dict, expected_response_type: int = None, expected_symbol_id: int = None) -> str:
        """Send message to cTrader server with proper request tracking"""
        self._msg_id += 1
        client_msg_id = str(self._msg_id)
        msg = {
            "clientMsgId": client_msg_id,
            "payloadType": payload_type,
            "payload": payload
        }

        # Register pending request for proper pairing
        if expected_response_type:
            self._pending_requests[client_msg_id] = {
                "payload_type": expected_response_type,
                "symbol_id": expected_symbol_id,
                "sent_at": datetime.now(timezone.utc),
                "request_payload": payload.copy()
            }

        # CRITICAL DEBUG: Log the complete message being sent
        if payload_type == PT_ACCOUNT_AUTH_REQ:
            logger.debug(f"[SEND] Sending PT_ACCOUNT_AUTH_REQ:")
            logger.debug(f"[SEND] Complete message: {msg}")
            logger.debug(f"[SEND] Payload only: {payload}")

            # BULLETPROOF VALIDATION: Prevent sending wrong account ID
            sent_account_id = payload.get('ctidTraderAccountId')
            if sent_account_id == 16612:
                logger.error(f"[SEND] ❌ CRITICAL ERROR: About to send WRONG account ID: {sent_account_id}")
                logger.error(f"[SEND] ❌ This would cause UNSUPPORTED_MESSAGE error!")
                logger.error(f"[SEND] ❌ Expected account ID: 42478187")
                raise RuntimeError(f"CRITICAL: Prevented sending wrong account ID {sent_account_id}! Expected 42478187")

            logger.debug(f"[SEND] ✅ Validation passed: sending correct account ID {sent_account_id}")

        await self.ws.send(json.dumps(msg))
        logger.debug(f"Sent: {payload_type} (id={client_msg_id})")
        return client_msg_id

    def send_from_other_thread(self, payload_type: int, payload: dict, timeout: float = None):
        """Thread-safe sender for cross-thread communication"""
        if not self._loop:
            raise RuntimeError("WS loop not ready")

        # Check authorization gate - queue if not ready
        if not getattr(self, '_authorized', False):
            logger.info(f"[WS] Not authorized yet → queueing send (type: {payload_type})")
            if not hasattr(self, '_send_queue'):
                self._send_queue = []
            self._send_queue.append((payload_type, payload))
            return "QUEUED"

        # Send immediately if authorized
        logger.debug(f"[WS] Authorized, sending immediately (type: {payload_type})")
        fut = asyncio.run_coroutine_threadsafe(
            self._send(payload_type, payload),
            self._loop
        )

        # Enhanced timeout handling - server still processes even after timeout
        if timeout:
            try:
                result = fut.result(timeout)
                logger.debug(f"[WS] Send completed successfully within {timeout}s")
                return result
            except asyncio.TimeoutError:
                logger.info(f"[WS] Send timeout after {timeout}s (normal - server still processing)")
                logger.info(f"[WS] Order queued on server, awaiting EXECUTION_EVENT (2126) for confirmation")
                return None  # Timeout is normal - server processes async
            except Exception as e:
                logger.warning(f"[WS] Send error: {e}")
                logger.info(f"[WS] Attempting graceful fallback, awaiting EXECUTION_EVENT")
                return None
        else:
            return fut  # Return Future for async handling

    async def _recv_until(self, expected_type: int, expect_id: Optional[str] = None, timeout: float = 10.0):
        """Receive messages until expected type arrives with proper message routing"""
        start = asyncio.get_event_loop().time()
        logger.debug(f"[RECV_UNTIL] Waiting for type {expected_type}, expect_id: {expect_id}, timeout: {timeout}s")

        while True:
            if asyncio.get_event_loop().time() - start > timeout:
                logger.error(f"[RECV_UNTIL] ❌ Timeout waiting for {expected_type} after {timeout}s")
                # Clean up pending request if timeout
                if expect_id and expect_id in self._pending_requests:
                    del self._pending_requests[expect_id]
                raise TimeoutError(f"Timeout waiting for {expected_type}")

            raw = await self.ws.recv()
            msg = json.loads(raw)
            pt = msg.get("payloadType")
            msg_id = msg.get("clientMsgId")

            # Only log received messages for non-frequent types
            if pt not in [2131, 2125, 2120]:
                logger.debug(f"[RECV_UNTIL] 📥 Received: type={pt}, msgId={msg_id}, expected={expected_type}")

            # Check for errors
            if pt == PT_ERROR_RES:
                error = msg.get("payload", {})
                logger.error(f"[RECV_UNTIL] ❌ cTrader error: {error}")
                # Clean up pending request on error
                if expect_id and expect_id in self._pending_requests:
                    del self._pending_requests[expect_id]
                raise RuntimeError(f"cTrader error: {error}")

            # Validate message using pending requests registry
            is_expected_message = False
            if pt == expected_type:
                if expect_id:
                    if msg_id == expect_id:
                        # Validate symbolId for trendbars to prevent out-of-order confusion
                        if expect_id in self._pending_requests:
                            pending = self._pending_requests[expect_id]
                            expected_symbol_id = pending.get("symbol_id")

                            if expected_symbol_id and pt == PT_GET_TRENDBARS_RES:
                                response_symbol_id = msg.get("payload", {}).get("symbolId")
                                if response_symbol_id and int(response_symbol_id) != int(expected_symbol_id):
                                    logger.warning(f"[RECV_UNTIL] ⚠️ SYMBOL ID MISMATCH: got {response_symbol_id}, expected {expected_symbol_id}")
                                    logger.debug(f"[RECV_UNTIL] This is likely out-of-order delivery, forwarding to main router")
                                    # Forward to main router instead of ignoring
                                    await self._route_message_to_main_handler(msg)
                                    continue

                            # Valid response - clean up pending request
                            del self._pending_requests[expect_id]
                        is_expected_message = True
                    else:
                        logger.debug(f"[RECV_UNTIL] ⚠️ Type match but wrong ID: got {msg_id}, expected {expect_id}")
                        # Forward to main router
                        logger.debug(f"[RECV_UNTIL] DEBUG: About to enter try block for forwarding")
                        try:
                            logger.debug(f"[RECV_UNTIL] 📤 INSIDE TRY: About to forward msgId={msg_id} to router...")
                            await self._route_message_to_main_handler(msg)
                            logger.debug(f"[RECV_UNTIL] ✅ AFTER FORWARD: Forwarding completed for msgId={msg_id}")
                        except Exception as e:
                            logger.error(f"[RECV_UNTIL] ❌ EXCEPTION CAUGHT: Error forwarding message: {e}")
                            import traceback
                            logger.error(f"[RECV_UNTIL] Traceback: {traceback.format_exc()}")
                        logger.debug(f"[RECV_UNTIL] DEBUG: After try-except block, about to continue")
                        continue
                else:
                    is_expected_message = True

            if is_expected_message:
                logger.debug(f"[RECV_UNTIL] ✅ Found expected message: type={pt}, msgId={msg_id}")
                return msg

            # CRITICAL FIX: Forward ALL unexpected messages to main router instead of ignoring
            # Only log forwarding for non-frequent message types
            if pt not in [2131, 2125]:  # Skip PT_SPOT_EVENT and PT_TRADER_RES
                logger.info(f"[RECV_UNTIL] 📨 Forwarding unexpected message to main router: type={pt}")
            await self._route_message_to_main_handler(msg)

    async def _route_message_to_main_handler(self, msg: Dict):
        """Route message to appropriate handler in main receive loop"""
        # Removed debug entry log to reduce verbosity
        try:
            pt = msg.get("payloadType")
            msg_id = msg.get("clientMsgId")
            # Only log routing for important message types
            if pt not in [2131, 2125, 2120]:  # Skip frequent message types
                logger.debug(f"[🔄 ROUTER] Routing message: type={pt}, msgId={msg_id}")

            if pt == PT_SPOT_EVENT:
                self._handle_spot_event(msg.get("payload", {}))
            elif pt == PT_ERROR_RES:
                logger.error(f"cTrader ERROR (routed): {msg}")
            elif pt == PT_PONG_RES:
                pass  # Ignore pongs
            elif pt == PT_NEW_ORDER_RES:
                logger.info(f"[🚨 ORDER RESPONSE] NEW_ORDER_RES (routed): {msg}")
                self._handle_order_response(msg)
            elif pt == PT_EXECUTION_EVENT:
                logger.info(f"[🚨 EXECUTION EVENT] EXECUTION_EVENT (routed): {msg}")
                self._handle_execution_event(msg)
                self._handle_account_event(msg)
            elif pt == PT_ORDER_ERROR_EVENT:
                logger.warning(f"[🚨 ORDER ERROR] ORDER_ERROR_EVENT (routed): {msg}")
                self._handle_order_error(msg)
            elif pt in [PT_TRADER_RES, PT_POSITION_STATUS_EVENT]:
                logger.info(f"[ACCOUNT] Account event (routed): {pt}")
                self._handle_account_event(msg)
            elif pt == 2134:  # PT_DEAL_LIST_RES
                logger.debug(f"[💰 DEAL_LIST] DEBUG: About to call _handle_deal_list_response for msgId={msg_id}")
                self._handle_deal_list_response(msg)
                logger.debug(f"[💰 DEAL_LIST] DEBUG: Returned from _handle_deal_list_response")
            elif pt == PT_GET_TRENDBARS_RES:
                logger.info(f"[📊 TRENDBARS] Processing out-of-order trendbars response (routed)")
                # Handle out-of-order trendbars by matching to correct symbol
                self._handle_out_of_order_trendbars(msg)
            else:
                logger.debug(f"[🔄 ROUTER] Unknown message type {pt} routed to main handler")

        except Exception as e:
            logger.error(f"[🔄 ROUTER] Error routing message: {e}")

    def _handle_out_of_order_trendbars(self, msg: Dict):
        """Handle out-of-order trendbars responses by matching to correct symbol"""
        try:
            payload = msg.get("payload", {})
            response_symbol_id = payload.get("symbolId")
            msg_id = msg.get("clientMsgId")

            if response_symbol_id:
                # Find the symbol name for this ID
                symbol = self.id_to_symbol.get(int(response_symbol_id))
                if symbol:
                    logger.info(f"[📊 TRENDBARS] Processing out-of-order response for {symbol} (ID: {response_symbol_id})")
                    # Process trendbars similar to _bootstrap_history
                    self._process_trendbars_response(symbol, payload, msg_id)
                else:
                    logger.warning(f"[📊 TRENDBARS] Unknown symbol ID in out-of-order response: {response_symbol_id}")
            else:
                logger.warning(f"[📊 TRENDBARS] No symbolId in out-of-order trendbars response")

        except Exception as e:
            logger.error(f"[📊 TRENDBARS] Error handling out-of-order trendbars: {e}")

    def _process_trendbars_response(self, symbol: str, payload: Dict, msg_id: str):
        """Process trendbars response for a specific symbol"""
        try:
            arr = payload.get("trendbar", [])
            logger.info(f"[📊 TRENDBARS] Processing {len(arr)} bars for {symbol} (msgId: {msg_id})")

            if arr and self.on_bar_callback:
                # Process similar to _bootstrap_history logic
                processed = []
                for i, bar in enumerate(arr):
                    # Similar processing as in _bootstrap_history
                    ts_ms = bar.get("utcTimestampInMinutes", 0) * 60 * 1000 if "utcTimestampInMinutes" in bar else 0

                    low_int = bar.get("low", 0)
                    delta_open = bar.get("deltaOpen", 0)
                    delta_high = bar.get("deltaHigh", 0)
                    delta_close = bar.get("deltaClose", 0)

                    low_price = low_int / 100000.0
                    open_price = (low_int + delta_open) / 100000.0
                    high_price = (low_int + delta_high) / 100000.0
                    close_price = (low_int + delta_close) / 100000.0

                    ts_iso = datetime.fromtimestamp(ts_ms/1000.0, tz=timezone.utc).isoformat()

                    processed.append({
                        "timestamp": ts_iso,
                        "open": open_price,
                        "high": high_price,
                        "low": low_price,
                        "close": close_price,
                        "volume": bar.get("volume", 0),
                        "spread": 2.0 if "US100" in symbol else 1.5
                    })

                if processed:
                    # Update bars storage
                    if symbol not in self.bars:
                        self.bars[symbol] = deque(maxlen=500)
                    self.bars[symbol].extend(processed[-100:])  # Add recent bars

                    # Send to callback
                    self.on_bar_callback(symbol, processed[-1], processed)
                    logger.info(f"[📊 TRENDBARS] Sent {len(processed)} out-of-order bars for {symbol}")

        except Exception as e:
            logger.error(f"[📊 TRENDBARS] Error processing trendbars response for {symbol}: {e}")

    # helper: receive (pro stávající volání v kódu)
    async def _receive(self, expect_type: int | None = None, expect_id: str | None = None):
        """
        Vrátí další zprávu, nebo čeká na konkrétní typ přes _recv_until.
        Zachovává stávající styl volání: await self._receive(PT_..., expect_id=...)
        """
        if expect_type is None:
            raw = await self.ws.recv()
            return json.loads(raw)
        msg = await self._recv_until(expect_type, expect_id=expect_id)
        return msg

    # ------------------------------------------------------------
    # Internal event loop
    # ------------------------------------------------------------
    
    def _run_loop(self):
        """Run the asyncio event loop in a thread"""
        
        import sys
        # WebSocket run loop started
        
        try:
            logger.info("[CTRADER] Thread _run_loop started")
            # Creating event loop
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            # Event loop created
            logger.info("[CTRADER] Starting connect_and_stream")
            # Starting connection stream
            self._loop.run_until_complete(self.connect_and_stream())
        except Exception as e:
            logger.error(f"[CTRADER] WebSocket loop crashed: {e}")
            logger.error(f"[CTRADER] Thread crashed: {e}")
            import traceback
            traceback.print_exc()
            
    async def connect_and_stream(self):
        """Main connection and streaming loop"""
        import sys
        # Connection initialization
        
        logger.info(f"[CTRADER] connect_and_stream started, running={self._running}")
        logger.info(f"[CTRADER] WS URI: {self.ws_uri}")
        
        while self._running:
            # Starting connection loop iteration
            try:
                # Attempting connection
                logger.info("Attempting connection...")
                await self._connect()
                # Connected, starting authentication
                await self._authorize_all()
                # Authorized, setting up subscriptions
                await self._subscribe_symbols()
                # Getting initial account snapshot
                await self._get_account_snapshot()

                # THREAD-SAFE COMMAND QUEUE: Initialize after authorization
                # Starting command processor
                await self._start_command_processor()

                # Subscriptions complete, starting message loop
                await self._recv_loop()
            except Exception as e:
                logger.error(f"[CONNECT] Connection error: {e}")
                logger.error(f"WebSocket error: {e}")
                import traceback
                traceback.print_exc()
            
            if not self._running:
                # Connection loop stopping
                break
            
            logger.info("[CONNECT] Reconnecting in 2 seconds...")
            logger.info("Reconnecting in 2 seconds...")
            await asyncio.sleep(2)
        
        # Connection loop ended

    async def _connect(self):
        """Establish WebSocket connection"""
        logger.info(f"Connecting WS: {self.ws_uri}")
        self.ws = await websockets.connect(
            self.ws_uri, 
            ping_interval=20, 
            ping_timeout=20, 
            max_size=8 * 1024 * 1024
        )
        logger.info("Connected!")

    # ------------------------------------------------------------
    # Authorization flow
    # ------------------------------------------------------------
    
    async def _authorize_all(self):
        """Complete authorization flow"""

        # CRITICAL: Verify account ID before proceeding
        if self.ctid_trader_account_id == 16612:
            raise RuntimeError(f"CRITICAL ERROR: ctid_trader_account_id is set to client_id (16612)! Should be actual trader account ID like 42478187")

        logger.info(f"[AUTH] Starting auth with account: {self.ctid_trader_account_id}")
        logger.info(f"[AUTH] Client ID: {self.client_id}")
        logger.info(f"[AUTH] WebSocket URI: {self.ws_uri}")

        # 1) App auth
        logger.info(f"[AUTH] Step 1: Application authentication...")
        mid = await self._send(PT_APPLICATION_AUTH_REQ, {
            "clientId": self.client_id,
            "clientSecret": self.client_secret,
        }, expected_response_type=PT_APPLICATION_AUTH_RES)
        await self._recv_until(PT_APPLICATION_AUTH_RES, expect_id=mid)
        logger.info("[AUTH] Application authorized")

        # 2) Get accounts by token
        logger.info(f"[AUTH] Step 2: Getting accounts...")
        mid = await self._send(PT_GET_ACCS_BY_TOKEN_REQ, {"accessToken": self.access_token}, expected_response_type=PT_GET_ACCS_BY_TOKEN_RES)
        res = await self._recv_until(PT_GET_ACCS_BY_TOKEN_RES)
        accounts = (res.get("payload") or {}).get("ctidTraderAccount", [])
        if not accounts:
            raise RuntimeError("No accounts returned")

        logger.info(f"[AUTH] Found {len(accounts)} accounts: {[a.get('ctidTraderAccountId') for a in accounts]}")

        # CRITICAL FIX: Preserve the configured account ID, don't overwrite it
        configured_account_id = self.ctid_trader_account_id

        chosen = None
        if self.ctid_trader_account_id:
            for a in accounts:
                if int(a.get("ctidTraderAccountId")) == int(self.ctid_trader_account_id):
                    chosen = a
                    break

        if not chosen:
            logger.warning(f"[AUTH] WARNING: Configured account ID {configured_account_id} not found in accounts!")
            logger.warning(f"[AUTH] Available accounts: {[a.get('ctidTraderAccountId') for a in accounts]}")
            # Use first account only if no specific account was configured
            if configured_account_id:
                raise RuntimeError(f"Configured account ID {configured_account_id} not found in available accounts: {[a.get('ctidTraderAccountId') for a in accounts]}")
            chosen = accounts[0]
            self.ctid_trader_account_id = int(chosen["ctidTraderAccountId"])

        logger.info(f"[AUTH] Using account: {self.ctid_trader_account_id} (configured: {configured_account_id})")

        # 3) Account auth
        logger.info(f"[AUTH] Step 3: Account authorization with ID {self.ctid_trader_account_id}...")

        # CRITICAL DEBUG: Log the exact payload we're sending
        auth_payload = {
            "ctidTraderAccountId": self.ctid_trader_account_id,
            "accessToken": self.access_token,
        }
        logger.debug(f"[AUTH] SENDING PT_ACCOUNT_AUTH_REQ payload: {auth_payload}")
        logger.debug(f"[AUTH] Message type: {PT_ACCOUNT_AUTH_REQ}")

        # BULLETPROOF VALIDATION: Double-check payload before sending
        if auth_payload["ctidTraderAccountId"] == 16612:
            logger.error(f"[AUTH] ❌ CRITICAL ERROR: auth_payload contains WRONG account ID: {auth_payload['ctidTraderAccountId']}")
            logger.error(f"[AUTH] ❌ This is the OAuth client_id, not the trader account ID!")
            logger.error(f"[AUTH] ❌ Expected trader account ID: 42478187")
            logger.error(f"[AUTH] ❌ Configured account ID: {configured_account_id}")
            logger.error(f"[AUTH] ❌ Current self.ctid_trader_account_id: {self.ctid_trader_account_id}")
            raise RuntimeError(f"CRITICAL: auth_payload has wrong account ID {auth_payload['ctidTraderAccountId']}! Expected 42478187")

        logger.debug(f"[AUTH] ✅ Payload validation passed: account ID {auth_payload['ctidTraderAccountId']} is correct")

        mid = await self._send(PT_ACCOUNT_AUTH_REQ, auth_payload, expected_response_type=PT_ACCOUNT_AUTH_RES)

        logger.info(f"[AUTH] Sent account auth, waiting for response...")
        await self._recv_until(PT_ACCOUNT_AUTH_RES, expect_id=mid)
        logger.info("[AUTH] Account authorized successfully")

        # 4) Build symbol maps PRVNÍ (PŘED bootstrap!)
        self.symbol_to_id.clear()
        self.id_to_symbol.clear()
        for sym in (self.requested_symbols or []):
            sid = (self.symbol_id_overrides or {}).get(sym.upper())
            if sid is None:
                logger.warning(f"No symbolId override for {sym}, skipping.")
                continue
            self.symbol_to_id[sym.upper()] = int(sid)
            self.id_to_symbol[int(sid)] = sym.upper()
        
        if not self.symbol_to_id:
            raise RuntimeError("No valid symbols to subscribe. Check 'symbols' and 'symbol_id_overrides'.")

        # Set authorized flag and flush any queued sends
        self._authorized = True
        await self._flush_send_queue()

        logger.info(f"Symbol map built: {self.symbol_to_id}")
        
        # 5) TEPRVE TEĎ načíst historii (po vytvoření map!)
        if self.use_historical_bootstrap:
            logger.info("[BOOTSTRAP] Starting history bootstrap")
            await self._bootstrap_history()
        
        # 6) Také načíst z cache
        self._load_history_on_startup()

    # ------------------------------------------------------------
    # Subscription and message handling
    # ------------------------------------------------------------
    
    async def _subscribe_symbols(self):
        """Subscribe to symbol spots"""
        ids = list(self.symbol_to_id.values())
        logger.info(f"[SUBSCRIBE] Starting subscription to symbols: {ids}")
        logger.debug(f"[SUBSCRIBE] Account ID: {self.ctid_trader_account_id}")

        payload = {
            "ctidTraderAccountId": self.ctid_trader_account_id,
            "symbolId": ids,
            "subscribeToSpotTimestamp": True,
        }
        logger.debug(f"[SUBSCRIBE] Sending payload: {payload}")

        mid = await self._send(PT_SUBSCRIBE_SPOTS_REQ, payload, expected_response_type=PT_SUBSCRIBE_SPOTS_RES)
        logger.debug(f"[SUBSCRIBE] Sent request with ID: {mid}, waiting for PT_SUBSCRIBE_SPOTS_RES ({PT_SUBSCRIBE_SPOTS_RES})")

        try:
            await self._recv_until(PT_SUBSCRIBE_SPOTS_RES, expect_id=mid, timeout=30.0)  # Longer timeout
            logger.info("[SUBSCRIBE] ✅ Subscribe confirmed successfully")
        except TimeoutError as e:
            logger.error(f"[SUBSCRIBE] ❌ Timeout waiting for subscription response: {e}")
            logger.warning(f"[SUBSCRIBE] This might indicate server issues or wrong symbol IDs")
            raise

    async def _unsubscribe_symbols(self, symbol_ids: List[int] = None):
        """Unsubscribe from symbol spots with proper validation"""
        try:
            # Use all symbols if none specified
            if symbol_ids is None:
                symbol_ids = list(self.symbol_to_id.values())

            # CRITICAL FIX: Check for empty symbolId list before sending
            if not symbol_ids:
                logger.warning("[UNSUBSCRIBE] No symbols to unsubscribe from, skipping UnsubscribeSpots request")
                return

            logger.info(f"[UNSUBSCRIBE] Unsubscribing from symbols: {symbol_ids}")

            payload = {
                "ctidTraderAccountId": self.ctid_trader_account_id,
                "symbolId": symbol_ids
            }

            mid = await self._send(PT_UNSUBSCRIBE_SPOTS_REQ, payload)
            logger.info(f"[UNSUBSCRIBE] Sent unsubscribe request with ID: {mid}")

            # Note: UnsubscribeSpots typically doesn't have a response, so we don't wait
            logger.info("[UNSUBSCRIBE] ✅ Unsubscribe request sent successfully")

        except Exception as e:
            logger.error(f"[UNSUBSCRIBE] Error unsubscribing from symbols: {e}")

    async def _recv_loop(self):
        """Main message receiving loop"""
        while self._running and self.ws:
            try:
                raw = await self.ws.recv()
                msg = json.loads(raw)
                pt = msg.get("payloadType")

                if pt == PT_SPOT_EVENT:
                    self._handle_spot_event(msg.get("payload", {}))
                elif pt == PT_ERROR_RES:
                    logger.error(f"cTrader ERROR: {msg}")
                elif pt == PT_PONG_RES:
                    pass
                elif pt == PT_NEW_ORDER_RES:
                    logger.info(f"[🚨 ORDER RESPONSE] NEW_ORDER_RES: {msg}")
                    self._handle_order_response(msg)
                elif pt == PT_EXECUTION_EVENT:
                    logger.info(f"[🚨 EXECUTION EVENT] EXECUTION_EVENT: {msg}")
                    self._handle_execution_event(msg)
                    # Also handle for account updates (margin, balance)
                    self._handle_account_event(msg)
                elif pt == PT_ORDER_ERROR_EVENT:
                    logger.warning(f"[🚨 ORDER ERROR] ORDER_ERROR_EVENT: {msg}")
                    self._handle_order_error(msg)
                elif pt in [PT_TRADER_RES, PT_POSITION_STATUS_EVENT]:
                    logger.info(f"[ACCOUNT] Account event: {pt}")
                    self._handle_account_event(msg)
                elif pt == 2134:  # PT_DEAL_LIST_RES
                    logger.info(f"[💰 DEAL_LIST] Processing deal list response")
                    self._handle_deal_list_response(msg)
                else:
                    # Skip logging for PT_SUBSCRIBE_DEPTH_QUOTES_REQ (type 2120) to reduce noise
                    if pt != 2120:
                        # Log unknown message types for debugging
                        logger.debug(f"[🚨 UNKNOWN MSG] Type {pt}: {msg}")
                    pass
            except Exception as e:
                logger.error(f"recv_loop error: {e}")
                break

    # ------------------------------------------------------------
    # Market data processing - M5 aggregation
    # ------------------------------------------------------------
    
    def _handle_spot_event(self, payload: Dict):
        """Handle spot events with M5 aggregation"""
        try:
            sid = payload.get("symbolId")
            bid = payload.get("bid")
            ask = payload.get("ask")
            if sid is None or bid is None or ask is None:
                return

            symbol = self.id_to_symbol.get(int(sid))
            if not symbol:
                return

            bid_price = bid / 100000.0
            ask_price = ask / 100000.0

            first = symbol not in self.current_price
            price_data = {
                "bid": bid_price,
                "ask": ask_price,
                "spread": ask_price - bid_price,
                "timestamp": datetime.now(timezone.utc),
            }
            self.current_price[symbol] = price_data

            # Notify price callbacks for account monitoring
            if self._price_callbacks:
                self._notify_price_callbacks(sid, price_data)
            
            if first:
                logger.info(f"[TICK] First spot for {symbol}: {bid_price:.2f}/{ask_price:.2f}")

            # Initialize structures
            if symbol not in self.bars:
                self.bars[symbol] = deque(maxlen=500)
                self.last_bar_block[symbol] = None

            # === M5 AGGREGATION (OPRAVENÁ) ===
            now = datetime.now(timezone.utc)
            current_5min_block = now.replace(
                minute=(now.minute // 5) * 5,
                second=0,
                microsecond=0
            )

            prev_block = self.last_bar_block.get(symbol)

            # Check if we need new M5 bar
            if prev_block is None or current_5min_block != prev_block:
                # DŮLEŽITÉ: Poslat UZAVŘENÝ bar, ne nový!
                if prev_block is not None and len(self.bars[symbol]) > 0:
                    closed_bar = dict(self.bars[symbol][-1])  # Kopie uzavřeného baru
                    logger.info(f"[M5] Closing bar for {symbol} at {prev_block.strftime('%H:%M')}: "
                            f"O:{closed_bar['open']:.2f} H:{closed_bar['high']:.2f} "
                            f"L:{closed_bar['low']:.2f} C:{closed_bar['close']:.2f}")
                    
                    # Poslat VŽDY, bez podmínky warmup
                    if self.on_bar_callback:
                        self.on_bar_callback(symbol, closed_bar)
                        logger.debug(f"[M5] Sent closed bar to main.py")
                
                # Vytvořit NOVÝ bar
                current_spread = self.current_price[symbol].get("spread", 0) if symbol in self.current_price else 0
                bar = {
                    "timestamp": now.isoformat(),
                    "open": bid_price,
                    "high": bid_price,
                    "low": bid_price,
                    "close": bid_price,
                    "volume": 1,
                    "spread": current_spread,
                }
                self.bars[symbol].append(bar)
                self.last_bar_block[symbol] = current_5min_block
                
                logger.debug(f"[M5] New bar started for {symbol} at {current_5min_block.strftime('%H:%M')}")
                # NEPOSÍLAT nový bar - počkat až bude uzavřený!
                
            else:
                # Update current M5 bar
                if len(self.bars[symbol]) > 0:
                    bar = self.bars[symbol][-1]
                    bar["high"] = max(bar["high"], bid_price)
                    bar["low"] = min(bar["low"], bid_price)
                    bar["close"] = bid_price
                    bar["volume"] = bar.get("volume", 0) + 1
                    bar["spread"] = self.current_price[symbol].get("spread", 0)

            # Tick callback stále běží
            if self.on_tick_callback:
                self.on_tick_callback(symbol, self.current_price[symbol])
                
        except Exception as e:
            logger.error(f"Error in _handle_spot_event: {e}")
            

    async def _bootstrap_history(self, count: int = 300):
        """Stáhnout historické M5 bary z cTrader API"""
        import sys
        logger.info(f"[BOOTSTRAP] Starting with {len(self.symbol_to_id)} symbols")

        # Symbol maps are already built before this point
        
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        from_ms = now_ms - count * 5 * 60 * 1000

        # Warm-up request to avoid first-request errors
        try:
            # Sending warm-up request
            first_symbol_id = list(self.symbol_to_id.values())[0]
            await self._send(PT_GET_TRENDBARS_REQ, {
                "ctidTraderAccountId": self.ctid_trader_account_id,
                "symbolId": int(first_symbol_id),
                "period": PERIOD_M5,
                "fromTimestamp": from_ms,
                "toTimestamp": now_ms
            })
            # Don't wait for response, just send to warm up
            await asyncio.sleep(0.5)
            # Warm-up complete, proceeding
        except Exception as e:
            # Warm-up request failed (expected)
            pass

        for symbol, symbol_id in self.symbol_to_id.items():
            try:
                # Processing {symbol} (ID: {symbol_id})


                # Generate unique message ID for tracking
                msg_id = await self._send(PT_GET_TRENDBARS_REQ, {
                    "ctidTraderAccountId": self.ctid_trader_account_id,
                    "symbolId": int(symbol_id),
                    "period": PERIOD_M5,
                    "fromTimestamp": from_ms,
                    "toTimestamp": now_ms
                }, expected_response_type=PT_GET_TRENDBARS_RES, expected_symbol_id=int(symbol_id))

                # Sent trendbars request for {symbol}

                try:
                    res = await self._recv_until(PT_GET_TRENDBARS_RES, expect_id=msg_id, timeout=15.0)
                    payload = res.get("payload", {})
                    res_msg_id = res.get("clientMsgId", "unknown")
                    response_symbol_id = payload.get("symbolId", "missing")

                    # Received response for {symbol}
                except TimeoutError as timeout_e:
                    # Timeout is OK - response may arrive out-of-order and be handled by router
                    logger.warning(f"[BOOTSTRAP] Timeout waiting for {symbol} (msgId={msg_id}) - response may arrive out-of-order")
                    logger.info(f"[BOOTSTRAP] Continuing - out-of-order handler will process response if it arrives")
                    # Try to load from cache as fallback
                    cached_bars = self._load_cached_bars(symbol)
                    if cached_bars:
                        logger.info(f"[BOOTSTRAP] Using cached data for {symbol}: {len(cached_bars)} bars")
                        self.bars[symbol] = deque(cached_bars[-500:], maxlen=500)
                        if self.on_bar_callback and len(cached_bars) > 0:
                            self.on_bar_callback(symbol, cached_bars[-1], cached_bars)
                    continue
                except Exception as recv_e:
                    # Handle first-request errors with retry
                    if "unsubscribe" in str(recv_e).lower():
                        logger.info(f"[BOOTSTRAP] Retrying request for {symbol}...")
                        try:
                            await asyncio.sleep(1.0)
                            retry_msg_id = await self._send(PT_GET_TRENDBARS_REQ, {
                                "ctidTraderAccountId": self.ctid_trader_account_id,
                                "symbolId": int(symbol_id),
                                "period": PERIOD_M5,
                                "fromTimestamp": from_ms,
                                "toTimestamp": now_ms
                            }, expected_response_type=PT_GET_TRENDBARS_RES, expected_symbol_id=int(symbol_id))
                            res = await self._recv_until(PT_GET_TRENDBARS_RES, expect_id=retry_msg_id, timeout=15.0)
                            payload = res.get("payload", {})
                            logger.info(f"[BOOTSTRAP] Retry successful for {symbol}")

                            # Debug retry payload
                            retry_arr = payload.get("trendbar", [])
                            if retry_arr:
                                first_bar = retry_arr[0]
                                low_int = first_bar.get("low", 0)
                                delta_open = first_bar.get("deltaOpen", 0)
                                open_price = (low_int + delta_open) / 100000.0
                                # Retry successful, data retrieved
                        except Exception as retry_e:
                            logger.error(f"[BOOTSTRAP] Retry failed for {symbol}: {retry_e}")
                            # Try cache as fallback
                            cached_bars = self._load_cached_bars(symbol)
                            if cached_bars:
                                logger.info(f"[BOOTSTRAP] Using cached data after retry failure: {len(cached_bars)} bars")
                                self.bars[symbol] = deque(cached_bars[-500:], maxlen=500)
                                if self.on_bar_callback and len(cached_bars) > 0:
                                    self.on_bar_callback(symbol, cached_bars[-1], cached_bars)
                            continue
                    else:
                        # For other errors, try cache as fallback before giving up
                        logger.warning(f"[BOOTSTRAP] Error for {symbol}: {recv_e} - trying cache fallback")
                        cached_bars = self._load_cached_bars(symbol)
                        if cached_bars:
                            logger.info(f"[BOOTSTRAP] Using cached data after error: {len(cached_bars)} bars")
                            self.bars[symbol] = deque(cached_bars[-500:], maxlen=500)
                            if self.on_bar_callback and len(cached_bars) > 0:
                                self.on_bar_callback(symbol, cached_bars[-1], cached_bars)
                        continue

                arr = payload.get("trendbar", [])
                base_timestamp = payload.get("timestamp", 0)

                logger.info(f"[BOOTSTRAP] Retrieved {len(arr)} bars for {symbol}")

                # Debug: Show payload content verification
                payload_symbol_id = payload.get("symbolId", "missing")

                # Debug: Show first bar data to verify correct symbol data
                if arr:
                    first_bar = arr[0]
                    low_int = first_bar.get("low", 0)
                    delta_open = first_bar.get("deltaOpen", 0)
                    open_price = (low_int + delta_open) / 100000.0
                    # Processing first bar for {symbol}
                
                processed = []
                current_open = None  # Začít s None
                
                # NAHRADIT celou sekci zpracování barů:
                # NAHRADIT celou sekci zpracování (řádky ~460-490):
                # NAHRADIT celou sekci zpracování (řádky ~460-490):
                for i, bar in enumerate(arr):
                    # Timestamp
                    if "utcTimestampInMinutes" in bar:
                        ts_ms = bar["utcTimestampInMinutes"] * 60 * 1000
                    else:
                        ts_ms = base_timestamp + (i * 5 * 60 * 1000)
                    
                    # SPRÁVNÉ DEKÓDOVÁNÍ - vše je relativní k LOW!
                    low_int = bar.get("low", 0)  # Absolutní hodnota
                    delta_open = bar.get("deltaOpen", 0)
                    delta_high = bar.get("deltaHigh", 0)
                    delta_close = bar.get("deltaClose", 0)
                    
                    # Všechny ceny počítáme od LOW
                    low_price = low_int / 100000.0
                    open_price = (low_int + delta_open) / 100000.0
                    high_price = (low_int + delta_high) / 100000.0
                    close_price = (low_int + delta_close) / 100000.0
                    
                    # Sanity check - high musí být nejvyšší, low nejnižší
                    if high_price < max(open_price, close_price):
                        high_price = max(open_price, close_price)
                    if low_price > min(open_price, close_price):
                        low_price = min(open_price, close_price)
                    
                    bar_range = high_price - low_price
                    
                    # Debug pro prvních pár barů
                    if i < 3:
                        print(f"Bar {i}: O={open_price:.2f}, H={high_price:.2f}, L={low_price:.2f}, C={close_price:.2f}, Range={bar_range:.2f}")
                    
                    # M5 může mít rozsah až 100-150 bodů při volatilitě
                    if bar_range > 200:
                        print(f"[WARNING] Bar {i}: unusually high range {bar_range:.1f}")
                    
                    if bar_range < 0:
                        print(f"[ERROR] Bar {i}: negative range, skipping")
                        continue
                    
                    ts_iso = datetime.fromtimestamp(ts_ms/1000.0, tz=timezone.utc).isoformat()
                    
                    # Estimate historical spread (bootstrap doesn't have tick data)
                    # Use typical spread for indices (DAX ~1.5-2 pips, NASDAQ ~2-3 pips)
                    typical_spread = 2.0 if "US100" in symbol else 1.5

                    processed.append({
                        "timestamp": ts_iso,
                        "open": open_price,
                        "high": high_price,
                        "low": low_price,
                        "close": close_price,
                        "volume": bar.get("volume", 0),
                        "spread": typical_spread
                    })
                                
                if processed:
                    logger.info(f"[BOOTSTRAP] Processed {len(processed)} bars for {symbol}")
                    
                    self.bars[symbol] = deque(processed[-500:], maxlen=500)

                    # Critical debug: verify data is different between symbols
                    if processed:
                        first_bar = processed[0]
                        last_bar = processed[-1]
                        # Data validation complete for {symbol}
                    
                    last_dt = datetime.fromisoformat(processed[-1]["timestamp"])
                    self.last_bar_block[symbol] = last_dt.replace(
                        minute=(last_dt.minute//5)*5,
                        second=0,
                        microsecond=0
                    )
                    
                    if self.on_bar_callback:
                        # Sending {symbol} data to main application
                        self.on_bar_callback(symbol, processed[-1], processed)
                        # {symbol} data sent successfully
                    
                    self._save_to_cache(symbol, processed)
                    
            except Exception as e:
                logger.error(f"[BOOTSTRAP] Error processing {symbol}: {e}")
                import traceback
                traceback.print_exc()
            
            await asyncio.sleep(1.0)  # Longer delay between symbols
                    
    def _load_cached_bars(self, symbol: str) -> List[Dict]:
        """Načíst bary z JSONL cache"""
        cache_path = f"{self.history_cache_dir}/{symbol}_M5.jsonl"
        bars = []
        
        try:
            if os.path.exists(cache_path):
                with open(cache_path, 'r') as f:
                    for line in f:
                        bars.append(json.loads(line))
                        
                # Ověřit stáří dat
                if bars:
                    last_bar_time = datetime.fromisoformat(bars[-1]['timestamp'].replace('Z', '+00:00'))
                    age_minutes = (datetime.now(timezone.utc) - last_bar_time).total_seconds() / 60
                    
                    if age_minutes > 60:  # Starší než hodina
                        logger.info(f"Cache for {symbol} is {age_minutes:.0f} min old, will refresh")
                        return []  # Raději stáhnout nová data
                        
        except Exception as e:
            logger.error(f"Failed to load cache for {symbol}: {e}")
            
        return bars
    
    async def _request_trendbars(self, symbol: str, symbol_id: int):
        """Požádat o historické bary z cTrader"""
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        from_ms = now_ms - (self.history_bars_count * 5 * 60 * 1000)  # M5 bars
        
        msg_id = await self._send(2137, {  # PT_GET_TRENDBARS_REQ
            "ctidTraderAccountId": self.ctid_trader_account_id,
            "symbolId": symbol_id,
            "period": 3,  # M5
            "fromTimestamp": from_ms,
            "toTimestamp": now_ms
        })
        
        # Počkat na odpověď
        response = await self._recv_until(2138, timeout=10)  # PT_GET_TRENDBARS_RES
        
        if response:
            self._process_trendbars(symbol, response.get('payload', {}))
    
    def _process_trendbars(self, symbol: str, payload: Dict):
        """Zpracovat historické bary"""
        trendbars = payload.get('trendbar') or payload.get('trendbars') or []
        
        processed_bars = []
        for bar in trendbars:
            processed_bar = {
                "timestamp": datetime.fromtimestamp(
                    bar['utcTimestamp'] / 1000.0, 
                    tz=timezone.utc
                ).isoformat(),
                "open": bar['open'] / 100000.0,
                "high": bar['high'] / 100000.0,
                "low": bar['low'] / 100000.0,
                "close": bar['close'] / 100000.0,
                "volume": bar.get('volume', 1)
            }
            processed_bars.append(processed_bar)
        
        if processed_bars:
            # Uložit do interní struktury
            self.bars[symbol] = deque(processed_bars, maxlen=500)
            
            # Uložit do cache pro příště
            self._save_to_cache(symbol, processed_bars)
            
            # Okamžitě zavolat callback s daty
            if self.on_bar_callback and len(processed_bars) >= self.bar_warmup:
                # Poslat poslední bar jako "nový"
                self.on_bar_callback(symbol, processed_bars[-1], processed_bars)
                logger.info(f"Bootstrap: Sent {len(processed_bars)} bars for {symbol}")
    
    def _save_to_cache(self, symbol: str, bars: List[Dict]):
        """Uložit bary do cache"""
        os.makedirs(self.history_cache_dir, exist_ok=True)
        cache_path = f"{self.history_cache_dir}/{symbol}_M5.jsonl"
        
        with open(cache_path, 'w') as f:
            for bar in bars:
                # Vytvořit kopii baru pro serializaci
                bar_copy = {}
                for key, value in bar.items():
                    if key == 'timestamp':
                        # Konvertovat datetime na string
                        if hasattr(value, 'isoformat'):
                            bar_copy[key] = value.isoformat()
                        else:
                            bar_copy[key] = str(value)
                    else:
                        bar_copy[key] = value
                # Zapsat serializovatelný bar
                f.write(json.dumps(bar_copy) + "\n")
                
    def _load_history_on_startup(self):
        """Načíst historii při startu z cache"""
        import os
        import json
        
        logger.info(f"[CACHE] Loading history from {self.history_cache_dir}")
        
        for symbol in self.symbol_to_id.keys():
            try:
                # Primární cesta
                cache_path = f"{self.history_cache_dir}/{symbol}_M5.jsonl"
                
                # Pokud neexistuje, zkusit alternativní cesty
                if not os.path.exists(cache_path):
                    alt_paths = [
                        f"./cache/{symbol}_M5.jsonl",
                        f"/config/cache/{symbol}_M5.jsonl",
                        f"cache/{symbol}_M5.jsonl"
                    ]
                    for alt in alt_paths:
                        if os.path.exists(alt):
                            cache_path = alt
                            logger.info(f"[CACHE] Found cache at alternate path: {alt}")
                            break
                    else:
                        logger.info(f"[CACHE] No cache found for {symbol}")
                        continue
                
                # Načíst bary
                bars = []
                with open(cache_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            bars.append(json.loads(line))
                
                if bars:
                    # Vzít posledních 100 barů
                    self.bars[symbol] = deque(bars[-100:], maxlen=500)
                    logger.info(f"[CACHE] Loaded {len(bars)} bars for {symbol} from {cache_path}")
                    
                    # Nastavit last_bar_block podle posledního baru
                    last_timestamp = bars[-1].get('timestamp')
                    if last_timestamp:
                        # Parse timestamp
                        if 'T' in last_timestamp:
                            last_dt = datetime.fromisoformat(last_timestamp.replace('Z', '+00:00'))
                        else:
                            last_dt = datetime.fromisoformat(last_timestamp)
                        
                        self.last_bar_block[symbol] = last_dt.replace(
                            minute=(last_dt.minute // 5) * 5,
                            second=0,
                            microsecond=0
                        )
                        logger.debug(f"[CACHE] Set last_bar_block for {symbol} to {self.last_bar_block[symbol]}")
                    
                    # DŮLEŽITÉ: Poslat všechny bary do main.py OKAMŽITĚ
                    if self.on_bar_callback and len(bars) > 0:
                        # Poslat poslední bar a všechna historická data
                        self.on_bar_callback(symbol, bars[-1], bars)
                        logger.info(f"[CACHE] Sent {len(bars)} historical bars to main.py for {symbol}")
                else:
                    logger.info(f"[CACHE] Cache file empty for {symbol}")
                    
            except Exception as e:
                logger.error(f"[CACHE] Failed to load cache for {symbol}: {e}")
                import traceback
                logger.error(traceback.format_exc())
                
        def set_event_bridge(self, bridge):
            """Set the event bridge for thread-safe communication"""
            self.event_bridge = bridge
            logger.info("[CTRADER] EventBridge connected")
    
    def _handle_order_response(self, msg: Dict):
        """Handle NEW_ORDER_RES - order acknowledgment from cTrader"""
        logger.info(f"[🚨 ORDER ACK] Order acknowledged by cTrader: {msg}")
        # TODO: Notify order executor of acknowledgment
    
    def _handle_execution_event(self, msg: Dict):
        """Handle EXECUTION_EVENT - position fill confirmation"""
        payload = msg.get("payload", {})
        execution_type = payload.get("executionType")

        if execution_type == 3:  # ORDER_FILLED
            logger.info(f"[🚨 POSITION OPENED] Order filled! Position created: {payload}")
            # Notify order executor that position is actually open
            if self.on_execution_callback or self._execution_callbacks:
                try:
                    # Call original callback
                    if self.on_execution_callback:
                        self.on_execution_callback('ORDER_FILLED', payload)
                    # Call new execution monitor callbacks
                    self._notify_execution_callbacks(payload)
                except Exception as e:
                    logger.error(f"[🚨 CALLBACK ERROR] Execution callback failed: {e}")
        else:
            logger.info(f"[🚨 EXECUTION] Other execution type {execution_type}: {payload}")
            # CRITICAL FIX: Notify for ALL execution types (including type 2 for SL/TP updates)
            if self.on_execution_callback or self._execution_callbacks:
                try:
                    # Call original callback
                    if self.on_execution_callback:
                        self.on_execution_callback(f'EXECUTION_TYPE_{execution_type}', payload)
                    # Call new execution monitor callbacks for ALL execution types
                    self._notify_execution_callbacks(payload)
                except Exception as e:
                    logger.error(f"[🚨 CALLBACK ERROR] Execution callback failed: {e}")
    
    def _handle_order_error(self, msg: Dict):
        """Handle ORDER_ERROR_EVENT - order rejection"""
        logger.warning(f"[🚨 ORDER REJECTED] cTrader rejected order: {msg}")
        # Notify order executor of rejection
        if self.on_execution_callback:
            try:
                payload = msg.get("payload", {})
                error_code = payload.get("errorCode", "UNKNOWN_ERROR")
                self.on_execution_callback('ORDER_REJECTED', payload)
            except Exception as e:
                logger.error(f"[🚨 CALLBACK ERROR] Order error callback failed: {e}")

    async def _flush_send_queue(self):
        """Flush queued sends after authorization"""
        if not hasattr(self, '_send_queue'):
            return

        queue = getattr(self, '_send_queue', [])
        if not queue:
            return

        logger.info(f"[WS] Flushing {len(queue)} queued sends after authorization")

        for payload_type, payload in queue:
            try:
                await self._send(payload_type, payload)
                logger.debug(f"[WS] Flushed queued send: type {payload_type}")
            except Exception as e:
                logger.error(f"[WS] Failed to flush queued send: {e}")

        # Clear queue
        self._send_queue = []
        logger.info("[WS] Send queue flushed")

    # ------------------------------------------------------------
    # Account Management
    # ------------------------------------------------------------

    async def request_deals_list(self, from_timestamp=None, to_timestamp=None, max_rows=1000):
        """Request deals list for balance and PnL calculation - CRITICAL FIX"""
        try:
            if from_timestamp is None:
                today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                from_timestamp = int(today.timestamp() * 1000)

            if to_timestamp is None:
                to_timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)

            payload = {
                "ctidTraderAccountId": self.ctid_trader_account_id,
                "fromTimestamp": from_timestamp,
                "toTimestamp": to_timestamp,
                "maxRows": max_rows
            }

            logger.info(f"[💰 DEAL_REQ] Requesting deals list from {from_timestamp} to {to_timestamp}, max_rows={max_rows}")

            # FIRE-AND-FORGET: Send request and let recv_loop handle response automatically
            mid = await self._send(PT_DEAL_LIST_REQ, payload, expected_response_type=PT_DEAL_LIST_RES)
            logger.info(f"[💰 DEAL_REQ] ✅ Sent deals request with msgId={mid}, response will be handled by recv_loop")

            # Don't wait for response - recv_loop will automatically route PT_DEAL_LIST_RES to _handle_deal_list_response
            return mid

        except Exception as e:
            logger.error(f"[💰 DEAL_REQ] Error requesting deals list: {e}")
            return None

    async def _get_account_snapshot(self):
        """Get account snapshot after authorization - uses PT_DEAL_LIST_REQ for balance and PT_TRADER_REQ for positions"""
        logger.info("[ACCOUNT] _get_account_snapshot() - Getting initial balance and positions")
        try:
            # CRITICAL FIX: Wait for account to fully initialize after authorization
            logger.info("[ACCOUNT] Waiting 1s for account initialization...")
            await asyncio.sleep(1.0)

            # CRITICAL FIX: Request PT_TRADER_RES for positions data (needed by AccountStateMonitor)
            logger.info("[ACCOUNT] Requesting PT_TRADER_REQ for positions data...")
            trader_payload = {
                "ctidTraderAccountId": self.ctid_trader_account_id
            }
            trader_msg_id = await self._send(PT_TRADER_REQ, trader_payload)
            logger.info(f"[ACCOUNT] PT_TRADER_REQ sent with msgId={trader_msg_id}, response will be handled by recv_loop")

            # DEMO API FIX: PT_TRADER_REQ doesn't return trader object on demo accounts
            # Use PT_DEAL_LIST_REQ instead to get balance from last deal
            logger.info("[ACCOUNT] Using PT_DEAL_LIST_REQ for initial balance (more reliable for demo)")

            # Request last 7 days of deals to get most recent balance
            from_timestamp = int((datetime.now(timezone.utc) - timedelta(days=7)).timestamp() * 1000)
            to_timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)

            payload = {
                "ctidTraderAccountId": self.ctid_trader_account_id,
                "fromTimestamp": from_timestamp,
                "toTimestamp": to_timestamp,
                "maxRows": 100
            }

            mid = await self._send(PT_DEAL_LIST_REQ, payload, expected_response_type=PT_DEAL_LIST_RES)
            logger.info(f"[ACCOUNT] PT_DEAL_LIST_REQ sent with msgId={mid}, waiting for response...")

            try:
                response = await self._receive(PT_DEAL_LIST_RES, expect_id=mid)
                logger.info(f"[ACCOUNT] PT_DEAL_LIST_RES received: {response is not None}")
            except TimeoutError:
                # Timeout is OK - response may arrive out-of-order and be handled by recv_loop
                logger.warning(f"[ACCOUNT] Timeout waiting for PT_DEAL_LIST_RES (msgId={mid}) - response may arrive out-of-order")
                logger.info(f"[ACCOUNT] Account snapshot will be updated when response arrives via recv_loop")
                return  # Exit gracefully - recv_loop will handle the response

            if response and "payload" in response:
                payload = response["payload"]
                deals = payload.get("deal", [])
                logger.info(f"[ACCOUNT] Received {len(deals)} deals from last 7 days")

                # Extract balance from deals (same logic as Account Monitor)
                actual_balance = None
                if deals:
                    last_balance = 0
                    last_version = 0

                    for deal in deals:
                        close_detail = deal.get("closePositionDetail", {})
                        if close_detail:
                            version = close_detail.get("balanceVersion", 0)
                            balance_raw = close_detail.get("balance", 0)
                            if version > last_version:
                                last_version = version
                                last_balance = balance_raw

                    if last_balance > 0 and last_version > 0:
                        actual_balance = last_balance / 100
                        logger.info(f"[ACCOUNT] ✅ Balance from deals: {actual_balance:,.2f} CZK (v{last_version})")
                    else:
                        logger.warning(f"[ACCOUNT] ⚠️ No closed deals found, using config balance")
                        actual_balance = self.account_balance
                else:
                    # No deals in response - use config balance
                    logger.warning(f"[ACCOUNT] No deals in response, using config balance")
                    actual_balance = self.account_balance

                # Send callback with balance (from deals or config)
                if actual_balance and actual_balance > 0:
                    logger.info(f"[ACCOUNT] Sending callback with balance: {actual_balance:,.2f} {self.account_currency}")

                    if self.on_account_callback:
                        # Create trader object with balance in cents (multiply by 100 for moneyDigits=2)
                        trader_data = {
                            "ctidTraderAccountId": self.ctid_trader_account_id,
                            "balance": int(actual_balance * 100),  # Convert to cents
                            "equity": int(actual_balance * 100),   # Same as balance (no open positions)
                            "margin": 0,
                            "freeMargin": int(actual_balance * 100),
                            "moneyDigits": 2,  # CRITICAL: Tell BalanceTracker to divide by 100
                            "depositCurrency": self.account_currency
                        }

                        callback_data = {
                            "balance": actual_balance,
                            "equity": actual_balance,
                            "margin_used": 0,
                            "free_margin": actual_balance,
                            "currency": self.account_currency,
                            "positions": 0,
                            "timestamp": datetime.now(timezone.utc),
                            "trader": trader_data
                        }
                        self.on_account_callback(callback_data)
                        logger.info(f"[ACCOUNT] ✅ Callback sent with balance: {actual_balance:,.2f} CZK")
                else:
                    logger.warning(f"[ACCOUNT] No valid balance available, will use config default")

                return
            else:
                logger.error(f"[ACCOUNT] No payload in PT_DEAL_LIST_RES! Response: {response}")

        except Exception as e:
            logger.error(f"[ACCOUNT] Failed to get account snapshot: {e}")


    def _handle_deal_list_response(self, msg: Dict):
        """Handle PT_DEAL_LIST_RES - daily deals for realized PnL"""
        logger.debug(f"[💰 DEAL_LIST] ENTRY: _handle_deal_list_response called")
        try:
            payload = msg.get('payload', {})
            deals = payload.get('deal', [])

            logger.info(f"[💰 DEAL_LIST] Received {len(deals)} deals")

            # Call account monitor callbacks for deals data (daily PnL)
            logger.debug(f"[💰 DEAL_LIST] Checking callbacks: count={len(self._account_callbacks)}")
            if self._account_callbacks:
                deal_account_data = {
                    "deals": deals,
                    "timestamp": datetime.now(timezone.utc),
                    "source": "PT_DEAL_LIST_RES"
                }
                logger.debug(f"[💰 DEAL_LIST] About to notify {len(self._account_callbacks)} callbacks")
                self._notify_account_callbacks(deal_account_data)
                logger.debug(f"[💰 DEAL_LIST] Callbacks notified successfully")
            else:
                logger.debug(f"[💰 DEAL_LIST] No callbacks registered!")

        except Exception as e:
            logger.error(f"[💰 DEAL_LIST] Error handling deal list: {e}")
            import traceback
            logger.error(f"[💰 DEAL_LIST] Traceback: {traceback.format_exc()}")

    # ------------------------------------------------------------
    # Account Monitoring Callback Registration
    # ------------------------------------------------------------

    def add_account_callback(self, callback: Callable):
        """Add callback for account updates (for account monitor)"""
        if callback not in self._account_callbacks:
            self._account_callbacks.append(callback)
            logger.info(f"[ACCOUNT] Registered callback for account updates")
        else:
            logger.info(f"[ACCOUNT_MONITOR] Callback already registered, skipping")

    def add_price_callback(self, callback: Callable):
        """Add callback for price updates (for PnL calculation)"""
        if callback not in self._price_callbacks:
            self._price_callbacks.append(callback)
            logger.info(f"[ACCOUNT_MONITOR] Added price callback: {callback.__name__ if hasattr(callback, '__name__') else 'unknown'}")

    def add_execution_callback(self, callback: Callable):
        """Add callback for execution events (for realized PnL)"""
        if callback not in self._execution_callbacks:
            self._execution_callbacks.append(callback)
            callback_name = callback.__name__ if hasattr(callback, '__name__') else str(callback)
            logger.info(f"[ACCOUNT_MONITOR] Added execution callback: {callback_name}")
            logger.info(f"[ACCOUNT_MONITOR] Total execution callbacks now: {len(self._execution_callbacks)}")
        else:
            callback_name = callback.__name__ if hasattr(callback, '__name__') else str(callback)
            logger.debug(f"[ACCOUNT_MONITOR] Execution callback already registered: {callback_name}")

    def request_trader_info(self):
        """Public method to request trader info from other threads"""
        try:
            if self._loop and self._loop.is_running():
                # Schedule account snapshot in WebSocket thread
                asyncio.run_coroutine_threadsafe(self._get_account_snapshot(), self._loop)
                logger.debug("[ACCOUNT_MONITOR] Scheduled trader info request")
            else:
                logger.warning("[ACCOUNT_MONITOR] WebSocket loop not running, cannot request trader info")
        except Exception as e:
            logger.error(f"[ACCOUNT_MONITOR] Error requesting trader info: {e}")

    def _notify_account_callbacks(self, account_data: Dict):
        """Notify all registered account callbacks"""
        logger.debug(f"[💰 NOTIFY] ENTRY: Notifying {len(self._account_callbacks)} callbacks")
        for i, callback in enumerate(self._account_callbacks):
            try:
                logger.debug(f"[💰 NOTIFY] Calling callback #{i}: {callback}")
                callback(account_data)
                logger.debug(f"[💰 NOTIFY] Callback #{i} completed successfully")
            except Exception as e:
                logger.error(f"[ACCOUNT_MONITOR] Error in account callback {callback}: {e}")
                import traceback
                logger.error(f"[ACCOUNT_MONITOR] Traceback: {traceback.format_exc()}")

    def _notify_price_callbacks(self, symbol_id: int, price_data: Dict):
        """Notify all registered price callbacks"""
        for callback in self._price_callbacks:
            try:
                callback(symbol_id, price_data)
            except Exception as e:
                logger.error(f"[ACCOUNT_MONITOR] Error in price callback {callback}: {e}")

    def _notify_execution_callbacks(self, execution_data: Dict):
        """Notify all registered execution callbacks"""
        for callback in self._execution_callbacks:
            try:
                callback(execution_data)
            except Exception as e:
                logger.error(f"[ACCOUNT_MONITOR] Error in execution callback {callback}: {e}")

    async def _request_current_positions(self):
        """Request current open positions"""
        try:
            logger.info(f"[POSITIONS] Requesting current open positions")

            # Use RECONCILE_REQ to get current positions and balance
            reconcile_payload = {
                "ctidTraderAccountId": self.ctid_trader_account_id
            }

            mid = await self._send(PT_TRADER_REQ, reconcile_payload)
            logger.info(f"[POSITIONS] RECONCILE_REQ sent to get current positions, waiting for response...")

            # Wait for reconcile response
            response = await self._receive(PT_TRADER_RES, expect_id=mid)
            if response:
                logger.info(f"[POSITIONS] Reconcile response received: {response}")

                # Extract balance from reconcile response if available
                payload = response.get('payload', {})
                if 'balance' in payload:
                    balance_raw = payload['balance']
                    logger.info(f"[ACCOUNT] Balance from reconcile: {balance_raw} (raw)")

                    # Convert with same logic as trader response
                    if balance_raw > 1000000:  # If larger than 10k, likely in cents/hundredths
                        self.account_balance = balance_raw / 100.0
                        logger.info(f"[ACCOUNT] Converted reconcile balance from cents: {balance_raw} → {self.account_balance}")
                    else:
                        self.account_balance = balance_raw
                        logger.info(f"[ACCOUNT] Using reconcile balance as-is: {self.account_balance}")

                    # Update account callback with corrected balance
                    if self.on_account_callback:
                        account_data = {
                            "balance": self.account_balance,
                            "equity": self.account_balance,
                            "margin_used": self.account_margin_used,
                            "free_margin": self.account_balance - self.account_margin_used,
                            "currency": self.account_currency,
                            "timestamp": datetime.now(timezone.utc)
                        }
                        self.on_account_callback(account_data)
                        logger.info(f"[ACCOUNT] Updated balance from reconcile: {self.account_balance} {self.account_currency}")

            else:
                logger.warning(f"[POSITIONS] No reconcile response received")

        except Exception as e:
            logger.error(f"[POSITIONS] Failed to request current positions: {e}")

    def _handle_account_event(self, msg):
        """Handle account-related events"""
        try:
            payload_type = msg.get("payloadType")
            payload = msg.get("payload", {})

            logger.info(f"[ACCOUNT_EVENT] Called with payloadType={payload_type}, PT_TRADER_RES={PT_TRADER_RES}, payload keys={list(payload.keys())}")

            if payload_type == PT_TRADER_RES:
                # Account balance update
                balance_raw = payload.get("balance", 0)
                currency = payload.get("depositCurrency", "CZK")

                logger.info(f"[ACCOUNT] Raw balance from trader event: {balance_raw}")

                # Guard: Ignore zero/empty balance (PT_TRADER_RES sometimes doesn't include equity)
                if not balance_raw:
                    logger.debug("[ACCOUNT] Ignoring zero/empty balance from PT_TRADER_RES")
                else:
                    # Convert with same logic
                    if balance_raw > 1000000:  # If larger than 10k, likely in cents/hundredths
                        self.account_balance = balance_raw / 100.0
                        logger.info(f"[ACCOUNT] Converted event balance from cents: {balance_raw} → {self.account_balance}")
                    else:
                        self.account_balance = balance_raw
                        logger.info(f"[ACCOUNT] Using event balance as-is: {self.account_balance}")

                    self.account_currency = currency
                    logger.info(f"[ACCOUNT] Balance updated from event: {self.account_balance} {self.account_currency}")

            elif payload_type == PT_POSITION_STATUS_EVENT:
                # Position updates for margin calculation
                logger.info(f"[ACCOUNT] Position status event: {payload}")

            elif payload_type == PT_EXECUTION_EVENT:
                # Extract margin info from execution events
                used_margin_raw = payload.get("usedMargin", 0)
                if used_margin_raw > 0:
                    # Convert margin from cents to base currency
                    if used_margin_raw > 1000000:  # Likely in cents
                        used_margin = used_margin_raw / 100.0
                        logger.info(f"[ACCOUNT] Converted used margin from cents: {used_margin_raw} → {used_margin}")
                    else:
                        used_margin = used_margin_raw
                        logger.info(f"[ACCOUNT] Using used margin as-is: {used_margin}")

                    self.account_margin_used = used_margin

                # IMPORTANT: Do NOT call on_account_callback for execution events
                # Execution events don't have trader balance data, only position info
                # Balance tracker should only update from PT_TRADER_RES with proper trader object
                logger.info(f"[ACCOUNT] Updated margin from execution event, skipping balance callback")
                return  # Exit early to avoid calling on_account_callback with execution event data

            # PT_RECONCILE_RES removed - using only PT_TRADER_RES in JSON protocol
                # Handle reconcile response for balance updates
                balance_raw = payload.get("balance", 0)
                if balance_raw > 0:
                    logger.info(f"[ACCOUNT] Raw balance from reconcile event: {balance_raw}")

                    if balance_raw > 1000000:  # Likely in cents
                        self.account_balance = balance_raw / 100.0
                        logger.info(f"[ACCOUNT] Converted reconcile event balance: {balance_raw} → {self.account_balance}")
                    else:
                        self.account_balance = balance_raw

            # Call account callback with updated data
            # ONLY for PT_TRADER_RES or PT_POSITION_STATUS_EVENT, NOT for PT_EXECUTION_EVENT

            # CRITICAL FIX: Demo accounts don't return balance in PT_TRADER_RES, but DO return positions
            # Always notify Account Monitor if we have position data, even if balance=0
            has_positions = 'position' in payload and payload.get('position')

            if self.account_balance > 0 or has_positions:
                account_data = {
                    "balance": self.account_balance,
                    "equity": self.account_balance,
                    "margin_used": self.account_margin_used,
                    "free_margin": self.account_balance - self.account_margin_used,
                    "currency": self.account_currency,
                    "timestamp": datetime.now(timezone.utc),
                    "trader": payload  # CRITICAL: Include trader payload for BalanceTracker (only from PT_TRADER_RES)
                }

                # Call legacy callback (only if balance > 0)
                if self.on_account_callback and self.account_balance > 0:
                    self.on_account_callback(account_data)
                    logger.info(f"[ACCOUNT] ✅ Called on_account_callback for payload_type={payload_type}")

                # CRITICAL: Always notify Account Monitor with PT_TRADER_RES position data (even if balance=0)
                trader_account_data = {
                    "trader": {
                        "balance": int(self.account_balance * 100),  # Convert back to cents
                        "equity": int(self.account_balance * 100),
                        "margin": int(self.account_margin_used * 100),
                        "freeMargin": int((self.account_balance - self.account_margin_used) * 100),
                        "depositCurrency": self.account_currency
                    },
                    "position": payload.get('position', []),  # Include positions from PT_TRADER_RES
                    "deals": [],
                    "timestamp": datetime.now(timezone.utc),
                    "source": "PT_TRADER_RES"
                }
                logger.info(f"[ACCOUNT] 📍 Notifying AccountMonitor with PT_TRADER_RES: {len(payload.get('position', []))} positions")
                self._notify_account_callbacks(trader_account_data)

        except Exception as e:
            logger.error(f"[ACCOUNT] Error handling account event: {e}")

    # ------------------------------------------------------------
    # THREAD-SAFE COMMAND QUEUE for Cross-Thread Operations
    # ------------------------------------------------------------

    async def _start_command_processor(self):
        """Initialize and start command queue processor"""
        try:
            import asyncio
            self._command_queue = asyncio.Queue()
            self._command_processor_task = asyncio.create_task(self._process_commands())
            logger.info("[COMMAND_QUEUE] ✅ Command processor started")
        except Exception as e:
            logger.error(f"[COMMAND_QUEUE] Error starting command processor: {e}")

    async def _process_commands(self):
        """Process commands from other threads"""
        try:
            while self._running:
                try:
                    # Wait for commands with timeout to allow clean shutdown
                    cmd = await asyncio.wait_for(self._command_queue.get(), timeout=1.0)

                    logger.info(f"[COMMAND_QUEUE] Processing command: {cmd['type']}")

                    if cmd['type'] == 'send_order':
                        await self._send_order_internal(cmd['payload'], cmd.get('callback'))
                    elif cmd['type'] == 'request_deals':
                        await self._request_deals_internal(cmd['payload'], cmd.get('callback'))
                    elif cmd['type'] == 'cancel_order':
                        await self._cancel_order_internal(cmd['payload'], cmd.get('callback'))
                    else:
                        logger.warning(f"[COMMAND_QUEUE] Unknown command type: {cmd['type']}")

                    # Mark task as done
                    self._command_queue.task_done()

                except asyncio.TimeoutError:
                    # Normal timeout, continue loop
                    continue
                except Exception as e:
                    logger.error(f"[COMMAND_QUEUE] Error processing command: {e}")

        except Exception as e:
            logger.error(f"[COMMAND_QUEUE] Command processor error: {e}")

    def send_order_from_thread(self, order_data: dict, callback=None):
        """Thread-safe order sending - Call from any thread"""
        if not self._command_queue:
            logger.error("[COMMAND_QUEUE] Command queue not initialized")
            return

        import asyncio
        try:
            asyncio.run_coroutine_threadsafe(
                self._command_queue.put({
                    'type': 'send_order',
                    'payload': order_data,
                    'callback': callback
                }),
                self._loop
            )
            logger.info("[COMMAND_QUEUE] Order command enqueued")
        except Exception as e:
            logger.error(f"[COMMAND_QUEUE] Error enqueuing order: {e}")

    async def _send_order_internal(self, order_data: dict, callback=None):
        """Internal order sending implementation"""
        try:
            # Implementation for order sending
            logger.info(f"[ORDER] Sending order: {order_data}")

            # TODO: Implement actual order sending logic
            # mid = await self._send(PT_ORDER_REQ, order_data)
            # response = await self._receive(PT_ORDER_RES, expect_id=mid)

            if callback:
                callback({'success': True, 'data': order_data})

        except Exception as e:
            logger.error(f"[ORDER] Error sending order: {e}")
            if callback:
                callback({'success': False, 'error': str(e)})

    async def _request_deals_internal(self, deals_data: dict, callback=None):
        """Internal deals request implementation"""
        try:
            logger.info(f"[DEALS] Requesting deals: {deals_data}")
            response = await self.request_deals_list(
                deals_data.get('from_timestamp'),
                deals_data.get('to_timestamp'),
                deals_data.get('max_rows', 100)
            )

            if callback:
                callback({'success': True, 'data': response})

        except Exception as e:
            logger.error(f"[DEALS] Error requesting deals: {e}")
            if callback:
                callback({'success': False, 'error': str(e)})

    async def _cancel_order_internal(self, cancel_data: dict, callback=None):
        """Internal order cancellation implementation"""
        try:
            logger.info(f"[CANCEL] Canceling order: {cancel_data}")

            # TODO: Implement order cancellation
            # mid = await self._send(PT_CANCEL_ORDER_REQ, cancel_data)
            # response = await self._receive(PT_CANCEL_ORDER_RES, expect_id=mid)

            if callback:
                callback({'success': True, 'data': cancel_data})

        except Exception as e:
            logger.error(f"[CANCEL] Error canceling order: {e}")
            if callback:
                callback({'success': False, 'error': str(e)})