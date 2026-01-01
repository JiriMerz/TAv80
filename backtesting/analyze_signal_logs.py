#!/usr/bin/env python3
"""
Script to analyze logs and identify why signals were not generated.
Looks for blocking conditions in process_market_data and detect_signals.
"""

import re
import sys
from collections import defaultdict
from datetime import datetime

def analyze_log_file(log_file_path: str):
    """Analyze log file and identify signal blocking reasons"""
    
    blocking_reasons = defaultdict(list)
    signal_attempts = []
    last_state = {}
    
    try:
        with open(log_file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"❌ Log file not found: {log_file_path}")
        print("Please provide the path to your log file.")
        return
    
    print(f"📊 Analyzing log file: {log_file_path}")
    print(f"📝 Total lines: {len(lines)}\n")
    
    for i, line in enumerate(lines, 1):
        # Find [PROCESS_DATA] entries
        if '[PROCESS_DATA]' in line:
            # Extract symbol
            symbol_match = re.search(r'\[PROCESS_DATA\] (\w+):', line)
            symbol = symbol_match.group(1) if symbol_match else 'UNKNOWN'
            
            # Check for blocking conditions
            if 'BLOCKED' in line:
                reason_match = re.search(r'BLOCKED - (.+)', line)
                if reason_match:
                    reason = reason_match.group(1).strip()
                    blocking_reasons[reason].append((i, line.strip()))
                    print(f"🚫 Line {i}: {symbol} - {reason}")
            
            # Check for successful entry
            if 'Entry -' in line:
                bars_match = re.search(r'(\d+) bars available', line)
                bars = bars_match.group(1) if bars_match else '?'
                signal_attempts.append({
                    'line': i,
                    'symbol': symbol,
                    'bars': bars,
                    'timestamp': extract_timestamp(line)
                })
        
        # Find [SIGNAL_CHECK] entries
        if '[SIGNAL_CHECK]' in line:
            symbol_match = re.search(r'\[SIGNAL_CHECK\] (\w+):', line)
            symbol = symbol_match.group(1) if symbol_match else 'UNKNOWN'
            signal_attempts.append({
                'line': i,
                'symbol': symbol,
                'type': 'SIGNAL_CHECK',
                'timestamp': extract_timestamp(line)
            })
        
        # Find [SIGNAL_DETECT] entries
        if '[SIGNAL_DETECT]' in line:
            if 'Starting signal detection' in line:
                symbol_match = re.search(r'\[SIGNAL_DETECT\] Starting signal detection', line)
                if symbol_match:
                    # Extract details
                    bars_match = re.search(r'bars=(\d+)', line)
                    price_match = re.search(r'price=([\d.]+)', line)
                    regime_match = re.search(r'regime=(\w+)', line)
                    
                    signal_attempts.append({
                        'line': i,
                        'type': 'SIGNAL_DETECT_START',
                        'bars': bars_match.group(1) if bars_match else '?',
                        'price': price_match.group(1) if price_match else '?',
                        'regime': regime_match.group(1) if regime_match else '?',
                        'timestamp': extract_timestamp(line)
                    })
            
            if 'No signals generated' in line:
                blocking_reasons['Edge detection filters'].append((i, line.strip()))
                print(f"🚫 Line {i}: Edge detection filters blocked signal")
            
            if 'SUCCESS' in line:
                signals_match = re.search(r'(\d+) signal\(s\) generated', line)
                signals_count = signals_match.group(1) if signals_match else '?'
                print(f"✅ Line {i}: {signals_count} signal(s) generated!")
        
        # Find [STRICT_FILTER] entries
        if '[STRICT_FILTER]' in line:
            if 'BLOCKED' in line:
                blocking_reasons['Strict regime filter'].append((i, line.strip()))
                print(f"🚫 Line {i}: Strict regime filter blocked")
        
        # Find [SWING_QUALITY] entries
        if '[SWING_QUALITY]' in line:
            if 'BLOCKED' in line:
                blocking_reasons['Low swing quality'].append((i, line.strip()))
                print(f"🚫 Line {i}: Swing quality too low")
        
        # Find [PULLBACK_CHECK] entries
        if '[PULLBACK_CHECK]' in line:
            # Check for blocking in pullback detection (look ahead for rejection)
            pass  # Will check in context
        
        # Find [PATTERN_DETECT] entries
        if '[PATTERN_DETECT]' in line:
            if 'Skipping - not in pullback zone' in line:
                blocking_reasons['Not in pullback zone'].append((i, line.strip()))
                print(f"🚫 Line {i}: Not in pullback zone (trend detected but price not at pullback)")
        
        # Find [SIGNAL_QUALITY] entries
        if '[SIGNAL_QUALITY]' in line:
            if 'BLOCKED' in line:
                blocking_reasons['Signal quality/confidence too low'].append((i, line.strip()))
                print(f"🚫 Line {i}: Signal quality/confidence below threshold")
        
        # Find [MICRO] entries (microstructure blocking)
        if '[MICRO]' in line:
            if 'Poor market conditions' in line or 'Outside prime trading hours' in line or 'Suboptimal trading conditions' in line:
                blocking_reasons['Microstructure quality'].append((i, line.strip()))
                print(f"🚫 Line {i}: Microstructure quality insufficient")
        
        # Find [COOLDOWN] entries
        if '[COOLDOWN]' in line:
            if 'blocked' in line.lower() or 'active' in line.lower():
                blocking_reasons['Cooldown'].append((i, line.strip()))
                print(f"🚫 Line {i}: Signal cooldown active")
        
        # Find [REGIME] entries to track regime state
        if '[REGIME]' in line and 'FINAL REGIME STATE' in line:
            # Next few lines will contain regime details
            for j in range(i, min(i+20, len(lines))):
                if 'Regime:' in lines[j]:
                    regime_match = re.search(r'Regime: (\w+)', lines[j])
                    if regime_match:
                        last_state['regime'] = regime_match.group(1)
                if 'Confidence:' in lines[j]:
                    conf_match = re.search(r'Confidence: ([\d.]+)', lines[j])
                    if conf_match:
                        last_state['confidence'] = conf_match.group(1)
                if 'EMA34 Trend:' in lines[j]:
                    ema_match = re.search(r'EMA34 Trend: (\w+)', lines[j])
                    if ema_match:
                        last_state['ema34_trend'] = ema_match.group(1)
                if 'Primary' in lines[j] and 'bars' in lines[j]:
                    primary_match = re.search(r'Primary.*?(\w+).*?Confidence: ([\d.]+)', lines[j])
                    if primary_match:
                        last_state['primary_regime'] = primary_match.group(1)
                        last_state['primary_confidence'] = primary_match.group(2)
                if 'Secondary' in lines[j] and 'bars' in lines[j]:
                    secondary_match = re.search(r'Secondary.*?(\w+).*?Confidence: ([\d.]+)', lines[j])
                    if secondary_match:
                        last_state['secondary_regime'] = secondary_match.group(1)
                        last_state['secondary_confidence'] = secondary_match.group(2)
                if 'Trend Change:' in lines[j]:
                    trend_change_match = re.search(r'Trend Change: (\w+)', lines[j])
                    if trend_change_match:
                        last_state['trend_change'] = trend_change_match.group(1)
    
    # Summary
    print("\n" + "="*80)
    print("📊 SUMMARY")
    print("="*80)
    
    print(f"\n🔍 Signal detection attempts: {len(signal_attempts)}")
    if signal_attempts:
        print("   Recent attempts:")
        for attempt in signal_attempts[-5:]:  # Show last 5
            print(f"     • Line {attempt['line']}: {attempt.get('type', 'PROCESS_DATA')} - {attempt.get('symbol', 'UNKNOWN')} - Bars: {attempt.get('bars', '?')}")
    
    if blocking_reasons:
        print(f"\n🚫 Blocking reasons found: {len(blocking_reasons)} categories")
        # Sort by frequency (most common first)
        sorted_reasons = sorted(blocking_reasons.items(), key=lambda x: len(x[1]), reverse=True)
        for reason, occurrences in sorted_reasons:
            print(f"\n  • {reason}: {len(occurrences)} occurrence(s)")
            # Show first 3 examples with more context
            for line_num, log_line in occurrences[:3]:
                # Truncate long lines but keep important info
                if len(log_line) > 120:
                    display_line = log_line[:120] + "..."
                else:
                    display_line = log_line
                print(f"    Line {line_num}: {display_line}")
    else:
        print("\n✅ No explicit blocking conditions found in logs")
        print("   Signals may be blocked by edge detection filters (check [SIGNAL_DETECT] logs)")
        print("   Or no signal detection was attempted")
    
    if last_state:
        print(f"\n📈 Last detected regime state:")
        for key, value in last_state.items():
            print(f"   {key}: {value}")
    
    # Recommendations
    print("\n" + "="*80)
    print("💡 RECOMMENDATIONS")
    print("="*80)
    
    if not blocking_reasons:
        print("""
  No explicit blocking conditions found. Check:
  1. [SIGNAL_DETECT] logs for filter rejections
  2. [STRICT_FILTER] logs for regime/EMA34 conflicts
  3. [PULLBACK_CHECK] logs for pullback validation
  4. [PATTERN_DETECT] logs for pattern detection
  5. [SIGNAL_QUALITY] logs for quality thresholds
  
  To see more details, search for:
  - "[SIGNAL_DETECT]"
  - "[STRICT_FILTER]"
  - "[PULLBACK_CHECK]"
  - "[PATTERN_DETECT]"
  - "[SIGNAL_QUALITY]"
        """)
    else:
        for reason in blocking_reasons.keys():
            if 'cTrader not connected' in reason:
                print("  • Ensure cTrader client is connected")
            elif 'Analysis not running' in reason:
                print("  • Check sensor.trading_analysis_status is RUNNING")
            elif 'Insufficient bars' in reason:
                print("  • Wait for more market data to accumulate")
            elif 'active tickets' in reason.lower():
                print("  • Close existing positions before new signals")
            elif 'trading hours' in reason.lower():
                print("  • Check trading hours configuration")
            elif 'Risk manager' in reason:
                print("  • Check risk manager status (can_trade=False)")
            elif 'market conditions' in reason.lower():
                print("  • Market conditions suboptimal (liquidity/microstructure)")
            elif 'Edge detector' in reason:
                print("  • Edge detector not initialized - check initialization")
            elif 'Strict regime filter' in reason:
                print("  • Regime and EMA34 must both confirm trend direction")
                print("    Check regime state and EMA34 trend alignment")
                print("    To disable: Set strict_regime_filter: false in config")
            elif 'Low swing quality' in reason:
                print("  • Swing quality is below minimum threshold")
                print("    Increase swing quality or adjust min_swing_quality in config")
            elif 'Not in pullback zone' in reason:
                print("  • System is in trend but price is not at pullback level")
                print("    This is expected behavior - signals only in pullback zones during trends")
            elif 'Signal quality/confidence too low' in reason:
                print("  • Signal quality or confidence below minimum threshold")
                print("    Adjust min_signal_quality or min_confidence in config")
            elif 'Microstructure quality' in reason:
                print("  • Market conditions are suboptimal (low liquidity/volume)")
                print("    Wait for better market conditions or adjust microstructure thresholds")
            elif 'Cooldown' in reason:
                print("  • Wait for signal cooldown period to expire")
                print("    Cooldown is reduced if market changes significantly")

def extract_timestamp(line: str) -> str:
    """Extract timestamp from log line"""
    # Try to match common log formats
    timestamp_patterns = [
        r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)',  # 2025-12-26 14:19:09.849
        r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})',        # 2025-12-26 14:19:09
    ]
    
    for pattern in timestamp_patterns:
        match = re.search(pattern, line)
        if match:
            return match.group(1)
    
    return "N/A"

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analyze_signal_logs.py <log_file_path>")
        print("\nExample:")
        print("  python analyze_signal_logs.py /path/to/appdaemon.log")
        sys.exit(1)
    
    log_file_path = sys.argv[1]
    analyze_log_file(log_file_path)

