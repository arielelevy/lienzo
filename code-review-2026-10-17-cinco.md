# Revisión de integración de cinco CLI — 2026-10-17

Alcance: cambios de cinco frentes Codex reales lanzados por Lienzo, con retorno on_stop hacia la coordinadora y archivos aislados por frente. La raíz aplicó code-audit a los deltas, comparó bases y verificó integración. No se aprobaron baselines, propuestas ni casillas.

## Identidad y continuidad

`codex_identity.py` deja de acreditar un hilo visible por dos snapshots de handles. La reproducción previa de `/new` refutó ese supuesto: el ACK correspondía al rollout abandonado. La mitigación rechaza el envío CLI basado sólo en esa prueba; implica pérdida de funcionalidad. Desktop conserva su contrato. El documento de A define una fuente autoritativa y envío condicionado como requisitos para rehabilitar CLI. No se afirma resolución funcional ni prueba real nueva de `/new` o `/clear`.

En `sessions.py`, un candidato rechazado retira la prueba anterior sólo si siguen vigentes tarjeta y PID, sin mover IDs, reglas, transcripción ni reservas inciertas. Las tres regresiones de raíz verifican carrera de PID, sustitución de tarjeta y conservación de referencias. Se corrigió el oráculo anterior que exigía la prueba refutada, manteniendo las comprobaciones de dos snapshots y set intacto.

## Cuota e informes

`optimization_research_quota.py` bloquea al llegar al 100 % de la ventana de cinco horas, incluso con margen semanal y flags ordinarios favorables. Una ventana ausente conserva su contrato. La misma decisión central cubre inicio y ejecución; no se lanzaron investigaciones pagas como prueba.

`entregas_informes.py` conserva el hito entregado y su fecha ante resultados tardíos. El diagnóstico de transporte sigue actualizándose. La entrega no acusa recepción ni integración. El frente C reprodujo cuatro fallos antes de corregir y verificó persistencia/concurrencia con transportes simulados.

## Memoria y plugins

`aprendizaje.py` reutiliza componentes de recurrencia dentro de una conexión/transacción; las consultas de lectura abren snapshot explícito. El cache no sobrevive a la operación. El origen proviene de incidentes existentes del mismo proyecto; el grupo es simétrico. Se verifican retiro de vínculos, auditoría y transacción de escritura sin rebajar límites temporales. No se infiere mejora universal de una muestra ni se elimina el fallo de rendimiento anterior.

`plugin_manifest.py` comprueba tipo string antes de consultar tipos permitidos; listas/diccionarios JSON inválidos generan errores del contrato en lugar de TypeError. No se agregan dependencias ni instalaciones.

## Evidencia focal de raíz

Identidad: 64 aprobadas, código 0. Cuota/informes: 94 aprobadas, código 0. Memoria/plugins: 83 aprobadas, código 0. Son conjuntos focales con solapamiento; no una suma de cobertura. La primera focal root de identidad falló por WinError 5 del sandbox y fue repetida con aprobación. Un wrapper de memoria falló al imprimir caracteres tras completar 83 pruebas; conservó el log, se corrigió su salida y se midió otra vez para conservar el código exacto.

Los informes completos, cinco roles de cada frente, preparaciones fallidas y logs permanecen en `.temp/coordinacion/2026-10-17/ronda-cinco-final/`. La validación global se registra por separado sobre 348 fuentes inventariadas.

## Visor remoto

Se revisó el delta de `RemoteBrowser.tsx`: valida la forma básica de mensajes JSON y las dimensiones/largo mínimo de cuadros binarios. Los errores se muestran en la UI. El bitmap decodificado se cierra con finally, incluso si el componente se desmonta o el dibujo falla. El chequeo de cancelación evita dibujar o enviar ACK al socket anterior tras cambiar PC. No se modificó el protocolo del servidor ni se probaron ventanas reales del usuario. La copia aislada de E pasó 18 recorridos de Chrome y memoria; se conservaron los fallos de dependencias y de fixtures previos. TypeScript de build se comprueba en la global, porque un `tsc --noEmit` sobre una config raíz con references no sustituye `tsc -b`.

## Pendientes reales

## Validación integrada final

Corrida `2026-10-17T23-45-47.860Z-28344`, estado `19d55d66200b0f5c`: siete casos globales con código 0. Backend 2327 aprobadas y 3 omitidas; interfaz global 136 aprobadas; memoria focal 153 aprobadas; memoria E2E, ESLint, build TypeScript/Vite y unitarias con código 0. La prueba adicional sobre el árbol principal, con Vite aislado sin proxy al servidor real, pasó 18 recorridos de Chrome y memoria en 23,2 s. Esos conjuntos se solapan: no se suman como cobertura única.

Las 348 fuentes/pruebas/versiones inventariadas permanecieron idénticas durante la medición. La lista completa de seis mutaciones aprobadas se midió en un worktree con el mismo estado Git: cinco destructivas detectadas y el control inocuo conservado, 83 % frente al mínimo configurado de 80 %. El runner de mutaciones salió 1 por ese control; la compuerta evaluó el umbral y devolvió PASS, código 0. No se aceptaron referencias ni se rebajaron umbrales. Las adiciones finales al informe/documentación son posteriores al corte; no alteran las fuentes probadas.

Las cinco CLI propias entregaron y se verificó que sus PID 42680, 31996, 46992, 41292 y 12776 ya no existían. Sus cinco reglas se retiraron conservando informes pendientes, sin acusarlos como integrados. PUT con enabled=false no desactivaba las reglas: se comprobó la respuesta y se usó DELETE, cuyo contrato conserva pendientes. Las sesiones de OpenSyync siguieron activas y no se reinició el servidor.

## Límites de entrega

Fuente autoritativa de hilo visible CLI; conexión Claude aprobada en la conversación receptora; coordinación del reinicio entre olas OpenSyync; medición real de coordinadora ocupada/quieta y recuperación; duración individual con eventos correlacionados; consumidores externos/narrativa curada, retención, presupuesto y aceptación; hardware LAN, Linux/macOS y Chrome habitual. Los informes de los cinco frentes separan lo construido de estas dependencias. Ningún fixture acredita una prueba real de esos recorridos.

El portapapeles sincronizado en modo ventana y las vistas específicas de controles por encargo/registro externo siguen sin implementar; son distintos del pegado local y de las consultas existentes. No se presentan como bloqueos exclusivamente de hardware ni como tareas terminadas.
