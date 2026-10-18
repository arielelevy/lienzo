# Code review — encargo hijo 0.4.0

Fecha: 2026-10-18. Alcance: cambios de este encargo en backend, frontend, cliente del skill y regresiones. Revisión estática secuencial con la skill `code-review`; sin agentes adicionales. El manifiesto `fuentes-congeladas.json` enumera los archivos y sus hashes. No incluye versión, README ni documentación de root.

## Resultado

Los bloqueos identificados durante la revisión se corrigieron antes del freeze. La focal final ejecutó **218 casos**, exit **0**. La UI ejecutó **2 casos**, exit **0**, contra Vite y API/SSE de fixtures. No certifica el servidor instalado ni una conversación Claude real.

| Hallazgo | Resolución y evidencia |
|---|---|
| Reconexión por PPID perdía el launcher terminado | El adaptador fija handles de toda la cadena antes de ready. `pin_ancestors` verifica orden FILETIME/PPID; permite imagen ausente solo en intermediarios terminados; exige Claude final vivo, imagen y registro exactos. Caso nativo `test_real_adapter_reconnects_after_its_launcher_exits`, sin mock de ancestralidad. |
| Un descriptor público con PID/argv no acredita consentimiento | Se descartó ese enfoque. El descriptor solo descubre el endpoint. El bootstrap exige ancestralidad OS. El caso nativo rechaza otro proceso con el mismo script `--serve`. |
| Cambio parcial de URL antes de validar secreto podía contaminar el poll | `bridge_credentials` valida candidatos completos; URL y secreto se asignan juntos. Tres regresiones mantienen ambos polls en la URL anterior y con el Bearer sintético anterior. |
| Reinicio graceful y cierre explícito eran indistinguibles | `resume` solo para reinicio; cierre explícito quita opt-in. Variantes poll ocioso y resultado incierto; sin replay. |
| Recuperación mismo-id reactivaba reglas ajenas apagadas | `retarget_rules(old,old)` selecciona únicamente `parked_to==old`. Prueba con regla manual apagada y regla agotada. |
| `PUT enabled` ignorado o activación implícita de parked | Booleano estricto, recuperación explícita o 409 con las sesiones faltantes; edición de otros campos no desestaciona. |
| DELETE respondía éxito conservando la regla | Local y federado devuelven 409 explicado cuando hay informes pendientes. Sin pendientes se elimina. |
| Purga de 24 h y cupo podían borrar el archivo visible | `archived_at` excluye la regla de purga y recorte automático; se recupera al volver el mismo origen. |
| Placeholders Claude abortaban reap | UUID inválido se saltea por tarjeta. Regresión con `pid-123` seguida de UUID válido. |
| Flecha desaparecía y no se podía reactivar | Flecha atenuada con motivo y checkbox Habilitada; badge de tarjeta sin regla a coordinadora del mismo repo. Dos pruebas Chromium con escrituras reales bloqueadas. |

## Pendiente de decisión de root

**Hipótesis estática, no defecto medido:** `prepare_launch()` deja `owner=None` y no publica descriptor. En un lanzamiento opt-in, el descriptor se publica después de que `availability()` vincule el owner y `reap()` observe el poll. Un reinicio inmediatamente después de `ready`, antes de ese ciclo, podría perder ese opt-in. `register()` manual publica el descriptor antes. Se avisó por tablero a root, HTTP 200. No se editó ni probó después del freeze ordenado.

Root tomó explícitamente el borde anterior y su regresión en `test_release_root_recovery.py`; su ajuste es posterior al freeze de este frente. No forma parte de los 218 casos ni de los hashes entregados originalmente. La integración del Claude real abierto por Ariel queda a cargo de root; no se conectó esa conversación por este frente.

## Validación y límites

- `focal-freeze.log`: 218 passed, exit 0. Incluye Windows real con dueño sintético, HTTP firmado de peer, guardas Codex y `/exit`.
- `focal-ui.log`: 2 passed, exit 0. Interfaz fuente por Vite 5179; fixtures declarados. Captura revisada visualmente.
- `arrows-unit.log`: 41 casos, `todo ok`, exit 0.
- `ruff-final.log` y `eslint-focal.log`: exit 0. Ruff se ejecutó antes del último cambio de candidato atómico; la focal posterior sí cubre ese cambio. No se hizo otra suite tras el freeze.
- Runner agéntico reutilizado: runtime-contratos, 51 passed, código de caso 0. Runner exit 1 por falta de baseline; compuerta exit 2 por `No hay baseline.json`. Sin PASS certificado.
- Sin aceptación de propuestas, baseline o mutaciones. Sin auditoría nueva de dependencias, suite global ni build; root los toma. No se cambiaron hooks, permisos, seguridad o consentimiento. La conexión automática sigue siendo opt-in (`claude_pipe: true`).

No hay otros bloqueos altos confirmados dentro de lo medido. La hipótesis anterior y la activación real requieren decisión de root.
