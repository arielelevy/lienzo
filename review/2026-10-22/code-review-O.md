# Code review — encargo O (Kiro: avisos, auto-aprobar visible, tarjetas fantasma)

2026-10-22, sesión a91b7f9f. Skill `code-review` (medium) sobre el delta de `lienzo/procinfo.py`,
`lienzo/autoaprobar.py`, `lienzo/agentes.py`, `lienzo/sessions.py`, `web/src/components/CardNeeds.tsx`,
`web/src/hooks/useNotifications.ts`, `web/src/types.ts` y `tests/test_kiro_avisos.py`. 10 hallazgos.

| # | Archivo | Hallazgo | Resolución |
|---|---|---|---|
| 1 | sessions.py | Si el turno siguiente empieza y termina entre dos lecturas, la tarjeta queda para siempre en la pregunta vieja | Corregido: la pregunta se suelta también cuando cambia el turno (`pregunta_turno`). Prueba roja → verde |
| 2 | sessions.py | Una pregunta vieja bloqueaba el diálogo de pantalla (barrido y auto-aprobar pedían `needs` vacío) | Corregido en `screen_once`: con diálogo en pantalla, la pregunta de fin de turno se suelta. Prueba roja → verde |
| 3 | autoaprobar.py | `auto_aprobado` no se borraba nunca | Corregido: se borra al apagar el auto-aprobar (como `auto_aprobar_omitido`), y la tarjeta lo muestra sólo en el turno en curso. Prueba roja → verde (servidor) |
| 4 | procinfo.py | Faltaban subcomandos sin TUI (`acp`, …) | Corregido: se suman `acp`, `doctor`, `translate`, `inline`, `integrations`. Prueba roja → verde |
| 5 | procinfo.py | El binario renombrado (`kiro-cli.exe.old.<ts>`) no leía el comando | Corregido. Prueba roja → verde |
| 6 | procinfo.py | El valor de otra opción se leía como subcomando | Corregido para `--agent`, `--model`, `--profile`. Prueba roja → verde |
| 7 | procinfo.py | Sin comando legible, la TUI real daba muerta (falso «murió trabajando») | Corregido: Kiro sin comando sigue contando como agente (antes del cambio era así). Prueba roja → verde |
| 8 | sessions.py | La pregunta sólo se detecta si termina en «?» | Parcial: se toleran `*` y `_` finales (negrita). La regla es la misma que usa Claude (`hook_notification`, `rules.py`). Pendiente común a los dos: opciones listadas después de la pregunta |
| 9 | sessions.py | Turno sin `id` ni `ts_start` | Corregido: la clave cae al final del texto. Prueba roja → verde |
| 10 | useNotifications.ts | La clave era la sesión: un aviso nuevo sin salir de «te necesita» no avisaba | Corregido: la clave es sesión + `needs.since`. La pregunta «idle» no avisa en el navegador, igual que con Claude (decisión de producto, no cambia) |

Rojo de los arreglos: `.temp/resultados/2026-10-22-O/rojo-revision.txt` (6 de 13 fallan sobre el delta anterior a la revisión).

## Segunda pasada (cartel de subagentes)

Skill `code-review` (low) sobre `_dialog_kiro_pendientes` y las ramas «N tool approval(s) pending» de `Kiro.permission_option` y `permission_reason`: sin hallazgos.
