# Phase 1 Monitoring Checklist
# Signal Quality Improvement - Daily Tracking

**Start Date**: 2025-10-08 (středa)
**End Date**: 2025-10-15 (úterý) - 3-5 obchodních dní
**Phase**: 1 - Critical Changes

---

## 📋 DENNÍ KONTROLA

### Den 1 - 2025-10-08 (středa)

**Systém:**
- [ ] TradingAssistant restartován po změnách v apps.yaml
- [ ] Logování běží normálně
- [ ] Žádné error hlášky v logu

**Signály:**
- Celkem generováno: _____
- První signál v: _____ (čas)
- Poslední signál v: _____ (čas)

**Kvalita:**
- Průměrná kvalita: _____%
- Průměrná confidence: _____%
- Průměrný RRR: _____

**Filtrace:**
- Rejected - nízký RRR (< 1.8): _____
- Rejected - proti trendu: _____
- Rejected - nízká swing kvalita (< 50): _____
- Rejected - cooldown: _____

**Poznámky:**
```
_______________________________________________
_______________________________________________
_______________________________________________
```

---

### Den 2 - 2025-10-09 (čtvrtek)

**Signály:**
- Celkem generováno: _____
- První signál v: _____ (čas)
- Poslední signál v: _____ (čas)

**Kvalita:**
- Průměrná kvalita: _____%
- Průměrná confidence: _____%
- Průměrný RRR: _____

**Výkon (pokud byly obchody):**
- Otevřené pozice: _____
- Uzavřené pozice: _____
- Win rate dnes: _____%
- P/L dnes: _____ CZK

**Poznámky:**
```
_______________________________________________
_______________________________________________
_______________________________________________
```

---

### Den 3 - 2025-10-10 (pátek)

**Signály:**
- Celkem generováno: _____
- První signál v: _____ (čas)
- Poslední signál v: _____ (čas)

**Kvalita:**
- Průměrná kvalita: _____%
- Průměrná confidence: _____%
- Průměrný RRR: _____

**Výkon:**
- Otevřené pozice: _____
- Uzavřené pozice: _____
- Win rate dnes: _____%
- P/L dnes: _____ CZK

**Poznámky:**
```
_______________________________________________
_______________________________________________
_______________________________________________
```

---

### Víkend - 2025-10-11/12/13 (pá/so/ne)

**Poznámka:** Žádné obchodování o víkendu.

---

### Den 4 - 2025-10-14 (pondělí)

**Signály:**
- Celkem generováno: _____
- První signál v: _____ (čas)
- Poslední signál v: _____ (čas)

**Kvalita:**
- Průměrná kvalita: _____%
- Průměrná confidence: _____%
- Průměrný RRR: _____

**Výkon:**
- Otevřené pozice: _____
- Uzavřené pozice: _____
- Win rate dnes: _____%
- P/L dnes: _____ CZK

**Poznámky:**
```
_______________________________________________
_______________________________________________
_______________________________________________
```

---

### Den 5 - 2025-10-15 (úterý) - VYHODNOCENÍ

**Signály:**
- Celkem generováno: _____
- První signál v: _____ (čas)
- Poslední signál v: _____ (čas)

**Kvalita:**
- Průměrná kvalita: _____%
- Průměrná confidence: _____%
- Průměrný RRR: _____

**Výkon:**
- Otevřené pozice: _____
- Uzavřené pozice: _____
- Win rate dnes: _____%
- P/L dnes: _____ CZK

**Poznámky:**
```
_______________________________________________
_______________________________________________
_______________________________________________
```

---

## 📊 TÝDENNÍ SOUHRN (po 3-5 dnech)

**Datum vyhodnocení**: _____________

### Celkové statistiky:

**Signály:**
- Celkem vygenerováno: _____
- Průměr na den: _____
- **Cíl**: 5-7/den
- **Status**: ✅ SPLNĚNO / ❌ NESPLNĚNO

**Kvalita:**
- Průměrná kvalita: _____%
- **Cíl**: ≥ 75%
- **Status**: ✅ SPLNĚNO / ❌ NESPLNĚNO

**Confidence:**
- Průměrná confidence: _____%
- **Cíl**: ≥ 75%
- **Status**: ✅ SPLNĚNO / ❌ NESPLNĚNO

**RRR:**
- Průměrný RRR: _____
- Min RRR pozorovaný: _____
- **Cíl**: All ≥ 1.8
- **Status**: ✅ SPLNĚNO / ❌ NESPLNĚNO

**Výkon (pokud byly obchody):**
- Celkem obchodů: _____
- Vítězných: _____
- Prohrávajících: _____
- Win rate: _____%
- **Cíl**: ≥ 55%
- **Status**: ✅ SPLNĚNO / ❌ NESPLNĚNO

**Profit:**
- Celkový P/L: _____ CZK
- Průměr na obchod: _____ CZK
- Profit factor: _____
- **Status**: POSITIVE / NEGATIVE

---

## ✅ ROZHODNUTÍ - POKRAČOVAT DO FÁZE 2?

### Kontrolní otázky:

1. **Běží systém stabilně bez chyb?**
   - [ ] ANO
   - [ ] NE - popis problému: _______________

2. **Je počet signálů v rozmezí 3-7/den?**
   - [ ] ANO (ideální)
   - [ ] NE - příliš mnoho (> 7/den)
   - [ ] NE - příliš málo (< 3/den)

3. **Je průměrná kvalita ≥ 75%?**
   - [ ] ANO
   - [ ] NE - průměr: _____%

4. **Jsou všechny signály s RRR ≥ 1.8?**
   - [ ] ANO
   - [ ] NE - našel jsem signály s RRR < 1.8

5. **Jsou všechny signály ve směru trendu?**
   - [ ] ANO (regime_alignment funguje)
   - [ ] NE - našel jsem signály proti trendu

6. **Je win rate ≥ 55% (pokud máme ≥ 10 obchodů)?**
   - [ ] ANO
   - [ ] NE - win rate: _____%
   - [ ] N/A - málo obchodů (< 10)

### FINÁLNÍ ROZHODNUTÍ:

- [ ] **GO TO PHASE 2** - Vše splněno, pokračujeme podle plánu
- [ ] **ADJUST & CONTINUE PHASE 1** - Malé úpravy, prodloužit testování
- [ ] **ROLLBACK** - Vrátit změny, problém v logice

---

## 🔧 POKUD JE POTŘEBA ÚPRAVA:

### Scénář A: Příliš málo signálů (< 3/den)

**Problém**: Filtry jsou příliš přísné.

**Úprava v apps.yaml:**
```yaml
edges:
  min_bars_between_signals: 4     # ↓ z 6 na 4
  # NEBO
  min_swing_quality: 40           # ↓ z 50 na 40
```

**Re-test**: +2 dny

---

### Scénář B: Stále moc signálů (> 7/den)

**Problém**: Filtry nejsou dostatečně přísné.

**Úprava v apps.yaml:**
```yaml
edges:
  min_bars_between_signals: 9     # ↑ z 6 na 9
  # NEBO
  min_signal_quality: 70          # ↑ z 60 na 70
```

**Re-test**: +2 dny

---

### Scénář C: Nízká kvalita (< 75% avg)

**Problém**: Threshold je správný, ale scoring logika je špatná.

**Akce**:
1. Prozkoumat, jaké signály mají nízkou kvalitu
2. Zkontrolovat microstructure bonuses v edges.py
3. Možná bug v quality calculation

**Re-test**: Po opravě logiky

---

### Scénář D: Nízký win rate (< 50%)

**Problém**: Kvalita signálů může být vysoká, ale edge detection logika je špatná.

**Akce**:
1. Analyzovat prohrávající signály
2. Zkontrolovat pattern detection
3. Možný problém v trend alignment nebo pullback logice

**Re-test**: Po identifikaci root cause

---

## 📞 DALŠÍ KROKY PO VYHODNOCENÍ

**Pokud GO TO PHASE 2:**
1. Otevřít `SIGNAL_QUALITY_IMPROVEMENT_PLAN.md`
2. Implementovat Fázi 2 změny
3. Vytvořit nový checklist pro Fázi 2

**Pokud ADJUST:**
1. Zaznamenat úpravu do plánu
2. Prodloužit test o 2 dny
3. Re-evaluovat

**Pokud ROLLBACK:**
1. Restore z backup: `apps.yaml.backup_20250108_XXXXXX`
2. Analyzovat root cause problému
3. Konzultovat s Claude o alternativním přístupu

---

## 📝 RYCHLÉ POZNÁMKY

**Místo pro volné poznámky během testování:**

```
_______________________________________________
_______________________________________________
_______________________________________________
_______________________________________________
_______________________________________________
_______________________________________________
_______________________________________________
_______________________________________________
_______________________________________________
_______________________________________________
```

---

## 📧 LOG COMMANDS PRO ANALÝZU

**Zkontrolovat signály za den:**
```bash
grep "SIGNAL GENERATED" /path/to/appdaemon.log | grep "2025-01-08"
```

**Zkontrolovat rejections:**
```bash
grep "SIGNAL REJECTED" /path/to/appdaemon.log | grep "2025-01-08"
```

**Zkontrolovat quality scores:**
```bash
grep "Quality Score:" /path/to/appdaemon.log | grep "2025-01-08"
```

**Zkontrolovat RRR:**
```bash
grep "RRR:" /path/to/appdaemon.log | grep "2025-01-08"
```
