# Revisión 0.5.1: consulta Git antes de actualizar

Alcance: Updates.tsx, updates.spec.ts y versionado 0.5.1. Misma sesión, cinco roles secuenciales.
Requisito de Ariel: otra mejora pusheada para probar Actualizar, sin aplicar ni reiniciar por él.

Defecto confirmado: el guard `busy` de 0.5.0 confundía phase=checking con una actualización
activa. No enviaba apply y seguía en «Iniciando». La prueba nueva falla contra el build anterior
0.5.0 y pasa contra el nuevo, sin modificar fuentes para el control negativo.

Corrección: esperar el fin de checking, mostrarlo, propagar su error y limitar la espera a 90 s.
Cada lectura de estado tiene timeout 10 s. Sólo se retoman sin apply las fases reales del mismo
target o una versión que ya está ejecutándose. El POST conserva el target elegido y el backend
conserva el rechazo de cambios locales, divergencia y target nuevo. No se solicita otro check Git.

Evidencia: 11 Chromium código 0 contra build aislado (9 updater + 2 versión), con fixtures que
bloquean escrituras. Incluye checking→available, checking→error y checking prolongado con reloj
controlado, además de reapertura, error anterior y PC remota. ESLint y tsc código 0; Vite aislado
código 0 con el aviso conocido de bundle >500 kB. Runner aprobado: frontend-lint y frontend-unit
código 0, igual al baseline. Control 0.5.0: 1 prueba falla por el comportamiento anterior esperado.

No hay cambios backend, nuevos paquetes, instalaciones ni nuevas pruebas globales innecesarias.
No hay PASS global de aceptación ni aprobación automática de baseline/casos/mutaciones. No se
publicó web/dist ni se aplicó una actualización real durante la verificación de esta mejora.

Prueba de motor separada pedida durante el trabajo: contrato2 real con SWI dedujo api/auth/web
afectados por db caída, reportes sano y una violación de integridad; store=null (sin persistencia).
API real de Lienzo contrato1 respondió, con 0 creencias antes/después y 0 diferencias. La ausencia
de datos reales no se presenta como una validación de recomendaciones reales de aprendizaje.
