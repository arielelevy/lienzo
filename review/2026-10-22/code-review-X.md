# Revisión X — V-1, V-2 y V-3

Sesión: `01a16589-246e-7362-b71f-428f4a70f7dc` (pid 17148). Fecha: 2026-10-22.
Alcance autorizado: delta del encargo X; decisiones 17/18 para investigación y pedido P de cambio por bloqueo, con unión de identidad aprobada expresamente por Ariel durante este encargo. V-4/V-5, Q y U quedan fuera.

## Cambios revisados

- `optimization_scheduler.py`: el lock de cola ordena cancelación aceptada y reserva irreversible de publicación. Una cancelación aceptada antes de esa reserva impide llamar a `record`. Durante la publicación se rechaza cancelar explícitamente; el contraste corre fuera del lock y la consulta de cola responde. La reserva se libera al persistir el resultado, incluso si el registro falla.
- `research_creencias.py`: «sostenida» exige coincidencia concluyente, evidencia independiente `humana`, `listo_para_revision is True` y ausencia de objeciones. Conserva ambos campos del contrato. Contradicción mantiene precedencia. No modifica veredictos humanos ni vigencia.
- `browser_stream.py`: adjunta identidad al aviso de bloqueo desde la PC dueña. Lee HWND/PID/rectángulos en un subproceso propio y breve, con `stdin=DEVNULL`, timeout y sin ventana de consola. Relee el catálogo tras CDP; si cambia el HWND o su geometría, pausa. No usa títulos. No modifica el modo DPI del server.
- `browser_host.mjs`: une PID browser de SystemInfo y rectángulo único nativo/CDP; exige un único target visible con contexto. Revalida target/contexto/windowId antes de devolverlo. Las sesiones temporales de lectura no limpian emulación ni activan páginas y se sueltan en `finally`.
- `RemoteBrowser.tsx`: selecciona por target/contexto sólo si corresponde al HWND visto. Ausencia o pérdida de identidad deja cero pestañas seleccionadas y pide elegir; no captura ni envía entrada a una cuenta elegida por título. Conserva la vuelta automática al desbloquear y el modo elegido por la persona.

## Hallazgos de la revisión y correcciones

1. Instanciar `browser_window.Windows()` dentro del servidor cambiaba el modo DPI del proceso y fallaba al repetir la inicialización. Corregido: lectura en subproceso propio por consulta; no se edita `browser_window.py`.
2. Usar `page()` para leer visibilidad podía limpiar el viewport de otro visor al adjuntar una página. Corregido: sesión CDP temporal de sólo lectura, sin `Emulation.*` ni `Input.*`; prueba explícita sobre el trace.
3. Cambio de selección nativa o geometría durante la consulta. Corregido: relectura del catálogo y comprobación de HWND, con dos regresiones unitarias.
4. Validación de `job` al cancelar: se conserva error de validación explícito antes de consultar el conjunto de publicaciones.

No quedan P1/P2 confirmados en el delta revisado estáticamente. Esto no acredita uso real ni ausencia de otros defectos.

## Evidencia y límites actuales

En `.temp/resultados/2026-10-22-X/`: rojo previo Python y host, logs verdes, artefactos de los cinco roles y comandos del runner. El primer intento Python dentro del sandbox falló por `PermissionError: [WinError 5]`; el primer intento Node por `Error: spawn EPERM`. Se repitieron con aprobación de ejecución y temporales propios. Esos errores de entorno no se cuentan como rojo funcional.

Rojo funcional: V-1 llamó a `record` después de cancelar y aceptó cancelar durante publicación; V-2 devolvió sostenida sin evidencia; V-3 no resolvía identidad por proceso/ventana.

Runner focal final: **74 unitarias Python y 10 casos host de identidad**, todos con código 0. Además, antes de agregar las dos carreras finales de identidad, ejecución directa del archivo completo de host: 47 casos con código 0. **5 recorridos Playwright** con un worker contra las fuentes servidas por Vite 7364 y API/WebSocket fijos: ambigüedad sin selección ni entrada, elección manual del segundo perfil, selección automática de identidad comprobada pese a título repetido, retorno al desbloquear y respeto del modo manual. Ruff, ESLint y TypeScript focales: código 0.

La primera corrida UI tuvo 4 casos aprobados y un error de cierre de traza: `browserContext.close: ENOENT: no such file or directory` en `web/node_modules/.playwright-artifacts`. Al buscar el `error-context.md` indicado ya no existía. Esa carpeta es compartida por las sesiones; la causa compatible con la evidencia es una eliminación concurrente de artefactos, no una aserción fallida de la app. Se conservó `ui.log`. Una nueva corrida con `--output` y `TEMP`/`TMP` exclusivos de X fuera del repo pasó los 5 casos; `ui-isolated.log` y `ui-command.json` conservan salida, argv, entorno, tiempos y código. No se cambió el caso ni la app para volverlo verde.

La compuerta devuelve **2 por falta de baseline**; el runner devuelve 1 por esa referencia ausente aunque sus dos casos devuelven 0. No se fijó baseline ni se ejecutaron/aprobaron mutaciones. Los `.nuevo.json` no están aceptados por una persona. No equivale a PASS de aceptación.

Implementado y probado localmente con fixtures. **Sin verificación en uso remoto real ni unión contra Chrome/Win32 real**; no se bloqueó la PC física. Se respetó la pausa de OpenSyync y luego se usaron los turnos navegador → build → suite, de a uno, liberados al terminar. El Vite propio se cerró tras verificar puerto 7364 y comando del proceso. No se reinició ni desplegó el server 7321 y no se escribió en Git. La suite global corresponde a la coordinadora.

## Cinco roles de pruebas agénticas

Trabajo secuencial en esta sesión, sin hijos. `agenticas/roles.json` registra revalidación y ejecución con tiempos reales, argv, códigos y logs. Explorer reconstruyó los estados por lectura y luego se recorrió la UI real con estado remoto fijo. Analyser cruzó V-1/V-2/V-3 con el contrato del motor y la unión aprobada por Ariel. Designer reutilizó los casos vigentes, corrigió el oráculo defectuoso de «sostenida» y agregó los bordes de cancelación e identidad, con propuestas sin aceptar. Executor conservó rojo y verde y lanzó el runner focal sin fijar referencias. Detective distinguió los fallos funcionales de los errores de sandbox/traza y mantuvo el código 2 real de la compuerta. Sin medición de mutación ni afirmación de cobertura total.

## Archivos del delta

`lienzo/optimization_scheduler.py`, `lienzo/research_creencias.py`, `lienzo/browser_stream.py`, `lienzo/browser_host.mjs`, `web/src/components/RemoteBrowser.tsx`, `tests/test_optimization_cancel_races.py`, `tests/test_research_creencias.py`, `tests/test_browser_lock_identity.py`, `tests/browser_host.test.mjs`, `tests/fixtures/browser_host_socket.mjs`, `web/tests-ui/chrome-lock.spec.ts`, `review/2026-10-22/code-review-X.md`.
