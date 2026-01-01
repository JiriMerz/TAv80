#!/usr/bin/env python3
"""
Stažení historických dat z Yahoo Finance pro backtesting
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, List

# Přidat src/ do Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

def download_from_yahoo(symbol: str, yahoo_symbol: str, period: str = "5d", interval: str = "5m") -> List[Dict]:
    """
    Stáhnout data z Yahoo Finance
    
    Args:
        symbol: Trading symbol (GER40, US100)
        yahoo_symbol: Yahoo Finance symbol (^GDAXI, ^NDX)
        period: Time period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max)
        interval: Interval (1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo)
    
    Returns:
        List of bar dictionaries
    """
    try:
        import yfinance as yf
        import pandas as pd
    except ImportError:
        print("❌ yfinance nebo pandas není nainstalován!")
        print("   Instalace: pip install yfinance pandas")
        return []
    
    print(f"📥 Stahuji data pro {symbol} ({yahoo_symbol}) z Yahoo Finance...")
    print(f"   Period: {period}, Interval: {interval}")
    
    try:
        ticker = yf.Ticker(yahoo_symbol)
        data = ticker.history(period=period, interval=interval)
        
        if data.empty:
            print(f"⚠️  Žádná data z Yahoo Finance pro {symbol}")
            return []
        
        print(f"✅ Staženo {len(data)} záznamů z Yahoo Finance")
        
        # Převést na náš formát
        bars = []
        for index, row in data.iterrows():
            # Convert index to UTC timestamp
            if index.tzinfo is None:
                # Assume UTC if no timezone info
                timestamp = index.replace(tzinfo=timezone.utc)
            else:
                timestamp = index.astimezone(timezone.utc)
            
            bar = {
                "timestamp": timestamp.isoformat(),
                "open": round(float(row['Open']), 2),
                "high": round(float(row['High']), 2),
                "low": round(float(row['Low']), 2),
                "close": round(float(row['Close']), 2),
                "volume": int(row['Volume']) if 'Volume' in row and not pd.isna(row['Volume']) else 0,
                "spread": round(2.5 if symbol == 'GER40' else 2.0, 2)  # Simulovaný spread
            }
            bars.append(bar)
        
        print(f"✅ Převzato {len(bars)} barů do našeho formátu")
        
        # Seřadit podle timestampu
        bars.sort(key=lambda b: b['timestamp'])
        
        return bars
        
    except Exception as e:
        print(f"❌ Chyba při stahování z Yahoo Finance: {e}")
        import traceback
        traceback.print_exc()
        return []

def save_data_to_jsonl(data: List[Dict], output_file: Path):
    """Uložit data do JSONL souboru"""
    with open(output_file, 'w') as f:
        for bar in data:
            f.write(json.dumps(bar) + "\n")
    print(f"💾 Uloženo {len(data)} barů do {output_file}")

def main():
    """Hlavní funkce"""
    print("=" * 70)
    print("📊 STAŽENÍ HISTORICKÝCH DAT Z YAHOO FINANCE")
    print("=" * 70)
    print()
    
    # Yahoo Finance symboly
    symbols = {
        'GER40': '^GDAXI',  # DAX index
        'US100': '^NDX',    # NASDAQ-100
    }
    
    # Period a interval
    # Zkusíme stáhnout 5-minutová intraday data (což potřebujeme pro backtesting)
    # Pro intraday data: max ~60 dní historie
    period = "60d"  # 60 dní historie (max pro intraday)
    interval = "5m"  # 5-minutové bary (což potřebujeme pro backtesting)
    print("📊 Stahuji 5-minutová intraday data z Yahoo Finance...")
    print(f"   Period: {period}, Interval: {interval}")
    
    data_dir = project_root / "backtesting" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    
    loaded_data = {}
    
    try:
        import pandas as pd
    except ImportError:
        print("❌ pandas není nainstalován!")
        print("   Instalace: pip install pandas")
        return
    
    # Import pandas i do download funkce
    import pandas as pd
    
    # Zkusit stáhnout data s různými nastaveními
    for symbol, yahoo_symbol in symbols.items():
        print(f"\n{'='*70}")
        print(f"📈 Zpracovávám {symbol} ({yahoo_symbol})")
        print('='*70)
        
        bars = download_from_yahoo(symbol, yahoo_symbol, period=period, interval=interval)
        
        if bars:
            first_bar = bars[0]
            last_bar = bars[-1]
            
            print(f"✅ Načteno {len(bars)} barů pro {symbol}")
            print(f"   První bar: {first_bar['timestamp'][:19]}")
            print(f"   Poslední bar: {last_bar['timestamp'][:19]}")
            print(f"   Cena (první/last): {first_bar['open']:.2f} / {last_bar['close']:.2f}")
            
            # Uložit do souboru jako M5 (5-minutová data)
            output_file = data_dir / f"{symbol}_M5.jsonl"
            save_data_to_jsonl(bars, output_file)
            loaded_data[symbol] = len(bars)
        else:
            print(f"❌ Nepodařilo se načíst data pro {symbol}")
            loaded_data[symbol] = 0
    
    print()
    print("=" * 70)
    print("📊 VÝSLEDEK")
    print("=" * 70)
    for symbol, count in loaded_data.items():
        status = "✅" if count > 0 else "❌"
        print(f"{status} {symbol}: {count} barů")
    
    print()
    print("💡 Data jsou uložena v backtesting/data/ a lze je použít pro backtesting!")
    print("   Spuštění: python3 backtesting/production_backtest.py")

if __name__ == "__main__":
    main()

