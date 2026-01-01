#!/usr/bin/env python3
"""
Načtení konfigurace z apps.yaml pro backtesting
"""

import yaml
import sys
from pathlib import Path

def load_apps_yaml(config_path: Path) -> dict:
    """Načíst apps.yaml konfiguraci"""
    try:
        with open(config_path, 'r') as f:
            # Nahradit !secret referencí (nejsou potřeba pro backtesting)
            content = f.read()
            # Odstranit řádky s !secret
            lines = []
            for line in content.split('\n'):
                if '!secret' in line:
                    # Nahradit !secret hodnotami z defaultů nebo None
                    if 'ws_uri' in line:
                        lines.append('  ws_uri: ""')
                    elif 'client_id' in line or 'client_secret' in line:
                        lines.append(f'  {line.split(":")[0].strip()}: ""')
                    elif 'access_token' in line:
                        lines.append('  access_token: ""')
                    elif 'ctid_trader_account_id' in line:
                        lines.append('  ctid_trader_account_id: 0')
                    elif 'trader_login' in line:
                        lines.append('  trader_login: ""')
                    else:
                        lines.append(line.split(':')[0] + ': ""')
                else:
                    lines.append(line)
            content = '\n'.join(lines)
            
            data = yaml.safe_load(content)
            return data.get('trading_assistant', {})
    except Exception as e:
        print(f"⚠️  Chyba při načítání apps.yaml: {e}")
        return {}

if __name__ == "__main__":
    project_root = Path(__file__).parent.parent
    config_path = project_root / "src" / "apps.yaml"
    config = load_apps_yaml(config_path)
    print(f"✅ Načtena konfigurace z {config_path}")
    print(f"   Klíče: {list(config.keys())[:10]}...")

