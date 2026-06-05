@echo off
echo.
echo  ====================================
echo    LabTrack - Iniciando servidor...
echo  ====================================
echo.
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python no encontrado.
    echo  Descargalo en: https://www.python.org/downloads/
    echo  Marca "Add Python to PATH" durante la instalacion.
    pause
    exit /b
)
python -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo  Instalando Flask (una sola vez)...
    pip install flask
)
echo  Iniciando LabTrack...
echo  Abre tu navegador en: http://localhost:5000
echo.
echo  Usuario admin:   admin@labtrack.hn / admin123
echo  Usuario tecnico: carlos@labtrack.hn / tech123
echo.
start "" http://localhost:5000
python server.py
pause
