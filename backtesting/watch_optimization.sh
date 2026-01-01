#!/bin/bash
# Sledování optimalizace v reálném čase

echo "👀 Sledování optimalizace..."
echo "   (Stiskněte Ctrl+C pro ukončení)"
echo ""

# Zkontrolovat, zda proces běží
if ! ps aux | grep -v grep | grep -q "optimize_params.py"; then
    echo "⚠️  Optimalizace NEBĚŽÍ!"
    exit 1
fi

# Sledovat log soubor nebo stdout procesu
echo "📊 Progress:"
echo ""

# Sledovat nové výsledky
watch -n 5 '
    if ps aux | grep -v grep | grep -q "optimize_params.py"; then
        echo "✅ Běží..."
        ps aux | grep -v grep | grep "optimize_params.py" | head -1 | awk "{print \"   PID: \"\$2\" | CPU: \"\$3\"% | Čas: \"\$10}"
    else
        echo "✅ Hotovo!"
    fi
    echo ""
    if ls backtesting/results/optimization_*.json 1> /dev/null 2>&1; then
        latest=$(ls -t backtesting/results/optimization_*.json | head -1)
        count=$(python3 -c "import json; f=open(\"$latest\"); data=json.load(f); print(len(data))" 2>/dev/null || echo "?")
        echo "📊 Testováno kombinací: $count"
    fi
' 2>/dev/null || {
    # Fallback pokud watch není dostupný
    while ps aux | grep -v grep | grep -q "optimize_params.py"; do
        clear
        echo "👀 Sledování optimalizace..."
        echo ""
        ps aux | grep -v grep | grep "optimize_params.py" | head -1
        echo ""
        if ls backtesting/results/optimization_*.json 1> /dev/null 2>&1; then
            latest=$(ls -t backtesting/results/optimization_*.json | head -1)
            count=$(python3 -c "import json; f=open('$latest'); data=json.load(f); print(len(data))" 2>/dev/null || echo "?")
            echo "📊 Testováno kombinací: $count"
        fi
        sleep 5
    done
    echo ""
    echo "✅ Optimalizace dokončena!"
}

