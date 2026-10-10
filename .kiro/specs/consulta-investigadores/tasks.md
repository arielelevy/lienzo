# Tareas: consulta entre investigadores

- [ ] 1. Motor: abrir, guardar y la vuelta 1
  - `lienzo/consulta.py` nuevo: modelo de datos, `cargar`, `abrir` con las validaciones (1.2, 1.3), guardado
    atómico en `~/.lienzo/consultas/<id>/`, pedido de la vuelta 1 con marca, enfoque y reglas (no editar),
    envío en paralelo por `consulta.enviar`, `tope_turnos`, `listar`, `ver`, `de_tarjeta`, `cancelar`.
  - _Requisitos: 1.1, 1.2, 1.3, 2.4, 2.5, 3.5, 6.1_
  - _Archivos: lienzo/consulta.py, tests/test_consulta.py_

- [ ] 2. Motor: respuestas, vueltas, síntesis, revisión y cierre
  - En `lienzo/consulta.py`: `turno_cerrado` y la función idempotente que toma una respuesta (marca en
    `last_prompt` o en el `mensaje.md` del adjunto), avance de vuelta con las respuestas de los otros con
    nombre y las tres secciones, convergencia por `SIN CAMBIOS`, síntesis, revisión `REPRESENTA BIEN`,
    `sintesis.md` con objeciones, captura en la memoria, envío al coordinador.
  - _Requisitos: 2.1, 2.2, 2.3, 2.6, 3.1, 3.2, 3.2b, 3.3_
  - _Archivos: lienzo/consulta.py, tests/test_consulta.py_
  - _Depende de: 1_

- [ ] 3. Motor: vigilancia (muertas, detenidas, vencidas, otra PC, reinicio)
  - En `lienzo/consulta.py`: `vigilar()` cada 30 s: respuestas por la vía lenta (espejadas o llegadas con
    el server caído), investigador que sale (muerto, detenido, espera vencida, envío fallido), sintetizador
    que sale, cancelación con menos de dos, aviso al coordinador.
  - _Requisitos: 2.5, 3.4, 6.3_
  - _Archivos: lienzo/consulta.py, tests/test_consulta.py_
  - _Depende de: 2_

- [ ] 4. Cableado en el server: rutas, envío, gancho, SSE y flechas
  - `lienzo/server.py`: rutas `POST/GET /consultas`, `GET /consultas/<id>`, `POST /consultas/<id>/cancelar`;
    `consulta.enviar` con el envío del tablero (local o reenviado) y la flecha `kind: "consulta"`;
    `consulta.cargar()` al arrancar; `vigilar()` desde el lazo de vivencia; SSE `consulta`.
    `lienzo/rules.py`: `fire_on_stop` llama `consulta.turno_cerrado` (con `try`), `add_link` con `consulta`.
  - _Requisitos: 1.1, 2.2, 2.4, 4.2, 6.2_
  - _Archivos: lienzo/server.py, lienzo/rules.py, tests/test_consulta_api.py_
  - _Depende de: 3_

- [ ] 5. Coordinar y la skill del lienzo
  - `coordinar.consulta(...)` y `coordinar.consulta_estado(cid)`; sección «Consulta entre investigadores»
    en `skills/lienzo/SKILL.md`: cuándo sí (problema difícil, respuestas criticables, investigadores de
    modelos de frontera con esfuerzo alto) y cuándo no (trabajo con archivos: SDD o un frente).
  - _Requisitos: 5.1, 5.2_
  - _Archivos: skills/lienzo/coordinar.py, skills/lienzo/SKILL.md, tests/test_coordinar.py_
  - _Depende de: 4_

- [ ] 6. Web: datos y estilo de investigador en la tarjeta
  - `types.ts` (`Consulta`, `Link.kind` con `"consulta"`), `api.ts` (consultas y SSE), estado en `App.tsx`;
    `Card.tsx` con la clase `investigador`, ícono y «vuelta 2 de 3 · esperando a Codex»; tokens
    `--investigador*` en `styles.css` (claro y oscuro).
  - _Requisitos: 4.1_
  - _Archivos: web/src/types.ts, web/src/api.ts, web/src/App.tsx, web/src/components/Card.tsx, web/src/styles.css_
  - _Depende de: 4_

- [ ] 7. Web: grupo, flechas y la vista de la consulta
  - `Board.tsx`: las tarjetas de una consulta abierta juntas en un marco con la pregunta; `Arrows.tsx`:
    trazo propio para `consulta` y su nombre en la leyenda; `Consulta.tsx` nuevo: vueltas lado a lado,
    síntesis y objeciones, Cancelar; `Header.tsx`: «Consultas» en el menú ⋯ con las últimas.
  - _Requisitos: 4.2, 4.3, 4.4_
  - _Archivos: web/src/components/Board.tsx, web/src/components/Arrows.tsx, web/src/components/Consulta.tsx, web/src/components/Header.tsx_
  - _Depende de: 6_

- [ ] 8. Comprobación final y prueba en vivo
  - pytest completo, ruff, build y lint de la web; recorrido de la web con fixtures; una consulta real entre
    un Claude y un Codex de esta PC (dos vueltas, síntesis en la memoria); code review y pruebas agénticas.
  - _Requisitos: 6.2_
  - _Archivos: .kiro/specs/consulta-investigadores/tasks.md_
  - _Depende de: 5, 7_
