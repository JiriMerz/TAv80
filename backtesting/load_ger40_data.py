#!/usr/bin/env python3
"""
Načtení historických dat pro GER40 z cTrader účtu

Jednoduchý skript - pouze připojení a načtení GER40 dat.
"""

import sys
import json
import asyncio
from pathlib import Path
from datetime import datetime

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


async def load_ger40_data():
    """Načíst historická data pro GER40 z cTrader"""
    print("=" * 60)
    print("📡 Připojování k cTrader účtu...")
    print("=" * 60)
    print()
    
    # Načíst credentials
    try:
        secrets = load_secrets()
        print("✅ Credentials načteny")
    except FileNotFoundError as e:
        print(f"❌ ERROR: {e}")
        return None
    
    # Zkusit použít SSL kontext
    try:
        import ssl
        import certifi
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        print("✅ SSL kontext vytvořen pomocí certifi")
    except ImportError:
        print("⚠️  certifi není nainstalováno, používám unverified SSL")
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
    except Exception as e:
        print(f"⚠️  Problém s SSL: {e}, používám unverified SSL")
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
        print("✅ SSL kontext aplikován")
    except Exception as e:
        print(f"⚠️  Nelze upravit websockets: {e}")
    
    print()
    
    # Načíst cTrader client
    from trading_assistant.ctrader_client import CTraderClient
    
    config = {
        'ws_uri': secrets.get('ws_uri'),
        'client_id': secrets.get('client_id'),
        'client_secret': secrets.get('client_secret'),
        'access_token': secrets.get('access_token'),
        'ctid_trader_account_id': int(secrets.get('ctid_trader_account_id', 0)),
        'trader_login': secrets.get('trader_login'),
        'symbols': [{'name': 'GER40'}],  # POUZE GER40
        'symbol_id_overrides': {'GER40': 203},
        'history_cache_dir': str(project_root / "backtesting" / "data"),
        'history_bars_count': 200,  # Zkusit menší počet (200 barů = ~17 hodin)
        'bar_warmup': 100,
        'use_historical_bootstrap': True  # Povolit automatické načítání historie
    }
    
    print("📡 Vytváření cTrader clientu...")
    client = CTraderClient(config)
    print("✅ Client vytvořen")
    print()
    
    # Spustit připojení a načítání
    bars_received = {'GER40': []}
    connection_success = False
    
    async def on_bar_callback(symbol, bar, all_bars):
        """Callback pro přijaté bary"""
        if symbol == 'GER40':
            bars_received['GER40'] = list(all_bars)
            print(f"📊 Přijato {len(all_bars)} barů pro {symbol}")
    
    # Nastavit callback
    client.on_bar_callback = on_bar_callback
    
    try:
        print("🔄 Spouštím připojení...")
        # Spustit connection loop v pozadí
        connection_task = asyncio.create_task(client.connect_and_stream())
        
        # Počkat na dokončení connect_and_stream (autentizace + bootstrap + cache načtení)
        print("⏳ Čekám na připojení, autentizaci a načtení historických dat...")
        print("   (to může trvat 30-60 sekund - autentizace + bootstrap + cache)")
        
        # Počkat, až bude connect_and_stream v určitém stádiu
        # V produkci se to volá v threadu, ale my máme task, takže počkáme na autentizaci
        max_wait = 60
        bars_count = 0
        authorized = False
        
        for i in range(max_wait):
            await asyncio.sleep(1)
            
            # Zkontrolovat, zda je autorizováno (po autentizaci se načte cache)
            if hasattr(client, '_authorized') and client._authorized:
                if not authorized:
                    print("✅ Autentizace dokončena, cache se načítá...")
                    authorized = True
            
            # Zkontrolovat, zda máme data (z cache nebo bootstrap)
            if 'GER40' in client.bars:
                current_count = len(client.bars['GER40'])
                if current_count != bars_count:
                    bars_count = current_count
                    if bars_count > 0:
                        print(f"   📊 Načteno {bars_count} barů...")
                
                # Pokud máme dostatek dat, ukončit
                if bars_count >= 100:
                    print(f"✅ Načteno {bars_count} barů (dostatečné množství)")
                    break
                    
            # Každých 5 sekund zobrazit status
            if i % 5 == 0 and i > 0:
                if bars_count > 0:
                    print(f"   ⏳ Čekám... ({i}/{max_wait}s, aktuálně {bars_count} barů)")
                elif authorized:
                    print(f"   ⏳ Autentizováno, čekám na data... ({i}/{max_wait}s)")
                else:
                    print(f"   ⏳ Čekám na autentizaci... ({i}/{max_wait}s)")
        
        # Zkontrolovat finální stav dat
        if 'GER40' in client.bars:
            bars_received['GER40'] = list(client.bars['GER40'])
            final_count = len(bars_received['GER40'])
            if final_count > bars_count:
                print(f"✅ Finální počet: {final_count} barů")
            
            if final_count == 0:
                print("⚠️  Žádná data nebyla načtena (ani z cache, ani z API)")
            elif final_count < 100:
                print(f"⚠️  Načteno pouze {final_count} barů (méně než očekávaných 100+)")
        else:
            print("⚠️  Nepodařilo se připojit")
            
    except Exception as e:
        print(f"❌ Chyba: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Zastavit client
        if hasattr(client, '_running'):
            client._running = False
        if hasattr(client, 'ws') and client.ws:
            try:
                await client.ws.close()
            except:
                pass
        connection_task.cancel()
    
    return bars_received.get('GER40', [])


def main():
    """Hlavní funkce"""
    print()
    print("=" * 60)
    print("📊 NAČÍTÁNÍ HISTORICKÝCH DAT - GER40")
    print("=" * 60)
    print()
    
    try:
        bars = asyncio.run(load_ger40_data())
        
        print()
        print("=" * 60)
        print("📊 VÝSLEDEK")
        print("=" * 60)
        print()
        
        if bars:
            print(f"✅ GER40: Načteno {len(bars)} barů")
            print()
            
            if len(bars) > 0:
                first_bar = bars[0]
                last_bar = bars[-1]
                
                print("📈 První bar:")
                print(f"   Timestamp: {first_bar.get('timestamp', 'N/A')}")
                print(f"   OHLC: O={first_bar.get('open', 0):.2f}, H={first_bar.get('high', 0):.2f}, "
                      f"L={first_bar.get('low', 0):.2f}, C={first_bar.get('close', 0):.2f}")
                print()
                
                print("📈 Poslední bar:")
                print(f"   Timestamp: {last_bar.get('timestamp', 'N/A')}")
                print(f"   OHLC: O={last_bar.get('open', 0):.2f}, H={last_bar.get('high', 0):.2f}, "
                      f"L={last_bar.get('low', 0):.2f}, C={last_bar.get('close', 0):.2f}")
                print()
                
                # Uložit data
                output_file = project_root / "backtesting" / "data" / "GER40_M5.jsonl"
                output_file.parent.mkdir(parents=True, exist_ok=True)
                
                with open(output_file, 'w') as f:
                    for bar in bars:
                        # Převést datetime na string
                        bar_copy = {}
                        for key, value in bar.items():
                            if isinstance(value, datetime):
                                bar_copy[key] = value.isoformat()
                            else:
                                bar_copy[key] = value
                        f.write(json.dumps(bar_copy) + "\n")
                
                print(f"💾 Data uložena do: {output_file}")
                print()
                print("✅ Úspěšně dokončeno!")
        else:
            print("❌ GER40: Data nebyla načtena")
            print()
            print("💡 Možné příčiny:")
            print("   - Problém s připojením k cTrader")
            print("   - Neplatné credentials")
            print("   - Timeout při načítání dat")
            
    except KeyboardInterrupt:
        print("\n⚠️  Přerušeno uživatelem")
    except Exception as e:
        print(f"\n❌ Chyba: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

