# Revisión: conservar la última lectura de cuotas

Alcance: cambios de esta sesión en `lienzo/cuotas.py`, `web/src/api.ts`, `web/src/components/Cuotas.tsx`, `tests/test_cuotas_cuenta.py`, `tests/test_kiro_quota.py` y `web/tests-ui/cuotas.spec.ts`. Se preservaron las modificaciones previas de cuotas federadas y arranque.

Revisión estática: caché por agente, sincronización y generación; fallo y timeout; recuperación; fecha de medición; accesibilidad; resolución de ejecutables y ausencia de secretos. Sin hallazgos bloqueantes en estos cambios. La conservación es explícitamente requerida por Ariel: mantiene `ok: false`, error y aviso visible; no habilita recomendaciones con datos viejos.

Verificación: 44 pruebas focales Python y 13 recorridos Playwright con respuestas de cuotas simuladas pasaron. Build compiló. Los primeros intentos de pruebas fallaron por restricciones del sandbox; las ejecuciones autorizadas fuera del sandbox pasaron. Lectura real después del reinicio: Codex `ok: true`, semanal 19 %, plan prolite. Kiro devuelve `ValueError`, pendiente de diagnóstico propio; no se informa lectura válida de Kiro.

Límites: la conservación vive en memoria del servidor y del navegador. No recupera una medición perdida antes de este cambio ni persiste tras cerrar ambos. No se ejecutaron mutaciones nuevas ni se aceptaron propuestas de casos. No se declara PASS global de la compuerta.
