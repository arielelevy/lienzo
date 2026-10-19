# Revisión del puente Tailchrome

Alcance: cambios de este pedido en `lienzo/server.py`, `lienzo/tailchrome.py`,
`lienzo/tailchrome.html`, las pruebas nuevas y README. Revisión estática secuencial
en esta sesión con el skill code-audit; no es una revisión independiente.

## Hallazgos corregidos

- La validación previa a leer el cuerpo también requería los headers de firma.
  Se agregó una única extracción de credenciales para el endpoint WebSocket,
  utilizada por la prevalidación y por la verificación completa. Las otras rutas
  siguen exigiendo sus headers originales.
- La reconexión inmediata chocaba con el cierre del listener anterior.
  Una generación cerrada ya puede reemplazarse; su limpieza no elimina la nueva
  generación ni cambia su ruta. El E2E reproduce desconexión y reconexión.
- Los callbacks de una pestaña anterior podían cerrar una conexión nueva.
  Los callbacks del navegador verifican su generación.
- La ruta del espejo sólo cambia después de confirmar la identidad cifrada.
  Los errores antes de crear el multiplexor cierran igualmente el WebSocket.
- Se rechazan aperturas con un número de canal reutilizado o del mismo sentido.

## Límites de confianza revisados

- Entrada local: requiere conexión local, Host admitido y Origin propio. La IP
  escrita en el formulario tiene que ser una IPv4 del rango Tailscale.
- Entrada de pares: exige emparejamiento previo, HMAC, ventana temporal y nonce
  no repetido. El ticket sólo sirve para `/peer/tailchrome`.
- El navegador no recibe la clave del par. Los sobres usan una clave derivada
  por canal y secuencias independientes por sentido. Se rechazan reflexión y replay.
- El destino TCP del canal está fijado al PeerHandler privado de esta PC; el
  navegador no puede elegir un host o puerto de reenvío. Los pedidos interiores
  siguen autenticándose por el mecanismo habitual.
- Cupo de 32 conexiones por canal, cargas de 16 KiB, límite de cola en el navegador
  y plazos de socket. Los puertos efímeros nunca se escriben en `peers.json`.
- Los nombres de PC se muestran con `textContent`. No se agregaron dependencias,
  reglas de firewall ni excepciones del antivirus.

## Evidencia

- Ruff y `git diff --check`: código 0.
- Batería ampliada: **193 passed**, incluyendo federación, PeerHandler, reglas,
  beacons, cambios de red, WebSocket y los casos nuevos del puente.
- Chromium con proxy HTTP local y dos procesos aislados: código 0. Pedidos
  firmados en ambos sentidos, SSE, desconexión, reconexión, cierre de pestaña y
  configuración persistente intacta. Salud sintética; no usa cuentas ni agentes reales.
- Capturas y logs locales: `pruebas-agenticas/resultados/tailchrome/`.
- Explorer, Analyser y Designer produjeron propuestas válidas; la trazabilidad no
  mostró huecos de casos. No se aceptaron propuestas ni baselines.
- La compuerta del perfil de propuestas dio **ESCALAR**, código 3: no tiene casos
  aceptados. Las ejecuciones directas anteriores se conservan por separado.
- La corrida global del perfil de release se interrumpió: había arrancado antes
  de los últimos ajustes y no acredita el código final. El runner la registró
  con código 1; no se contabiliza como aprobada. La batería focal de 193 pruebas
  y el E2E posterior sí corresponden al código final.

## Pendientes reales

No se detectaron hallazgos críticos o altos abiertos en el delta revisado.
Falta la prueba entre las PCs reales con Tailchrome instalado. No se midieron
transferencia sostenida, demora de Chrome remoto ni comportamiento bajo suspensión
prolongada de pestañas. La extensión oficial de Tailscale no se probó. El puente
requiere un destino con listener alcanzable; no cubre dos PCs sólo con extensiones.
No se ejecutó mutación y no hay certificación PASS de aceptación.
