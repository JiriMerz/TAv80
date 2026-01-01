#!/usr/bin/env python3
"""
Skript pro načtení testovacích historických dat z veřejného zdroje (Yahoo Finance)
Použije se pro backtesting, když jsou trhy zavřené nebo pro rychlé testování
"""

import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
import json

# Přidat src/ do Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

def generate_mock_data(symbol: str, count: int = 500) -> list:
    """
    Vygenerovat mock historická data pro testování
    Používá realistické ceny pro GER40 a US100
    """
    # Základní ceny pro symboly
    base_prices = {
        'GER40': 24300.0,
        'US100': 25500.0
    }
    
    base_price = base_prices.get(symbol, 10000.0)
    
    # Začít od současného času a jít zpět
    now = datetime.now(timezone.utc)
    # Zaokrouhlit na posledních 5 minut
    now = now.replace(minute=(now.minute // 5) * 5, second=0, microsecond=0)
    
    bars = []
    current_price = base_price
    
    for i in range(count):
        # Vypočítat timestamp (každých 5 minut zpět)
        bar_time = now - timedelta(minutes=5 * (count - i - 1))
        
        # Simulovat cenový pohyb (realističtější volatilita)
        import random
        random.seed(hash(f"{symbol}{bar_time.isoformat()}") % 1000)  # Pro konzistenci
        
        # Volatilita podle symbolu (GER40 ~100-200 pips, US100 ~50-150 pips)
        volatility = 150 if symbol == 'GER40' else 100
        
        # Generovat OHLC
        price_change = random.uniform(-volatility, volatility)
        open_price = current_price
        high_price = open_price + abs(random.uniform(0, volatility * 0.6))
        low_price = open_price - abs(random.uniform(0, volatility * 0.6))
        close_price = open_price + price_change
        
        # Zajistit, že high je nejvyšší a low je nejnižší
        high_price = max(open_price, high_price, close_price)
        low_price = min(open_price, low_price, close_price)
        
        # Zaokrouhlit na 2 desetinná místa
        open_price = round(open_price, 2)
        high_price = round(high_price, 2)
        low_price = round(low_price, 2)
        close_price = round(close_price, 2)
        
        # Objem (random, ale realistický)
        volume = random.randint(100, 1000)
        
        # Spread (realistický pro indexy)
        spread = round(random.uniform(1.5, 3.0), 2)
        
        bar = {
            "timestamp": bar_time.isoformat(),
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "volume": volume,
            "spread": spread
        }
        
        bars.append(bar)
        current_price = close_price  # Pro další iteraci
    
    return bars

def load_from_yahoo_finance(symbol: str, count: int = 500) -> list:
    """
    Načíst historická data z Yahoo Finance
    Poznámka: Yahoo Finance neposkytuje 5-minutová data přes API zdarma
    Použijeme denní data a interpolujeme je, nebo použijeme mock data
    """
    try:
        import yfinance as yf
        
        # Mapování symbolů
        yahoo_symbols = {
            'GER40': '^GDAXI',  # DAX index
            'US100': '^NDX',    # NASDAQ-100
        }
        
        yahoo_symbol = yahoo_symbols.get(symbol)
        if not yahoo_symbol:
            print(f"⚠️  Neznámý symbol: {symbol}, použiju mock data")
            return generate_mock_data(symbol, count)
        
        print(f"📥 Stahuji data pro {symbol} ({yahoo_symbol}) z Yahoo Finance...")
        
        # Stáhnout data za posledních několik dní (potřebujeme ~500 M5 barů = ~2 dny)
        ticker = yf.Ticker(yahoo_symbol)
        
        # Zkusit stáhnout 1-minutová data (pokud jsou dostupná)
        # Poznámka: Yahoo Finance má limit na historická intraday data (obvykle jen 7 dní zpět)
        data = ticker.history(period="5d", interval="1m")
        
        if data.empty:
            print(f"⚠️  Yahoo Finance nevrátila data, použiju mock data")
            return generate_mock_data(symbol, count)
        
        # Převést na M5 bary (agregovat 1-minutová data do 5-minutových)
        bars = []
        data_5min = data.resample('5T').agg({
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum'
        }).dropna()
        
        # Vzít posledních count barů
        data_5min = data_5min.tail(count)
        
        for idx, row in data_5min.iterrows():
            bar = {
                "timestamp": idx.to_pydatetime().replace(tzinfo=timezone.utc).isoformat(),
                "open": round(float(row['Open']), 2),
                "high": round(float(row['High']), 2),
                "low": round(float(row['Low']), 2),
                "close": round(float(row['Close']), 2),
                "volume": int(row['Volume']) if not pd.isna(row['Volume']) else 0,
                "spread": round(2.0 if symbol == 'GER40' else 2.5, 2)  # Odhadovaný spread
            }
            bars.append(bar)
        
        if len(bars) < count:
            print(f"⚠️  Yahoo Finance vrátila pouze {len(bars)} barů (požadováno {count}), použiju mock data pro zbytek")
            # Doplnit mock daty
            mock_bars = generate_mock_data(symbol, count - len(bars))
            bars = mock_bars + bars  # Mock data na začátek
        
        return bars[:count]
        
    except ImportError:
        print("⚠️  yfinance není nainstalováno, použiju mock data")
        print("   Pro instalaci: pip install yfinance")
        return generate_mock_data(symbol, count)
    except Exception as e:
        print(f"⚠️  Chyba při načítání z Yahoo Finance: {e}")
        print("   Použiju mock data")
        return generate_mock_data(symbol, count)

def save_bars_to_cache(symbol: str, bars: list, cache_dir: Path):
    """Uložit bary do cache souboru (JSONL formát)"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{symbol}_M5.jsonl"
    
    with open(cache_file, 'w') as f:
        for bar in bars:
            f.write(json.dumps(bar) + '\n')
    
    print(f"💾 Uloženo {len(bars)} barů do {cache_file}")

def main():
    print("=" * 60)
    print("📊 NAČÍTÁNÍ TESTOVACÍCH HISTORICKÝCH DAT")
    print("=" * 60)
    print()
    
    cache_dir = project_root / "backtesting" / "data"
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    symbols = ['GER40', 'US100']
    bars_count = 500  # Požadovaný počet barů
    
    all_data = {}
    
    for symbol in symbols:
        print(f"\n📊 Načítám data pro {symbol}...")
        
        # Zkusit načíst z Yahoo Finance
        bars = load_from_yahoo_finance(symbol, bars_count)
        
        if bars:
            print(f"✅ Načteno {len(bars)} barů pro {symbol}")
            if len(bars) > 0:
                first_bar = bars[0]
                last_bar = bars[-1]
                print(f"   První bar: {first_bar['timestamp']}")
                print(f"   Poslední bar: {last_bar['timestamp']}")
                print(f"   Cena (první/last): {first_bar['open']:.2f} / {last_bar['close']:.2f}")
            
            all_data[symbol] = bars
            save_bars_to_cache(symbol, bars, cache_dir)
        else:
            print(f"❌ Nepodařilo se načíst data pro {symbol}")
    
    print()
    print("=" * 60)
    print("📊 VÝSLEDEK")
    print("=" * 60)
    
    for symbol, bars in all_data.items():
        if bars:
            print(f"✅ {symbol}: {len(bars)} barů")
    
    print()
    print("💡 Tato data lze použít pro backtesting i když jsou trhy zavřené!")
    print()

if __name__ == "__main__":
    try:
        import pandas as pd
    except ImportError:
        print("⚠️  pandas není nainstalováno, použiju pouze mock data")
        print("   Pro instalaci: pip install pandas yfinance")
        pd = None
    
    main()

