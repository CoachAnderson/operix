@echo off
chcp 65001 >nul
title Conector OraculoInvest - MetaTrader 5
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python nao encontrado. Instale o Python 3.13 64 bits em https://www.python.org/downloads/windows/
  echo Marque "Add python.exe to PATH" na instalacao e rode este arquivo de novo.
  pause
  exit /b 1
)

if not exist .venv (
  echo Preparando o conector pela primeira vez...
  py -3 -m venv .venv || goto erro
)
.venv\Scripts\python -m pip install --disable-pip-version-check -q -r requirements.txt || goto erro

if not exist conector.ini (
  copy conector.ini.exemplo conector.ini >nul
  echo.
  echo Abra o arquivo conector.ini, cole o token do painel e rode este arquivo de novo.
  notepad conector.ini
  exit /b 0
)

:loop
.venv\Scripts\python oraculo_conector.py
echo O conector parou. Reiniciando em 10 segundos (feche esta janela para encerrar)...
timeout /t 10 >nul
goto loop

:erro
echo Nao foi possivel instalar as dependencias. Confira a internet e tente de novo.
pause
