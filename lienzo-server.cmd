@echo off
rem Interprete explicito: no usar el alias python de WindowsApps.
set PYTHONIOENCODING=utf-8
rem --peers: escucha a las otras PCs de la LAN (7322) y las anuncia, aunque no haya ninguna emparejada
py -3.14 "%~dp0lienzo\server.py" --peers %*
