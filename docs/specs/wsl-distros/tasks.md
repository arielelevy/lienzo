# Tareas: Descubrir y direccionar varias distros de WSL

- [x] 1. Prefijo por distro en los comandos de tmux
  - En `lienzo/tmux.py`: nuevo `_argv(distro=None)` (nativo `[]`; via WSL `["wsl.exe"]`; con distro `["wsl.exe", "-d", distro]`); `_PREFIX` queda como default (distro None). `_tmux`, `send`, `screen`, `list_panes`, `pane_pid`, `target_valid`, `pid_alive`, `cmdline`, `comm`, `proc_cwd` y `all_agents` ganan parámetro `distro=None` y arman el argv con `_argv`. Sin distro, argv idéntico al de hoy. Prueba: argv exacto en los tres casos (`tmux ...`, `wsl.exe tmux ...`, `wsl.exe -d X tmux ...`) para send/ screen/ list_panes, y plataforma no-win32 sin código activo.
  - _Requisitos: 3.1, 3.2, 5.1, 5.2_
  - _Archivos: lienzo/tmux.py, tests/test_tmux_distros.py_

- [x] 2. Descubrir las distros (`distros()` con caché TTL)
  - En `lienzo/tmux.py`: nuevo `distros()` que corre `["wsl.exe", "-l", "-q"]` directo (sin `_PREFIX` delante) por `subproc.correr` (timeout 15 s, nunca levanta); re-decodifica UTF-16-le si el texto trae `\x00`; descarta líneas vacías y el placeholder «Windows Subsystem for Linux»; caché en memoria `{"ts", "vals"}` con `DISTROS_TTL_S = 60.0` y lock; nuevo `invalidar_distros()`. En Mac/Linux devuelve `[]` sin llamar a `wsl.exe`. Prueba: parseo UTF-16, salida vacía, binario ausente, error sin levantar, plataforma no-win32 sin llamadas, caché (dos consultas → una llamada; TTL vencido → re-parsea).
  - _Requisitos: 1.1, 1.2, 1.3, 1.4_
  - _Archivos: lienzo/tmux.py, tests/test_tmux_distros.py_

- [x] 3. Unir los panes de todas las distros
  - En `lienzo/tmux.py`: nuevo `list_panes_todas()`: consulta `distros()`; con 0 o 1 distro llama `list_panes()` directo (camino de hoy, en serie); con más de una, un hilo por distro (misma forma que `fan_out`) y une los resultados. Una distro que falla o no corre devuelve `[]` y no corta a las demás (rc != 0 por `subproc.correr`, sin excepción). Prueba: unión de dos distros, distro que falla salteada sin excepción, una sola distro con argv de hoy.
  - _Requisitos: 3.3, 3.4_
  - _Archivos: lienzo/tmux.py, tests/test_tmux_distros.py_
  - _Depende de: 2_

- [x] 4. Home UNC por distro para las transcripciones
  - En `lienzo/tmux.py`: `wsl_unc_home(distro=None)` deja de ser `lru_cache(1)` y pasa a cachear por distro (dict `{distro: home_unc}` con lock): mismo comando actual (`bash -lc 'printf ...'`) pero con `-d <distro>` cuando se pide una. La llamada sin argumento conserva el comportamiento actual (`agentes.py:332` no cambia). Si la distro no contesta, None. Prueba: `wsl_unc_home("otra-distro")` arma el argv con `-d` y resuelve la home de esa distro; sin argumento, argv de hoy; caché por distro.
  - _Requisitos: 3.6_
  - _Archivos: lienzo/tmux.py, tests/test_tmux_distros.py_
  - _Depende de: 1_

- [x] 5. Barrido etiquetado con la distro (`backend.py`)
  - En `lienzo/backend.py`: `proc_key` pasa de `(is_tmux, pid)` a `(is_tmux, d.get("distro") or "", pid)`; `_tmux_sweep` usa `list_panes_todas()` y agrega `"distro"` a cada agente (siempre, también la default); los sueltos: con una sola distro `all_agents()` de esa distro (camino de hoy), con más de una por distro etiquetando cada resultado; `alive` y los validadores pasan `d.get("distro")` hacia tmux. Actualizar la prueba existente de colisión de `proc_key` (tupla de 3). Prueba: fixtures de dos distros → cada tarjeta con su `distro`, también la default; win32 y tmux nativo sin `distro`.
  - _Requisitos: 2.1, 2.2, 2.3, 3.3_
  - _Archivos: lienzo/backend.py, tests/test_backend_tmux.py_
  - _Depende de: 3_

- [x] 6. Escribir y capturar con la distro de la tarjeta (`sessions.py`)
  - En `lienzo/sessions.py`: `compose_send`/`run_send` pasan `distro=s.get("distro")` a `tmux.send` (junto al `wsl` que ya calculan en `sessions.py:2545`); igual la lectura de pantalla con `tmux.screen`. El mensaje con adjuntos sigue traduciendo rutas con `ruta_wsl` (ahora la tarjeta trae su distro). Prueba: send a tarjeta con `distro` argv con `-d`; a tarjeta sin `distro`, argv de hoy; adjunto a agente de WSL con ruta traducida.
  - _Requisitos: 3.1, 3.5_
  - _Archivos: lienzo/sessions.py, tests/test_tmux_distros.py_
  - _Depende de: 1_

- [x] 7. `/health` trae `distros_wsl`
  - En `lienzo/server.py` (rama health de `Handler.do_GET`): agregar `"distros_wsl": tmux.distros()` en Windows con WSL; `[]` en otro caso. La ruta sigue autenticada como el resto de health. Prueba: health autenticado trae la lista parseada; con plataforma no-win32, `[]`.
  - _Requisitos: 1.1, 1.3_
  - _Archivos: lienzo/server.py, tests/test_health.py_
  - _Depende de: 2_

- [x] 8. Lanzar eligiendo la distro (`server.py` + `launch.py`)
  - En `lienzo/server.py` (`accion_launch`): aceptar `distro` opcional en el body; SI viene y no está en `tmux.distros()` (re-parseando con `invalidar_distros()` ante verdad vencida) → 400 `{"error": "distro desconocida: <distro>"}` sin crear tarjeta; SI no viene → distro default (hoy). En `lienzo/launch.py`: con `distro` en Windows, spawn por `_launch_tmux` con argv prefijado `["wsl.exe", "-d", distro]` y `cwd` traducido con `ruta_wsl`; la tarjeta nace con `distro` y queda direccionada a esa distro desde el nacimiento. Prueba: launch con distro válida (argv `-d`, tarjeta con `distro`), con distro desconocida (400, sin tarjeta), sin distro (argv de hoy).
  - _Requisitos: 4.1, 4.2, 4.4_
  - _Archivos: lienzo/server.py, lienzo/launch.py, tests/test_tmux_distros.py_
  - _Depende de: 2, 5_

- [x] 9. UI: etiqueta de distro en la tarjeta
  - En `web/src/types.ts`: `distro?: string` en el tipo de sesión. En `web/src/components/Card.tsx`: junto al indicador de backend tmux, etiqueta discreta con `s.distro` (solo si viene; tarjetas win32 y tmux nativo sin etiqueta). Verificación: `npm run build` y `npm run lint` en `web/` pasan.
  - _Requisitos: 2.4, 2.3_
  - _Archivos: web/src/types.ts, web/src/components/Card.tsx_
  - _Depende de: 5_

- [x] 10. UI: selector de distro en el diálogo de lanzamiento
  - En `web/src/components/Launch.tsx`: leer `distros_wsl` de la salud de la PC elegida (`peers[].health`, ya viaja por `GET /peers`); visible solo si hay más de una, con la default preseleccionada; con una sola, sin selector. El `POST /sessions/launch` incluye `distro` solo si el selector está visible. Verificación: `npm run build` y `npm run lint` en `web/` pasan.
  - _Requisitos: 4.3_
  - _Archivos: web/src/types.ts, web/src/components/Launch.tsx_
  - _Depende de: 7, 8, 9_

- [x] 11. Comprobación final de la spec
  - Correr la batería completa: `py -3.14 -m pytest tests -q` (todas las existentes sin cambios + las nuevas), `py -3.14 -m ruff check .`, y en `web/` `npm run build`, `npm run lint` y las unitarias TypeScript (`node --test`). Con el server andando, el recorrido Playwright (`npm run test:ui`) de tarjeta con distro y del diálogo con selector.
  - _Requisitos: 5.1, 5.2, 5.3_
  - _Archivos: ninguna (solo corre pruebas y verificaciones)_
  - _Depende de: 9, 10_
