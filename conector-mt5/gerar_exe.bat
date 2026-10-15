@echo off
REM Gera OraculoConector.exe (para distribuir sem exigir Python no computador do cliente).
REM Rode no Windows, com Python 3.13 64 bits instalado.
cd /d "%~dp0"
py -3 -m venv .venv-build
.venv-build\Scripts\python -m pip install -q -r requirements.txt pyinstaller==6.22.3
.venv-build\Scripts\pyinstaller --onefile --name OraculoConector --console oraculo_conector.py
copy conector.ini.exemplo dist\conector.ini.exemplo >nul
copy LEIA-ME.txt dist\LEIA-ME.txt >nul
echo Pronto: dist\OraculoConector.exe
pause
