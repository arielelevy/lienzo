# Qué es cada archivo de estado

[Volver al README](../README.md)

```
~/.lienzo/
  events/ pending/ answers/   hooks y permisos en curso
  adjuntos/                   archivos y textos largos enviados a las sesiones
  sessions/                   una tarjeta por sesión
  links.json, rules.json      envíos hechos y conexiones
  config.json                 auto_*, launch_roots, copy_roots, git_check, auto_reload,
                              mem_aviso_gb, max_sesiones_por_repo
  auth.json                   clave TOTP del acceso remoto
  peer.json, peers.json       identidad de esta PC y PCs emparejadas (con la clave del par)
  launch/                     un .cmd y un .json (título y agente) por sesión lanzada desde el
                              tablero; se borran a los 7 días
  restaurar.json              sesiones para relanzar tras un reinicio
  sucesion.json               muertas con reglas estacionadas y quién sucedió a quién
  rondas.json                 avisos coordinados, turnos y sus políticas
  conocimiento.sqlite         la memoria de todos los proyectos (una base por instancia, replicada entre PCs)
  proyectos/<proyecto>/       cuerpos de encargos e informes y evidencia de cada proyecto
  xfer/                       copias entre PCs (trabajos/) y hashes de lo recibido (hashes.db)
  chrome-remoto/              perfil separado de Chrome para la vista por pestañas
  rechazos.jsonl              pedidos rechazados (401, 403, Host no válido), sin cuerpos ni
                              credenciales; rota a 1 MB en rechazos.jsonl.1
  remote_run.jsonl            cada pedido a /peer/run, sin argv ni salida; rota igual
  research-ledger.sqlite      reservas y cargos de Azure del investigador
  private/azure-openai.dpapi  la key de Azure OpenAI, cifrada con DPAPI
  *.corrupto-<fecha>          un JSON que no se pudo leer, apartado en vez de pisarlo; los JSON
                              de estado se escriben por la escritura atómica de atomico.py
  lienzo.log                  una línea por hecho; lo de más de 30 días se depura una vez por día
```
