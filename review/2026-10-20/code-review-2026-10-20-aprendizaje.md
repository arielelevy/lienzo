# Code review: aprendizaje en segundo plano, intentos y revisión (D1-D3)

**Fecha:** 2026-10-20
**Autor y revisor:** frente D (Claude), con autorización de la coordinadora. La review la hice yo sobre mi propio cambio; no es una review independiente.
**Alcance:** PR review de los archivos exclusivos autorizados.

| Archivo | Cambio |
|---|---|
| `lienzo/optimization_scheduler.py` | D1: espera de 30 min después de un corte del entorno. D2: comandos `requeue_research` y `dismiss_research` |
| `lienzo/optimization_queue.py` | D3: un trabajo pausado se conserva al reiniciar. D2: transiciones con historial |
| `web/src/components/OptimizationScheduler.tsx` | D2: «Revisar», «Reencolar investigación» y «Descartar» (con confirmación) |
| `docs/APRENDIZAJE.md` | La doc alineada con D1-D3 |
| `tests/test_optimization_intentos.py` (nuevo) | Regresiones de D1-D3 |
| `tests/test_optimization_research.py` | Oráculo ajustado al backoff (autorizado) |
| `web/tests-ui/aprendizaje-revision.spec.ts` (nuevo) | Spec de UI de la revisión |

## Defectos de origen (reproducidos antes del cambio)
- **D1:** un corte por actividad, agentes o memoria pausaba sin espera. El próximo tick gastaba el segundo inicio del caso en las mismas condiciones, y el caso quedaba en review. En vivo había 4 trabajos así: 97e0f3c4, e99b8bb1, 7c4ef1b3 y 1b373fcc.
- **D2:** review no tenía salida: `enqueue_research` deduplica todo el historial y no había ninguna acción sobre un trabajo en review.
- **D3:** al reiniciar, un trabajo `paused` pasaba a review sin tener proceso vivo. La doc solo lo decía para `running`.

## Pruebas (rc)
| Corrida | Resultado | Evidencia |
|---|---|---|
| Regresiones nuevas antes del cambio | 24 failed, 6 passed (rc 1) | `.temp/coordinacion/2026-10-20/D-antigravity/aprendizaje/intentos-antes.log` |
| Suite de optimización después del cambio (8 archivos) | 161 passed (rc 0) | `intentos-despues.log` |
| `tsc --noEmit`, eslint, ruff check y format | rc 0 | consola |
| Playwright `aprendizaje-revision.spec.ts`, 1 worker, contra Vite propio en 5173 | 1 passed (rc 0) | `playwright.log` |

Vite se lanzó solo para esta prueba (PID 2664) y lo cerré con `Stop-Process`. El puerto 5173 quedó libre. No reinicié el backend.

## Hallazgos de la review

| Severidad | Cantidad |
|---|---|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | 0 |
| LOW | 2 |

- **LOW 1.** `_cancelled` sigue usando el literal «pausado por el usuario» en lugar de `RESEARCH_PAUSED`. El texto es idéntico, así que no hay error, pero existen dos fuentes para el mismo valor. Es fuera del cambio mínimo y lo dejé así.
- **LOW 2.** Un trabajo en review con `not_before` viejo, de una pausa anterior al reinicio, mantiene esa espera después de reencolarlo. Es conservador: respeta la espera y no gasta antes de tiempo.

Lo que verifiqué y no es un defecto:
- El comando valida fuera del lock (estado, intentos agotados, política). La cola vuelve a validar bajo su lock antes de escribir. Una carrera con el tick solo puede terminar en un rechazo, nunca en una escritura indebida.
- El historial está acotado: cada vuelta a review gasta un inicio (reinicio en `running` o «intentos agotados»), y con un techo de 2 inicios son pocas entradas.
- No hay ningún camino que mate un PID. Un `paused` conserva su `pid`, y el runner solo corta el árbol que lanzó.
- Una falla al guardar revierte la transición (se probó con `OSError`).
- Reencolar un caso agotado se rechaza antes de leer la cuota, y nunca pone `attempts` en 0.
- Descartar no altera las corridas de 24 h ni la deduplicación.

## Límites
- La review es de autor. No hubo una segunda review independiente ni una ejecución de las acciones contra la cola real.
- La reproducción de D1 forzó la memoria baja desde el arranque. En vivo, el disparador es la memoria que cae o la actividad que aparece a mitad de la ejecución.
- La UI se probó contra Vite con el API simulado. El build que sirve el server (`web/dist`) no está regenerado: la UI nueva no se ve en 7321 hasta un build coordinado.
- Archivar trabajos para liberar el tope de 100 queda fuera; necesita una propuesta separada.
- No corrí la suite global ni mutación.
