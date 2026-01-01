#!/bin/bash
# Skript pro kontrolu stavu optimalizace

echo "🔍 Kontrola stavu optimalizace..."
echo ""

# Zkontrolovat, zda proces běží
if ps aux | grep -v grep | grep -q "optimize_params.py"; then
    echo "✅ Optimalizace běží"
    ps aux | grep -v grep | grep "optimize_params.py" | head -1 | awk '{print "   PID: "$2" | CPU: "$3"% | Čas: "$10}'
    echo ""
    echo "💡 Pro sledování progress použij: tail -f /tmp/optimization.log"
else
    echo "⏹️  Optimalizace NEBĚŽÍ"
    echo ""
fi

# Zkontrolovat výsledky
if ls backtesting/results/optimization_*.json 1> /dev/null 2>&1; then
    latest=$(ls -t backtesting/results/optimization_*.json | head -1)
    echo "📊 Nejnovější výsledky:"
    echo "   $latest"
    echo "   Vytvořeno: $(stat -f "%Sm" "$latest" 2>/dev/null || stat -c "%y" "$latest" 2>/dev/null)"
    echo ""
    
    # Zobrazit počet výsledků
    count=$(python3 -c "import json; f=open('$latest'); data=json.load(f); print(len(data))" 2>/dev/null || echo "?")
    echo "   Počet testovaných kombinací: $count"
    echo ""
    
    # Zobrazit TOP 3
    echo "🏆 TOP 3 nejlepší kombinace:"
    python3 -c "
import json
import sys

try:
    with open('$latest', 'r') as f:
        results = json.load(f)
    
    # Seřadit podle score
    results.sort(key=lambda x: x.get('score', 0), reverse=True)
    
    for i, r in enumerate(results[:3], 1):
        params = r.get('params', {})
        print(f'\\n{i}. Score: {r.get(\"score\", 0):.4f}')
        print(f'   PnL: {r.get(\"pnl_pct\", 0):+.2f}% ({r.get(\"total_pnl\", 0):+,.0f} CZK)')
        print(f'   Trades: {r.get(\"total_trades\", 0)} | WR: {r.get(\"win_rate\", 0):.1f}% | PF: {r.get(\"profit_factor\", 0):.2f}')
        print(f'   Parametry: min_q={params.get(\"min_signal_quality\")}, min_conf={params.get(\"min_confidence\")}, min_rrr={params.get(\"min_rrr\")}')
except Exception as e:
    print(f'   Chyba při čtení: {e}')
" 2>/dev/null || echo "   (Nelze zobrazit)"
else
    echo "📊 Žádné výsledky zatím nebyly vytvořeny"
    echo ""
fi

# Zkontrolovat optimized_config.yaml
if [ -f "backtesting/config/optimized_config.yaml" ]; then
    echo "✅ Optimální konfigurace vytvořena:"
    echo "   backtesting/config/optimized_config.yaml"
    echo ""
    echo "💡 Pro použití: cp backtesting/config/optimized_config.yaml backtesting/config/backtest_config.yaml"
fi

