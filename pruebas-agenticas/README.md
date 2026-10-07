# Pruebas agénticas en Lienzo

La configuración ejecuta suites existentes con el runner del plugin instalado. Requiere Node 24+, Python 3.14, dependencias de `web`, Chromium de Playwright y el lienzo real en `127.0.0.1:7321`.

Usa el runner del plugin instalado. Esta revisión se ejecutó desde la raíz del repo:

```powershell
$pluginRoot = 'C:/Users/ArielLevy/.codex/plugins/cache/pruebas-agenticas/pruebas-agenticas/0.5.18'
node "$pluginRoot/runner/validar.mjs" pruebas-agenticas/pruebas-agenticas.json
node "$pluginRoot/runner/ejecutar.mjs" pruebas-agenticas/pruebas-agenticas.json
node "$pluginRoot/runner/compuerta.mjs" pruebas-agenticas/pruebas-agenticas.json --informe
node "$pluginRoot/runner/tendencia.mjs" pruebas-agenticas/pruebas-agenticas.json
```

En otra instalación, resolver la ruta real del plugin y ajustar `$pluginRoot`. No usar rutas del checkout de otra aplicación. En PowerShell, conservar `$LASTEXITCODE` de cada comando; al invocarlo mediante un proceso externo, `exit $LASTEXITCODE` evita que todos los códigos no cero se conviertan en 1.

`resultados/` queda ignorado por Git y guarda logs, `actual.json`, historial SQLite, propuestas `.nuevo.json` e informe de revisión. La evidencia local no se publica con el código.

La corrida inicial tiene pendientes baseline, aprobación de requisitos/casos y mutaciones. `ejecutar` escribe los resultados pero sale con 1 si falta baseline. `compuerta` sale con 2 si falta baseline; no es un PASS. `--fijar` y `--aceptar` requieren revisión y aprobación humanas según el plugin. Los casos nuevos de Designer y las mutaciones no se agregan automáticamente a la configuración.

Las pruebas UI bloquean escrituras al server real y usan fixtures, salvo humo GET. Se excluye la spec de capturas para preservar imágenes de documentación. No verifican publicación en una TUI real. Las pruebas de teclado y de peers vivos requieren un entorno controlado y autorización explícita para las escrituras.

No agregar `--basetemp` apuntando adentro de este repo: los tests de identidad necesitan carpetas fuera de Git. Tampoco mutar el árbol del servidor en uso; preparar un worktree y un servicio aislado después de revisar y aprobar las mutaciones.
