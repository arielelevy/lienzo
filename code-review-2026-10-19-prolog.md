# Revisión del cambio pendiente: Prolog opcional y actualización simple

Alcance: diff de Lienzo completo y archivos nuevos `prolog_learning.py` y
`test_prolog_learning.py`; motor separado en `D:/Apps/motor-logico`.
Revisión estática en esta sesión, sin agentes adicionales. No es auditoría global del repo.

## Hallazgos corregidos

- El motor estaba dentro del repo Lienzo. Se separó en un repo Git local hermano; el adaptador
  acepta `LIENZO_PROLOG_ENGINE` o la ruta hermana. No instala ni actualiza el motor con Lienzo.
- Reabrir el diálogo de actualización podía repetir el POST apply. Ahora consulta el estado y
  retoma una operación existente del mismo target; prueba de navegador específica.
- El fallo Prolog no aclaraba la continuidad del aprendizaje. El mensaje ahora distingue la
  consulta fallida del aprendizaje normal; prueba de API confirma que no llama al motor al leer
  creencias y sigue funcionando después de un 503.
- La prueba de respuesta parcial comprobaba antes otro error de contrato. Se corrigió el fixture
  para comprobar realmente que una respuesta incompleta nunca se interpreta como éxito vacío.
- Corregido fin de archivo extra en pruebas UI. `git diff --check` sin errores.

## Evidencia

- 74 pruebas focales backend: Prolog real en Ubuntu WSL, creencias, aprendizaje real y updater.
- 34 pruebas Chromium contra build aislado en puerto 7398: aprendizaje, updates, PCs y versión.
  Las API de navegador usan fixtures y bloquean escrituras reales. No prueban un reinicio real.
- Ruff, ESLint directo y TypeScript: código 0. Vite aislado: código 0, aviso de bundle >500 kB.
- Motor separado: 2 pruebas de contrato con SWI real, sin importar Lienzo, código 0.
- Runner oficial parcial: frontend-lint terminó por timeout sin salida; frontend-unit código 0
  y memoria-focal código 0 (153 passed). Runner código 1 por diferencia de lint con baseline.
  La corrida parcial no acredita aceptación global; no se fijó baseline ni se aceptaron casos.

## Límites y pendientes reales

Sin hallazgos bloqueantes adicionales identificados en el alcance estático revisado. Esto no
equivale a certificar todo Lienzo. La compuerta global anterior tenía fallos pendientes y esta
revisión no los convierte en PASS. No se ejecutaron nuevas mutaciones ni suite global completa.

Motor independiente con contrato 1/reglas 1, sólo dominio learning. Chesstudia todavía no está
conectado; no hay reglas de ajedrez, servidor HTTP ni MCP. Git local inicializado sin remoto.
Prolog es segunda opinión de sólo lectura: no valida, aprende ni actualiza creencias por sí solo.
Límites visibles: snapshots grandes rechazados, runtime ausente/timeout => 503 de esa consulta.

No se reinstaló software, no se publicó web/dist y no se reinició ni actualizó Lienzo en ejecución.
El corte inicial permaneció sin commit para revisión. Ariel autorizó después commits y release,
con los repos separados y sin aplicar la actualización en Lienzo.

## Cierre con dos CLI independientes

Claude A investigó los timeouts y midió una nueva corrida del runner: 5 de 5 casos código 0,
igual al baseline. Backend: 2561 passed, 3 skipped en 464 s; lint 12,9 s; unitarias código 0;
memoria-focal 153 passed y memoria-e2e código 0. Eventos Windows 524/42/107 acreditan suspensión
por batería crítica durante las dos corridas con timeouts; no se cambiaron límites para taparlos.
La compuerta global conserva FAIL por su evidencia completa vieja y mutaciones de otro estado.

Claude B corrigió error viejo del updater presentado como fallo de un nuevo intento, con prueba
negativa en build aislado y restauración por hash. Eliminó textos «Al día», agregó ausencia del
repo visible antes de lanzar WSL, rechazo de contrato booleano y diferencial de 8 grafos/9 estados.
Verificación: 63 focales backend, 14 UI en preview aislado y 16 Prolog tras el último ajuste;
Ruff, ESLint, tsc y build aislado código 0. Sus fuentes quedaron congeladas con hashes registrados.
Coordinadora retiró CSS del antiguo formulario de updates y ajustó la barra de progreso.
Build final aislado 0.5.0: 35 pruebas Chromium código 0; hashes de fuentes B conservados.

Otra sesión del usuario es dueña del repo motor y sus commits: incorpora contrato2 genérico y
persistencia opcional sin alterar el contrato1 de Lienzo, contrastado en 120 snapshots sin diferencias.
La revisión del motor aquí citada era de su primer corte; su dueña actualiza su revisión y README.
Lienzo usa exclusivamente contrato1/reglas1 de sólo lectura. Las tres infografías y sus fuentes
quedaron en el repo motor, fuera de Lienzo. Sin reinicios, instalaciones ni apply.
