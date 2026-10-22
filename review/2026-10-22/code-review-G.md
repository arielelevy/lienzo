# Code review — encargo G (decisiones 1 y 17), 2026-10-22

Skill `code-review` en nivel high sobre el delta de G. La revisión se hizo en un fork de la misma sesión,
leyendo el código sin ejecutarlo. Encontró 10 hallazgos y los 10 se corrigieron. Cada corrección tiene una
prueba que falla si se reintroduce el defecto: en una copia fuera del repo, 9 de 9 regresiones de backend
quedaron detectadas y el mutante de control sobrevivió (`.temp/resultados/2026-10-22-G/regresiones-revision.log`).
La regresión de UI (R8) se mide en `mejoras.spec.ts`.

| # | Hallazgo | Corrección | Prueba que lo detecta |
|---|---|---|---|
| R1 | Una reserva rechazada por tope mensual o por ledger devolvía `stopped`, pero el scheduler ya había sumado el intento y la corrida. El caso llegaba a «intentos agotados» sin que se hubiera enviado nada. | Si `meta.launched` es `False`, `_research_result` restaura los intentos, las corridas y los adaptadores de corrida, y pospone 30 min. | `test_reservation_race_postpones_without_launching` |
| R2 | `adapter_for` comparaba la cuota de Codex con el `uso_semanal_max_pct` crudo del archivo, mientras que la evaluación usa `min(80, archivo)`. Con un archivo en 90 y Codex en 85 %, no pasaba a Claude. | El mismo tope en los dos lados. | `test_switch_uses_the_same_capped_threshold_as_the_evaluation` |
| R3 | Un adaptador pedido por trabajo esquivaba la regla de coda-dgx, así que un proyecto de Globant podía mandarse a Claude, Codex o Azure. | `adapter_named(name, project)` rechaza los proyectos que están en la regla local. | `test_a_coda_project_cannot_be_sent_to_another_adapter` |
| R4 | Al contar las corridas por adaptador, el techo de 6 por día del código pasaba a valer para cada adaptador y no para todo el investigador. | `policy.evaluate` recibe `runs_today` (global, contra el techo del código) y `adapter_runs_today` (contra el tope de la autorización). | `test_daily_ceiling_is_global_and_the_authorization_cap_is_per_adapter`, `test_scheduler_passes_global_and_per_adapter_counts` |
| R5 | Toda corrida de Azure sin uso informado se cargaba como reserva entera, aunque no hubiera salido nada. | Si no se lanzó ningún proceso, o si el hijo falló antes de conectarse (y lo informa con uso 0 y `sin_envio`), se liquida en 0. Un error HTTP después de enviar sigue como cargo desconocido. | `test_nothing_sent_is_settled_at_zero`, `test_child_refusing_the_host_reports_zero_usage` |
| R6 | Si la liquidación fallaba, `investigate` cortaba antes de guardar la salida cruda y la respuesta pagada. | `_settle` atrapa el fallo, deja la reserva abierta (cuenta entera) y la ejecución sigue. El ledger convierte `sqlite3.Error` en `Unreadable`. | `test_ledger_failure_after_the_call_keeps_the_result_and_the_reservation` |
| R7 | La cuota de Claude se pedía en vivo cada 60 s y otra vez al terminar. | A mitad de corrida se lee cada 300 s, y una lectura de menos de 60 s se reutiliza. | `test_claude_quota_is_not_read_every_minute` |
| R8 | La UI habilitaba «Encolar» según `research_view`, que el scheduler de fondo reescribe con otro proyecto o adaptador. | La UI guarda la evaluación que pidió la persona (proyecto y adaptador) y decide los botones con esa. | `mejoras.spec.ts`: «investigador: Claude cuando Codex no tiene cuota…» |
| R9 | El hijo de Azure fallaba con un traceback si la respuesta no era un objeto, o con una entrada incompleta. | Mensaje limpio en los dos casos. Una entrada inválida informa uso 0, porque no se envió nada. | `test_child_rejects_a_non_object_response`, `test_child_refusing_the_host_reports_zero_usage` |
| R10 | La decisión entre posponer y fallar dependía del prefijo del mensaje: el tope por ejecución, que no cambia para un mismo paquete, se posponía para siempre. | Excepciones tipadas (`ledger.BudgetExceeded` y `ledger.Unreadable` posponen; `ValueError` falla una vez). | `test_oversized_packet_fails_before_sending`, `test_per_run_cap_fails_once_instead_of_postponing` |

## Límites que quedan

- Un error HTTP de Azure después de enviar queda como cargo desconocido con la reserva entera, que hoy es
  de USD 1.25 como máximo. Es conservador a propósito: no hay forma de saber si Azure lo facturó.
- `claude_assess` repite el umbral de 5 h de `cuotas._not_eligible` (usa la misma constante). No se unificó
  porque `cuotas` es de otro dueño.
- Una vez, con R4 aplicado, la batería de la copia pasó los 300 s. No se reprodujo: con el mismo mutante
  tardó 23 s, y sin mutante salieron 5 de 5 vueltas en 20 a 26 s (`repeticion-5.log`). La causa no está
  identificada.
