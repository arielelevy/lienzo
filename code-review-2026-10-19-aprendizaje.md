# Revisión e integración del aprendizaje

Alcance: cambios de aprendizaje implementados por la CLI Claude
`03edfd91-33dd-4805-a7ec-8afaf6c5a4bf` por encargo directo de Ariel; integración por Codex
para guardar el trabajo verificado y desbloquear la actualización. No se aprueban tareas,
baselines ni mutaciones. Se conserva la memoria real; no se crean creencias de demostración.

## Revisión estática

Se revisaron el delta de conocimiento/API/cliente, creencias y las nuevas vistas/pruebas.
El checklist reutiliza `_Respaldos`, sin segundo motor de dependencias. Propuestas y uso
no promocionan creencias. El informe liga sus controles al encargo al capturarlo o adoptarlo;
una revisión sustituye controles anteriores del mismo tipo y conserva verificación humana.
La evidencia de veredicto sigue siendo distinta de una fuente de hipótesis.

Hallazgos enviados a Claude para corregir antes del checkpoint:

- Las lecturas múltiples del evaluador necesitaban una transacción de lectura explícita para
  no mezclar estado de la creencia y grafo en revisiones diferentes.
- Contexto inválido no debe convertirse en `{}` y ampliar la aplicabilidad; debe fallar cerrado.

Correcciones contrastadas en disco: `evaluar` inicia `BEGIN` antes de leer nodos, apoyos y
respaldos; el contexto inválido recibe estado y motivo propios y nunca entra en aplicables.
El ref de contexto de React se sincroniza mediante un efecto, corrigiendo el warning de lint
sin desactivar la regla. El runner final de backend registró 133 passed en 23,43 s (código de
caso 0; runner sin baseline), incluidos contextos rotos y los nuevos controles.

El cliente y la API de encargos exigen ahora `tipo_trabajo`, admitiendo `sin_clasificar`
explícito. Es un cambio de contrato solicitado y reconocido en el checkpoint del usuario;
las integraciones deben enviar el campo. El modelo interno conserva lectura de históricos
sin clasificar. Se actualizó el oráculo del alta normal; no se debilita el resultado esperado.

La UI agrupa tres vistas anteriores, muestra motivos y cadenas, y deja veredicto y uso como
acciones explícitas. La firma `persona:<nombre>` conserva el contrato existente de LAN:
es atribución declarada, no prueba criptográfica de identidad humana. Los resultados de
controles declarados siguen requiriendo contrastar la referencia; no equivalen a auditoría.

## Evidencia

Cinco roles secuenciales de Claude registrados en
`pruebas-agenticas/resultados/aprendizaje-real/roles.json`. Config propia nueva: no tiene
baseline ni mutaciones aceptadas y no constituye certificación PASS. La evidencia inicial
del runner registra 125 pruebas de backend con retorno 0 y runner 1 por baseline ausente;
el checkpoint inicial comunicado por Claude registra 311 focales, Ruff limpio y 6 UI con
fixtures. El checkpoint final y la verificación de integración se conservan en ese directorio
y en `pruebas-agenticas/resultados/updates/`.

Límites: no se acredita mejora estadística por estos tests, no se validan creencias históricas
ni se instala el motor Prolog. La batería global anterior agotó el backend y no es PASS;
estos cambios se entregan con su validación focal y sus límites explícitos.

Checkpoint final recibido y leído: Claude declara sin más escrituras, 319 pruebas en 13 archivos
(58,54 s), 6 recorridos UI (4,7 s), lint/tsc/Ruff con código 0. Registro e informe en
`.temp/coordinacion/2026-10-19/checkpoint-aprendizaje-claude.md`. Se contrastó además el log
real del runner de 133 pruebas y su código 0 por caso; el baseline permanece sin aceptar.
La publicación de UI y recarga se realiza con el actualizador de Lienzo, sobre el commit limpio.
