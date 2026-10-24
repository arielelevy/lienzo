# Revisión F — segunda pasada

Fecha: 2026-10-24. Alcance: correcciones solicitadas en
`.temp/coordinacion/2026-10-24/revision-F-hallazgos-2.md`, incluido cart.
Revisión estática de preguntas.py y de los enganches modificados en rules.py,
sessions.py y server.py, con sus pruebas. Sin auditoría de dependencias: no cambiaron.

Los diez hallazgos se reprodujeron con pruebas antes del arreglo, en orden.
El pedido de cart también produjo cuatro fallas antes del cambio.

| Punto | Corrección revisada | Prueba en tests/test_revision_F2.py |
|---|---|---|
| 1 | Normalización de question nulo en ambos lectores | test_01_* |
| 2 | Editor abierto no se elige otra vez; espera de redibujo acotada | test_02_* |
| 3 | Throttle en memoria, fuera de la tarjeta y del touch | test_03_* |
| 4 | Throttle antes de copiar y buscar coordinadora; copias sólo de campos mutables relevantes | test_04_* |
| 5 | Guardas independientes por sesión, sin RLock global | test_05_* |
| 6 | Espera de hasta 3 s, fuera de state.lock, con reserva atómica | test_06_* |
| 7 | Reserva durable por destino e informe; rollback si falla guardar | test_07_* |
| 8 | Router compartido, conserva la guarda en_turno y la atribución | test_08_* |
| 9 | Trabajador de recordatorios independiente del planificador | test_09_* |
| 10 | Limpieza de cierre centralizada en barrer | test_10_* |
| cart | Respuesta explícita admite diálogos reservados; error muestra endpoint | test_cart_* |

Hallazgos adicionales corregidos durante esta revisión:

- La comprobación de ocupación y la reserva deben ser atómicas. Se trasladaron al mismo bloque de lock. La espera usa Event y reloj monotónico.
- El caché conserva referencia de origen para no reutilizar una tarjeta reemplazada. barrer elimina entradas retiradas y preguntas cerradas.
- No se copian historiales ni capturas en obtener o al buscar coordinadora. test_04_no_copia_historial_ni_capturas usa un objeto que falla si se copia.
- El diálogo numérico genérico no debe usar flechas. test_cart_dialogo_numerico_no_manda_enter falló con 409 antes del arreglo; ahora exige exactamente número sin Enter.
- Las pruebas de recordatorios deben usar el router real con teclado sustituido. El fixture compartido se adaptó sin cambiar los oráculos de entrega, persistencia ni sin_aviso.

No quedan hallazgos críticos o altos identificados dentro de este alcance.
No se inventan métricas de complejidad o cobertura: no se midieron con herramientas específicas.
Ruff se limita al módulo y pruebas del encargo. No se reformatean los módulos compartidos.

La validación final y el estado de Git quedan en
`.temp/coordinacion/2026-10-24/informe-F-segunda-revision.md`.
El servicio vivo no se reinicia y no representa el despliegue de estos cambios.
La limpieza visual de una pregunta cerrada ocurre en el siguiente barrido de 0,5 s.
