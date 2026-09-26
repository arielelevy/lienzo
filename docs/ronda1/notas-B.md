# Notas del frente B · lo que vi fuera de mis archivos

## `tests/test_server.py::test_coordinadora_una_por_repo` queda roto (ajeno, pero con arreglo a mano)

Es consecuencia directa de mi cambio (`set_coordinator` y `stopped_recipients` ahora comparan
`repo_key`, plan §3.6, en vez de `repo`). El frente A lo encontro por su lado y lo documento igual
en su `notas-A.md`, con una linea final: "probablemente se resuelve solo cuando B termine de poner
`repo_key` en las sesiones de prueba". No edite `test_server.py` porque no esta en mi lista de
archivos ("Tocás solo los archivos de tu encargo"), pero el arreglo es de una linea por sesion, para
quien integre:

```python
def test_coordinadora_una_por_repo(aislado, con_pid):
    A, B, C = COORD, SID, NEW
    for sid, repo in ((A, "lienzo"), (B, "lienzo"), (C, "otro")):
        s = st.sessions.get(sid) or ses.new_session(sid, "claude", "hook")
        s["repo"] = repo
        s["repo_key"] = repo  # <-- agregar esta linea: antes las tres quedaban con repo_key=None
        st.sessions[sid] = s
```

Con eso el test vuelve a pasar tal cual esta escrito (A y B comparten `repo_key="lienzo"`, C tiene
`repo_key="otro"`), sin tocar la aserciones.

## `server.py::create_rule` no lleva `pc`

La via manual de crear una regla desde la API (`POST /rules`) no le agrega `pc` al dict que arma;
solo la automatica `schedule_continue` de `rules.py` (mia) lo hace. `server.py` no lo toca nadie en
esta ronda (encargo comun). Cuando alguien lo toque, agregar `"pc": identity.pc_id()` al dict de
`create_rule` es simetrico a lo que ya hice en `schedule_continue`.

## `hook.py` (frente A) es quien tendria que agregarle `pc` al pendiente

El encargo comun dice "pendientes nuevos llevan pc". El archivo de pendiente (`~/.lienzo/pending/*.json`,
o el que sea bajo `LIENZO_HOME`) lo escribe `hook.py`, no `sessions.py`: mi `read_pending()` /
`public_pending()` ya pasan cualquier clave extra tal cual (solo sacan `nonce`), asi que en cuanto
`hook.py` le agregue `pc` al escribirlo, se ve solo en `/pending` sin tocar nada de lo mio. Lo dejo
anotado por si al frente A (o a quien siga con `hook.py`) le sirve saber que del lado de
`sessions.py` no hace falta nada mas.

## `model` de CODA: no esta expuesto, se deja en `None`

Revise el esquema que usa `coda.py` (tablas `sessions` y `messages` via sqlite): no hay ninguna
columna con el modelo. El encargo permitia dejarlo en `None` en vez de inventar un acceso nuevo a su
base desde `sessions.py`, asi que elegi eso. Si en algun momento CODA empieza a guardarlo, `model_of`
en `sessions.py` es el unico lugar que haria falta tocar (hoy retorna `None` de entrada para
`agent == "coda"`).
