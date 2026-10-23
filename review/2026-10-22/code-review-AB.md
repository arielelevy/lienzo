# Revisión AB — revisión delegada de creencias

Fecha local: 2026-10-22. Alcance: delta AB en nueve archivos de código/pruebas. Revisión estática secuencial en la sesión pid-12096 (session_id resuelto en vivo: 01a16604-075a-75b1-af97-0aa9edf14110). Skill `code-review`; no revisión independiente ni auditoría global de dependencias.

## Resultado

Sin hallazgos P1/P2 pendientes dentro de AB. AB.3 pertenece al lote de reevaluación de AA por instrucción expresa de la coordinadora; no se duplica. No se aprueba una release, baseline ni mutación.

Se revisaron `lienzo/creencias_revision_ia.py`, `lienzo/metadatos_creencias.py`, los hooks AB de `lienzo/creencias.py`, `lienzo/conocimiento_api.py`, `web/src/components/LearningReviewIA.tsx`, la integración de dos líneas en `web/src/components/Learning.tsx`, `tests/test_creencias_revision_ia.py`, `web/tests-ui/aprendizaje-revision-ia.spec.ts` y `pruebas-agenticas/revision_ia_real_AB.py`.

## Hallazgos corregidos

- La evidencia podía cambiar mientras respondía la IA. `creencias_revision_ia.py:230` toma una foto de creencias, fuentes, vínculos y destinos; vuelve a comprobarla dentro de `BEGIN IMMEDIATE`. Un conflicto revierte la tanda completa.
- Deshacer podía pisar trabajo posterior o fallar al fusionar una canónica de la misma tanda. `creencias_revision_ia.py:314` comprueba contenido y secuencia; deshace dependencias en orden inverso y ajusta sólo los cursores de fotos cuyo contenido coincide. Conserva auditoría y enlaces retirados. Los cambios de restauración usan la acción replicable `datos`, con origen `deshacer_revision_ia`.
- Una corrección podía conservar una cláusula Prolog de otra acción. `creencias_revision_ia.py:175` no copia `regla_logica` al cambiar texto/acción. AA debe generar/evaluar su nueva formalización; no se ejecuta texto lógico de la IA.
- La confianza heredada decía «veredicto humano» para una aceptación delegada. `creencias.py:152` distingue evidencia `ia_delegada` y confianza delegada. Una revisión humana posterior limpia la marca. Cubierto por `test_human_verdict_supersedes_delegation`.
- La fusión compara proyecto, alcance, dimensión, contexto, regla, excepciones y acción normalizada; rechaza autor sin persona, autorrespaldo y más de 30 fuentes. Une fuentes y vínculos sin borrar observaciones ni historial.
- La salida final de Codex se verifica por existencia y tamaño antes de leerla. Claude usa `--restricted --safe-mode --tools ""`; Codex usa sandbox `read-only`, hooks deshabilitados y aprobación `never`. Ambos tienen plazo de 90 s, salida acotada y eliminación de variables de facturación API mediante el runner existente.
- La lectura inicial de tandas de UI se aborta al operar para que una respuesta tardía no oculte el resumen nuevo. La instancia de componente se renueva por proyecto.

## Evidencia

- Rojo inicial: `ModuleNotFoundError: No module named 'creencias_revision_ia'`, cinco fallas, en `.temp/resultados/2026-10-22-AB/rojo.log`.
- Final de backend: **42 passed, 1 skipped in 9.95s**, `focal-review.log`. La omitida identifica AB.3 pendiente de AA.
- Caso vigente reutilizado por el plugin: **64 passed in 19.59s**, código de caso 0, `salidas/ciclo-creencias-y-patrones.log`. Corresponde al estado previo al último ajuste de confianza; el ajuste tiene la ejecución focal posterior indicada arriba.
- UI: **1 passed (2.6s)** en `ui-verde4.log`, con aplicar, deshacer uno, deshacer tanda y reabrir. UI real desde Vite aislado 7368, respuestas API fijas. Las **17 regresiones existentes** pasaron en `ui-verde2.log`. Las fallas previas del caso nuevo fueron fixtures incompletos (`total`, `muestra_parcial`) y selección del proyecto al recargar; no se contaron como defectos de producto.
- TypeScript y ESLint de rutas AB: código 0. Ruff de todas las rutas Python AB: limpio. `git diff --check` de integraciones: limpio.
- Una llamada a Claude real revisó una propuesta de una copia consistente SQLite: decidió `corregir`; se aplicó y se deshizo. `ia-real.json`. La fuente original se abrió `mode=ro`; no se cambió la memoria en uso.

## Límites reales

- `compuerta.mjs --informe` devolvió **2**: `No hay baseline.json: fijarlo a mano con ejecutar.mjs --fijar`. No es PASS ni ESCALAR (3). `tendencia.mjs` devolvió 0. No se ejecutaron ni aprobaron mutaciones. Blueprint, requisitos y casos nuevos son propuestas sin `--aceptar`; los validadores los leyeron y trazabilidad informó «Sin hallazgos», pero no están certificados.
- Codex se verificó con respuestas fijas y contrato de comando; la llamada real fue con Claude.
- No se reinició 7321 ni se desplegó la UI. El recorrido de uso real del tablero con las nuevas rutas queda para la integración de la coordinadora.
- Metadatos ausentes en la evidencia quedan como listas vacías con procedencia, según contrato AA; no se inventan ni se solicitan a Ariel. La llamada real encontró campos ausentes y los conservó como desconocidos. Se sigue la evidencia hasta informe/encargo/tarjeta productora; no se usa el modelo de la tarjeta actual como sustituto.
- No se midieron métricas de complejidad ni se auditó el repositorio completo. El alcance se concentró en atomicidad, permisos, aislamiento de proyectos, límites, semántica de fusión y reversión.

ESTADO: revisión del delta AB lista; AB.3 e integración real pendientes de AA/coordinadora.
