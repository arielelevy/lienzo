# Auto-aprobación de Antigravity

Revisión focal secuencial de agentes.py y test_autoaprobar.py, autorizada por el
reporte de Ariel de que auto-aprobar no responde el permiso. Sin subagentes.

Explorer: GET /sessions confirmó pid-7368, agente Antigravity, con pregunta
Requesting permission for:, detalle Get-ChildItem -Path . Run this command?,
opción 1 Yes, run command, opciones 2/3 persistentes y 4 No, cancel. El motivo
de omisión era «no es un permiso». Observación de API real, no navegación UI.

Analyser: el contrato de autoaprobar.py pide aprobar permisos cuando el ajuste
está activo y excluye preguntas con opciones. Antigravity.permission_option
devolvía None siempre: causa confirmada, independiente del parser y del lector
de historial. No implica soporte de fin/on_stop.

Designer: regresión del texto observado a través de screen.dialog y au.ronda
con answer_dialog sustituido; debe elegir 1. Cinco clases negativas: pregunta
de biblioteca, confianza, sólo aprobación persistente, ausencia de cancelación,
y aprobación actual mezclada con always allow. No se cambia el baseline.

Executor: roja 1 failed/5 passed; después del cambio runner vigente
backend-pytest con PYTEST_ADDOPTS -k "autoaprobar or antigravity or agentes or screen or dialog":
239 passed, 2757 deselected, 7.65 s; runner código 0.
Corrida 2026-10-21T18-31-32.106Z-24912; logs y actual.parcial.json en
pruebas-agenticas/resultados. Ruff y git diff --check códigos 0.

Detective/review: comparación exacta de cabecera y etiquetas; requiere cancelar
y elige únicamente Yes, run command, sin fallback a opciones permanentes.
Sin cambios en transporte, teclas, hooks, otras TUIs o configuración. Sin nuevos
bloqueantes detectados en el delta. Las opciones numeradas usan el transporte
preexistente; no se acreditó ejecución efectiva del número en la terminal real.
No se envió texto a otra sesión ni se modificó el ajuste de auto-aprobación.
No se midió mutación ni global nueva. WSL sigue pendiente. Metadatos de 0.6.6
y enlaces de release revisados sin cambios de dependencias.
