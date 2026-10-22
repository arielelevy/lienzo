# Revisión del encargo Y — 2026-10-22

Alcance: delta propio de nombre nativo de Claude, título de ventanas CODA/Codex/Kiro, cuotas mensuales de Kiro y documentación del canal de respaldo. Revisión estática con el skill `code-review`, realizada por Codex `pid-26256` en la misma sesión. No es una revisión independiente ni de los cambios de otros frentes.

## Resultado

Sin P1/P2 pendientes identificados en el delta revisado. TypeScript, Ruff y ESLint pasaron con código 0. Los nueve casos UI pasaron en 13.7 s y se revisaron las capturas de 1440/390 px. No se declara aprobación de release ni PASS de la compuerta.

## Cambios revisados

- `lienzo/native_follow.py`: sólo títulos `user`, Claude vivo y quieto (`termino`), sin diálogo, marca externa, detención ni `typing`. Un intento por nombre/PID/inicio. Se vuelve a comprobar identidad y título antes de ejecutar. Un trabajo viejo no pisa un título nuevo. Los errores quedan visibles en `native_sync_error`.
- `lienzo/console_titles.py`: ya no se cachea un éxito; se relee cada ciclo de 30 s, conservando la supresión de fallos repetidos. `console_title.py` se revisó y se probó en Windows sin modificarlo: compara `GetConsoleTitleW` antes de `SetConsoleTitleW`. Tmux también compara el título antes de renombrar. No se envían teclas para cambiar títulos de ventanas.
- `lienzo/sessions.py`: integración en `liveness_pass`, reserva de `nombrar_nativo` compartida por pedidos manuales/automáticos y rechazo temporal de `/send` durante la operación. Se conserva el envío existente de `/rename` y `/remote-control`; se vuelve a comprobar que no haya empezado un turno entre ambos comandos. Cambios mínimos sobre un archivo compartido; no se tocó `hooks_eventos.py` ni `server.py`.
- `lienzo/kiro_quota.py`: `initialize` debe terminar antes de `_kiro/account/getUsage`. No se envía `session/new`, `session/prompt` ni autorización de herramientas. La cuenta la autentica la CLI instalada. No se leen ni persisten tokens. Se rechazan pedidos inversos del servidor. Plazo único de lectura, proceso propio sin ventana y limpieza de su árbol en `finally`.
- `lienzo/cuotas.py`: Kiro comparte caché y lector paralelo, conserva desconocidos como `null` y queda fuera de la comparación semanal Claude/Codex. No se interpreta el contador de créditos del turno o la sesión como consumo mensual.
- `web/src/api.ts`, `web/src/components/Cuotas.tsx`, `web/src/cuotas.css`: fila de Kiro, créditos usados/disponibles, mensajes y renovación explícitamente desconocidos cuando faltan. Botones y nombre accesible. Contenedor con salto de línea en pantallas angostas. El contrato admite un servidor anterior sin `kiro` y lo explica.
- `web/src/components/Card.tsx`: se retiró únicamente el segundo `/native` después del PUT del título. El servidor concentra el seguimiento y evita duplicarlo con la UI.
- `skills/lienzo/SKILL.md`: nombre que sigue al título y canal nativo como respaldo cuando Lienzo no puede escribir a la tarjeta, según el agregado explícito de Ariel.

## Hallazgos corregidos durante la revisión

1. Reserva sólo automática: un `/native` manual podía superponerse. `nombrar_nativo` ahora reserva la consola para ambos caminos. Reproducción roja y corrección verde en `tests/test_native_follow.py::test_manual_native_does_not_overlap_automatic`; log rojo en `.temp/resultados/2026-10-22-Y/native-race-red.log`.
2. El navegador mandaba `/native` inmediatamente tras cambiar título: duplicaba el seguimiento nuevo del servidor. Se retiró ese envío de `useRename`.
3. Final de sincronización sin publicar el cambio de ocupado: se publica el estado al salir, aun con error.
4. Cachear un éxito impedía reparar «CODA» cuando el agente pisaba el título sin cambiar la tarjeta. Tres reproducciones rojas (CODA, Codex, Kiro), luego verdes. Se mantiene la escritura condicional del helper Windows y se agrega comparación en tmux.
5. Incluir la lectura de Kiro en los lanzamientos podía agregar espera ajena a Claude/Codex. Los lanzamientos y la precarga consultan sólo sus ventanas semanales; `GET /cuotas` conserva los tres lectores. Rojo en `kiro-launch-red.log`, luego verde.
6. La sesión puede estar quieta pero con un borrador marcado como `typing`: se difiere también en ese estado y se vuelve a comprobar antes de cada comando nativo. Rojo en `native-typing-red.log`, luego verde.
7. Fixture UI: el patrón `**/cuotas*` devolvía JSON también para el nuevo `cuotas.css`, impidiendo cargar la aplicación. Se acotó a `url.pathname === '/cuotas'`. El caso de renombrar registra su interceptación después del bloqueo general de escrituras. Se conservaron los fallos iniciales; no se alteraron expectativas ni baselines.
8. Si un turno empieza entre despacho y envío, el rechazo por ocupado no debe consumir el cambio de nombre pendiente. El 409 `native_deferred` conserva ese cambio para cuando quede quieta. Rojo en `native-defer-red.log`, luego verde.

## Evidencia local

`114 passed in 5.04s` con `test_console_titles.py`, `test_native_follow.py`, `test_kiro_quota.py`, `test_cuotas_cuenta.py` y `test_launch.py`. Incluye la exclusión real entre dos hilos de `/native` y el aplazamiento si arranca otro turno durante el despacho. Log crudo: `.temp/resultados/2026-10-22-Y/unit-final.log`.

Ruff sobre las rutas Python propias y el helper revisado: salida `All checks passed!`, código 0. ESLint sobre `api.ts`, `Cuotas.tsx`, el cambio de `Card.tsx` y `cuotas.spec.ts`: código 0.

`node node_modules/typescript/bin/tsc --noEmit --pretty false`, desde `web`: código 0, sin salida. Se tomó y liberó `build` antes de pedir `navegador`.

Playwright, `cuotas.spec.ts`, un worker, Vite propio en `127.0.0.1:7462`: `9 passed (13.7s)`. UI real sobre código fuente con APIs interceptadas, no medición de saldo mediante el servidor productivo. Verifica tres agentes, lectura ausente, caché, refresco manual, lanzamientos, nombres accesibles, Kiro mensual a 1440/390 px sin desborde del indicador y PUT del título sin duplicar `/native`. Las capturas se inspeccionaron visualmente. Log: `.temp/resultados/2026-10-22-Y/ui-final.log`; capturas: su subcarpeta `playwright/`. Vite detenido y turno `navegador` liberado a W.

Lectura real ACP sin inferencia: KIRO PRO, 130.37 usados / 1000, 869.63 disponibles, renovación 2026-11-01, mensajes `null`. El primer intento dentro del sandbox falló; fuera del sandbox la consulta devolvió esos datos. El saldo es una medición de ese momento, no un valor fijo del producto.

Ventana CODA real existente, PID 32212: antes «CODA»; después «opensyync | encargo H - integrar THREAT_MAP_VERSION 3 en web_api». Primera aplicación `changed: true`; segunda `changed: false`. Sin sesión nueva, prompt ni inferencia. Evidencia: `console-real.json`. No se forzó otro turno del modelo para volver a pisarla.

## Límites reales

- Sin reinicio ni despliegue: el 7321 aún no contiene el seguimiento nuevo. No se afirma haber verificado el cambio automático en las coordinadoras reales `607da9a5` y `56cfac40` ni visibilidad cruzada entre PCs.
- El saldo se obtiene por una extensión ACP interna de la CLI instalada; un cambio de contrato se informa como lectura fallida, sin inventar números.
- Sin baselines nuevos, aceptación de casos ni mutaciones sobre este árbol compartido. Las propuestas de cinco roles están en `.temp/resultados/2026-10-22-Y/`.
- La compuerta del plugin devolvió código 1 porque no existe `actual.json` en la carpeta aislada de Y; no es un PASS. Las unitarias directas están registradas por separado.

## Archivos propios

`lienzo/native_follow.py`, `lienzo/console_titles.py`, `lienzo/kiro_quota.py`, `lienzo/cuotas.py`, delta acotado de `lienzo/sessions.py`, `tests/test_console_titles.py`, `tests/test_native_follow.py`, `tests/test_kiro_quota.py`, `web/src/api.ts`, `web/src/components/Cuotas.tsx`, delta acotado de `web/src/components/Card.tsx`, `web/src/cuotas.css`, `web/tests-ui/cuotas.spec.ts`, `skills/lienzo/SKILL.md`, este informe.

ESTADO: listo para commit
