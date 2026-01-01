#!/usr/bin/env python3
"""
Stažení historických dat z cTrader pro backtesting
"""

import sys
import json
import asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Potlačit verbose logy
import logging
logging.basicConfig(level=logging.WARNING)

# Přidat src/ do Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))


def load_secrets() -> dict:
    """Načíst credentials ze secrets.yaml - nejdřív z backtesting/, pak z src/"""
    # Zkusit backtesting/secrets.yaml jako první
    secrets_path = project_root / "backtesting" / "secrets.yaml"
    if not secrets_path.exists():
        # Fallback na src/secrets.yaml
        secrets_path = project_root / "src" / "secrets.yaml"
    
    if not secrets_path.exists():
        raise FileNotFoundError(f"secrets.yaml not found at {secrets_path} or backtesting/secrets.yaml")
    
    print(f"📂 Načítám credentials z: {secrets_path}")
    secrets = {}
    with open(secrets_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and ':' in line:
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip().strip('"\'')
                secrets[key] = value
    
    return secrets


async def download_data_for_symbol(symbol: str, symbol_id: int, secrets: dict, days_back: int = 30) -> list:
    """
    Stáhnout historická data pro daný symbol z cTrader
    
    Používá více požadavků v dávkách, protože cTrader API má limit:
    - Maximálně 5 požadavků za sekundu
    - Každý požadavek vrací omezené množství dat (~100-200 barů)
    
    Args:
        symbol: Název symbolu (např. 'US100')
        symbol_id: ID symbolu v cTrader
        secrets: Credentials pro cTrader API
        days_back: Kolik dní zpět stáhnout (default: 30)
    """
    print(f"\n📡 Stahuji data pro {symbol} (ID: {symbol_id}) - {days_back} dní zpět...")
    
    # Zkusit použít SSL kontext
    try:
        import ssl
        import certifi
        ssl_context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
    except Exception:
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
    
    # Monkey-patch websockets.connect pro SSL
    try:
        import websockets
        original_connect = websockets.connect
        
        async def connect_with_ssl(*args, **kwargs):
            if len(args) > 0 and isinstance(args[0], str) and args[0].startswith('wss://'):
                if 'ssl' not in kwargs:
                    kwargs['ssl'] = ssl_context
            return await original_connect(*args, **kwargs)
        
        websockets.connect = connect_with_ssl
    except Exception:
        pass
    
    # Načíst cTrader client
    from trading_assistant.ctrader_client import CTraderClient
    
    # Konfigurace klienta
    client_config = {
        'ws_uri': secrets.get('ws_uri', 'wss://openapi-v2.ctrader.com/cbots'),
        'access_token': secrets.get('access_token', ''),
        'trader_login': secrets.get('trader_login', ''),
        'client_id': secrets.get('client_id', ''),
        'client_secret': secrets.get('client_secret', ''),
        'ctid_trader_account_id': int(secrets.get('ctid_trader_account_id', 0)),
        'symbols': [{'name': symbol}],
        'symbol_id_overrides': {symbol: symbol_id},
        'bar_warmup': 500,  # Stáhnout více barů pro backtest
        'use_historical_bootstrap': True,
        'history_cache_dir': str(project_root / "backtesting" / "data"),
        'history_bars_count': 500,  # Stáhnout 500 barů (demo API má limit ~200 barů)
        'account_balance': 2000000,
    }
    
    client = CTraderClient(client_config)
    
    # Callback pro shromáždění barů
    collected_bars = []
    bars_received = asyncio.Event()
    
    def on_bar_callback(raw_symbol, bar, all_bars=None, history=None):
        """Callback pro přijetí baru - podporuje různé signatury"""
        # cTrader volá callback s různými signaturami:
        # - on_bar_callback(symbol, bar, all_bars) - trendbars
        # - on_bar_callback(symbol, bar) - closed bar
        # - on_bar_callback(symbol, bar, all_bars, history) - cache loading
        
        if all_bars is not None:
            # Máme all_bars - použít je
            collected_bars.clear()
            collected_bars.extend(all_bars)
            bars_received.set()
        elif hasattr(client, 'bars') and raw_symbol in client.bars:
            # Nemáme all_bars, ale máme client.bars - použít je
            bars_from_client = list(client.bars[raw_symbol])
            if len(bars_from_client) > 0:
                collected_bars.clear()
                collected_bars.extend(bars_from_client)
                bars_received.set()
    
    # Registrovat callback
    client.on_bar_callback = on_bar_callback
    
    try:
        # Připojit se
        print(f"   [1/5] Připojuji se k cTrader...")
        connect_task = asyncio.create_task(client.connect_and_stream())
        print(f"   [1/5] ✅ connect_and_stream spuštěno")
        
        # Počkat na připojení (max 30 sekund)
        print(f"   [2/5] Čekám na připojení a autentizaci...")
        authorized = False
        for i in range(30):
            await asyncio.sleep(1)
            if hasattr(client, '_authorized') and client._authorized:
                if not authorized:
                    print(f"   [2/5] ✅ Autentizováno po {i+1} sekundách")
                    authorized = True
            if i % 5 == 0 and i > 0:
                status = "autentizováno" if authorized else "čekám na autentizaci"
                print(f"      ⏳ {status}... ({i}/30s)")
        else:
            if not authorized:
                print(f"   [2/5] ⚠️  Timeout při připojování (30s) - pokračuji")
        
        # Počkat na historická data z bootstrap (max 30 sekund)
        print(f"   [3/5] Čekám na historická data z bootstrap...")
        try:
            for i in range(30):
                await asyncio.sleep(1)
                
                # Zkontrolovat client.bars
                if hasattr(client, 'bars') and symbol in client.bars:
                    bars_from_client = list(client.bars[symbol])
                    if len(bars_from_client) > 0:
                        collected_bars.clear()
                        collected_bars.extend(bars_from_client)
                        print(f"   [3/5] ✅ Data načtena z bootstrap: {len(collected_bars)} barů")
                        break
                
                # Zkontrolovat callback
                if bars_received.is_set():
                    print(f"   [3/5] ✅ Data přijata přes callback: {len(collected_bars)} barů")
                    break
                
                if i % 5 == 0 and i > 0:
                    print(f"      ⏳ Čekám na data... ({i}/30s)")
            else:
                print(f"   [3/5] ⚠️  Timeout - data nebyly přijata během 30 sekund")
        except Exception as e:
            print(f"   [3/5] ⚠️  Chyba při čekání na data: {e}")
        
        # VŽDY zkusit načíst z cache (i když máme data z API, cache může mít více)
        # Zkusit také produkční cache (může mít více dat)
        print(f"   [4/5] Kontroluji cache pro více dat...")
        cache_paths = [
            project_root / "backtesting" / "data" / f"{symbol}_M5.jsonl",
            project_root / "cache" / f"{symbol}_M5.jsonl",
            project_root / "src" / "cache" / f"{symbol}_M5.jsonl",
        ]
        
        cache_file = None
        for path in cache_paths:
            if path.exists():
                cache_file = path
                break
        
        if cache_file:
            print(f"   📂 Načítám z cache: {cache_file}")
            print(f"      (zkoušel jsem: {', '.join([str(p) for p in cache_paths])})")
            cache_bars = []
            with open(cache_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            bar = json.loads(line)
                            cache_bars.append(bar)
                        except json.JSONDecodeError:
                            continue
            
            # Použít cache, pokud má více barů než API data
            if len(cache_bars) > len(collected_bars):
                print(f"   [4/5] ✅ Cache má více dat: {len(cache_bars)} > {len(collected_bars)} barů")
                collected_bars = cache_bars
            elif len(collected_bars) == 0 and len(cache_bars) > 0:
                print(f"   [4/5] ✅ Používám cache (API nevrátilo data): {len(cache_bars)} barů")
                collected_bars = cache_bars
            elif len(collected_bars) > 0:
                print(f"   [4/5] ✅ Používám API data: {len(collected_bars)} barů (cache: {len(cache_bars)})")
        else:
            print(f"   [4/5] ⚠️  Cache soubor neexistuje: {cache_file}")
        
        # Odpojit se
        print(f"   [5/5] Odpojuji se...")
        try:
            if hasattr(client, '_running'):
                client._running = False
            if hasattr(client, 'ws') and client.ws:
                try:
                    await client.ws.close()
                except:
                    pass
            try:
                connect_task.cancel()
            except:
                pass
            print(f"   [5/5] ✅ Odpojeno")
        except Exception as e:
            print(f"   [5/5] ⚠️  Chyba při odpojování: {e}")
        
        return collected_bars
        
    except Exception as e:
        print(f"   ❌ Chyba při stahování dat: {e}")
        import traceback
        traceback.print_exc()
        
        # Zkusit načíst z cache jako fallback
        cache_file = project_root / "backtesting" / "data" / f"{symbol}_M5.jsonl"
        if cache_file.exists():
            print(f"   📂 Fallback: Načítám z cache: {cache_file}")
            collected_bars = []
            with open(cache_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            bar = json.loads(line)
                            collected_bars.append(bar)
                        except json.JSONDecodeError:
                            continue
            print(f"   ✅ Načteno {len(collected_bars)} barů z cache")
            return collected_bars
        
        return []


async def main():
    """Hlavní funkce pro stažení dat"""
    print("=" * 70)
    print("📡 STAŽENÍ HISTORICKÝCH DAT Z CTRADER PRO BACKTESTING")
    print("=" * 70)
    print()
    
    # Načíst credentials
    try:
        secrets = load_secrets()
        print("✅ Credentials načteny")
    except FileNotFoundError as e:
        print(f"❌ ERROR: {e}")
        return
    
    # Symboly pro backtest
    symbols = {
        'GER40': 203,
        'US100': 208
    }
    
    data_dir = project_root / "backtesting" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    
    all_data = {}
    
    for symbol, symbol_id in symbols.items():
        bars = await download_data_for_symbol(symbol, symbol_id, secrets, days_back=30)
        
        if bars:
            # Uložit do cache
            cache_file = data_dir / f"{symbol}_M5.jsonl"
            with open(cache_file, 'w') as f:
                for bar in bars:
                    # Zajistit, že timestamp je string
                    bar_copy = bar.copy()
                    if 'timestamp' in bar_copy:
                        if hasattr(bar_copy['timestamp'], 'isoformat'):
                            bar_copy['timestamp'] = bar_copy['timestamp'].isoformat()
                    f.write(json.dumps(bar_copy) + "\n")
            
            print(f"💾 Uloženo {len(bars)} barů do {cache_file}")
            all_data[symbol] = len(bars)
        else:
            print(f"⚠️  Žádná data pro {symbol}")
            all_data[symbol] = 0
    
    print()
    print("=" * 70)
    print("📊 VÝSLEDEK")
    print("=" * 70)
    for symbol, count in all_data.items():
        if count > 0:
            print(f"✅ {symbol}: {count} barů")
        else:
            print(f"❌ {symbol}: Žádná data")
    print()
    print("💡 Data jsou uložena v backtesting/data/")
    print("   Backtest je nyní připraven ke spuštění!")


if __name__ == "__main__":
    asyncio.run(main())

