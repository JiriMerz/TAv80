# Signal Quality Improvement Plan - 3-Phase Implementation

**Datum zahájení**: 2025-10-08
**Cíl**: Snížit počet signálů, výrazně zvýšit kvalitu
**Metoda**: Postupná 3-fázová implementace s testováním

---

## 📊 SOUČASNÝ STAV (před změnami)

### Klíčové parametry:
```yaml
edges:
  min_swing_quality: 25
  min_signal_quality: 60
  min_confidence: 70
  min_rrr: 0.2  # TESTING ONLY!
  require_regime_alignment: false
  min_bars_between_signals: 3

microstructure:
  min_liquidity_score: 0.1
```

### Problém:
- **Příliš mnoho signálů** (10-15/den)
- **Nízká selektivita** - generují se i slabé signály
- **Min RRR 0.2** je testovací hodnota, produkční by měla být ≥1.5

---

## 🎯 FÁZE 1: KRITICKÉ ZMĚNY (OKAMŽITĚ)

**Implementováno**: 2025-10-08
**Testování**: 3-5 obchodních dní (do 2025-10-15)
**Cíl**: Odstranit zjevně nekvalitní signály

### Změny v apps.yaml:

```yaml
edges:
  min_rrr: 1.8                      # ↑ z 0.2 → **NEJVÝZNAMNĚJŠÍ ZMĚNA**
  require_regime_alignment: true    # ↑ z false → jen ve směru trendu
  min_swing_quality: 50             # ↑ z 25 → dvojnásobek!
  min_bars_between_signals: 6       # ↑ z 3 → kompromis (30 min na M5)
```

### Odůvodnění změn:

| Parametr | Před | Po | Dopad |
|----------|------|-----|-------|
| **min_rrr** | 0.2 | **1.8** | Eliminuje signály s malým profit potenciálem |
| **regime_alignment** | false | **true** | Obchoduje JEN ve směru trendu (ADX alignment) |
| **min_swing_quality** | 25% | **50%** | Vyžaduje jasnou strukturu |
| **cooldown** | 3 bary | **6 barů** | Max 2 signály/hod místo 4/hod |

### Očekávaný dopad:
- **Signály/den**: 10-15 → **5-7** (-50%)
- **Průměrná kvalita**: 60-70% → **75-80%**
- **Win rate**: 45-50% → **55-60%**

### Co sledovat během testování:

#### Denní metriky:
- [ ] Počet generovaných signálů
- [ ] Průměrná kvalita signálů
- [ ] Průměrná confidence
- [ ] Skutečný win rate
- [ ] Průměrný RRR realizovaný

#### Varování (red flags):
- ⚠️ **Méně než 2 signály/den** → příliš přísné, zvážit uvolnění
- ⚠️ **Kvalita stále pod 70%** → pokračovat do Fáze 2
- ⚠️ **Win rate pod 50%** → problém není v počtu ale v logice

#### Úspěch (green flags):
- ✅ **3-6 signálů/den** s kvalitou 75%+
- ✅ **Win rate 55%+**
- ✅ **Žádné signály s RRR < 1.8**
- ✅ **Všechny signály ve směru trendu**

---

## 🎯 FÁZE 2: QUALITY GATES (3-5 DNÍ PO FÁZI 1)

**Implementace**: Pokud Fáze 1 úspěšná
**Datum**: ~2025-10-15
**Testování**: 5-7 obchodních dní
**Cíl**: Zpřísnit kvalitativní požadavky

### Plánované změny:

```yaml
edges:
  min_signal_quality: 75            # ↑ z 60
  min_confidence: 80                # ↑ z 70

microstructure:
  min_liquidity_score: 0.3          # ↑ z 0.1 (kompromis mezi 0.1 a 0.5)
  volume_zscore_threshold: 2.0      # ↑ z 1.5

swings:
  atr_multiplier_m5: 1.5            # ↑ z 1.2
```

### Očekávaný dopad Fáze 2:
- **Signály/den**: 5-7 → **2-4** (další -30%)
- **Průměrná kvalita**: 75-80% → **80-85%**
- **Win rate**: 55-60% → **60-65%**

### Podmínky pro aktivaci Fáze 2:
1. ✅ Fáze 1 běží stabilně 3-5 dní
2. ✅ Generuje 3-6 signálů/den
3. ✅ Win rate ≥ 55%
4. ✅ Průměrná kvalita ≥ 75%

---

## 🎯 FÁZE 3: FINE-TUNING (2 TÝDNY PO FÁZI 1)

**Implementace**: Po vyhodnocení Fáze 2
**Datum**: ~2025-10-22
**Cíl**: Optimalizace podle reálných dat

### Možné úpravy (podle výsledků):

#### Pokud MÁLO SIGNÁLŮ (< 2/den):
```yaml
edges:
  min_bars_between_signals: 4       # ↓ z 6 zpět na 4
  min_swing_quality: 45             # ↓ z 50 na 45
```

#### Pokud STÁLE MOC SIGNÁLŮ (> 6/den):
```yaml
edges:
  min_bars_between_signals: 12      # ↑ z 6 na 12 (1 hod)
  min_confidence: 85                # ↑ z 80 na 85

microstructure:
  min_liquidity_score: 0.5          # ↑ z 0.3 na 0.5
```

#### Pokud VYSOKÁ KVALITA, OPTIMALIZOVAT RISK:
```yaml
risk_adjustments:
  quality_80_plus: 1.3              # ↑ z 1.2 (odměna)
  quality_50_80: 0.8                # ↓ z 1.0 (penalizace mid-quality)
  quality_below_50: 0.0             # Zakázat úplně
```

---

## 📈 METRIKY A MONITORING

### Denní tracking (Google Sheets / CSV):

| Datum | Signály celkem | Kvalita avg | Confidence avg | RRR avg | Win rate | Profit/Loss |
|-------|---------------|-------------|----------------|---------|----------|-------------|
| 2025-10-08 | ? | ? | ? | ? | ? | ? |
| 2025-10-09 | ? | ? | ? | ? | ? | ? |
| 2025-10-10 | ? | ? | ? | ? | ? | ? |
| 2025-10-14 | ? | ? | ? | ? | ? | ? |
| 2025-10-15 | ? | ? | ? | ? | ? | ? |
| ... | ... | ... | ... | ... | ... | ... |

### Týdenní vyhodnocení:

**Týden 1 (Fáze 1):**
- [ ] Celkem signálů: _____
- [ ] Průměrná kvalita: _____
- [ ] Win rate: _____
- [ ] Profit factor: _____
- [ ] **Rozhodnutí**: Pokračovat do Fáze 2? ANO / NE / UPRAVIT

**Týden 2 (Fáze 2):**
- [ ] Celkem signálů: _____
- [ ] Průměrná kvalita: _____
- [ ] Win rate: _____
- [ ] Profit factor: _____
- [ ] **Rozhodnutí**: Pokračovat do Fáze 3? ANO / NE / UPRAVIT

---

## 🔧 IMPLEMENTAČNÍ KROKY

### Fáze 1 - Dnes (2025-10-08):

1. ✅ **Záloha**: `apps.yaml.backup_20251008_080305`
2. ✅ **Úprava**: Změny aplikovány do apps.yaml
3. ⏳ **Restart**: Restartovat TradingAssistant
4. ⏳ **Monitoring**: Sledovat první signály
5. ⏳ **Log**: Začít zapisovat denní metriky

### Kontrolní seznam před Fází 2:

- [ ] Fáze 1 běží 3-5 dní bez chyb
- [ ] Min. 15 signálů vygenerováno celkem
- [ ] Průměrná kvalita ≥ 75%
- [ ] Win rate ≥ 55%
- [ ] Dokumentovány výsledky v tabulce
- [ ] Rozhodnutí: GO / NO-GO / ADJUST

### Kontrolní seznam před Fází 3:

- [ ] Fáze 2 běží 5-7 dní
- [ ] Min. 10 signálů vygenerováno
- [ ] Stabilní win rate
- [ ] Identifikovány problémové oblasti
- [ ] Připraven fine-tuning plán

---

## 📝 POZNÁMKY A ÚPRAVY

### 2025-10-08 - Fáze 1 implementace:
- Záloha vytvořena: `apps.yaml.backup_20251008_080305`
- Změny aplikovány: min_rrr (1.8), regime_alignment (true), swing_quality (50), cooldown (6)
- Restart systému: [ČAS]
- První signál po změnách: [TBD]

### Prostor pro poznámky během testování:

```
Den 1 (2025-10-08 st):
-

Den 2 (2025-10-09 čt):
-

Den 3 (2025-10-10 pá):
-

Víkend (2025-10-12/13):
- Žádné obchodování

Den 4 (2025-10-14 po):
-

Den 5 (2025-10-15 út):
- VYHODNOCENÍ FÁZE 1
```

---

## 🎯 OČEKÁVANÉ KONEČNÉ VÝSLEDKY (po Fázi 3)

| Metrika | Před | Po změnách | Zlepšení |
|---------|------|------------|----------|
| Signály/den | 10-15 | **2-4** | -75% |
| Min kvalita | 60% | **75%** | +25% |
| Avg kvalita | 65-70% | **80-85%** | +20% |
| Min RRR | 0.2 | **1.8** | +800% |
| Win rate | 45-50% | **60-65%** | +25% |
| Profit factor | 1.2-1.5 | **1.8-2.2** | +45% |

---

## ⚠️ RIZIKA A MITIGACE

### Riziko 1: Příliš málo signálů
**Symptom**: < 2 signály/den
**Mitigace**: Snížit cooldown z 6 na 4, nebo min_swing_quality z 50 na 40

### Riziko 2: Kvalita se nezlepší
**Symptom**: Stále průměr pod 75%
**Mitigace**: Problém může být v logice edge detection, ne jen v thresholdech

### Riziko 3: False positives na vysoké kvalitě
**Symptom**: Kvalita 80%+ ale win rate pod 50%
**Mitigace**: Přehodnotit scoring logiku v edges.py a microstructure bonusy

---

## 📞 KONTAKT PRO DALŠÍ ITERACI

Po 3-5 dnech testování Fáze 1:
1. Vyhodnotit metriky z tabulky
2. Rozhodnout o Fázi 2
3. Pokračovat v tomto dokumentu v sekci poznámek

**Příští review**: ~2025-10-15 (úterý)
