#!/usr/bin/env python3
"""
Načtení historických dat z cTrader účtu pro GER40 a US100

Jednoduchý skript pro načtení a ověření historických dat.
"""

import sys
import json
import asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List
import logging

# Potlačit verbose logy z cTrader clientu
logging.getLogger('trading_assistant').setLevel(logging.WARNING)
logging.getLogger('root').setLevel(logging.WARNING)

# Přidat src/ do Python path pro import trading_assistant modulů
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

def load_secrets() -> Dict:
    """Načíst credentials ze secrets.yaml"""
    secrets_path = project_root / "src" / "secrets.yaml"
    if not secrets_path.exists():
        raise FileNotFoundError(f"secrets.yaml not found at {secrets_path}")
    
    # Jednoduché parsování YAML (bez závislosti na PyYAML)
    secrets = {}
    with open(secrets_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and ':' in line:
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip().strip('"\'')  # Odstranit uvozovky
                secrets[key] = value
    
    return secrets


async def load_historical_data():
    """Načíst historická data z cTrader"""
    try:
        secrets = load_secrets()
    except FileNotFoundError as e:
        print(f"❌ ERROR: {e}")
        print("\n💡 Tip: Ujisti se, že soubor src/secrets.yaml existuje s cTrader credentials")
        return None
    
    # Pokusit se opravit SSL problémy pomocí certifi
    try:
        import ssl
        import certifi
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        print("✅ SSL kontext vytvořen pomocí certifi")
    except ImportError:
        print("⚠️  certifi není nainstalováno, používám default SSL kontext")
        print("💡 Pro opravu SSL problémů spusť: pip install certifi")
        ssl_context = None
    except Exception as e:
        print(f"⚠️  Problém s SSL kontextem: {e}")
        ssl_context = None
    
    # Načíst cTrader client
    from trading_assistant.ctrader_client import CTraderClient
    
    # Monkey-patch pro přidání SSL kontextu do websockets.connect
    original_connect = None
    try:
        import websockets
        original_connect = websockets.connect
        
        if ssl_context:
            # Vytvořit wrapper pro websockets.connect s SSL kontextem
            async def connect_with_ssl(*args, **kwargs):
                if len(args) > 0 and isinstance(args[0], str) and args[0].startswith('wss://'):
                    if 'ssl' not in kwargs:
                        kwargs['ssl'] = ssl_context
                return await original_connect(*args, **kwargs)
            
            websockets.connect = connect_with_ssl
            print("✅ SSL kontext aplikován na websockets.connect")
        else:
            # Pokud nemáme ssl_context, zkusit unverified SSL pro testování
            print("⚠️  Používám unverified SSL kontext (pouze pro testování)")
            import ssl
            unverified_ssl = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            unverified_ssl.check_hostname = False
            unverified_ssl.verify_mode = ssl.CERT_NONE
            
            async def connect_with_unverified_ssl(*args, **kwargs):
                if len(args) > 0 and isinstance(args[0], str) and args[0].startswith('wss://'):
                    if 'ssl' not in kwargs:
                        kwargs['ssl'] = unverified_ssl
                return await original_connect(*args, **kwargs)
            
            websockets.connect = connect_with_unverified_ssl
    except Exception as e:
        print(f"⚠️  Nelze upravit websockets.connect: {e}")
        print("💡 Zkus nainstalovat certifi: pip install certifi")
    
    # Konfigurace pro cTrader client
    config = {
        'ws_uri': secrets.get('ws_uri'),
        'client_id': secrets.get('client_id'),
        'client_secret': secrets.get('client_secret'),
        'access_token': secrets.get('access_token'),
        'ctid_trader_account_id': secrets.get('ctid_trader_account_id'),
        'trader_login': secrets.get('trader_login'),
        'symbols': [
            {'name': 'GER40'},
            {'name': 'US100'}
        ],
        'symbol_id_overrides': {
            'GER40': 203,
            'US100': 208
        },
        'history_cache_dir': str(project_root / "backtesting" / "data"),
        'history_bars_count': 500,  # ~2 dny M5 dat
        'bar_warmup': 100
    }
    
    print("📡 Připojování k cTrader...")
    client = CTraderClient(config)
    
    # Spustit client v async kontextu
    try:
        # Start connection
        await client.connect_and_stream()
        
        # Počkat na připojení a autentizaci
        await asyncio.sleep(3)
        
        print("⏳ Načítám historická data...")
        
        # Načíst historická data
        await client._bootstrap_history(count=500)
        
        # Počkat na dokončení načítání
        await asyncio.sleep(5)
        
        # Získat načtená data
        results = {}
        for symbol in ['GER40', 'US100']:
            if symbol in client.bars:
                bars = list(client.bars[symbol])
                results[symbol] = bars
                print(f"✅ {symbol}: Načteno {len(bars)} barů")
                
                if bars:
                    first_bar = bars[0]
                    last_bar = bars[-1]
                    print(f"   První bar: {first_bar.get('timestamp', 'N/A')}")
                    print(f"   Poslední bar: {last_bar.get('timestamp', 'N/A')}")
                    print(f"   Rozsah: {first_bar.get('open', 0):.2f} - {last_bar.get('close', 0):.2f}")
            else:
                print(f"⚠️  {symbol}: Data nebyla načtena")
                results[symbol] = []
        
        # Zavřít spojení
        if hasattr(client, 'ws') and client.ws:
            await client.ws.close()
        
        return results
        
    except Exception as e:
        print(f"❌ Chyba při načítání dat: {e}")
        import traceback
        traceback.print_exc()
        return None


def check_cache_data() -> Dict:
    """Zkontrolovat, zda existují cache data v různých možných umístěních"""
    # Možné cesty k cache
    cache_paths = [
        project_root / "backtesting" / "data",  # Backtesting cache
        project_root / "src" / "cache",  # HA cache
        project_root / "cache",  # Root cache
        Path("./cache"),  # Relative cache
    ]
    
    results = {}
    
    for symbol in ['GER40', 'US100']:
        bars = []
        found_cache = None
        
        # Hledat cache v různých umístěních
        for cache_dir in cache_paths:
            cache_file = cache_dir / f"{symbol}_M5.jsonl"
            if cache_file.exists():
                found_cache = cache_file
                break
        
        if found_cache:
            try:
                print(f"   📂 Cache nalezen: {found_cache}")
                with open(found_cache, 'r') as f:
                    for line in f:
                        if line.strip():
                            bars.append(json.loads(line))
                
                results[symbol] = bars
                print(f"✅ {symbol}: Nalezeno {len(bars)} barů v cache")
                
                if bars:
                    first_bar = bars[0]
                    last_bar = bars[-1]
                    print(f"   První bar: {first_bar.get('timestamp', 'N/A')}")
                    print(f"   Poslední bar: {last_bar.get('timestamp', 'N/A')}")
                    if 'open' in first_bar and 'close' in last_bar:
                        print(f"   První cena: {first_bar.get('open', 0):.2f}")
                        print(f"   Poslední cena: {last_bar.get('close', 0):.2f}")
            except Exception as e:
                print(f"⚠️  {symbol}: Chyba při čtení cache: {e}")
                results[symbol] = []
        else:
            print(f"ℹ️  {symbol}: Cache soubor neexistuje")
            results[symbol] = []
    
    return results


def save_data_to_json(data: Dict, output_file: Path):
    """Uložit data do JSON souboru"""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Převést datetime objekty na stringy pro JSON serializaci
    serializable_data = {}
    for symbol, bars in data.items():
        serializable_bars = []
        for bar in bars:
            serializable_bar = {}
            for key, value in bar.items():
                if isinstance(value, datetime):
                    serializable_bar[key] = value.isoformat()
                else:
                    serializable_bar[key] = value
            serializable_bars.append(serializable_bar)
        serializable_data[symbol] = serializable_bars
    
    with open(output_file, 'w') as f:
        json.dump(serializable_data, f, indent=2)
    
    print(f"💾 Data uložena do {output_file}")


def main():
    """Hlavní funkce"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Načtení historických dat pro backtesting')
    parser.add_argument('--from-ctrader', action='store_true', 
                       help='Načíst data z cTrader API (místo cache)')
    args = parser.parse_args()
    
    print("=" * 60)
    print("📊 Načítání historických dat z cTrader")
    print("=" * 60)
    print()
    
    # Nejdřív zkontrolovat cache (pokud nechceme načíst z cTrader)
    if not args.from_ctrader:
        print("🔍 Kontrola cache dat...")
        cache_data = check_cache_data()
        print()
        
        # Vyhodnotit výsledky
        ger40_count = len(cache_data.get('GER40', []))
        us100_count = len(cache_data.get('US100', []))
        
        print("=" * 60)
        print("📊 VÝSLEDEK NAČÍTÁNÍ DAT")
        print("=" * 60)
        print(f"GER40: {ger40_count} barů {'✅' if ger40_count > 0 else '❌'}")
        print(f"US100: {us100_count} barů {'✅' if us100_count > 0 else '❌'}")
        print()
        
        if ger40_count > 0 and us100_count > 0:
            print("✅ Cache data jsou k dispozici!")
            output_file = project_root / "backtesting" / "data" / "historical_data.json"
            save_data_to_json(cache_data, output_file)
            print()
            print("💡 Tip: Data byla uložena do backtesting/data/historical_data.json")
            print("💡 Můžeš je použít pro backtesting")
            return
    
    # Načíst z cTrader
    print("📡 Načítám data z cTrader API...")
    print("⚠️  Toto může trvat několik minut...")
    print()
    
    try:
        # Zkontrolovat, zda je certifi nainstalováno
        try:
            import certifi
            print("✅ certifi je nainstalováno")
        except ImportError:
            print("⚠️  certifi není nainstalováno")
            print("💡 Pro lepší SSL podporu spusť: pip install certifi")
            print("   (skript použije unverified SSL jako fallback)")
            print()
        
        # Potlačit verbose logy během načítání
        import logging
        logging.basicConfig(level=logging.ERROR)
        
        data = asyncio.run(load_historical_data())
        
        if data:
            ger40_count = len(data.get('GER40', []))
            us100_count = len(data.get('US100', []))
            
            print()
            print("=" * 60)
            print("📊 VÝSLEDEK NAČÍTÁNÍ DAT")
            print("=" * 60)
            print(f"GER40: {ger40_count} barů {'✅' if ger40_count > 0 else '❌'}")
            print(f"US100: {us100_count} barů {'✅' if us100_count > 0 else '❌'}")
            print()
            
            if ger40_count > 0 and us100_count > 0:
                output_file = project_root / "backtesting" / "data" / "historical_data.json"
                save_data_to_json(data, output_file)
                print("✅ Načítání dokončeno!")
                print(f"💾 Data uložena do: {output_file}")
            else:
                print("⚠️  Některá data nebyla načtena")
        else:
            print("❌ Nepodařilo se načíst data z cTrader")
            print()
            print("💡 Možná řešení:")
            print("   1. Zkontroluj SSL certifikáty: pip install certifi")
            print("   2. Zkontroluj připojení k internetu")
            print("   3. Ověř credentials v src/secrets.yaml")
            print("   4. Zkus použít cache data (spusť bez --from-ctrader)")
            
    except KeyboardInterrupt:
        print("\n⚠️  Přerušeno uživatelem")
    except Exception as e:
        print(f"\n❌ Chyba: {e}")
        import traceback
        traceback.print_exc()
        print()
        print("💡 Tip: Zkus nejdřív použít cache data:")
        print("   python backtesting/load_historical_data.py")


if __name__ == "__main__":
    main()

