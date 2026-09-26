# Notas del frente A · lo que vi fuera de mis archivos

## `tests/test_server.py::test_coordinadora_una_por_repo` falla (ajeno)

Con la suite completa (`python -m pytest tests -q`) queda 1 test rojo, y no es mio:

```
tests/test_server.py::test_coordinadora_una_por_repo
AssertionError: assert ['43e4160d-...0000'] == ['599a7e3e-...0001']
```

`lienzo/sessions.py::set_coordinator` (827) ya compara `other.get("repo_key") == s.get("repo_key")`
en vez de `repo` (el frente B ya lo engancho a mi `identity.repo_key`, como decia el encargo comun).
El test arma tres sesiones con `s["repo"] = "lienzo"|"otro"` pero nunca les pone `repo_key`, asi que
las tres quedan con `repo_key` en `None` y la comparacion las trata a todas como del mismo repo. Es
del frente B (dueno de `sessions.py` y de ese test en `test_server.py`); no lo toque. Probablemente
se resuelve solo cuando B termine de poner `repo_key` en las sesiones de prueba.

## Para el frente C: las dos dudas de su `notas-C.md`

- **El `OSError` de `subprocess.run` en `test_home.py`** (`WinError 50`/`WinError 6` segun la
  corrida, siempre en `_make_inheritable` → `_winapi.DuplicateHandle`): es un problema del entorno
  de esta sesion (el proceso no tiene un handle de stdin heredable valido), no de Windows en
  general. Se arregla pasando `stdin=subprocess.DEVNULL` a cada `subprocess.run` que hace
  `capture_output=True`. Ya lo aplique en `test_home.py` y en `test_identity.py`: los dos quedaron
  verdes. Si a `test_federation.py` le pasa lo mismo con su cliente SSE o sus sockets, probablemente
  sea el mismo origen.
- **`except OSError, ValueError:`** (y las otras variantes en `sessions.py`, `rules.py`, etc.): no
  es una rareza de la build, es sintaxis valida de Python 3.14 (PEP 758, "except sin parentesis
  para varios tipos"), equivalente a `except (OSError, ValueError):`. Lo confirme con
  `ast.parse`/`py_compile` sin error, y de yapa `python -m black` reformatea `except (X, Y):` a
  `except X, Y:` solo, asi que es el estilo que el proyecto ya adopto en toda la base con esta
  version de Python. No hace falta tocar nada.

## `install.py` no lo probe con una instalacion real

El encargo pedia `--help` y una instalacion en seco si existe, nunca contra el `settings.json` real.
No hay un modo `--dry-run` en `install.py`, asi que en vez de inventar uno (no era mio agregar
funcionalidad nueva a `install.py` mas alla de `LIENZO_HOME`) probe `cmd()` y `entry()` con
`monkeypatch.setattr(install, "LIENZO_HOME", ...)` en `tests/test_home.py`
(`test_install_le_pasa_el_flag_al_hook_solo_si_la_variable_estaba_definida`), que ejercita la misma
logica sin escribir nada en disco. Si la coordinadora quiere ademas una instalacion en seco real,
haria falta agregar un `--dry-run` a `install.py`, que queda para otra ronda.
