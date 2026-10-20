# Actualizaciones desde Lienzo

Cuando hay una versión pendiente aparece **Actualizar** en el menú ⋯ y en el menú del botón
derecho de cada PC disponible. Si no hay novedades, la entrada no aparece. Al pulsarla comienza
la actualización de esa PC y se abre una ventana con progreso y resultado, sin otra confirmación.
La versión de abajo a la izquierda también permite iniciar cuando hay novedades.
El servidor consulta Git cada cinco minutos. Cerrar la ventana no cancela la actualización;
volver a abrirla retoma el progreso. Los impedimentos se muestran como errores visibles.

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
