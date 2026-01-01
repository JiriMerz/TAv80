# Rozdíly v SL/TP a Position Sizing: Produkce vs. Backtest

**Datum:** 2025-12-26

## 🔍 Problém

Produkce a backtest používají **jinou logiku** pro výpočet SL/TP a position sizing, což vede k rozdílným výsledkům.

## 📊 Produkce (main.py → simple_order_executor.py)

### 1. V `main.py` (`_try_auto_execute_signal`):

```python
# Získá SL/TP ceny ze signálu
entry_price = signal_dict.get('entry', 0)
stop_loss = signal_dict.get('stop_loss', 0)
take_profit = signal_dict.get('take_profit', 0)

# PŘEPOČÍTÁ distances z cen
sl_distance_points = abs(entry_price - stop_loss)
tp_distance_points = abs(take_profit - entry_price)

# Nebo použije ADVANCED strategii (pokud je zapnutá):
if use_advanced_sl_tp:
    # Vypočítá base SL z ATR, quality, atd.
    base_sl_pips = ...
    adjusted_sl_pips = ...
    sl_distance_points = adjusted_sl_pips / 100.0
    tp_distance_points = sl_distance_points * fixed_rrr  # Např. 2.0
    
    # Aplikuje SL/TP band system
    sl_final_pts, _ = risk_manager.apply_structural_sl_band(alias, sl_distance_points)
    tp_final_pts, _ = risk_manager.apply_structural_tp_band(alias, sl_final_pts, tp_distance_points)
    
    # Aktualizuje signál s band-adjusted hodnotami
    auto_signal["sl_distance_points"] = sl_final_pts
    auto_signal["tp_distance_points"] = tp_final_pts

# Předá do order_executor jako distances
auto_signal = {
    'sl_distance_points': sl_distance_points,
    'tp_distance_points': tp_distance_points,
    ...
}
```

### 2. V `simple_order_executor.py` (`can_execute_trade`):

```python
# Získá distances ze signálu
sl_distance_points = signal.get('sl_distance_points', 0)
tp_distance_points = signal.get('tp_distance_points', sl_distance_points * 2)  # FALLBACK!

# ZNOVU vypočítá SL/TP ceny z distances
if direction.upper() == 'BUY':
    stop_loss_price = signal.get('stop_loss', entry_price - sl_distance_points)
    take_profit_price = signal.get('take_profit', entry_price + tp_distance_points)
else:
    stop_loss_price = signal.get('stop_loss', entry_price + sl_distance_points)
    take_profit_price = signal.get('take_profit', entry_price - tp_distance_points)

# Volá risk_manager s PŘEPOČÍTANÝMI cenami
position_size = self.risk_manager.calculate_position_size(
    symbol=symbol,
    entry=entry_price,
    stop_loss=stop_loss_price,  # ← PŘEPOČÍTANÁ cena!
    take_profit=take_profit_price,  # ← PŘEPOČÍTANÁ cena!
    ...
)
```

### 3. V `risk_manager.py` (`calculate_position_size`):

```python
# Může dále upravit SL/TP:
# - Swing-based SL adjustment
# - ATR-based SL adjustment
# - Intraday TP limits (max 60 points, max 1.8:1 RRR)
# - Minimum RRR (1.3:1)

# Vypočítá position size na základě FINÁLNÍHO SL
sl_distance_points = abs(entry - stop_loss)  # ← FINÁLNÍ SL distance
sl_distance_pips = sl_distance_points * 100

# Wide stops adjustment (pokud je zapnutý)
if use_wide_stops:
    # Pokud by position byla příliš velká, rozšíří SL
    theoretical_position = risk_amount_czk / (sl_distance_pips * pip_value)
    if theoretical_position > max_position:
        required_sl_pips = risk_amount_czk / (target_position * pip_value)
        sl_distance_points = required_sl_pips / 100.0
        # Upraví SL cenu
        if stop_loss < entry:  # BUY
            stop_loss = entry - sl_distance_points
        else:  # SELL
            stop_loss = entry + sl_distance_points

# Fixed position sizing (8-20 lots)
position_size = target_position  # Např. 12 lots
# Aplikuje adjustments (quality, microstructure, atd.)
position_size = position_size * quality_adj * micro_adj
```

## 📊 Backtest (production_backtest.py)

### 1. V `production_backtest.py` (`_execute_signal`):

```python
# Používá PŘÍMO SL/TP ceny ze signálu (bez přepočtu!)
entry_price = signal.entry
stop_loss = signal.stop_loss  # ← PŘÍMO ze signálu
take_profit = signal.take_profit  # ← PŘÍMO ze signálu

# Volá risk_manager s PŘÍMÝMI cenami
position = self.risk_manager.calculate_position_size(
    symbol=symbol,
    entry=entry_price,
    stop_loss=stop_loss,  # ← PŘÍMO ze signálu
    take_profit=take_profit,  # ← PŘÍMO ze signálu
    ...
)
```

### 2. V `risk_manager.py` (`calculate_position_size`):

```python
# Stejná logika jako v produkci, ale:
# - NEMÁ přístup k SL/TP band system (není v backtestu)
# - NEMÁ přístup k advanced SL/TP strategii
# - Používá PŘÍMO SL/TP ze signálu (bez přepočtu v main.py)
```

## ⚠️ Klíčové rozdíly

### 1. **SL/TP přepočet v produkci:**
- Produkce **přepočítává** SL/TP distances z cen v `main.py`
- Může použít **ADVANCED strategii** (ATR-based, quality-based, atd.)
- Aplikuje **SL/TP band system** (strukturní úrovně)
- Backtest používá **přímo** SL/TP ze signálu

### 2. **Fallback v simple_order_executor:**
```python
tp_distance_points = signal.get('tp_distance_points', sl_distance_points * 2)
```
- Pokud `tp_distance_points` není v signálu, použije `sl_distance_points * 2`
- To může vést k jinému TP než EdgeDetector vytvořil!

### 3. **Wide stops adjustment:**
- Produkce může **rozšířit SL**, pokud by position byla příliš velká
- Backtest také, ale s jinými vstupními hodnotami

### 4. **Intraday TP limits:**
- Produkce aplikuje: `max_intraday_tp_points = 60.0`, `max_rrr = 1.8:1`
- Backtest také, ale s jinými vstupními SL/TP

## 💡 Řešení

### Možnost 1: Synchronizovat backtest s produkcí

Upravit `production_backtest.py` tak, aby používal stejnou logiku jako produkce:

```python
def _execute_signal(self, symbol: str, signal, current_price: float, timestamp: datetime):
    # 1. Získat SL/TP ceny ze signálu
    entry_price = signal.entry
    stop_loss = signal.stop_loss
    take_profit = signal.take_profit
    
    # 2. PŘEPOČÍTAT distances (jako v produkci)
    sl_distance_points = abs(entry_price - stop_loss)
    tp_distance_points = abs(take_profit - entry_price)
    
    # 3. Aplikovat ADVANCED strategii (pokud je zapnutá)
    if use_advanced_sl_tp:
        # ... stejná logika jako v main.py ...
        sl_distance_points = ...
        tp_distance_points = ...
    
    # 4. Aplikovat SL/TP band system
    sl_final_pts, _ = self.risk_manager.apply_structural_sl_band(symbol, sl_distance_points)
    tp_final_pts, _ = self.risk_manager.apply_structural_tp_band(symbol, sl_final_pts, tp_distance_points)
    
    # 5. ZNOVU vypočítat SL/TP ceny z distances
    if signal.signal_type.value == "BUY":
        stop_loss = entry_price - sl_final_pts
        take_profit = entry_price + tp_final_pts
    else:
        stop_loss = entry_price + sl_final_pts
        take_profit = entry_price - tp_final_pts
    
    # 6. Volat risk_manager s PŘEPOČÍTANÝMI cenami
    position = self.risk_manager.calculate_position_size(...)
```

### Možnost 2: Zjednodušit produkci

Upravit produkci tak, aby používala přímo SL/TP ze signálu (jako backtest), ale to by mohlo změnit produkční chování.

## 📊 Doporučení

**Doporučuji Možnost 1** - synchronizovat backtest s produkcí, aby používal stejnou logiku pro SL/TP a position sizing. To zajistí, že backtest výsledky budou odpovídat produkci.

