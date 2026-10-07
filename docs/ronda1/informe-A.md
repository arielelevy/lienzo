# Informe del frente A · carpeta de estado configurable e identidad de la PC

Registro histórico de esta ronda. Los resultados corresponden al código revisado en ese momento.

## Que queda

- **`lienzo/identity.py`** (nuevo, ~195 lineas): `pc_id()`, `pc_info()` y `repo_key(cwd)`, las tres
  firmas exactas del encargo comun.
  - `pc_id`/`pc_info` sobre `<LIENZO_HOME>/peer.json` (`pc_id` de 12 hex, `name` el hostname en
    minusculas, `color` de una paleta fija de 8 colores elegido por `pc_id`). Se crea una sola vez;
    un archivo corrupto o sin `pc_id` valido se regenera sin romper el arranque. Cubierto por
    `test_pc_id_estable_entre_llamadas`, `test_pc_id_se_crea_una_sola_vez`,
    `test_peer_json_corrupto_se_regenera_sin_romper_el_arranque`,
    `test_peer_json_sin_pc_id_tambien_se_regenera`, `test_pc_info_trae_pc_id_nombre_y_color_de_la_paleta`,
    `test_pc_id_estable_entre_procesos`, `test_dos_lienzo_home_distintos_dan_pc_id_distintos` (estas
    dos ultimas son la prueba a mano del punto 6 del encargo, hecha con `subprocess` en vez de a
    mano).
  - `repo_key`: lee `.git/config` con `configparser` (sin `git` por subprocess), con cache por
    `config_path` + mtime. Resuelve worktrees (`.git` archivo → `gitdir:` → `commondir` → el
    `config` compartido). Normaliza `https://`, `https://user:pass@`, `git@host:a/b` (scp-like) y
    `ssh://git@host/a/b` a `host/a/b` en minusculas, sin `.git` final. Sin remote: el nombre de la
    carpeta raiz del repo; sin repo (o sin `cwd`): `state.repo_of(cwd)`. Cubierto por
    `test_repo_key_formas_equivalentes_de_github` (las tres URLs de GitHub del encargo dan la misma
    clave), `test_repo_key_ssh_uri`, `test_repo_key_sin_remote_usa_la_carpeta_raiz`,
    `test_repo_key_carpeta_fuera_de_un_repo`, `test_repo_key_sin_cwd` (el caso `None`),
    `test_repo_key_subcarpeta_del_repo`, `test_repo_key_worktree`,
    `test_repo_key_recalcula_si_cambia_el_config`, y `test_repo_key_del_propio_lienzo` (humo contra
    el `.git/config` real de este repo: da `github.com/arielelevy/lienzo`).

- **`lienzo/state.py`**: `LIENZO = os.environ.get("LIENZO_HOME") or os.path.join(HOME, ".lienzo")`.
  Unica fuente de la ruta para el proceso del server (`sessions.py`, `rules.py`, `server.py` ya la
  toman de `state.LIENZO`, no los toque). Cubierto por `test_state_sin_la_variable_sigue_en_home_lienzo`
  y `test_state_con_la_variable_sale_de_ahi` en `tests/test_home.py`.

- **`lienzo/auth.py`**: ahora importa `state` y usa `LIENZO = state.LIENZO` (auth.py no tenia el
  motivo de hook.py para evitarlo: no corre como subproceso por evento ni tiene que cuidar su
  stdout). Cubierto por `test_auth_sale_de_la_misma_fuente_que_state` y
  `test_auth_sin_la_variable_sigue_en_home_lienzo`.

- **`lienzo/hook.py`**: sigue sin importar `state` (vi por que: corre como subproceso en cada
  evento, tiene que arrancar rapido, y en `PermissionRequest` su stdout es el JSON que Claude Code
  parsea como decision, asi que no puede arrastrar el import mas pesado de `state.py` ni el riesgo
  de que algo de ese modulo imprima algo). Duplique la lectura de `LIENZO_HOME` con un comentario
  que explica por que, mas un `--lienzo-home <ruta>` en el propio `argv` (prioridad sobre la
  variable de entorno) para el punto 3 del encargo: el proceso que dispara el hook no hereda el
  entorno de quien corrio `install.py`. Cubierto por `test_hook_con_la_variable_sale_de_ahi`,
  `test_hook_sin_la_variable_sigue_en_home_lienzo`, `test_hook_prioriza_el_flag_de_argv_sobre_la_variable`.

- **`install.py`**: `LIENZO_HOME = os.environ.get("LIENZO_HOME")` al importar; si estaba definida,
  `cmd()` (Claude/Codex) y `entry()` (CODA, forma exec) le agregan `--lienzo-home <ruta>` al
  comando del hook; si no, quedan exactamente como antes. Probado con `--help` (sin tocar nada) y
  con `monkeypatch.setattr(install, "LIENZO_HOME", ...)` sobre `cmd()`/`entry()` en
  `test_install_le_pasa_el_flag_al_hook_solo_si_la_variable_estaba_definida`: no hay forma de probar
  una instalacion en seco sin agregarle un `--dry-run` que no era mio inventar (anotado en
  `notas-A.md`).

- **`extensions/pi-lienzo.ts`**: `process.env.LIENZO_HOME || join(process.env.USERPROFILE ||
  homedir(), ".lienzo")`, mismo criterio. Corri `extensions/pi-lienzo.test.mjs` (no es mio, no lo
  edite) con `node --experimental-strip-types`: sigue en verde (1 test, ~190 ms). No le agregue un
  caso para `LIENZO_HOME` porque el archivo no es de mi encargo; lo dejo anotado en `notas-A.md`
  como algo que convendria sumar.

## Que medi

- `tests/test_home.py` + `tests/test_identity.py`: 24 tests nuevos, 4,76 s en total (los mas
  lentos son los que arrancan un proceso `python -c` de verdad para probar la estabilidad entre
  procesos: 1,38 s y 1,00 s; el resto son milisegundos). Maquina sin otra tarea pesada corriendo
  (`Get-Process node` antes de medir no mostro nada).
- `repo_key` sobre `D:\Apps\lienzo` (su propio `.git/config`, real): en frio 1,27 ms, **con
  cache 0,037 ms de promedio** (1000 llamadas).
- Corrida completa, `python -m pytest tests -q`: 259 pasan, 1 falla (259 antes hoy eran ~236 en
  el README + lo que sumaron B/C/D en esta misma ronda). El que falla es
  `test_coordinadora_una_por_repo`, ajeno (ver `notas-A.md`), no lo arregle.
- `python -m ruff check` y `python -m black --check` sobre mis archivos exactos: limpios. `black`
  reformateo `identity.py` y `hook.py` solo (convirtio `except (X, Y):` a `except X, Y:`, que es el
  estilo del resto del proyecto en Python 3.14, ver `notas-A.md`).

## Que deje afuera y por que

- `install.py --dry-run`: no existia, y agregar un modo nuevo no era del encargo (que pedia probar
  con lo que hay); anotado.
- Ningun caso nuevo en `extensions/pi-lienzo.test.mjs` para `LIENZO_HOME`: el archivo no esta en mi
  lista de "solo estos".
- `federation.py`, `health.py`, `sessions.py`, `rules.py`, `server.py`: no los toco, son de otros
  frentes o de otra ronda.

## Que vi fuera de mis archivos

Todo en `docs/ronda1/notas-A.md`: el test de `test_server.py` que falla (del frente B, con la
explicacion de por que), y dos respuestas a las dudas que dejo el frente C en su propio
`notas-C.md` (el `OSError` de `subprocess` en Windows y el `except X, Y:`).
