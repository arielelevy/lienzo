@echo off
rem Arranca lienzo-server en 127.0.0.1:7321 con el Python 3.14 (mas rapido) si esta, si no el de la Store.
set PY=%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe
if not exist "%PY%" set PY=python
set PYTHONIOENCODING=utf-8
"%PY%" "%~dp0lienzo\server.py" %*
