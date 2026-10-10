# Conocimiento por proyecto

Parte de la skill `lienzo` (se lee desde `SKILL.md` cuando hace falta).

## Conocimiento por proyecto (inventario, veredictos, aprendizaje y panel)

**Lo que pasa por el lienzo queda solo** (pedido de Ariel, 2026-10-09; anexo A de v5): proyecto =
carpeta. La primera vez que el lienzo ve una sesión en una carpeta, crea su proyecto (raíz del repo;
para un worktree, la del repo principal; sin repo, la carpeta) y la sesión. Desde ahí cada pedido,
respuesta final, envío (`send`, del tablero o de otra sesión, con su `de`), disparo de regla `on_stop`
y aviso automático queda como captura `observado`, con sesión, agente, modelo, PC y hora. Una
respuesta final con bloque ```` ```conocimiento ```` se incorpora igual que una entrega; si la sesión
tiene un único encargo `enviado`, queda entregado como su revisión siguiente, y una entrega explícita
posterior con el mismo texto devuelve ese informe (no duplica). **No hace falta llamar a
`proyecto`, `abrir_ronda`, `encargo`, `encargo_enviado` ni `entregar` para que algo quede**: siguen
sirviendo para nombrar el proyecto, agrupar en rondas y dejar el encargo explícito. Para conocer el
id antes de la primera captura: `c.proyecto_carpeta(cwd)`. Para leer: `c.capturas(pid, clase=...)`,
`c.prosa(pid, "consulta")`, `c.preguntar(pid, [...], prosa=True)` (la prosa vuelve aparte, marcada
«prosa, no declarado»). No se guardan adjuntos, secretos con forma conocida (se tapan) ni carpetas
temporales. Texto con U+FFFD o mojibake se rechaza al entregar o declarar, con línea y columna;
`c.texto_roto(pid)` mide y `c.reparar_texto(pid, aplicar=True)` repara el mojibake por auditoría.
**Desde cualquier terminal**, el agente que trabaja (Claude, Codex, coda, Pi) consulta la memoria de su
carpeta con `py <skill>/memoria.py` (briefing), `memoria.py "consulta"` (búsqueda, la prosa aparte),
`--archivo ruta`, `--tema t`, `--por-que <id>`, `--capturas`: sólo lee, texto con ids citables.
**Entre PCs** la memoria se replica sola cada 120 s por el canal firmado (proyectos unidos por
remote); `c.replicar(pc)` la fuerza y `c.estado_replica(pid)` muestra choques y duplicados, que se
resuelven con un veredicto. Con la réplica andando, `encargo_enviado` acepta una tarjeta de la otra PC.
Otras consultas del plan v5: `c.por_que(pid, alternativa)`, `c.briefing(pid, encargos=[...],
markdown=True)`, `c.reincorporar(pid, informe)`, `c.evidencia(...)`, `c.respaldar(pid)`.

El lienzo guarda, en una base por instancia (`~/.lienzo/conocimiento.sqlite`, privada, fuera de los repos)
con el proyecto como dimensión, y con los cuerpos en `~/.lienzo/proyectos/<proyecto>/`,
las rondas, los encargos tal como se mandaron, los informes tal como se entregaron (con hash y
revisión) y lo que el server observa de las sesiones que trabajan un encargo: cuándo cierran, qué
permiso les denegaron, qué error de API cortó un turno, si murieron a medias. Es una base SQLite con búsqueda BM25 (FTS5) y un grafo
de nodos tipados con estado (hallazgo, decisión, alternativa, incidente, regla, medición, pregunta,
tema, evidencia) que recorre con CTE. El diseño completo está en
`docs/propuesta-memoria-2026-10-08/v5.md`; lo de abajo es lo que ya existe.

El proyecto es la unidad: no la PC ni la ronda. Tiene identidad propia porque `repo_key` cambia si
una PC tiene remote y la otra no. Se registra una vez con sus remotes y carpetas:

```python
c.proyecto(
    "teorema",
    "Teorema",
    remotes=["github.com/arielelevy/teorema"],
    carpetas=[{"pc": "<pc_id>", "cwd": "D:/Apps/Teorema"}],
)
c.proyecto_de(s)  # -> "teorema" o None, por el repo_key o la carpeta de la tarjeta
```

Una ronda se abre antes de repartir y cada encargo la cita. Después de lanzar o mandar, se vincula
la tarjeta; al leer el informe del frente, se entrega entero:

```python
r = c.abrir_ronda("teorema", "ronda 4: halving racional")
e = c.encargo("teorema", r["id"], "A", texto_del_encargo, archivos=["codigo/sustituciones.py"])
s = c.lanzar_y_titular(None, "D:/Apps/Teorema", "Teorema - encargo A - ...", agent="codex")
c.encargo_enviado(
    "teorema", e["id"], s
)  # pendiente -> enviado; desde acá el server observa la sesión (una tarjeta de otra PC vale si la memoria ya se replicó con esa PC; si no, 409)
...  # llega el aviso on_stop
c.entregar("teorema", e["id"], c.informe(s))  # informe r1 con hash; el encargo pasa a entregado
c.cerrar_ronda("teorema", r["id"])
c.conocimiento("teorema")  # resumen: nodos por tipo y estado, rondas
c.conocimiento("teorema", "halving OR mitad", saltos=1)  # BM25 + vecinos por el grafo
```

### El bloque `conocimiento` del informe (etapa 2)

Lo que un frente aprendió se declara, no se adivina de la prosa: el informe termina con un bloque
```` ```conocimiento ```` con JSON (`version: 1`, `nodos`, `vinculos`). Al entregarlo, el server lo
valida entero (ids locales únicos, tipos declarables de hallazgo a evidencia, campos obligatorios por
tipo, relaciones del frente: `motivada_por`, `elige`, `descarta`, `derivada_de`, `aplica_a`, `sobre`,
`apoya`; extremos por id local o `nodo:<id>` del proyecto) y lo incorpora en la misma transacción:
cada nodo nace con el estado inicial de su tipo, en la ronda del encargo, `declarado_en` el informe,
y los hallazgos `encontrado_por` la sesión que trabajó el encargo. Con un solo error no entra nada:
el informe queda igual y `datos.conocimiento` dice `pendiente_de_vincular` con los errores por
posición (`nodo h1`, `vinculos[2]`); la corrección es una revisión nueva. Reenviar el mismo informe
devuelve los ids ya creados.

El texto que se le pega al frente en el encargo, con la plantilla y las reglas, es
`coordinar.INSTRUCCION_CONOCIMIENTO`. Si el encargo cita nodos existentes (un incidente, un tema),
pasarle sus ids para que use `nodo:<id>`.

```python
inf = c.entregar("teorema", e["id"], c.informe(s))
inf["datos"].get("conocimiento")   # {"estado": "incorporado", "ids": {"h1": "...", ...}} o los errores
```

`coordinar.veredicto` aplica una lista atómica de cambios, con revisión, evidencia y motivo.
`cerrar_ronda` acepta veredictos y `sin_resolver`; todo el cierre es transaccional.
`pendientes_memoria` evita confundir los pendientes de conocimiento con los permisos de `pendientes()`.
`briefing`, `preguntar` (offset/limite) y `vista` recuperan conocimiento con IDs citables.
`preparar_encargo` agrega el briefing y la plantilla JSON al texto para el frente.
`recurrencia`, `cuestionar`, `avisos`, `dependencias` y `lecciones` exponen el aprendizaje operativo.
El menú ⋯ → Memoria consulta las mismas rutas, sin escrituras automáticas.

Cada PC tiene su base y se replican entre sí (ver arriba y el anexo C de v5).
Nada pasa a `vigente` ni `confirmado` sin un veredicto; lo que entra por el server o por un bloque
queda `propuesto` u `observado`.
