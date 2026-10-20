# Actualizaciones desde Lienzo

Abrí **⋯ → Actualizaciones** o tocá la versión abajo a la izquierda. Elegí esta PC o una PC
emparejada, consultá qué cambió y usá **Actualizar**. El indicador avisa cuando hay novedades.
También podés hacer botón derecho sobre una PC en la tira superior: **Actualizar…** abre
directamente esa máquina si hay una versión pendiente. Si está al día, muestra **Al día**
deshabilitado; si aún no se conoce el estado, permite consultar sin aplicar nada.
El servidor consulta Git cada cinco minutos; el botón Buscar novedades fuerza una consulta.

La actualización prepara un worktree temporal y compila la interfaz antes de avanzar `main`
con fast-forward. Si hay cambios locales, commits propios, una compilación fallida o el checkout
cambia durante la preparación, se detiene y muestra el motivo. No hace stash, reset ni force-push.
Conserva assets anteriores para pestañas abiertas. Después recarga el proceso del servidor bajo
`lienzo-server.cmd`; la app reconecta y las CLI siguen abiertas. No es recarga de módulos Python
en caliente. Un cambio en dependencias Python o su requisito de versión exige instalación revisada.

Las PCs anteriores a esta funcionalidad necesitan una primera actualización convencional.
Cada PC aplica su propio checkout y su compilación; el tablero puede pedirlo por el canal
firmado existente. La API no permite actualizar desde el túnel público.

## API

Lectura local: `GET /updates`. Para otra PC: `GET /updates?pc=<pc_id>`.
Devuelve `phase`, `busy`, `available`, `running` (commit cargado), `head`, `target`, `version`,
`checked_at`, `changes`, `blocked` y `error`. El GET lee caché; no ejecuta Git.

Las escrituras requieren `X-Lienzo: 1` y JSON, con las mismas restricciones de Host, origen y
autenticación de Lienzo:

- `POST /updates/check`, cuerpo `{}` o `{"pc":"<pc_id>"}`: consulta asíncrona.
- `POST /updates/apply`, cuerpo `{"target":"<SHA consultado>"}` y opcionalmente `pc`:
  actualiza sólo el commit consultado. Una versión nueva exige volver a consultar.
- Ambas devuelven 202 al iniciar o 409 si hay una operación en curso o un impedimento.
  Consultar `GET /updates` hasta que termine; el estado persiste durante la recarga.

Fases: `idle`, `checking`, `current`, `available`, `preparing`, `building`, `applying`,
`restarting`, `applied`, `error`. Un error visible no se convierte en «al día».
Los comandos no piden entrada interactiva ni publican stderr que pueda contener credenciales.

La preparación y compilación fallidas no avanzan el checkout. Si falla publicar la interfaz o
recargar después del fast-forward, se informa error y no se fuerza un rollback destructivo.
El diario `~/.lienzo/update.json` permite identificar una operación interrumpida.
