@echo off
rem Interprete explicito: no usar el alias python de WindowsApps.
set PYTHONIOENCODING=utf-8
rem El server mira sus .py y, si cambian (git pull, edicion), sale con 75: aca se relanza en la misma ventana.
rem Cualquier otra salida (Ctrl+C, error, matar el PID) corta el bucle.
set LIENZO_RELOAD=1
:otra
rem --peers: escucha a las otras PCs de la LAN (7322) y las anuncia, aunque no haya ninguna emparejada
py -3.14 "%~dp0lienzo\server.py" --peers %*
if errorlevel 75 if not errorlevel 76 (
  timeout /t 1 /nobreak >nul
  goto otra
)
