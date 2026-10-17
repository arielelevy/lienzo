# Revisión del cierre Desktop — 2026-10-17

Alcance: delta de conexión/reconexión Claude, capacidad publicada, roles Desktop, componente de conexión y pruebas afectadas. Se aplicó el skill code-audit a los cambios autorizados; las revisiones de las rondas anteriores permanecen separadas en la raíz.

## Contratos y concurrencia

`lienzo/claude_pipe_runtime.py`: reconexión explícita bajo el bloqueo de ciclo de vida. Valida la misma encarnación del proceso antes de sustituir un adaptador inactivo; conserva uno saludable y el historial de reservas. No hay repetición de envíos inciertos. `lienzo/server.py` valida `reconnect` como booleano estricto y sólo publica campos permitidos del comando de conexión.

`lienzo/server.py` y `web/src/components/Card.tsx`: los pares exactos Claude/Claude Desktop y Codex/Codex Desktop requieren canal disponible para habilitar coordinación. Retirar el rol no exige canal vivo. Esto no amplía los permisos de interrupción, aprobación ni control de consola.

`lienzo/sessions.py`: Claude Desktop conserva el motivo del transporte real cuando falta el adaptador. Un ACK histórico no se convierte en capacidad de envío.

## Interfaz

`web/src/components/ClaudeConnection.tsx`: instancia por sesión; respuestas tras desmontaje ignoradas; temporizador limpiado; comando vencido oculto; renovación explícita. La copia informa errores y el bootstrap se ejecuta sólo en la conversación receptora. No se modifican hooks ni permisos.

## Hallazgos corregidos

La primera global detectó cinco dobles con la firma anterior de `register`, una expectativa obsoleta de transporte desconectado y dos mediciones de movimiento contaminadas por tiras del servidor real. Se ajustaron contratos de prueba y se aislaron `/avisos`, `/consultas` y `/memoria` en el tablero fijo. La tolerancia de movimiento permanece en 2 px. El fallo restante de interfaz fue `net::ERR_CONNECTION_REFUSED` antes de entrar al recorrido; quedó registrado y se repitió la batería para comprobar disponibilidad y comportamiento.

Focal Desktop: 116 backend y 21 UI aprobados. Contratos adicionales: 44 backend aprobados. No se suman como casos únicos. ESLint, TypeScript y Ruff focales aprobaron.

## Resultado final medido

Corrida `2026-10-17T23-18-58.190Z-4800`: siete casos globales con código 0. Backend: 2298 aprobadas y 3 omitidas; interfaz: 136 aprobadas; memoria focal: 153 aprobadas; memoria E2E: código 0; lint, build y unitarias: código 0. Se verificaron las 341 fuentes inventariadas sin cambios durante el corte. Los conjuntos backend/memoria se solapan.

La lista de seis mutaciones aprobadas se midió en un worktree aislado con huella Git idéntica `25bd5e97fed0233a`. Detectó las cinco destructivas y conservó el control inocuo: 5 de 6, 83%, por encima del umbral configurado de 80%. El runner de mutaciones sale 1 por ese control sobreviviente; la compuerta aplica el umbral y devolvió `VEREDICTO: PASS`, código 0. No se aceptaron referencias nuevas. Resultados y cinco roles secuenciales en `.temp/coordinacion/2026-10-17/desktop-cierre/`.

La primera medición aislada se detuvo sin mutar: `test_medicion_300_incidentes_cadena_de_40_y_20_reglas` midió 344,1 ms frente a 200 ms. La segunda pasó la sanidad y completó las seis mutaciones sin cambiar fuentes ni umbral. Se conserva el primer fallo como evidencia de rendimiento intermitente bajo carga; el PASS final no borra esa observación ni certifica tiempos estables. Las adiciones documentales finales son posteriores al corte; las fuentes probadas permanecen iguales.

## Pendientes reales

La P0 de identidad visible de Codex CLI tras `/new` sigue abierta y reproducida en la revisión de la ronda de cuatro. No hay confirmación nueva de adaptador Claude real en la conversación receptora durante este cierre. El backend activo requiere reinicio coordinado para cargar los módulos Python. No se cerraron casillas ni se aceptaron baselines o mutaciones.
