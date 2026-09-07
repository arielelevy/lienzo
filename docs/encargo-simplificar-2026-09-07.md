# Encargo B — Simplificar el código del backend (lienzo/*.py)

Sos una de tres sesiones trabajando en paralelo sobre `D:\Apps\lienzo`. Tu territorio es
**solo `lienzo/*.py`** (y `install.py` si hace falta). No toques `web/`, `tests/`, ni `docs/`
salvo este archivo. Otra sesión está en el front y otra en el pentest: no pises esos archivos.

## Qué hacer

Una pasada de **simplificación** sobre el Python, sin cambiar el comportamiento. El objetivo es
menos código y más legible, no features. Buscá:

- Funciones largas que se puedan partir en piezas con nombre.
- Lógica repetida entre `sessions.py`, `state.py`, `server.py`, `rules.py`, `transcripts.py`
  que salga a un helper compartido (ojo con `short` duplicada, `parse_ts`, el reparto de
  estados corriendo/termino, etc.).
- Condiciones y ramas ilegibles, banderas muertas, comentarios que ya no describen el código.
- Manejo de errores redundante o dobles caminos que hacen lo mismo.

Guiate por el archivo más grande primero: `sessions.py` (~1240 líneas) y `server.py` (~840).
No es refactor por refactor: cada cambio tiene que dejar el archivo más fácil de leer para el
próximo. Si algo está largo pero es claro y tiene una razón escrita, dejalo.

## Reglas de la ronda

- **No commitees, no reinicies el server, no hagas push, no pises `git`.** Yo (la coordinadora)
  verifico, reinicio el server y commiteo. Reiniciar el server matando el proceso equivocado se
  lleva puestos otros Python de la máquina: no lo hagas vos.
- Antes de dar por cerrado, dejá en verde:
  - `python -m pytest tests -q` (97 tests)
  - `python -m ruff check lienzo tests install.py`
  - `python -m black --check lienzo tests install.py`
- Solo biblioteca estándar: no agregues dependencias. Sin `psutil`, sin frameworks.
- Si un cambio toca la forma de un dato que el front consume (`/sessions`, reglas, links),
  **no lo hagas**: eso lo coordino yo con la sesión del front. Quedate en lo interno.

## Cuando termines

Informe corto: qué simplificaste (por archivo), líneas antes/después si es notorio, qué tests
corriste y cómo salieron, y lo que dejaste afuera y por qué. Llega solo a mi consola.
