# Anexo C de v5. Replicación de la memoria entre PCs (2026-10-09)

Diseño corto e implementación en `lienzo/replica.py`, sobre el canal firmado que ya existe entre
PCs emparejadas (HMAC por par, `/peer/*`). Pruebas: `tests/test_replica.py`.

## Propiedad

No hay una base dueña. Cada PC escribe sólo en su base y es la autoridad de los cambios que nacieron
en ella: cada `cambio` lleva `pc` (la PC de origen) y `seq_origen` (su número allá). Una PC le pide a
cada par vivo los cambios con origen en ese par, desde su cursor. Con hasta cuatro PCs no se reenvían
cambios ajenos: cada uno se trae de su PC de origen (si esa PC está apagada, llega cuando vuelve).
Qué PC es la «dueña» mientras no haya base compartida sigue abierta (PENDIENTES.md): este diseño
funciona con cualquiera de las opciones.

## Identidad del proyecto entre PCs

Por remote, como en el anexo A: el remote une la misma carpeta en dos PCs. Un proyecto sin remote no
se replica (no hay forma de saber que es el mismo) y se informa en `sin_remote`. Uno que existe sólo
en el par se crea acá con su id (o `-2`) y sus remotes, sin carpeta en esta PC.

## Concurrencia

- Ids globales: los nodos usan UUID; la sesión, un UUID derivado del `session_id`, así que la PC del
  coordinador y la de la sesión crean el mismo nodo.
- Un cambio de estado, texto o datos gana si es el más nuevo por (fecha, pc). Si el nodo local ya no
  estaba como el cambio remoto lo vio (`anterior`), queda un choque en `replica_conflicto` para la
  coordinadora. Los dos cambios quedan en el historial.
- Vínculos: el más nuevo por fecha decide si está activo.
- Lo que no se puede aplicar todavía (un vínculo cuyo nodo creó una tercera PC) espera en
  `replica_pendiente` y se reintenta en cada vuelta.

## Recuperación tras un corte

Cada lote (500 cambios) se aplica en una transacción junto con el cursor nuevo. Un corte a mitad no
aplica nada ni mueve el cursor; la vuelta siguiente repite el lote, y `(pc, seq_origen)` único lo
vuelve idempotente. Las capturas, inmutables, se copian por id desde el rowid de origen.

## Revisiones que no se pierden

Cada revisión de informe es un nodo propio con su cuerpo y su hash; los cuerpos y la evidencia se
traen aparte, se verifican por hash y entran al índice de prosa. Ningún cambio se borra al replicar.

## Duplicados

Si otro nodo local ya tiene la `clave_ingesta` del remoto (la misma evidencia subida en las dos PCs, o
el mismo informe entregado en las dos), el remoto entra igual, sin la clave, y queda una sugerencia en
`replica_duplicado`. No se fusiona solo: lo decide la coordinadora con un veredicto.

## Operación

- `POST /peer/conocimiento {op}`: `proyectos`, `cambios`, `capturas`, `cuerpo`. Sólo lee la base de
  la PC que atiende.
- El server sincroniza cada 120 s con los pares vivos; `POST /conocimiento/replicar {pc?}` lo fuerza;
  `GET /conocimiento/<p>/replica` muestra cursores, choques, duplicados y pendientes.
- Un par con un lienzo sin réplica responde «ruta desconocida»: se avisa una vez y se saltea.

## Encargos a tarjetas de otra PC

`encargo_enviado` para una tarjeta de otra PC vale cuando esta PC ya replicó con esa en el proyecto
(hay cursor): el nodo sesión y el vínculo `ejecutado_por` llegan a la PC de la sesión, que registra
sus observaciones, y vuelven. Sin réplica sigue el 409, con el motivo.

## Lo que falta

- Probarlo entre las dos PCs reales (hasta ahora, dos bases simuladas en un proceso).
- Una PC apagada mucho tiempo frena sólo sus propios cambios; no hay reenvío entre terceros.
