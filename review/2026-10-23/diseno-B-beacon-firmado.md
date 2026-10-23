# Encargo B: direcciones firmadas y migración del beacon

2026-10-23. Entrega de diseño, sin cambios de protocolo en producción.

## Causa comprobada

`beacon._recibir` autentica el payload y el timestamp, pero publica `addr[0]` en `_seen` y en
`note_peer_address`. Esa dirección no está en el HMAC. El NAT puede convertirla en una puerta sin
listener. Un datagrama válido capturado también puede adelantarse al original desde otra dirección;
el timestamp creciente sólo rechaza las repeticiones posteriores.

Reproductor: `py -3.14 .temp/coordinacion/2026-10-23/B-repro-beacon.py`. No usa peers, archivos ni
consolas reales. Construye un payload con `ips` y HMAC válido: el decoder lo acepta, pero el receptor
elige el origen NAT. Se conserva rojo como evidencia; no integra la suite normal.

## Formato propuesto

Conservar el sobre `{payload, ts, sig}` y el HMAC actual. Agregar dentro de `payload` un campo
`addresses_version: 1` y `ips: [IPv4, ...]`. Conservar `version: 1`: el decoder viejo devuelve el objeto
con campos adicionales y sigue operando. No mandar un segundo paquete legacy: podría ganar la
carrera de timestamps o permitir un downgrade.

El emisor obtiene direcciones de interfaces locales, incluidas la LAN y la IP propia de Tailscale;
`red.tailnet_ips()` enumera destinos remotos y NO sirve como lista propia. Excluir loopback,
unspecified, multicast, broadcast y link-local. Publicar sólo direcciones de la máquina que tiene el
listener; revisar por separado el caso del listener dentro de WSL. Limitar a 32 direcciones IPv4
únicas y al tamaño máximo del datagrama. No aceptar hostnames ni URLs.

El receptor valida tipos, cantidad y direcciones después de verificar la firma. Un campo presente
pero inválido rechaza el anuncio completo: no cae al origen. Las candidatas del espejo salen
únicamente de la lista firmada vigente. `addr` queda para diagnóstico y respuesta UDP, nunca para
persistir ni elegir el host TCP. Mantener el sondeo y orden LAN/Tailscale de `red` y `server`.

La lista nueva reemplaza el conjunto anunciado anterior; no acumular indefinidamente direcciones
que desaparecieron. Separar direcciones de emparejamiento, anuncios vigentes y dirección conectada;
no borrar ni cambiar la conexión sana hasta que otra candidata valide el canal firmado `/peer`.
Que un puerto TCP abra no acredita identidad. Conservar ventana temporal y orden de timestamps.

## Compatibilidad y límite de seguridad

| Emisor | Receptor | Resultado propuesto |
|---|---|---|
| nuevo | viejo | El viejo verifica el mismo HMAC y tolera los campos; conserva su comportamiento actual. |
| viejo | nuevo | Acepta presencia autenticada y conserva la conexión/candidatas conocidas; no aprende `addr[0]`. |
| nuevo | nuevo | Aprende exclusivamente la lista firmada. |

El caso viejo → nuevo no puede descubrir con seguridad una IP desconocida después de DHCP: el viejo
no firmó una dirección. No hay forma de deducirla del paquete sin volver a confiar en su origen.
Por eso no se entrega una implementación que prometa recuperación total entre versiones.

Migración propuesta: primera versión agrega el campo y mide recepción sin cambiar el ruteo. Cuando
ambas PCs anuncian listas válidas y se verifica comunicación firmada en ambos sentidos, una segunda
versión activa ruteo estricto. Guardar por par la capacidad firmada para impedir downgrade posterior.
Durante la primera etapa la vulnerabilidad sigue abierta y debe decirse. No activar el cambio
estricto por timeout ni por anuncio sin firma. El rollback de binario no debe reabrir aprendizaje
por origen en un par marcado estricto; exige una acción explícita de recuperación.

## Validación previa a implementar

1. Compatibilidad usando el decoder y receptor de la versión vieja real, además del nuevo.
2. HMAC alterado, IPs agregadas fuera del payload, lista vacía, tipo incorrecto, más de 32,
   duplicados, loopback, IPv6 no soportada y datagrama truncado: nunca generan candidatas.
3. Reenvío desde NAT/origen distinto, replay y downgrade: no cambian destino.
4. Dos procesos aislados con puertos altos y claves propias: SSE y request firmado en ambos sentidos,
   primero viejo/nuevo y luego nuevo/nuevo. Repetir invirtiendo el orden de actualización.
5. Dos PCs reales: LAN, Tailscale, WSL/NAT, IP cambiada, una interfaz caída y reinicio de cada lado.
   Conservar evidencia del host elegido y una operación autenticada por sentido, sin claves.

No se reinició el servidor ni se actualizó ninguna PC. Esta validación mixta queda pendiente.
