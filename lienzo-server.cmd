@echo off
rem Interprete explicito: no usar el alias python de WindowsApps.
set PYTHONIOENCODING=utf-8
py -3.14 "%~dp0lienzo\server.py" %*
