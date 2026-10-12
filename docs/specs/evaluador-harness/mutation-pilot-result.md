# Mutaciones del piloto publicado

Autorización de Ariel: aprobar y probar los pendientes. Medición completa de la lista, sin caché ni muestra, sobre una copia Git aislada del commit `51cd1d4`. La copia contiene un commit local `ff400c8` que agrega solo la configuración de mutaciones. Ningún fuente del servidor activo fue mutado.

| Mutación | Tipo | Resultado | Evidencia revisada |
|---|---|---|---|
| inactividad-desconocida-permitida | Defecto | Detectado | Cuatro aserciones fallaron para None, NaN, bool y valor negativo |
| pago-automatico | Defecto | Detectado | Fallaron las aserciones de estado de pagos del scheduler y de la API |
| control-actividad-docstring | Inocuo | Sobrevivió | Los 86 tests del caso focal pasaron |
| control-docstring | Inocuo | Sobrevivió | Los 86 tests del caso focal pasaron |

Sanidad previa: 86 tests aprobados. Los dos defectos se detectaron por su comportamiento específico, sin fallas de arranque, temporales o conectividad. Ambos controles sobrevivieron como correspondía. Árbol aislado limpio al finalizar, sin backups ni fuentes mutados pendientes.

El runner cuenta todos los mutantes, incluidos los controles: 2 de 4 muertos, 50%. Para esta lista el máximo esperado es 50%, porque matar un control inocuo sería una señal de mala atribución. Se pidió a Ariel elegir el mínimo; todavía no se lo configura ni se declara PASS general sin esa decisión. La validación debe comprobar además que todos los defectos mueran y todos los controles sobrevivan; el porcentaje por sí solo no basta.

Resultados y logs completos: `pruebas-agenticas/resultados/mutation-isolated-51cd1d4/pruebas-agenticas/resultados/scheduler/`. Esta evidencia corresponde al commit medido, no certifica modificaciones posteriores del piloto automático.

Recorrido secuencial: Explorer reutilizó requisitos y revisó las fuentes; Analyser fijó el oráculo de bloqueo y pagos; Designer convirtió las propuestas en reemplazos exactos y añadió un control por archivo; Executor ejecutó validar, ejecutar y mutar --sin-cache; Detective leyó los logs de cada muerte/control y verificó restauración. Sin agentes adicionales, servicios pagos ni modificación de baseline.
