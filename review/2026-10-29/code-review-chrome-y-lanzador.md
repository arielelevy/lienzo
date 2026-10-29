# Revisión: Chrome remoto se reconecta solo y `claude -p` dice quién lo lanzó

Alcance: `web/src/components/RemoteBrowser.tsx`, `lienzo/procs.py` (`launcher_of`, `_tool_name`),
`lienzo/agentes.py` (`claude_cuenta`), `web/src/lanzado-por.ts`, tarjeta y pruebas.

Chrome remoto, modo ventana: una entrada rechazada o sin confirmar ahora suelta lo retenido y cierra el canal.
El canal nuevo arranca con los pendientes ya rechazados: lo que no se confirmó no se reenvía, igual que con el
botón «Reconectar entrada sin reenviar», que se quitó. El reintento usa el mismo contador de `onclose`: tope de 5 y
vuelta a cero con `opened`. Si el mouse falla en cada clic, se reconecta en cada clic; no hay bucle sin entrada del
usuario. El aviso amarillo sigue siendo `role="alert"` y se va a los 40 s o con ×.

Lanzador: sólo para `external.kind == "batch"`. Sube hasta 12 procesos con OpenProcess, sin CIM. La herramienta es el
primer ancestro que no es shell ni intérprete pelado; para `python -m X` es X. La cuenta sale del registro de Claude
Code validado por `procStart`; sin registro único queda en null y no se adivina. La tarjeta lo muestra entre
paréntesis sólo sin `transcript_path`. Con un server anterior sin `launcher` no muestra nada.

Verificación: los 5 tests de `chrome-window-flow.spec.ts` contra el build nuevo, `lanzado-por.test.ts`, los 95 tests
de Python de ejecuciones externas y escritorio, tsc, eslint y ruff, todo en ok. Los 4 tests de `test_install_skill.py`
fallan con WinError 50 y 6 al crear el junction. Ningún archivo de este cambio toca ese módulo.

Sin hallazgos abiertos.
