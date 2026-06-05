#!/bin/bash
echo ""
echo "  ===================================="
echo "    LabTrack - Iniciando servidor..."
echo "  ===================================="
echo ""
if ! command -v python3 &>/dev/null; then
    echo "  ERROR: Python 3 no encontrado."
    echo "  Instalalo en: https://www.python.org/downloads/"
    exit 1
fi
python3 -c "import flask" 2>/dev/null || pip3 install flask
echo "  Servidor iniciado en http://localhost:5000"
echo "  Admin:   admin@labtrack.hn / admin123"
echo "  Tecnico: carlos@labtrack.hn / tech123"
echo ""
[[ "$OSTYPE" == "darwin"* ]] && sleep 1.5 && open http://localhost:5000 &
python3 server.py
