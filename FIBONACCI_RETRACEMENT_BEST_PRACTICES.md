# Fibonacci Retracement Best Practices pro Swing Trading

## 📊 Nejčastější a nejspolehlivější úrovně

Podle best practices v swing tradingu jsou nejdůležitější Fibonacci retracement úrovně:

### ⭐ Hlavní úrovně (nejspolehlivější):

1. **38.2%** - Střední pullback
   - Běžný v zdravých trendech
   - Poskytuje dobré risk-reward příležitosti
   - Často slouží jako podpora/odpor

2. **50%** - Psychologická polovina
   - Neoficiální Fibonacci číslo, ale široce používané
   - Psychologický midpoint, kde obchodníci očekávají obrat
   - Často funguje jako silná úroveň

3. **61.8%** (Golden Ratio) - **NEJDŮLEŽITĚJŠÍ**
   - Považováno za nejspolehlivější úroveň pro vstupní body
   - Silná podpora/odpor
   - Často indikuje potenciální obrat nebo pokračování trendu

### 📌 Vedlejší úrovně:

4. **23.6%** - Menší pullback
   - Často pozorovaný v silných trendech
   - Méně spolehlivý než 38.2%+

5. **78.6%** - Hluboký retracement
   - Může signalizovat hlavní obrat nebo konsolidaci
   - Méně častý než ostatní úrovně

---

## 🎯 Aktuální nastavení vs. Best Practices

### Aktuální konfigurace:
```yaml
min_retracement_pct: 0.118  # 11.8% - NEOBVYKLÉ, ne-Fibonacci
max_retracement_pct: 0.618  # 61.8% - ✅ SPRÁVNÉ
```

### Doporučené nastavení podle best practices:

**Varianta 1 - Konzervativní (DOPORUČENO):**
```yaml
min_retracement_pct: 0.382  # 38.2% - Spolehlivější signály
max_retracement_pct: 0.618  # 61.8% - Golden ratio
```

**Varianta 2 - Vyvážené:**
```yaml
min_retracement_pct: 0.236  # 23.6% - Více signálů, stále standardní
max_retracement_pct: 0.618  # 61.8% - Golden ratio
```

**Varianta 3 - Agresivní:**
```yaml
min_retracement_pct: 0.118  # 11.8% - Mnoho signálů, vyšší riziko falešných
max_retracement_pct: 0.618  # 61.8% - Golden ratio
```

---

## 💡 Proč je 11.8% problematické?

1. **Ne-Fibonacci úroveň** - 11.8% není standardní Fibonacci retracement
2. **Příliš agresivní** - Generuje signály příliš brzy v pullbacku
3. **Více falešných signálů** - Pullback ještě nemusí být dokončen
4. **Nižší spolehlivost** - Neexistuje historická data potvrzující tuto úroveň

---

## ✅ Doporučení

**Pro swing trading v jasném trendu s vstupy na pullback dnech:**

- **Minimum: 38.2%** - Nejspolehlivější úroveň podle best practices
- **Maximum: 61.8%** - Golden ratio, silná úroveň (současné nastavení je správné)

**Kombinace s reversal patterns:**
- Pokud detekujeme reversal pattern (hammer, engulfing, pin bar) na Fibonacci úrovni, je to silný signál
- Reversal pattern na 38.2% nebo 61.8% má vyšší pravděpodobnost úspěchu

---

## 📈 Reference

- Edgeful.com: 38.2% level represents a moderate pullback, common in healthy trends
- STPTrading.io: 50% serves as psychological midpoint
- MasteryTraderAcademy: 61.8% (Golden Ratio) is most critical retracement point, most reliable for entry points


