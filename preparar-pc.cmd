@echo off
rem Deja una PC del lienzo siempre disponible (decision 11, 2026-10-22):
rem   1. el lienzo arranca solo al iniciar sesion (acceso directo en la carpeta Inicio de ESTE usuario);
rem   2. las 4 reglas de firewall del emparejamiento (install.py --peer-only), lo unico que pide administrador.
rem Se puede correr de nuevo: el acceso directo se reescribe y las reglas se reemplazan, no se duplican.
setlocal
set "REPO=%~dp0"
set "INICIO=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

echo == 1. Arranque al iniciar sesion
> "%INICIO%\lienzo.cmd" echo @start "lienzo" /min "%REPO%lienzo-server.cmd"
if errorlevel 1 (echo    no se pudo escribir en "%INICIO%") else (echo    listo: "%INICIO%\lienzo.cmd")

echo.
echo == 2. Reglas de firewall (se abre el pedido de administrador)
powershell -NoProfile -Command "Start-Process -Wait -Verb RunAs -FilePath py -ArgumentList '-3.14','\"%REPO%install.py\"','--peer-only'"
if errorlevel 1 echo    no se acepto el pedido de administrador: las reglas no se crearon

echo.
echo == 3. Como quedo
for %%R in ("Lienzo Peer TCP" "Lienzo Beacon UDP" "Lienzo Peer TCP Tailscale" "Lienzo Beacon UDP Tailscale") do (
  netsh advfirewall firewall show rule name=%%R >nul 2>&1 && (echo    OK    %%~R) || (echo    FALTA %%~R)
)
if exist "%INICIO%\lienzo.cmd" (echo    OK    arranque al iniciar sesion) else (echo    FALTA arranque al iniciar sesion)
echo.
pause