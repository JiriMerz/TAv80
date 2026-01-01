# Signal Blocking Conditions - Complete Reference

Tento dokument popisuje všechny podmínky, které mohou blokovat generování signálů.

## 1. System State Checks (process_market_data)

### 1.1 cTrader Connection
**Log:** `[PROCESS_DATA] {alias}: BLOCKED - cTrader not connected (status: {status})`
- **Kontrola:** `binary_sensor.ctrader_connected != "on"`
- **Řešení:** Zkontroluj připojení cTrader klienta

### 1.2 Analysis Status
**Log:** `[PROCESS_DATA] {alias}: BLOCKED - Analysis not running (status: {status})`
- **Kontrola:** `sensor.trading_analysis_status != "RUNNING"`
- **Řešení:** Zkontroluj, že analýza běží

### 1.3 Insufficient Bars
**Log:** `[MAIN] {alias}: Insufficient bars {count}/{required}`
- **Kontrola:** `len(bars) < self.analysis_min_bars` (obvykle 100 barů)
- **Řešení:** Počkej na akumulaci více dat

### 1.4 Active Tickets
**Log:** `[PROCESS_DATA] {alias}: BLOCKED - {count} active tickets`
- **Kontrola:** `active_tickets > 0`
- **Řešení:** Zavři existující pozice před generováním nových signálů

### 1.5 Trading Hours
**Log:** `[PROCESS_DATA] {alias}: BLOCKED - Outside trading hours at {time} UTC`
- **Kontrola:** `not self._is_within_trading_hours(alias)`
- **Řešení:** Zkontroluj konfiguraci obchodních hodin v `apps.yaml`

### 1.6 Risk Manager
**Log:** `[PROCESS_DATA] {alias}: BLOCKED - Risk manager (can_trade=False)`
- **Kontrola:** `not risk_status.can_trade`
- **Řešení:** Zkontroluj risk manager stav (denní limit, margin, atd.)

### 1.7 Microstructure/Market Conditions
**Log:** 
- `[PROCESS_DATA] {alias}: BLOCKED - Poor market conditions (liquidity {score} < {threshold})`
- `[PROCESS_DATA] {alias}: BLOCKED - Outside prime trading hours`
- `[PROCESS_DATA] {alias}: BLOCKED - Suboptimal trading conditions`
- **Kontrola:** `not self.edge.is_quality_trading_time(alias, micro_data)`
- **Řešení:** Počkej na lepší tržní podmínky (likvidita, trading hours)

### 1.8 Edge Detector Not Initialized
**Log:** `[PROCESS_DATA] {alias}: BLOCKED - Edge detector not initialized`
- **Kontrola:** `not hasattr(self, 'edge') or self.edge is None`
- **Řešení:** Zkontroluj inicializaci EdgeDetector

### 1.9 Missing Data
**Log:** `[PROCESS_DATA] {alias}: BLOCKED - Missing data: {missing_list}`
- **Kontrola:** `not swing or not piv or not regime_data`
- **Řešení:** Zkontroluj, že všechny analýzy (regime, pivots, swing) proběhly úspěšně

## 2. Signal Cooldown (process_market_data)

### 2.1 Signal Cooldown Active
**Log:** `[COOLDOWN] {alias}: Signal cooldown active ({remaining}min remaining, market_changed={bool}, last_direction={dir})`
- **Kontrola:** `time_since_signal < effective_cooldown`
- **Cooldown:**
  - Base: 30 minut (1800 sekund)
  - Market changed: 10 minut (600 sekund)
  - Opposite direction: 15 minut (900 sekund)
- **Řešení:** Počkej na vypršení cooldown period

### 2.2 Same Direction Cooldown
**Log:** `[COOLDOWN] {alias}: Skipping {direction} signal - same direction cooldown active ({remaining}min remaining)`
- **Kontrola:** Stejný směr jako poslední signál a `time_since_signal < base_cooldown`
- **Řešení:** Počkej na vypršení 30min cooldown

### 2.3 Opposite Direction Cooldown
**Log:** `[COOLDOWN] {alias}: Skipping {direction} signal - opposite direction cooldown active ({remaining}min remaining, last was {last_dir})`
- **Kontrola:** Opačný směr ale `time_since_signal < 900` (15 min)
- **Řešení:** Počkej na vypršení 15min cooldown

## 3. Edge Detection Filters (detect_signals)

### 3.1 Insufficient Bars
**Log:** `[SIGNAL_DETECT] Rejection: Insufficient bars for analysis`
- **Kontrola:** `len(bars) < 20`
- **Řešení:** Počkej na více dat

### 3.2 Edge Detection Cooldown
**Log:** `[SIGNAL_DETECT] Rejection: Signal cooldown active`
- **Kontrola:** `current_bar_index - self._last_signal_bar_index < self.min_bars_between_signals`
- **Řešení:** Počkej na více barů od posledního signálu

### 3.3 Strict Regime Filter ⚠️ NEJČASTĚJŠÍ BLOKER
**Log:** `🚫 [STRICT_FILTER] BLOCKED: regime={regime}, EMA34={ema34_trend}, reasons={reasons}`
- **Kontrola:** 
  - Regime MUSÍ být `TREND_UP` nebo `TREND_DOWN`
  - EMA34 MUSÍ ukazovat trend (`UP` nebo `DOWN`)
  - Oba směry MUSÍ souhlasit
- **Řešení:** 
  - Zkontroluj, že regime je v trendu
  - Zkontroluj, že EMA34 trend souhlasí se směrem regime
  - Pokud není v trendu, signály se negenerují
  - Pro backtesting: vypni `strict_regime_filter: false` v config

### 3.4 Swing Quality
**Log:** `🚫 [SWING_QUALITY] BLOCKED: {quality}% < {min}%, regime={regime}, ADX={adx}`
- **Kontrola:** `swing_quality < self.min_swing_quality` (obvykle 60%)
- **Exception:** V silném trendu (ADX > 25) se tato kontrola přeskočí
- **Řešení:** Počkej na lepší swing kvalitu nebo silnější trend

### 3.5 Pullback Detection
**Log:** (Žádný explicitní "BLOCKED" log, ale žádný pullback nebyl nalezen)
- **Kontrola:** `pullback_opportunity = self.pullback_detector.detect_pullback_opportunity(...)`
- **Řešení:** Pokud není pullback, systém pokračuje k pattern detection

### 3.6 Pattern Detection - Not in Pullback Zone
**Log:** `⏭️ [PATTERN_DETECT] Skipping - not in pullback zone (trend: {trend})`
- **Kontrola:** V trendu ale ne v pullback zóně
- **Řešení:** V trendech se signály generují jen v pullback zónách

### 3.7 Signal Quality/Confidence
**Log:** `🚫 [SIGNAL_QUALITY] BLOCKED: Quality {quality}% < {min}%` nebo `Confidence {conf}% < {min}%`
- **Kontrola:** 
  - `signal.signal_quality < self.min_signal_quality` (obvykle 60%)
  - `signal.confidence < self.min_confidence` (obvykle 50%)
- **Řešení:** Signál neprošel kvalitními thresholdy

### 3.8 No Patterns/Structure Breaks
**Log:** `⏸️ [SIGNAL_DETECT] No signals generated (all filters passed but no valid signals)`
- **Kontrola:** Žádné patterny ani structure breaks nebyly nalezeny
- **Řešení:** Počkej na lepší tržní podmínky pro pattern detection

## 4. Jak analyzovat logy

### Použití analyze_signal_logs.py

```bash
# Spustit analýzu log souboru
python backtesting/analyze_signal_logs.py /path/to/appdaemon.log

# Nebo pokud máš log v Home Assistant
python backtesting/analyze_signal_logs.py /config/home-assistant.log
```

### Hledání v logu

Hledej následující patterny v logu:

```bash
# Najít všechny BLOCKED zprávy
grep "BLOCKED" appdaemon.log

# Najít všechny STRICT_FILTER blokace
grep "STRICT_FILTER" appdaemon.log

# Najít všechny SIGNAL_DETECT zprávy
grep "SIGNAL_DETECT" appdaemon.log

# Najít všechny COOLDOWN zprávy
grep "COOLDOWN" appdaemon.log

# Najít všechny [PROCESS_DATA] zprávy
grep "\[PROCESS_DATA\]" appdaemon.log
```

### Typický workflow v logu

1. `[BAR] {alias}: Calling process_market_data` - Bar uzavřen, začíná analýza
2. `[PROCESS_DATA] {alias}: Entry - {bars} bars available` - Vstup do process_market_data
3. `[PROCESS_DATA] {alias}: System checks - cTrader={status}, Analysis={status}` - Systémové kontroly
4. `[REGIME] ===== FINAL REGIME STATE =====` - Regime detekován
5. `[PIVOT] Daily pivots calculated` - Pivots spočítány
6. `[SIMPLE_SWING] Detected {n} swings` - Swings detekovány
7. `[SIGNAL_CHECK] {alias}: Calling detect_signals` - Zavolán detect_signals
8. `🔍 [SIGNAL_DETECT] Starting signal detection` - Edge detection začíná
9. `✅ [STRICT_FILTER] PASSED` nebo `🚫 [STRICT_FILTER] BLOCKED` - Strict filter kontrola
10. `✅ [SWING_QUALITY] PASSED` nebo `🚫 [SWING_QUALITY] BLOCKED` - Swing quality kontrola
11. `✅ [SIGNAL_GENERATED]` nebo `⏸️ [SIGNAL_DETECT] No signals generated` - Výsledek

## 5. Nejčastější problémy

### Problém 1: Žádné signály kvůli STRICT_FILTER
**Příznaky:**
```
🚫 [STRICT_FILTER] BLOCKED: regime=RANGE, EMA34=None, reasons=['Regime is not TREND (current: RANGE/RANGE)', 'EMA34 does not show trend (current: None)']
```

**Řešení:**
- Systém negeneruje signály v RANGE režimu (pouze v TREND)
- Zkontroluj regime detection - proč je RANGE místo TREND?
- Zkontroluj EMA34 trend - proč je None?
- Pro backtesting: vypni `strict_regime_filter: false`

### Problém 2: Žádné signály kvůli cooldown
**Příznaky:**
```
[COOLDOWN] NASDAQ: Signal cooldown active (25min remaining, market_changed=False, last_direction=BUY)
```

**Řešení:**
- Počkej na vypršení cooldown period (30 min pro stejný směr, 15 min pro opačný)
- Nebo počkej na výraznou změnu trhu (2x ATR nebo 1% cenová změna)

### Problém 3: Žádné signály kvůli trading hours
**Příznaky:**
```
[PROCESS_DATA] NASDAQ: BLOCKED - Outside trading hours at 18:00 UTC
```

**Řešení:**
- Zkontroluj konfiguraci trading hours v `apps.yaml`
- Ujisti se, že je aktuální čas v definovaných hodinách

### Problém 4: Žádné signály kvůli nízké kvalitě
**Příznaky:**
```
🚫 [SWING_QUALITY] BLOCKED: 45.0% < 60.0%, regime=TREND_UP, ADX=23.5
🚫 [SIGNAL_QUALITY] BLOCKED: Quality 55.0% < 60.0%
```

**Řešení:**
- Počkej na lepší swing kvalitu (>= 60%)
- Nebo silnější trend (ADX > 25) pro vynechání swing quality checku
- Sniž thresholdy v config (ne doporučeno pro produkci)

## 6. Debugging Tips

1. **Zapni DEBUG logování** v `apps.yaml`:
   ```yaml
   log_level: DEBUG
   ```

2. **Sleduj konkrétní symbol**:
   ```bash
   grep "NASDAQ" appdaemon.log | grep -E "(PROCESS_DATA|SIGNAL_DETECT|STRICT_FILTER|COOLDOWN)"
   ```

3. **Zkontroluj regime state**:
   ```bash
   grep "FINAL REGIME STATE" appdaemon.log | tail -20
   ```

4. **Zkontroluj EMA34 trend**:
   ```bash
   grep "EMA34 Trend:" appdaemon.log | tail -20
   ```

5. **Sleduj flow jednoho baru**:
   - Najdi čas uzavření baru (např. 14:30:00)
   - Hledej všechny logy mezi 14:30:00 a 14:35:00 pro tento symbol
   - Sleduj celý flow od `[BAR]` přes `[PROCESS_DATA]` až k `[SIGNAL_DETECT]`

