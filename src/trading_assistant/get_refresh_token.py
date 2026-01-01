#!/usr/bin/env python3
"""
cTrader OAuth2 Token Helper
===========================

Tento skript ti pomůže získat refresh_token pro automatickou obnovu tokenů.

Použití:
    python3 get_refresh_token.py

Požadavky:
    - client_id a client_secret z cTrader Open API
    - Registrovaná redirect_uri v cTrader aplikaci
"""

import json
import sys
import webbrowser
from urllib.parse import urlencode, urlparse, parse_qs
import http.server
import socketserver
import threading

# ============================================================
# KONFIGURACE - Vyplň své údaje
# ============================================================

# Z cTrader Open API (https://openapi.ctrader.com)
CLIENT_ID = ""  # Vyplň svůj client_id
CLIENT_SECRET = ""  # Vyplň svůj client_secret

# Redirect URI musí být registrovaná v cTrader aplikaci
# Pro lokální použití můžeš použít:
REDIRECT_URI = "http://localhost:8080/callback"

# ============================================================
# KROK 1: Autorizační URL
# ============================================================

def get_authorization_url():
    """Vytvoří URL pro autorizaci"""
    base_url = "https://openapi.ctrader.com/apps/auth"
    
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "trading"  # nebo "accounts" pro read-only
    }
    
    return f"{base_url}?{urlencode(params)}"

# ============================================================
# KROK 2: Lokální server pro zachycení authorization code
# ============================================================

authorization_code = None
server_should_stop = False

class CallbackHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        global authorization_code, server_should_stop
        
        # Parse the URL
        parsed = urlparse(self.path)
        
        if parsed.path == "/callback":
            # Get the authorization code from query params
            query_params = parse_qs(parsed.query)
            
            if "code" in query_params:
                authorization_code = query_params["code"][0]
                
                # Send success response
                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.end_headers()
                
                html = """
                <!DOCTYPE html>
                <html>
                <head><title>Autorizace úspěšná</title></head>
                <body style="font-family: Arial; text-align: center; padding: 50px;">
                    <h1 style="color: green;">✅ Autorizace úspěšná!</h1>
                    <p>Authorization code byl zachycen.</p>
                    <p>Můžeš zavřít toto okno a vrátit se do terminálu.</p>
                    <p style="color: gray; font-size: 12px;">Code: """ + authorization_code[:20] + """...</p>
                </body>
                </html>
                """
                self.wfile.write(html.encode())
                server_should_stop = True
                
            elif "error" in query_params:
                error = query_params.get("error", ["unknown"])[0]
                error_desc = query_params.get("error_description", [""])[0]
                
                self.send_response(400)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.end_headers()
                
                html = f"""
                <!DOCTYPE html>
                <html>
                <head><title>Chyba autorizace</title></head>
                <body style="font-family: Arial; text-align: center; padding: 50px;">
                    <h1 style="color: red;">❌ Chyba autorizace</h1>
                    <p>Error: {error}</p>
                    <p>{error_desc}</p>
                </body>
                </html>
                """
                self.wfile.write(html.encode())
                server_should_stop = True
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        pass  # Suppress logging

# ============================================================
# KROK 3: Výměna authorization code za tokeny
# ============================================================

def exchange_code_for_tokens(code):
    """Vymění authorization code za access_token a refresh_token"""
    import urllib.request
    
    token_url = "https://openapi.ctrader.com/apps/token"
    
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI
    }
    
    json_data = json.dumps(data).encode('utf-8')
    
    req = urllib.request.Request(
        token_url,
        data=json_data,
        headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        print(f"\n❌ Chyba při výměně kódu: HTTP {e.code}")
        print(f"   {error_body}")
        return None

# ============================================================
# HLAVNÍ PROGRAM
# ============================================================

def main():
    global authorization_code, server_should_stop
    
    print("=" * 60)
    print("cTrader OAuth2 Token Helper")
    print("=" * 60)
    print()
    
    # Check configuration
    if not CLIENT_ID or not CLIENT_SECRET:
        print("❌ CHYBA: Musíš vyplnit CLIENT_ID a CLIENT_SECRET!")
        print()
        print("Otevři tento soubor a vyplň své údaje z cTrader Open API:")
        print(f"   {__file__}")
        print()
        print("CLIENT_ID a CLIENT_SECRET najdeš na:")
        print("   https://openapi.ctrader.com/apps")
        return
    
    print(f"Client ID: {CLIENT_ID}")
    print(f"Redirect URI: {REDIRECT_URI}")
    print()
    
    # Generate authorization URL
    auth_url = get_authorization_url()
    
    print("KROK 1: Autorizace")
    print("-" * 40)
    print()
    print("Otevři tento odkaz v prohlížeči a přihlas se:")
    print()
    print(f"  {auth_url}")
    print()
    
    # Ask user if they want to open browser automatically
    try:
        response = input("Otevřít prohlížeč automaticky? [Y/n]: ").strip().lower()
        if response != 'n':
            webbrowser.open(auth_url)
            print("✅ Prohlížeč otevřen")
    except:
        pass
    
    print()
    print("KROK 2: Čekám na autorizaci...")
    print("-" * 40)
    print()
    print(f"Spouštím lokální server na {REDIRECT_URI}")
    print("Po autorizaci budeš přesměrován zpět...")
    print()
    
    # Start local server to catch the callback
    port = int(REDIRECT_URI.split(":")[-1].split("/")[0])
    
    try:
        with socketserver.TCPServer(("", port), CallbackHandler) as httpd:
            httpd.timeout = 1  # Check every second
            
            while not server_should_stop:
                httpd.handle_request()
            
            if authorization_code:
                print()
                print("✅ Authorization code zachycen!")
                print()
                print("KROK 3: Výměna za tokeny...")
                print("-" * 40)
                
                tokens = exchange_code_for_tokens(authorization_code)
                
                if tokens:
                    access_token = tokens.get("accessToken", "")
                    refresh_token = tokens.get("refreshToken", "")
                    expires_in = tokens.get("expiresIn", 0)
                    
                    print()
                    print("✅ ÚSPĚCH! Tokeny získány:")
                    print("=" * 60)
                    print()
                    print("ACCESS TOKEN:")
                    print(f"  {access_token}")
                    print()
                    print("REFRESH TOKEN:")
                    print(f"  {refresh_token}")
                    print()
                    print(f"Platnost: {expires_in} sekund ({expires_in/3600:.1f} hodin)")
                    print()
                    print("=" * 60)
                    print()
                    print("DALŠÍ KROKY:")
                    print()
                    print("1. Přidej do secrets.yaml:")
                    print()
                    print(f"   access_token: \"{access_token}\"")
                    print(f"   refresh_token: \"{refresh_token}\"")
                    print()
                    print("2. Restartuj AppDaemon")
                    print()
                    
                    # Save to file
                    output_file = "ctrader_tokens.json"
                    with open(output_file, 'w') as f:
                        json.dump({
                            "access_token": access_token,
                            "refresh_token": refresh_token,
                            "expires_in": expires_in
                        }, f, indent=2)
                    print(f"💾 Tokeny uloženy do: {output_file}")
                    
    except OSError as e:
        if "Address already in use" in str(e):
            print(f"❌ Port {port} je již obsazený!")
            print()
            print("Alternativní postup:")
            print("1. Otevři autorizační URL ručně")
            print("2. Po autorizaci zkopíruj 'code' parametr z URL")
            print("3. Spusť: python3 get_refresh_token.py --code TVUJ_KOD")
        else:
            raise

if __name__ == "__main__":
    # Check for --code argument
    if len(sys.argv) > 2 and sys.argv[1] == "--code":
        CLIENT_ID = input("CLIENT_ID: ").strip() if not CLIENT_ID else CLIENT_ID
        CLIENT_SECRET = input("CLIENT_SECRET: ").strip() if not CLIENT_SECRET else CLIENT_SECRET
        
        code = sys.argv[2]
        print(f"Vyměňuji code za tokeny...")
        tokens = exchange_code_for_tokens(code)
        if tokens:
            print(json.dumps(tokens, indent=2))
    else:
        main()


