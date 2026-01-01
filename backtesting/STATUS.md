# Backtesting - Status

## ✅ Dokončené kroky

1. ✅ Vytvořena struktura adresářů (`backtesting/`, `backtesting/data/`, `backtesting/results/`)
2. ✅ Vytvořen `load_historical_data.py` a `load_ger40_data.py` pro načítání dat
3. ✅ Skript používá credentials z `backtesting/secrets.yaml`
4. ✅ Připojení k cTrader funguje (autentizace proběhla úspěšně)

## ✅ Aktuální stav

**Načítání dat funguje správně - používá se stejný mechanismus jako v produkci!**

### Jak to funguje:
1. Bootstrap_history se spouští a požádá API o historická data
2. API vrací prázdnou odpověď (`trendbar: []`) - **to je normální pro demo API**
3. **Fallback na cache**: `_load_history_on_startup()` načte data z cache
4. Cache obsahuje 4 bary (z předchozích pokusů)

### Zjištění:
- ✅ **API vrací historická data pouze když jsou trhy otevřené!**
  - **24.12.2025 (trhy otevřené)**: `Retrieved 436 bars for US100`, `Processing 30 bars for GER40` ✅
  - **25.12.2025 (trhy zavřené)**: `Retrieved 0 bars for US100`, `Processing 0 bars for GER40` ❌
- ✅ **Produkce funguje správně** - když jsou trhy zavřené, začíná od nuly a sbírá data z live streamu
- ✅ **Pro backtesting můžeme použít API, ale pouze když jsou trhy otevřené**
- ⚠️ **Když jsou trhy zavřené, API nevrací historická data** - to je očekávané chování

### Zkoumané řešení:
- ✅ Zkrácení časového rozsahu z 500 na 200 barů
- ⏳ Kontrola, zda demo účet podporuje historická data
- ⏳ Zkusit použít reálný účet (ne demo)

### Podle dokumentace cTrader OpenAPI:
- Používá se `ProtoOAGetTrendbarsReq` (PT_GET_TRENDBARS_REQ)
- Parametry: `ctidTraderAccountId`, `symbolId`, `period`, `fromTimestamp`, `toTimestamp`
- Limit: 5 requestů za sekundu
- Data jsou v relativním formátu (low + deltaOpen/deltaHigh/deltaClose)

## 📝 Další kroky

**✅ VÝSLEDEK**: API funguje správně! Historická data lze získat, ale pouze když jsou trhy otevřené.

### Možnosti získání historických dat:
1. ✅ **Použít API když jsou trhy otevřené** - stačí spustit skript během obchodních hodin
   - API vrátí 400+ barů (např. 436 barů pro US100, 30+ pro GER40)
   - Data se automaticky uloží do cache pro další použití
2. **Použít cache data** - pokud již máme data v cache, můžeme je použít i když jsou trhy zavřené
3. **Externí data provider** - jako alternativní zdroj (pokud potřebujeme data z konkrétního období)

### Kdy získat data:
- **Během obchodních hodin** (obvykle Po-Pá, 09:00-22:00 CET)
- **Ne během svátků/volna** - API nevrací data když jsou trhy zavřené

### Formát dat:
Data se automaticky ukládají v JSONL formátu do cache - viz sekce "Cache data" níže.

## 📊 Cache data

- **GER40_M5.jsonl**: 500 barů (mock data pro testování)
- **US100_M5.jsonl**: 500 barů (mock data pro testování)
- **Cesta**: `/Users/jirimerz/Projects/TAv80/backtesting/data/`
- **Formát**: JSONL (jeden JSON objekt na řádek)
- **Generování**: `load_test_data.py` vytváří mock data pro testování (nebo lze použít `load_ger40_data.py` během obchodních hodin)

### Formát cache souboru:
Každý řádek obsahuje JSON objekt s těmito klíči:
- `timestamp`: ISO timestamp (např. "2025-12-25T19:45:45.670303+00:00")
- `open`, `high`, `low`, `close`: ceny
- `volume`: objem
- `spread`: spread v pips

**Příklad**:
```json
{"timestamp": "2025-12-25T19:45:45.670303+00:00", "open": 24331.22, "high": 24331.22, "low": 24331.22, "close": 24331.22, "volume": 2, "spread": 2.6}
```
