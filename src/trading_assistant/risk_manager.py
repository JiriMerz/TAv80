"""
Risk Management & Position Sizing Module
Sprint 4: Complete implementation
Version 1.0.0
25-08-29 06:55
"""

from typing import Dict, Optional, List
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import threading
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


@dataclass
class PositionSize:
    """Position sizing calculation result"""
    symbol: str
    lots: float
    risk_amount_czk: float
    risk_percent: float
    margin_required_czk: float
    entry_price: float
    stop_loss: float
    take_profit: float
    potential_profit_czk: float
    point_value: float
    breakeven_points: float = 0
    units: int = 0
    commission_czk: float = 0
    position_id: str = ""  # cTrader position ID
    direction: str = ""    # BUY or SELL
    

@dataclass
class RiskStatus:
    """Current risk status"""
    open_positions: int
    total_risk_czk: float
    total_risk_pct: float
    margin_used_czk: float
    margin_used_pct: float
    daily_pnl_czk: float
    daily_pnl_pct: float
    can_trade: bool
    warnings: List[str]
    account_balance: float


class RiskManager:
    """
    Complete risk management system
    - Position sizing with multiple adjustments
    - Portfolio risk monitoring
    - Daily loss limits
    """
    
    def __init__(self, config: Dict, balance_tracker=None):
        """Initialize with configuration from apps.yaml"""

        self.config = config  # Uložit celý config pro pozdější použití
        self.balance_tracker = balance_tracker
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Account parameters
        self.account_balance = float(config.get('account_balance', 100000))
        self.account_currency = config.get('account_currency', 'CZK')
        self.max_risk_per_trade = float(config.get('max_risk_per_trade', 0.01))
        self.max_risk_total = float(config.get('max_risk_total', 0.03))
        self.max_positions = int(config.get('max_positions', 3))
        self.daily_loss_limit = float(config.get('daily_loss_limit', 0.02))
        self.max_margin_usage = float(config.get('max_margin_usage', 80.0))
        
        # Symbol specifications
        self.symbol_specs = config.get('symbol_specs', {})
        
        # Risk adjustments
        self.risk_adjustments = config.get('risk_adjustments', {})
        self.regime_adjustments = config.get('regime_adjustments', {})
        self.volatility_adjustments = config.get('volatility_adjustments', {})
        
        # PHASE 2: Dynamic risk reduction configuration
        drawdown_config = self.risk_adjustments.get('drawdown_reduction_enabled', False)
        self.drawdown_reduction_enabled = drawdown_config if isinstance(drawdown_config, bool) else False
        self.drawdown_threshold_pct = self.risk_adjustments.get('drawdown_threshold_pct', 0.10)  # 10%
        self.risk_reduction_factor = self.risk_adjustments.get('risk_reduction_factor', 0.5)  # 50% reduction
        self.recovery_threshold_pct = self.risk_adjustments.get('recovery_threshold_pct', 0.05)  # 5%
        
        # Track equity high for drawdown calculation
        self.equity_high = self.account_balance  # Initial equity high
        
        # Track current state
        self.open_positions: List[PositionSize] = []
        self.daily_pnl = 0.0
        self.last_reset_date = datetime.now(timezone.utc).date()

        # Auto-detect actual account size after balance tracker is available
        self._balance_detection_attempted = False

        logger.info(f"RiskManager initialized: Balance={self.account_balance} {self.account_currency}, "
                   f"Risk={self.max_risk_per_trade*100}%/trade, Max positions={self.max_positions}")
    
    def get_open_positions_copy(self, symbol: Optional[str] = None) -> List[PositionSize]:
        """
        Thread-safe getter for open positions
        
        Args:
            symbol: Optional symbol filter
            
        Returns:
            Copy of open positions list (filtered by symbol if provided)
        """
        with self._lock:
            if symbol:
                return [p for p in self.open_positions if p.symbol == symbol]
            return list(self.open_positions)

    def _auto_detect_account_size(self):
        """Auto-detect actual account size and update daily loss limit to 5%"""
        if self._balance_detection_attempted or not self.balance_tracker:
            return

        try:
            actual_balance = self.balance_tracker.get_current_balance()
            if actual_balance and actual_balance > 0 and actual_balance != self.account_balance:
                old_balance = self.account_balance
                old_daily_limit = self.daily_loss_limit

                # Update account balance
                self.account_balance = actual_balance

                # Keep daily loss limit from config (don't override with hardcoded value)
                # self.daily_loss_limit already set from config in __init__
                # PHASE 2: Respect config value (0.02 = 2%), don't override to 5%

                logger.warning(f"[AUTO-DETECT] Account size updated: {old_balance:,.0f} → {actual_balance:,.0f} {self.account_currency}")
                logger.info(f"[AUTO-DETECT] Daily loss limit: {self.daily_loss_limit*100:.1f}% = {actual_balance*self.daily_loss_limit:,.0f} CZK (from config)")

            self._balance_detection_attempted = True

        except Exception as e:
            logger.error(f"[AUTO-DETECT] Failed to detect account size: {e}")
            self._balance_detection_attempted = True

    def calculate_position_size(self, symbol: str, entry: float, stop_loss: float,
                           take_profit: float, regime: str = "UNKNOWN",
                           signal_quality: float = 50, atr: float = 0,
                           microstructure_data: Optional[Dict] = None,
                           swing_state: Optional[Dict] = None) -> Optional[PositionSize]:
        """Calculate position size with WIDE STOPS strategy for low pip values"""
        try:
            # Auto-detect account size if balance tracker is available
            self._auto_detect_account_size()

            symbol_spec = self._get_symbol_spec(symbol)
            if not symbol_spec:
                logger.error(f"[RISK] No spec for symbol {symbol}")
                return None
            
            # Get risk parameters
            risk_pct = self.max_risk_per_trade  # 0.005 = 0.5%
            
            # PHASE 2: Apply drawdown-based risk reduction
            if self.drawdown_reduction_enabled:
                current_drawdown_pct = self._calculate_current_drawdown()
                risk_adjustment = self._get_drawdown_risk_adjustment(current_drawdown_pct)
                risk_pct = risk_pct * risk_adjustment
                
                if risk_adjustment < 1.0:
                    logger.info(f"[RISK] Drawdown adjustment: {current_drawdown_pct*100:.1f}% drawdown → "
                              f"risk reduced to {risk_pct*100:.2f}% (factor: {risk_adjustment:.2f})")
            
            risk_amount_czk = self.account_balance * risk_pct
            
            # Get pip value (already per 1.0 lot)
            pip_value = symbol_spec.get('pip_value_per_lot', 0.21)
            
            logger.info(f"[RISK] === POSITION CALCULATION FOR {symbol} ===")
            logger.info(f"[RISK] Target risk: {risk_amount_czk:.0f} CZK ({risk_pct*100:.2f}%)")
            logger.info(f"[RISK] Pip value: {pip_value:.3f} CZK per pip per lot")
            
            # Calculate SL distance
            sl_distance_points = abs(entry - stop_loss)
            sl_distance_pips = sl_distance_points * 100  # FIXED: 1 point = 100 pips for DAX/NASDAQ
            
            # Get wide stops parameters
            use_wide_stops = self.config.get('use_wide_stops', True)
            target_position = self.config.get('target_position_lots', 5.0)
            min_position = self.config.get('min_position_lots', 1.0)
            max_position = self.config.get('max_position_lots', 15.0)
            
            # OLD LIMITS - NOW ONLY FOR DIAGNOSTICS (not used for clamping)
            legacy_min_sl = symbol_spec.get('min_sl_points', 150.0)
            legacy_max_sl = symbol_spec.get('max_sl_points', 300.0)
            legacy_optimal_sl = symbol_spec.get('optimal_sl_points', 200.0)

            # Initialize working limits (will be updated by ATR if reasonable)
            min_sl_points = legacy_min_sl
            max_sl_points = legacy_max_sl
            optimal_sl_points = legacy_optimal_sl
            
            # === SWING-BASED DYNAMIC ADJUSTMENT ===
            swing_sl_adjusted = False
            if swing_state and self.config.get('use_swing_stops', False):
                swing_sl = self._calculate_swing_based_sl(
                    symbol, entry, stop_loss, swing_state
                )
                if swing_sl:
                    old_sl = stop_loss
                    stop_loss = swing_sl['price']
                    sl_distance_points = abs(entry - stop_loss)
                    sl_distance_pips = sl_distance_points * 100  # FIXED: 1 point = 100 pips
                    swing_sl_adjusted = True
                    
                    logger.info(f"[RISK] SWING-BASED SL: {old_sl:.1f} → {stop_loss:.1f} "
                              f"(swing: {swing_sl['swing_type']} @ {swing_sl['swing_price']:.1f}, "
                              f"buffer: {swing_sl['buffer']:.1f})")
            
            # === ATR-BASED DYNAMIC ADJUSTMENT ===  
            if not swing_sl_adjusted and atr > 0:  # ATR dostupné a nepoužily se swingy
                atr_sl_multiplier = self.config.get('atr_sl_multiplier', 2.0)
                atr_min_multiplier = self.config.get('atr_min_multiplier', 1.5)
                atr_max_multiplier = self.config.get('atr_max_multiplier', 3.0)
                
                # Dynamické limity na základě ATR
                atr_based_min = atr * atr_min_multiplier
                atr_based_max = atr * atr_max_multiplier  
                atr_based_optimal = atr * atr_sl_multiplier
                
                logger.info(f"[RISK] ATR={atr:.1f}, ATR-based SL range: {atr_based_min:.1f}-{atr_based_max:.1f} (optimal: {atr_based_optimal:.1f})")
                
                # Použij ATR limity pokud jsou rozumné, jinak fallback na statické
                if atr_based_min >= 20 and atr_based_max <= 600:  # Relaxed sanity check for M5
                    min_sl_points = max(min_sl_points, atr_based_min)
                    max_sl_points = min(max_sl_points, atr_based_max) 
                    optimal_sl_points = atr_based_optimal
                    
                    logger.info(f"[RISK] Using ATR-based SL limits: {min_sl_points:.1f}-{max_sl_points:.1f} (optimal: {optimal_sl_points:.1f})")
                else:
                    logger.warning(f"[RISK] ATR-based limits unreasonable, using static fallback")
            elif not swing_sl_adjusted:
                logger.debug(f"[RISK] No ATR available, using static SL limits")
            
            logger.info(f"[RISK] Initial SL: {sl_distance_points:.1f} points ({sl_distance_pips:.0f} pips)")
            
            # === WIDE STOPS ADJUSTMENT ===
            if use_wide_stops and pip_value < 1.0:
                # Calculate what position we'd get with current SL
                theoretical_position = risk_amount_czk / (sl_distance_pips * pip_value)
                
                logger.info(f"[RISK] Theoretical position with current SL: {theoretical_position:.2f} lots")
                
                # If position would be too large, widen the SL
                if theoretical_position > max_position:
                    # Calculate required SL for target position
                    required_sl_pips = risk_amount_czk / (target_position * pip_value)
                    required_sl_points = required_sl_pips / 10
                    
                    logger.info(f"[RISK] Adjusting SL to {required_sl_points:.1f} points for {target_position:.1f} lot position")
                    
                    # Use the larger SL
                    if required_sl_points > sl_distance_points:
                        sl_distance_points = required_sl_points
                        sl_distance_pips = required_sl_pips
                        
                        # Adjust actual SL price
                        if stop_loss < entry:  # BUY
                            stop_loss = entry - sl_distance_points
                        else:  # SELL
                            stop_loss = entry + sl_distance_points
            
            # DIAGNOSTIC ONLY - old limits (no more clamping, just logging)
            if sl_distance_points < legacy_min_sl:
                logger.info(f"[DIAGNOSTIC] SL below legacy minimum: {sl_distance_points:.1f} < {legacy_min_sl} (not clamping)")
            elif sl_distance_points > legacy_max_sl:
                logger.info(f"[DIAGNOSTIC] SL above legacy maximum: {sl_distance_points:.1f} > {legacy_max_sl} (not clamping)")
            else:
                logger.info(f"[DIAGNOSTIC] SL within legacy range: {legacy_min_sl} <= {sl_distance_points:.1f} <= {legacy_max_sl}")

            # SL/TP band system will handle all clamping in main.py auto-trading section
            
            # === FIXED POSITION SIZING STRATEGY ===
            # Always use fixed position sizing for our strategy (8-20 lots range)
            target_position = symbol_spec.get('target_position_lots', 12.0)
            min_fixed_lots = self.config.get('min_position_lots', 8.0)
            max_fixed_lots = self.config.get('max_position_lots', 20.0)

            # Start with target position (12 lots)
            position_size = target_position

            logger.info(f"[RISK] FIXED POSITION SIZING: Base target {target_position:.1f} lots (range: {min_fixed_lots}-{max_fixed_lots})")
            
            # Apply adjustments
            regime_adj = self.regime_adjustments.get(regime, 1.0)
            quality_adj = self._get_quality_adjustment(signal_quality)
            
            # === MICROSTRUCTURE ADJUSTMENTS ===
            micro_adj = 1.0
            if microstructure_data:
                liquidity = microstructure_data.get('liquidity_score', 0.5)
                
                # Reduce position in low liquidity
                if liquidity < 0.5:
                    micro_adj = 0.7
                    logger.info(f"[RISK] Low liquidity {liquidity:.2f}, reducing risk by 30%")
                
                # Increase position in high liquidity with volume confirmation
                elif liquidity > 0.8 and microstructure_data.get('volume_zscore', 0) > 1:
                    micro_adj = 1.2
                    logger.info(f"[RISK] High liquidity with volume confirmation, increasing risk by 20%")
                
                # ORB bonus
                or_data = microstructure_data.get('opening_range', {})
                if or_data.get('orb_triggered'):
                    micro_adj = micro_adj * 1.1
                    logger.info(f"[RISK] ORB alignment, increasing position by 10%")
            
            # Apply quality adjustment only (limit other adjustments for fixed sizing)
            position_size = position_size * quality_adj

            # Limit micro adjustments to prevent extreme position sizes
            if micro_adj < 0.8:
                micro_adj = 0.8  # Max 20% reduction
            elif micro_adj > 1.2:
                micro_adj = 1.2  # Max 20% increase

            position_size = position_size * micro_adj

            logger.info(f"[RISK] After adjustments (quality={quality_adj:.2f}, micro={micro_adj:.2f}): {position_size:.1f} lots")

            # Round to lot step
            lot_step = symbol_spec['lot_step']
            position_size = round(position_size / lot_step) * lot_step

            # Apply FIXED POSITION LIMITS (8-20 lots)
            if position_size < min_fixed_lots:
                logger.info(f"[RISK] Position {position_size:.1f} < min {min_fixed_lots}, using minimum")
                position_size = min_fixed_lots
            elif position_size > max_fixed_lots:
                logger.info(f"[RISK] Position {position_size:.1f} > max {max_fixed_lots}, using maximum")
                position_size = max_fixed_lots
            
            # Margin check
            margin_per_lot = symbol_spec.get('margin_per_lot', 25000)
            required_margin = position_size * margin_per_lot
            
            used_margin = sum(pos.margin_required_czk for pos in self.open_positions)
            free_margin = self.account_balance - used_margin
            max_allowed_margin = free_margin * 0.5
            
            if required_margin > max_allowed_margin:
                max_lots = max_allowed_margin / margin_per_lot
                old_size = position_size
                position_size = round(max_lots / lot_step) * lot_step
                position_size = max(min_lot, position_size)
                
                logger.warning(f"[RISK] Margin constraint: reduced from {old_size:.2f} to {position_size:.2f} lots")
                required_margin = position_size * margin_per_lot
            
            # Final calculations
            actual_risk_czk = sl_distance_pips * position_size * pip_value
            actual_risk_pct = (actual_risk_czk / self.account_balance) * 100
            
            # INTRADAY-OPTIMIZED TP LOGIC
            tp_distance_points = abs(take_profit - entry)
            
            # Get intraday constraints from config
            max_intraday_tp_points = symbol_spec.get('max_intraday_tp_points', 60.0)  # Max 60 points pro intraday
            conservative_rrr_limit = self.config.get('conservative_rrr_limit', 1.8)  # Max 1.8:1 R:R pro intraday
            
            # Apply conservative intraday limits FIRST
            max_conservative_tp = sl_distance_points * conservative_rrr_limit
            max_allowed_tp = min(max_intraday_tp_points, max_conservative_tp)
            
            # If original TP is too aggressive, cap it
            if tp_distance_points > max_allowed_tp:
                tp_distance_points = max_allowed_tp
                logger.info(f"[RISK] TP capped for intraday realism: {tp_distance_points:.1f} points (was {abs(take_profit - entry):.1f})")
                
                if take_profit > entry:  # BUY
                    take_profit = entry + tp_distance_points
                else:  # SELL
                    take_profit = entry - tp_distance_points
            
            # Ensure minimum RRR (but not excessive)
            min_tp_distance = sl_distance_points * 1.3  # Lowered from 1.5 to 1.3
            if tp_distance_points < min_tp_distance:
                tp_distance_points = min(min_tp_distance, max_allowed_tp)  # Respect intraday cap
                
                if take_profit > entry:  # BUY
                    take_profit = entry + tp_distance_points
                else:  # SELL
                    take_profit = entry - tp_distance_points
            
            tp_distance_pips = tp_distance_points * 100  # FIXED: 1 point = 100 pips
            potential_profit_czk = tp_distance_pips * position_size * pip_value
            
            # Commission
            commission = symbol_spec.get('commission_per_lot', 4.20) * position_size
            
            # Final validation
            min_profit_ratio = self.config.get('min_profit_ratio', 0.25)
            min_required_profit = actual_risk_czk * min_profit_ratio
            
            if potential_profit_czk < min_required_profit:
                logger.warning(f"[RISK] Profit {potential_profit_czk:.0f} below minimum {min_required_profit:.0f} CZK - adjusting TP")
                
                # Increase TP to meet minimum
                required_tp_pips = (min_required_profit / (position_size * pip_value)) if (position_size * pip_value) > 0 else tp_distance_pips
                tp_distance_pips = max(tp_distance_pips, required_tp_pips)
                tp_distance_points = tp_distance_pips / 100  # FIXED: 1 point = 100 pips
                
                if take_profit > entry:  # BUY
                    take_profit = entry + tp_distance_points
                else:  # SELL
                    take_profit = entry - tp_distance_points
                    
                potential_profit_czk = tp_distance_pips * position_size * pip_value
            
            logger.info(f"[RISK] === FINAL POSITION ===")
            logger.info(f"  Size: {position_size:.2f} lots")
            logger.info(f"  SL: {sl_distance_pips:.0f} pips = {actual_risk_czk:.0f} CZK ({actual_risk_pct:.2f}%)")
            logger.info(f"  TP: {tp_distance_pips:.0f} pips = {potential_profit_czk:.0f} CZK")
            logger.info(f"  RRR: 1:{tp_distance_pips/sl_distance_pips if sl_distance_pips > 0 else 0:.1f}")
            logger.info(f"  Margin: {required_margin:.0f} CZK")
            
            return PositionSize(
                symbol=symbol,
                lots=position_size,
                risk_amount_czk=actual_risk_czk,
                risk_percent=actual_risk_pct,
                margin_required_czk=required_margin,
                entry_price=entry,
                stop_loss=stop_loss,  # ADJUSTED SL
                take_profit=take_profit,  # ADJUSTED TP
                potential_profit_czk=potential_profit_czk,
                point_value=sl_distance_points,
                breakeven_points=commission / (position_size * pip_value * 100) if position_size > 0 else 0,  # FIXED: 1 point = 100 pips
                commission_czk=commission
            )
            
        except Exception as e:
            logger.error(f"[RISK] Position sizing error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
        
    def add_position(self, position: PositionSize):
        """Add position to tracking (thread-safe)"""
        with self._lock:
            self.open_positions.append(position)
        
        # NOVÝ LOG - rozšířený
        total_risk = sum(p.risk_amount_czk for p in self.open_positions)
        total_risk_pct = (total_risk / self.account_balance) * 100
        
        logger.info(f"[RISK] Position added: {position.symbol} {position.lots:.2f} lots, "
                f"Risk: {position.risk_amount_czk:.0f} CZK")
        logger.info(f"[RISK] Portfolio update: {len(self.open_positions)} positions, "
                f"Total risk: {total_risk:.0f} CZK ({total_risk_pct:.1f}%), "
                f"Remaining capacity: {(self.max_positions - len(self.open_positions))} positions")
        
        # Warning pokud se blížíme k limitům
        if len(self.open_positions) >= self.max_positions - 1:
            logger.warning(f"[RISK] Approaching max positions limit: "
                        f"{len(self.open_positions)}/{self.max_positions}")
        
        if total_risk_pct >= (self.max_risk_total * 100) - 1:
            logger.warning(f"[RISK] Approaching max risk limit: "
                        f"{total_risk_pct:.1f}%/{self.max_risk_total*100:.1f}%")

    def remove_position(self, symbol: str, pnl_czk: float = 0):
        """Remove position and update daily PnL (thread-safe)"""
        with self._lock:
            # Najdi pozici pro log
            removed_position = None
            for p in self.open_positions:
                if p.symbol == symbol:
                    removed_position = p
                    break
            
            self.open_positions = [p for p in self.open_positions if p.symbol != symbol]
            self.daily_pnl += pnl_czk
        
        # ROZŠÍŘENÝ LOG
        if removed_position:
            logger.info(f"[RISK] Position closed: {symbol} {removed_position.lots:.2f} lots, "
                    f"PnL: {pnl_czk:+.0f} CZK, "
                    f"Risk was: {removed_position.risk_amount_czk:.0f} CZK")
        else:
            logger.warning(f"[RISK] Position closed: {symbol} (not found in tracking), "
                        f"PnL: {pnl_czk:+.0f} CZK")
        
        # Portfolio status po uzavření
        current_balance = (self.balance_tracker.get_current_balance()
                          if self.balance_tracker else self.account_balance)
        total_risk = sum(p.risk_amount_czk for p in self.open_positions)
        total_risk_pct = (total_risk / current_balance) * 100
        daily_pnl_pct = (self.daily_pnl / current_balance) * 100
        
        logger.info(f"[RISK] Portfolio after close: {len(self.open_positions)} positions, "
                f"Total risk: {total_risk:.0f} CZK ({total_risk_pct:.1f}%), "
                f"Daily PnL: {self.daily_pnl:+.0f} CZK ({daily_pnl_pct:+.1f}%)")
        
        # Warning/Info o daily PnL
        if daily_pnl_pct <= -self.daily_loss_limit * 100:
            logger.error(f"[RISK] ⛔ Daily loss limit reached: {daily_pnl_pct:.1f}% "
                        f"(limit: {-self.daily_loss_limit*100:.1f}%)")
        elif daily_pnl_pct <= -(self.daily_loss_limit * 100) * 0.5:
            logger.warning(f"[RISK] Approaching daily loss limit: {daily_pnl_pct:.1f}% "
                        f"(limit: {-self.daily_loss_limit*100:.1f}%)")
        elif daily_pnl_pct >= self.daily_loss_limit * 100:  # Dobrý den
            logger.info(f"[RISK] 🎯 Excellent day: {daily_pnl_pct:+.1f}% profit")

    def get_risk_status(self) -> RiskStatus:
        """Get current risk status"""

        # Auto-detect account size if balance tracker is available
        self._auto_detect_account_size()

        # Reset daily PnL if new day (midnight reset)
        today = datetime.now(ZoneInfo("Europe/Prague")).date()
        if today != self.last_reset_date:
            # ENHANCED LOGGING FOR MIDNIGHT RESET
            logger.error(f"[RISK] 🌅 MIDNIGHT RESET: New trading day {today}")
            if self.daily_pnl != 0:
                logger.error(f"[RISK] 🌅 Previous day final PnL: {self.daily_pnl:+.0f} CZK")

            self.daily_pnl = 0
            self.last_reset_date = today
            logger.error(f"[RISK] 🌅 Daily loss limit RESET - trading now allowed again")
        
        # Calculate totals using current balance
        current_balance = (self.balance_tracker.get_current_balance()
                          if self.balance_tracker else self.account_balance)
        
        # PHASE 2: Update equity high for drawdown calculation
        current_equity = current_balance
        if self.balance_tracker and hasattr(self.balance_tracker, 'unrealized_pnl'):
            current_equity = current_balance + (self.balance_tracker.unrealized_pnl or 0)
        
        if current_equity > self.equity_high:
            self.equity_high = current_equity
            logger.debug(f"[RISK] New equity high: {self.equity_high:,.0f} CZK")

        total_risk_czk = sum(p.risk_amount_czk for p in self.open_positions)
        total_risk_pct = (total_risk_czk / current_balance) * 100

        margin_used_czk = sum(p.margin_required_czk for p in self.open_positions)
        margin_used_pct = (margin_used_czk / current_balance) * 100

        # Include unrealized PnL in daily loss calculation for more accurate limit enforcement
        unrealized_pnl = (self.balance_tracker.unrealized_pnl
                          if self.balance_tracker else 0)
        total_daily_pnl = self.daily_pnl + unrealized_pnl
        daily_pnl_pct = (total_daily_pnl / current_balance) * 100
        
        # NOVÝ LOG - periodický status (jen občas)
        if not hasattr(self, '_last_status_log') or \
        (datetime.now() - self._last_status_log).seconds > 300:  # Každých 5 minut
            logger.debug(f"[RISK] Current status: Positions={len(self.open_positions)}, "
                        f"Risk={total_risk_czk:.0f} CZK ({total_risk_pct:.1f}%), "
                        f"Margin={margin_used_czk:.0f} CZK ({margin_used_pct:.1f}%), "
                        f"Daily PnL={self.daily_pnl:+.0f} + {unrealized_pnl:+.0f} = {total_daily_pnl:+.0f} CZK ({daily_pnl_pct:+.1f}%)")
            self._last_status_log = datetime.now()
        
        # Check limits
        warnings = []
        can_trade = True
        
        if len(self.open_positions) >= self.max_positions:
            warnings.append(f"Max positions reached ({self.max_positions})")
            can_trade = False
            # ENHANCED LOGGING
            logger.error(f"[RISK] 🚫 MAX POSITIONS LIMIT REACHED: {len(self.open_positions)}/{self.max_positions} - NO NEW POSITIONS ALLOWED")
            position_symbols = [p.symbol for p in self.open_positions]
            logger.error(f"[RISK] 🚫 Current positions: {', '.join(position_symbols)}")
            
        if total_risk_pct >= self.max_risk_total * 100:
            warnings.append(f"Max total risk reached ({self.max_risk_total*100:.1f}%)")
            can_trade = False
            # NOVÝ LOG
            logger.debug(f"[RISK] ⚠️ Total risk limit hit: {total_risk_pct:.1f}%/{self.max_risk_total*100:.1f}%")
            
        if daily_pnl_pct <= -self.daily_loss_limit * 100:
            warnings.append(f"Daily loss limit reached ({self.daily_loss_limit*100:.1f}%)")
            can_trade = False
            # ENHANCED LOGGING
            logger.error(f"[RISK] 🚫 DAILY LOSS LIMIT REACHED: {daily_pnl_pct:.1f}%/{-self.daily_loss_limit*100:.1f}% - NO NEW POSITIONS ALLOWED")
            logger.error(f"[RISK] 🚫 Daily PnL: {self.daily_pnl:+.0f} CZK (limit: {-current_balance*self.daily_loss_limit:+.0f} CZK)")
            
        if margin_used_pct > self.max_margin_usage:
            warnings.append(f"High margin usage ({margin_used_pct:.1f}%)")
            # NOVÝ LOG
            logger.warning(f"[RISK] ⚠️ High margin usage: {margin_used_pct:.1f}%/{self.max_margin_usage:.1f}%")
        
        # Log když se stav změní
        if hasattr(self, '_last_can_trade') and self._last_can_trade != can_trade:
            if can_trade:
                logger.info(f"[RISK] ✅ Trading enabled - all limits OK")
            else:
                logger.warning(f"[RISK] ⛔ Trading disabled: {', '.join(warnings)}")
        self._last_can_trade = can_trade
        
        return RiskStatus(
            open_positions=len(self.open_positions),
            total_risk_czk=round(total_risk_czk, 2),
            total_risk_pct=round(total_risk_pct, 2),
            margin_used_czk=round(margin_used_czk, 2),
            margin_used_pct=round(margin_used_pct, 2),
            daily_pnl_czk=round(self.daily_pnl, 2),
            daily_pnl_pct=round(daily_pnl_pct, 2),
            can_trade=can_trade,
            warnings=warnings,
            account_balance=round(self.account_balance, 2)
        )
        
    def _can_open_position(self) -> bool:
        """Check if can open new position"""
        status = self.get_risk_status()
        return status.can_trade
    
    def format_position_ticket(self, position: PositionSize, 
                     entry: float, stop: float, take: float) -> str:
        """Format position as trade ticket - plain text"""
        
        # Vypočítat pips
        sl_pips = abs(entry - stop) * 100  # FIXED: 1 point = 100 pips
        tp_pips = abs(take - entry) * 100  # FIXED: 1 point = 100 pips
        
        # Určit směr
        direction = "BUY" if stop < entry else "SELL"
        
        return f"""
        ===== TRADE TICKET =====
        Symbol: {position.symbol}
        Direction: {direction}
        
        Entry: {entry:.1f}
        Stop Loss: {stop:.1f} ({sl_pips:.0f} pips)
        Take Profit: {take:.1f} ({tp_pips:.0f} pips)
        
        Lots: {position.lots:.2f}
        Risk: {position.risk_amount_czk:.0f} CZK ({position.risk_percent:.2f}%)
        Margin: {position.margin_required_czk:.0f} CZK
        ======================
        """
    
    def _get_symbol_spec(self, symbol: str) -> Dict:
        """Get symbol specification - FIXED for M5 fallback values"""
        spec = self.symbol_specs.get(symbol, {})
        
        if not spec:
            # Try to map from raw symbol to spec key
            if 'DAX' in symbol.upper() or 'DE40' in symbol.upper() or 'DE' in symbol.upper():
                spec = self.symbol_specs.get('DAX', {})
            elif 'NASDAQ' in symbol.upper() or 'US100' in symbol.upper() or 'NAS' in symbol.upper():
                spec = self.symbol_specs.get('NASDAQ', {})
        
        if not spec:
            logger.warning(f"[RISK] No spec for {symbol}, using M5 defaults")
            return {
                'pip_value_per_lot': 0.21,
                'min_lot': 0.01,
                'max_lot': 20.0,
                'lot_step': 0.01,
                'margin_per_lot': 25000,
                'commission_per_lot': 4.20,
                'min_sl_points': 150.0,    # M5 wide stops
                'max_sl_points': 300.0,    # M5 wide stops
                'optimal_sl_points': 200.0, # M5 wide stops
                'max_spread_pips': 20.0
            }
        
        return spec

    def _get_quality_adjustment(self, quality: float) -> float:
        """Get risk adjustment based on signal quality"""
        if quality >= 80:
            return self.risk_adjustments.get('quality_80_plus', 1.2)
        elif quality >= 50:
            return self.risk_adjustments.get('quality_50_80', 1.0)
        else:
            return self.risk_adjustments.get('quality_below_50', 0.7)

    def _get_regime_adjustment(self, regime: str) -> float:
        """Get risk adjustment based on market regime"""
        return self.regime_adjustments.get(regime, 0.7)

    def _can_trade(self) -> bool:
        """Check if trading is enabled"""
        status = self.get_risk_status()
        return status.can_trade

    # === NEW: SL/TP Band System Methods ===

    def _pips_per_point(self, symbol: str) -> int:
        """Get pips per point for symbol conversion"""
        spec = self._get_symbol_spec(symbol) or {}
        pip_pos = int(spec.get("pip_position", 2))
        return 10 ** pip_pos

    def _points_from_pips(self, symbol: str, pips: float) -> float:
        """Convert pips to points for symbol"""
        return float(pips) / self._pips_per_point(symbol)

    def _sl_band_pips(self, symbol: str) -> tuple[float, float, float]:
        """Get SL band configuration: anchor, lo_pips, hi_pips"""
        spec = self._get_symbol_spec(symbol) or {}
        anchor = float(spec.get("sl_anchor_pips", 4000.0))
        band = float(spec.get("sl_band_pct", 0.25))
        lo, hi = anchor * (1.0 - band), anchor * (1.0 + band)
        return anchor, lo, hi

    def apply_structural_sl_band(self, symbol: str, structural_sl_points: float) -> tuple[float, dict]:
        """
        Apply SL band to structural SL calculation.
        Returns: (clamped_points, diagnostics)
        """
        pp = self._pips_per_point(symbol)
        anchor, lo_pips, hi_pips = self._sl_band_pips(symbol)

        # Convert structural SL (points -> pips)
        structural_pips = structural_sl_points * pp

        # Clamp to band
        clamped_pips = max(lo_pips, min(structural_pips, hi_pips))
        clamped_points = clamped_pips / pp

        diag = {
            "anchor_pips": int(anchor),
            "band_pct": (hi_pips - anchor) / anchor,  # ~0.25
            "structural_pips": round(structural_pips, 1),
            "clamped_pips": int(clamped_pips),
            "lo_pips": int(lo_pips),
            "hi_pips": int(hi_pips),
        }
        return clamped_points, diag

    def apply_structural_tp_band(
        self,
        symbol: str,
        final_sl_points: float,
        structural_tp_points: float = None
    ) -> tuple[float, dict]:
        """
        Apply TP band to structural TP calculation.
        If structural_tp_points is None, uses RRR target × final SL.
        Returns: (clamped_points, diagnostics)
        """
        spec = self._get_symbol_spec(symbol) or {}
        pp = self._pips_per_point(symbol)

        sl_anchor = float(spec.get("sl_anchor_pips", 4000.0))
        rr_target = float(spec.get("tp_rr_target", 2.0))

        # TP anchor: explicit tp_anchor_pips or sl_anchor * rr_target
        tp_anchor_pips = float(spec.get("tp_anchor_pips", sl_anchor * rr_target))
        band_pct = float(spec.get("tp_band_pct", spec.get("sl_band_pct", 0.25)))

        lo_pips = tp_anchor_pips * (1.0 - band_pct)
        hi_pips = tp_anchor_pips * (1.0 + band_pct)

        if structural_tp_points and structural_tp_points > 0:
            tp_struct_pips = structural_tp_points * pp
            source = "structural"
        else:
            # Default: maintain RRR × final SL
            tp_struct_pips = final_sl_points * pp * rr_target
            source = "rr_target"

        clamped_pips = max(lo_pips, min(tp_struct_pips, hi_pips))
        tp_points_final = clamped_pips / pp

        diag = {
            "tp_anchor_pips": int(round(tp_anchor_pips)),
            "band_pct": band_pct,
            "lo_pips": int(round(lo_pips)),
            "hi_pips": int(round(hi_pips)),
            "tp_struct_pips": int(round(tp_struct_pips)),
            "source": source,
            "clamped_pips": int(round(clamped_pips)),
        }
        return tp_points_final, diag

    def _calculate_margin_usage(self) -> float:
        """Calculate current margin usage percentage"""
        margin_used = sum(p.margin_required_czk for p in self.open_positions)
        return (margin_used / self.account_balance) * 100 if self.account_balance > 0 else 0
    
    def _calculate_swing_based_sl(self, symbol: str, entry: float, 
                                 original_sl: float, swing_state: Dict) -> Optional[Dict]:
        """
        Calculate stop loss based on recent swing structure
        
        Logic:
        - For BUY: Place SL below recent swing low with buffer
        - For SELL: Place SL above recent swing high with buffer
        - Buffer = 0.3×ATR or 10-30 points based on symbol
        - Respect min/max SL distance limits
        
        Args:
            symbol: Trading symbol
            entry: Entry price
            original_sl: Original stop loss price
            swing_state: Dictionary with swing data from SwingEngine
            
        Returns:
            Dict with swing-based SL info or None if not applicable
        """
        try:
            if not swing_state:
                return None
            
            # Get symbol specs for buffer calculation
            symbol_spec = self._get_symbol_spec(symbol)
            if not symbol_spec:
                return None
            
            # Determine trade direction
            is_buy = original_sl < entry
            
            # Get relevant swing levels
            last_high = swing_state.get('last_high')
            last_low = swing_state.get('last_low')
            swings = swing_state.get('swings', [])
            
            if not swings:
                logger.debug(f"[RISK] No swings available for swing-based SL")
                return None
            
            # Calculate buffer - use ATR if available, otherwise fixed
            buffer_points = self._calculate_swing_buffer(symbol, swing_state)
            
            swing_sl_price = None
            swing_type = None
            swing_price = None
            
            if is_buy and last_low:
                # BUY trade: SL below last swing low
                swing_price = last_low.get('price') if isinstance(last_low, dict) else last_low
                swing_sl_price = swing_price - buffer_points
                swing_type = "LOW"
                
                logger.info(f"[RISK] BUY swing SL: below last LOW {swing_price:.1f} - {buffer_points:.1f} = {swing_sl_price:.1f}")
                
            elif not is_buy and last_high:
                # SELL trade: SL above last swing high  
                swing_price = last_high.get('price') if isinstance(last_high, dict) else last_high
                swing_sl_price = swing_price + buffer_points
                swing_type = "HIGH"
                
                logger.info(f"[RISK] SELL swing SL: above last HIGH {swing_price:.1f} + {buffer_points:.1f} = {swing_sl_price:.1f}")
            
            if swing_sl_price is None:
                logger.debug(f"[RISK] No relevant swing level found for direction")
                return None
            
            # Validate swing SL distance
            sl_distance = abs(entry - swing_sl_price)
            # Legacy swing constraints (diagnostic only, no clamping)
            legacy_min_sl = symbol_spec.get('min_sl_points', 150.0)
            legacy_max_sl = symbol_spec.get('max_sl_points', 300.0)
            swing_min_sl = self.config.get('swing_min_sl_points', legacy_min_sl * 0.8)
            swing_max_sl = self.config.get('swing_max_sl_points', legacy_max_sl * 1.5)

            # Diagnostic logging only (no more clamping)
            if sl_distance < swing_min_sl:
                logger.info(f"[SWING DIAGNOSTIC] SL below legacy swing minimum: {sl_distance:.1f} < {swing_min_sl:.1f}")
            elif sl_distance > swing_max_sl:
                logger.info(f"[SWING DIAGNOSTIC] SL above legacy swing maximum: {sl_distance:.1f} > {swing_max_sl:.1f}")
            else:
                logger.info(f"[SWING DIAGNOSTIC] SL within legacy swing range: {swing_min_sl:.1f} <= {sl_distance:.1f} <= {swing_max_sl:.1f}")

            # Use swing SL as calculated (no clamping)
            
            # Check if swing SL is better than original
            original_distance = abs(entry - original_sl)
            swing_distance = abs(entry - swing_sl_price)
            
            # Prefer swing SL if it's reasonable and follows market structure
            if abs(swing_distance - original_distance) / original_distance > 2.0:  # More than 200% different
                logger.warning(f"[RISK] Swing SL too different from original: {swing_distance:.1f} vs {original_distance:.1f}")
                return None
            
            return {
                'price': swing_sl_price,
                'swing_type': swing_type,
                'swing_price': swing_price,
                'buffer': buffer_points,
                'distance_points': swing_distance,
                'original_distance': original_distance,
                'improvement': original_distance - swing_distance
            }
            
        except Exception as e:
            logger.error(f"[RISK] Error calculating swing-based SL: {e}")
            return None
    
    def _calculate_swing_buffer(self, symbol: str, swing_state: Dict) -> float:
        """
        Calculate buffer for swing-based stop loss
        
        Priority:
        1. ATR-based: 0.3×ATR (adaptive to volatility) 
        2. Swing quality-based: Higher quality = smaller buffer
        3. Fixed fallback: 20-30 points based on symbol
        """
        try:
            # Get base buffer from symbol specs
            symbol_spec = self._get_symbol_spec(symbol)
            base_buffer = symbol_spec.get('swing_buffer_points', 20.0) if symbol_spec else 20.0
            
            # Try ATR-based buffer first (preferred)
            last_impulse_atr = swing_state.get('last_impulse_atr', 0)
            if last_impulse_atr > 0:
                # Use 30% of last impulse move as buffer
                atr_buffer = last_impulse_atr * 0.3
                atr_buffer_points = atr_buffer  # ATR already in points, no conversion needed
                
                # Reasonable bounds for ATR buffer
                if 10 <= atr_buffer_points <= 60:
                    logger.debug(f"[RISK] Using ATR-based buffer: {atr_buffer_points:.1f} points")
                    return atr_buffer_points
            
            # Quality-based adjustment
            swing_quality = swing_state.get('swing_quality', 50)
            if swing_quality > 80:
                quality_multiplier = 0.8  # High quality = smaller buffer
            elif swing_quality > 60:
                quality_multiplier = 1.0  # Normal buffer
            else:
                quality_multiplier = 1.3  # Low quality = larger buffer
            
            final_buffer = base_buffer * quality_multiplier
            logger.debug(f"[RISK] Using quality-adjusted buffer: {final_buffer:.1f} points (quality: {swing_quality:.1f})")
            
            return final_buffer
            
        except Exception as e:
            logger.error(f"[RISK] Error calculating swing buffer: {e}")
            return 20.0  # Safe fallback
    
    def _calculate_current_drawdown(self) -> float:
        """
        Calculate current drawdown percentage from equity high
        
        Returns:
            Drawdown as decimal (0.10 = 10% drawdown)
        """
        if not self.drawdown_reduction_enabled:
            return 0.0
        
        current_balance = (self.balance_tracker.get_current_balance()
                          if self.balance_tracker else self.account_balance)
        
        # Include unrealized PnL in equity calculation
        current_equity = current_balance
        if self.balance_tracker and hasattr(self.balance_tracker, 'unrealized_pnl'):
            current_equity = current_balance + (self.balance_tracker.unrealized_pnl or 0)
        
        if self.equity_high <= 0:
            return 0.0
        
        if current_equity > self.equity_high:
            self.equity_high = current_equity
            return 0.0
        
        drawdown = (self.equity_high - current_equity) / self.equity_high
        return max(0.0, drawdown)
    
    def _get_drawdown_risk_adjustment(self, drawdown_pct: float) -> float:
        """
        Get risk adjustment factor based on current drawdown
        
        Args:
            drawdown_pct: Current drawdown as decimal (0.10 = 10%)
            
        Returns:
            Risk adjustment factor (1.0 = no change, 0.5 = half risk)
        """
        if not self.drawdown_reduction_enabled:
            return 1.0
        
        # If drawdown exceeds threshold, reduce risk
        if drawdown_pct >= self.drawdown_threshold_pct:
            logger.warning(f"[RISK] Drawdown {drawdown_pct*100:.1f}% >= threshold {self.drawdown_threshold_pct*100:.1f}% - "
                          f"applying risk reduction factor {self.risk_reduction_factor:.2f}")
            return self.risk_reduction_factor
        
        # If drawdown below recovery threshold, return to normal
        if drawdown_pct <= self.recovery_threshold_pct:
            return 1.0
        
        # Linear interpolation between recovery and threshold
        # At recovery_threshold: factor = 1.0
        # At drawdown_threshold: factor = risk_reduction_factor
        if self.drawdown_threshold_pct > self.recovery_threshold_pct:
            ratio = (drawdown_pct - self.recovery_threshold_pct) / (self.drawdown_threshold_pct - self.recovery_threshold_pct)
            factor = 1.0 - (ratio * (1.0 - self.risk_reduction_factor))
            return max(self.risk_reduction_factor, min(1.0, factor))
        
        return 1.0