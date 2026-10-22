# Code review — encargo P (2026-10-22)

Skill `code-review` (nivel high) sobre el delta de P: `lienzo/browser_window.py`, `lienzo/browser_host.mjs`,
`web/src/components/RemoteBrowser.tsx`, `web/src/remote-browser.css`, `tests/test_browser_window.py`,
`tests/browser_host.test.mjs`, `tests/fixtures/browser_host_socket.mjs`, `web/tests-ui/chrome-lock.spec.ts`,
`web/tests-ui/chrome-profiles.spec.ts`. Diez hallazgos.

| # | Hallazgo | Decisión | Prueba (rojo antes) |
|---|---|---|---|
| 1 | `profile_label` no nombra el perfil Default: su AppUserModelID es «Chrome» a secas | Corregido: con id «Chrome» manda `--profile-directory` del comando de relanzado, salvo que traiga `--user-data-dir` | `test_profile_label_from_the_window_app_id[Chrome-…Default-Persona]` y `[…--user-data-dir…]` |
| 2 | `locked()` toma como bloqueo cualquier `OpenInputDesktop` negado: un contexto sin ese permiso dejaba la vista quieta para siempre | Corregido: sin escritorio legible, bloqueo sólo si no hay ventana al frente o está LockApp. «Winlogon» (UAC/contraseña) sigue contando: ahí Windows tampoco deja capturar ni mandar entrada | `test_locked_reads_…[None-Chrome_WidgetWin_1…-False]` |
| 3 | `run_lock` muere con `ValueError` al escribir en stdout cerrado | Corregido: termina en silencio con `OSError` o `ValueError` | `test_lock_thread_ends_quietly_when_the_output_is_closed` (antes colgaba) |
| 4 | `LockWatch` lo tocan tres hilos sin candado | Corregido: `lock_mutex` alrededor de `update`/`force` y del aviso | Sin prueba propia (carrera); cubierta por las de bloqueo |
| 5 | La unión contexto→perfil por título puede tomar el perfil del Chrome de la persona para el Chrome aislado de Lienzo; y no se reintenta si cambian títulos | Corregido: sólo se aprende con `mode === 'existing'`; con contextos sin nombre se vuelve a pedir la lista cuando cambian los títulos | `chrome-profiles.spec.ts` «con el Chrome propio de Lienzo…» |
| 6 | `profile()` lee y parsea Local State una vez por ventana; COM se inicia en cada llamada | Corregido: una lectura por lista; COM una vez por hilo | `test_windows_list_says_the_profile_…` (cuenta lecturas) |
| 7 | `run_lock` mira el bloqueo sin ventana abierta y usa `time.sleep` fijo | Corregido: sólo con ventana (también en pausa: el visor en espera necesita el desbloqueo), con el `sleep` inyectado | `test_lock_thread_does_not_look_without_a_window` (antes colgaba) |
| 8 | Con BGRA crudo se compara el byte alfa, que GDI podría dejar indefinido | No se cambia: medido en esta PC, alfa constante 255 en las dos rutas (BitBlt en pantalla y PrintWindow tapada), 5 capturas cada una. Un cambio de ruta costaría a lo sumo un juego de parches | Medición en el informe |
| 9 | Si la persona vuelve a la ventana completa durante el bloqueo, la imagen queda quieta sin aviso | Corregido: aviso «X sigue bloqueada: la imagen queda quieta y la entrada no llega hasta desbloquearla» | `chrome-lock.spec.ts` tercera prueba |
| 10 | La preferencia de pestaña (la activa al bloquearse) queda guardada y vuelve a elegirse mucho después | Corregido: se usa una sola vez | Sin prueba propia (depende de cerrar pestañas después); cambio de tres líneas |

Rojo de los arreglos de Python: 3 fallas y 2 cuelgues con el código previo a la revisión; verde después
(`tests/test_browser_window.py`: 83 pasan). UI: 3 rojas contra el build previo a la revisión; después 114 de 114
(57 pruebas de Chrome × 2 repeticiones) contra el build nuevo.

Intermitencia propia encontrada y corregida en la prueba: «al bloquearse… vuelve a la ventana» exigía que `resume`
fuera el último mensaje, pero al volver a verse el visor manda su tamaño después; ahora busca `resume` después del
desbloqueo.
