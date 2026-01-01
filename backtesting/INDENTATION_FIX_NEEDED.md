# Problém s odsazením v process_market_data

## Problém

V metodě `process_market_data` v souboru `src/trading_assistant/main.py` je problém s odsazením - kód po řádku 1294 není správně odsazen v `try` bloku.

## Příčina

Při poslední úpravě došlo k chybě v odsazení - kód po řádku 1294 má 8 mezer místo 12 (není v try bloku).

## Řešení

Celou metodu `process_market_data` (řádky 1287-1683) je nutné zkontrolovat a opravit odsazení:

1. **Outer try blok** (řádek 1289) - tělo by mělo mít 12 mezer
2. **Inner try bloky** (např. řádky 1327, 1338, 1373, atd.) - `try:` by měl mít 12 mezer, tělo 16 mezer
3. **Inner except bloky** - `except:` by měl mít 12 mezer, tělo 16 mezer
4. **Outer except blok** (řádek 1679) - `except Exception as outer_e:` by měl mít 8 mezer (method level)

## Doporučení

Nejjednodušší řešení: použít Python formatter nebo opravit metodu manuálně s pomocí IDE, které automaticky opravuje odsazení.

Alternativně: použít `autopep8` nebo `black` pro automatickou opravu formátování.

## Důsledek

Dokud není problém s odsazením opraven, kód nebude fungovat správně a logy `[PROCESS_DATA] Entry` se nebudou zobrazovat, což způsobuje, že signály nejsou generovány.

