# Dominio de Lienzo
Actualizado: 2026-10-26 (03b7537 + 39d9b95). Índice para retomar trabajo: una línea por entidad y
dónde vive. La arquitectura está en DISENO.es.md; las decisiones de producto, en docs/PRODUCTO.md.

## Entidades

### Sesiones y agentes
- **Sesión (tarjeta)**: un proceso de agente con su transcripción, `session_id`, `pid`, título y estado
  (`corriendo`, `te_necesita`, `termino`, `muerta`). Vive en `lienzo/sessions.py`; la UI en `web/src/`.
- **Agente**: el proveedor de CLI (claude, codex, pi, coda, kiro) con su contrato de identidad,
  transcripción y reanudación. `lienzo/agentes.py`, más uno por agente (`coda.py`, `kiro.py`, `codex_*.py`).
- **Evento de hook**: lo que manda un agente al cerrar un turno, pedir permiso, etc. Entra por
  `lienzo/hook.py` y se aplica a la tarjeta en `lienzo/hooks_eventos.py`.
- **Transcripción / turno**: la conversación leída por la cola; el último turno da `last_reply`.
  `lienzo/transcripts.py`.
  Claude identifica las cuentas de `CLAUDE_CONFIG_DIR` y `LIENZO_CLAUDE_SMARTBI_DIR` por su registro
  `sessions/<pid>.json`, verificando `procStart`; el barrido usa el `sessionId` exacto para leer
  la conversación de esa cuenta (`agentes.py`, `sessions.py`).
- **Envío**: texto tecleado (o encolado, en Codex) a una sesión. `lienzo/send.py`, `lienzo/codex_queue.py`;
  la entrada HTTP es `POST /sessions/<sid>/send`.
- **Lanzamiento / restauración / sucesión**: abrir una sesión nueva (`lienzo/launch.py`), relanzarla tras un
  reinicio (`lienzo/restore.py`) y pasarle las reglas de una muerta a su sucesora (`sessions.py`,
  `~/.lienzo/sucesion.json`).
- **Pendiente (permiso)**: un diálogo de permiso esperando decisión. `lienzo/sessions.py`, `lienzo/autoaprobar.py`.

### Coordinación
- **Coordinadora (★)**: una sesión por repo, en toda la federación, que reparte y recibe informes.
  `PUT /sessions/<sid>/coordinator`; continuidad al desaparecer en `lienzo/huerfanos.py`.
- **Regla**: `on_stop` (al cerrar cada turno de `from`, le manda `text` a `to`) o `at` (a una hora).
  Topes por ventana y total, filtro `solo_si`, `dedupe`. `lienzo/rules.py`; validar y editar en
  `lienzo/rules_api.py`; persiste en `~/.lienzo/rules.json`.
- **Informe**: la foto de un turno que una regla `on_stop` lleva a la coordinadora. Vive dentro de su regla
  (`rule["informes"]`), con estado `pendiente` → `entregado` → `recibido` → `integrado`; los dos últimos
  sólo por acuse explícito de la sesión destino. `lienzo/entregas_informes.py`.
- **Link (flecha)**: rastro de un envío entre sesiones, con `from` y `link_to`. `state.links`, `~/.lienzo/links.json`.
- **Ronda larga**: aviso a N frentes con `ACK`, turno de un recurso pesado, memoria. `lienzo/rondas.py`.
- **Consulta entre investigadores**: vueltas entre 2-3 agentes y un revisor. `lienzo/consulta.py`.
- **Auditoría de sesiones**: ronda cada 5 min que marca ociosas evitables. `lienzo/auditoria.py`.
  La coordinadora del repo declara `espera_declarada` en la tarjeta con motivo y vencimiento
  (`PUT /sessions/<sid>/espera`); un nuevo pedido o estado la invalida y al vencer avisa.
- **Cliente de coordinación**: lo que usa una coordinadora desde Python (`frentes`, `cablear`, `enviar`,
  `informe`). `skills/lienzo/coordinar.py`.

### Varias PCs
- **PC / peer**: una PC emparejada, con `pc_id`, salud y capacidades. `lienzo/federation.py`,
  `lienzo/pairing.py`, `lienzo/beacon.py`, `lienzo/health.py`; `~/.lienzo/peers.json`.
- **Espejo**: las sesiones, reglas y links de cada peer, en memoria; reenvía a la PC dueña.
  `lienzo/mirror.py`.
- **Cuota de cuenta**: lectura local en `lienzo/cuotas.py`; `cuotas_federadas.py` consulta `/peer/cuotas`
  firmado cuando otra PC puede aportar una lectura. La lectura local válida prevalece y las cuentas no se suman.
- **Trabajo de copia (xfer)**: copia por bloques verificados entre PCs, dentro de `copy_roots` o
  `launch_roots`. `lienzo/xfer.py`.
- **Secreto**: un token cifrado de un solo uso entre PCs. `lienzo/secretos.py`.

### Conocimiento por proyecto
- **Proyecto, creencia, evidencia, veredicto**: la memoria del proyecto en `~/.lienzo/conocimiento.sqlite`,
  replicada entre PCs. `lienzo/conocimiento.py`, `lienzo/creencias.py`, `lienzo/veredictos.py`,
  `lienzo/replica.py`; captura automática en `lienzo/captura.py`.

## Flujos principales
- **Informe de un frente**: el frente cierra un turno → hook `Stop` (`hooks_eventos.py`) → `rules.py`
  dispara cada regla `on_stop` con `from` = frente → `entregas_informes.conservar` guarda la foto en la
  regla → envío a `to` → `resultado` marca `entregado` → la coordinadora acusa `recibido` / `integrado`.
- **Borrar una regla**: `DELETE /rules/<id>` (`server.py`) → si vive en otra PC, se reenvía por el espejo →
  `rules.retirar_regla`: sin informes pendientes la borra (200); con pendientes la deja `enabled: false`
  con `disabled_reason` y responde 409 `conservada: true`, `desactivada: true` y `pendientes`.
  Si ya estaba apagada conserva su motivo. `coordinar.borrar_reglas_hacia_mi()` las avisa y
  `reglas_apagadas_hacia_mi()` lista las que deberían entregar y no lo hacen.
- **Encargo**: la coordinadora lanza o reusa un frente → `PUT /title` → regla `on_stop` frente → coordinadora
  → `POST /send` con el encargo.
- **Restaurar tras reinicio**: `restore.py` relanza con el retomar del agente → la sucesora hereda título y
  reglas estacionadas.

## Reglas que no se rompen
- Una regla no forma bucle A↔B y siempre tiene tope (`rules_api.py`).
- Un informe no pasa a `recibido` ni `integrado` sin acuse de la sesión destino (`entregas_informes.acusar`).
- Una sesión detenida (`stopped_by`) no recibe envíos: 409, y las reglas que la apuntan se saltean.
- Cada PC es dueña de lo suyo: consola, pantalla, hooks y recursos se piden a esa PC por `/peer/*` firmado.
- Copias sólo dentro de `copy_roots` o `launch_roots`, sin enlaces en el camino (`xfer.permitido`).
