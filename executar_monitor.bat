@echo off
REM Usa o diretório do próprio script (%~dp0) — sem caminho absoluto fixo.
cd /d "%~dp0"
python monitor_diario_oficial.py
pause