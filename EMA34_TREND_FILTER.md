# Trendová filtrace pomocí EMA(34)

**Datum:** 2025-01-03  
**Funkce:** Trendová filtrace před otevřením pozice  
**Status:** ✅ IMPLEMENTOVÁNO

---

## 🎯 Cíl

Přidat trendovou filtraci pomocí EMA(34) na close price, která zajistí, že se otevírají **pouze pozice v souladu s trendem**, nikdy protitrendově.

---

## 📊 Implementace

### 1. Výpočet EMA(34)

**Funkce:** `_calculate_ema(bars: List[Dict], period: int) -> float`

- Vypočítá Exponential Moving Average na close prices
- Period: 34 (podle požadavku)
- Používá standardní EMA vzorec: `EMA = (Close × Multiplier) + (Previous EMA × (1 - Multiplier))`
- Multiplier = `2 / (period + 1)`

**Umístění:** `src/trading_assistant/main.py` (řádky ~4092-4120)

### 2. Určení trendu

**Funkce:** `_get_trend_from_ema34(alias: str) -> Optional[str]`

- Získá aktuální cenu (close posledního baru)
- Vypočítá EMA(34)
- Porovná cenu s EMA(34):
  - **UP trend:** `price > EMA(34)` → vrací `'UP'`
  - **DOWN trend:** `price < EMA(34)` → vrací `'DOWN'`
  - **Nejasný trend:** `price == EMA(34)` nebo nedostatek dat → vrací `None`

**Umístění:** `src/trading_assistant/main.py` (řádky ~4122-4155)

### 3. Kontrola trendu před otevřením pozice

**Umístění:** `_try_auto_execute_signal()` - na začátku, hned po kontrole auto-trading enabled

**Logika:**

```python
# Uptrend (price > EMA34):
- ✅ POVOLENO: BUY signály
- ❌ BLOKOVÁNO: SELL signály

# Downtrend (price < EMA34):
- ✅ POVOLENO: SELL signály
- ❌ BLOKOVÁNO: BUY signály

# Nejasný trend (price == EMA34 nebo nedostatek dat):
- ✅ POVOLENO: Oba směry (BUY i SELL)
```

**Umístění:** `src/trading_assistant/main.py` (řádky ~4157-4185)

---

## 🔄 Workflow

### Scenario 1: Uptrend, BUY signál

1. **Signal Detection:**
   ```
   [AUTO-TRADING] 🔍 Checking signal: NASDAQ BUY
   ```

2. **Trend Check:**
   ```
   [AUTO-TRADING] ✅ Trend aligned: UP trend, BUY signal
   ```

3. **Position Opening:**
   ```
   [AUTO-TRADING] 🚀 Opening position: NASDAQ BUY
   ```

### Scenario 2: Uptrend, SELL signál (BLOKOVÁNO)

1. **Signal Detection:**
   ```
   [AUTO-TRADING] 🔍 Checking signal: NASDAQ SELL
   ```

2. **Trend Check:**
   ```
   [AUTO-TRADING] ❌ BLOCKED: Protitrend signal detected
   [AUTO-TRADING] 📊 Trend: UP (Price > EMA34), Signal: SELL
   [AUTO-TRADING] 🛡️ Only BUY signals allowed in uptrend - blocking SELL signal
   ```

3. **Position Opening:**
   ```
   ❌ NEOTEVŘE SE - signál je blokován
   ```

### Scenario 3: Downtrend, SELL signál

1. **Signal Detection:**
   ```
   [AUTO-TRADING] 🔍 Checking signal: NASDAQ SELL
   ```

2. **Trend Check:**
   ```
   [AUTO-TRADING] ✅ Trend aligned: DOWN trend, SELL signal
   ```

3. **Position Opening:**
   ```
   [AUTO-TRADING] 🚀 Opening position: NASDAQ SELL
   ```

### Scenario 4: Downtrend, BUY signál (BLOKOVÁNO)

1. **Signal Detection:**
   ```
   [AUTO-TRADING] 🔍 Checking signal: NASDAQ BUY
   ```

2. **Trend Check:**
   ```
   [AUTO-TRADING] ❌ BLOCKED: Protitrend signal detected
   [AUTO-TRADING] 📊 Trend: DOWN (Price < EMA34), Signal: BUY
   [AUTO-TRADING] 🛡️ Only SELL signals allowed in downtrend - blocking BUY signal
   ```

3. **Position Opening:**
   ```
   ❌ NEOTEVŘE SE - signál je blokován
   ```

### Scenario 5: Nejasný trend (price == EMA34)

1. **Signal Detection:**
   ```
   [AUTO-TRADING] 🔍 Checking signal: NASDAQ BUY
   ```

2. **Trend Check:**
   ```
   [AUTO-TRADING] ⚠️ Trend unclear (insufficient data or price at EMA34) - allowing signal
   ```

3. **Position Opening:**
   ```
   ✅ POVOLENO - oba směry jsou povoleny při nejasném trendu
   ```

---

## 📋 Technické detaily

### Požadavky na data

- **Minimální počet barů:** 34 (pro výpočet EMA(34))
- **Pokud méně než 34 barů:** Trend je `None` → oba směry povoleny
- **Pokud price == EMA34:** Trend je `None` → oba směry povoleny

### Výpočet EMA

```python
multiplier = 2.0 / (period + 1.0)  # Pro period=34: 2/35 = 0.0571

# Start with SMA of first 'period' bars
ema = sum(close for bar in bars[:period]) / period

# Apply EMA formula to remaining bars
for bar in bars[period:]:
    close = bar['close']
    ema = (close * multiplier) + (ema * (1.0 - multiplier))
```

### Porovnání trendu

```python
if current_price > ema34:
    trend = 'UP'      # Uptrend - pouze BUY
elif current_price < ema34:
    trend = 'DOWN'    # Downtrend - pouze SELL
else:
    trend = None      # Nejasný - oba směry
```

---

## ⚙️ Konfigurace

**Aktuálně:** Trendová filtrace je **vždy aktivní** (hardcoded)

**Možné budoucí rozšíření:**
- Přidat konfigurační parametr `enable_ema34_trend_filter: true/false`
- Přidat konfigurační parametr `ema_period: 34` (pro možnost změny periody)
- Přidat konfigurační parametr `allow_counter_trend: false` (pro možnost povolit protitrendové signály)

---

## ✅ Výhody

1. **Snížení rizika:** Protitrendové signály jsou blokovány
2. **Lepší win rate:** Obchodování pouze ve směru trendu
3. **Jednoduchost:** EMA(34) je jednoduchý a spolehlivý indikátor
4. **Rychlost:** Kontrola probíhá před otevřením pozice, ne během signal generation

---

## ⚠️ Omezení

1. **Sideways trhy:** Při nejasném trendu (price == EMA34) jsou povoleny oba směry
2. **Nedostatek dat:** Pokud je méně než 34 barů, trend je `None` → oba směry povoleny
3. **Lag:** EMA(34) má určitou lag - může reagovat pomaleji na změny trendu
4. **Close-and-Reverse:** Trendová filtrace se aplikuje i na reverse signály (což je správné)

---

## 🧪 Testování

### Test Case 1: Uptrend + BUY signál
- **Očekávání:** ✅ Pozice se otevře
- **Log:** `✅ Trend aligned: UP trend, BUY signal`

### Test Case 2: Uptrend + SELL signál
- **Očekávání:** ❌ Pozice se neotevře
- **Log:** `❌ BLOCKED: Protitrend signal detected`

### Test Case 3: Downtrend + SELL signál
- **Očekávání:** ✅ Pozice se otevře
- **Log:** `✅ Trend aligned: DOWN trend, SELL signal`

### Test Case 4: Downtrend + BUY signál
- **Očekávání:** ❌ Pozice se neotevře
- **Log:** `❌ BLOCKED: Protitrend signal detected`

### Test Case 5: Nejasný trend (price == EMA34)
- **Očekávání:** ✅ Oba směry povoleny
- **Log:** `⚠️ Trend unclear - allowing signal`

---

## 📝 Související soubory

- `src/trading_assistant/main.py` - Implementace EMA(34) trendové filtrace
  - `_calculate_ema()` - Výpočet EMA
  - `_get_trend_from_ema34()` - Určení trendu
  - `_try_auto_execute_signal()` - Kontrola trendu před otevřením pozice

---

*Implementace dokončena: 2025-01-03*








