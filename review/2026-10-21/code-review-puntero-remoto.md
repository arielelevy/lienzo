# Revisión del seguimiento del puntero remoto

Alcance: `lienzo/browser_stream.py`, `web/src/components/RemoteBrowser.tsx` y sus pruebas
en `tests/test_browser_tabs_stream.py` y `web/tests-ui/chrome.spec.ts`.
Revisión estática y pruebas focales; no certifica la integración completa ni el caso LAN.

## Problema y cambio

La UI conservaba la última posición pendiente, pero esperaba el ACK anterior. El receptor
tenía una cola FIFO de 64 pedidos sin reemplazo de hover. La regresión con un movimiento
bloqueado y una ráfaga de 80 posiciones reprodujo un rechazo de una tecla posterior.
Eso prueba el comportamiento de la cola; no atribuye por sí solo el incidente real de Ariel.

La UI permite hasta cuatro pedidos de hover sin confirmación y conserva el último pendiente.
La cola receptora reemplaza sólo su último pedido cuando ambos son movimientos absolutos
sin botones, tienen igual generación, geometría y modificadores, y el nuevo número es mayor.
No cruza teclado, ruedas, arrastres, liberaciones, cambios de tamaño o selección.

El pedido reemplazado recibe `outcome: superseded`: significa sustituido, no ejecutado.
La UI sólo acepta esa respuesta para un hover propio pendiente. Una confirmación así para
una tecla bloquea la entrada como incierta y no la reenvía. Los mensajes en ejecución no
se cancelan; el límite se aplica a lo pendiente. La cola sigue acotada y sus cambios se
realizan bajo el lock de Queue, sin esperar red dentro de él.

## Evidencia

- Rojo backend: la tecla 81 fue rechazada tras llenar la cola. Verde inicial: 19 aprobadas.
- Rojo UI: con ACK retenido sólo salió un movimiento. Verde: avanzó con ventana acotada y
  entregó la última posición al detener el puntero, incluyendo respuesta superseded.
- Backend final: 57 aprobadas, incluyendo límites de orden, generaciones, cifrado y releases.
- UI sobre bundle de producción aislado: 39 aprobadas en 28,0 s, sin tocar Chrome real.
- ESLint focal y build: código 0. El build atravesó una suspensión de Windows; su salida
  correcta no se usa como prueba de rendimiento. Ruff y diff check se ejecutaron sobre el delta.

La corrida UI inicial atravesó suspensión del 21/10, 13:34:44Z → 14:01:54Z, y dejó
33 aprobadas/6 fallidas. Se preservó. Una corrida posterior en desarrollo dio 38/1:
el fixture de perfiles presupone una inicialización, mientras desarrollo duplica efectos.
Se conservó su test original y se contrastó el bundle de producción, que pasó. El selector
del caso nuevo se corrigió para buscar el alert con su texto, conservando bloqueo y no replay.
No se modificaron baselines, listas de casos aprobados ni umbrales.

Logs y trazas privados: `.temp/coordinacion/2026-10-21/hover-*`.

## Revisión y límites

No se identificaron hallazgos bloqueantes concretos en este delta. Se revisaron límites de
cola, validación de tipos/coordenadas, cierre, correlación de ACK, orden y separación de
generaciones. El reemplazo nunca confirma ejecución de botones o teclas. Un navegador
anterior puede ignorar el outcome del hover; la nueva UI reconoce además su semántica.

El transporte sigue siendo WebSocket/TCP: no puede retirar bytes ya enviados y puede sufrir
bloqueo por paquetes anteriores. Cuatro no es una tasa universal óptima ni un resultado
de latencia LAN medida. Hace falta probar el comportamiento real después de actualizar
las dos puntas. Dibujar o arrastrar no adopta el descarte de hover; la rueda conserva suma.

Referencias primarias consultadas:
[noVNC](https://github.com/novnc/noVNC/blob/master/core/rfb.js) conserva la última posición
y limita movimientos; [W3C Pointer Events](https://www.w3.org/TR/pointerevents/#coalesced-events)
distingue eventos combinados y conservación del trazo. No se presenta esto como una
certificación del «estado del arte» ni como prueba de haber resuelto el incidente real.
