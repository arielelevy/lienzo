# Requisitos: réplica y tamaño de respuestas en la consulta

## Introducción

En una consulta entre investigadores (`lienzo/consulta.py`) puede pasar que un investigador no llegue a
leer una respuesta de otro: el agente la ignoró, el adjunto no se abrió, o la vuelta siguió sin ese
insumo. Hoy no hay forma de reponerla: o se le escribe a mano por la caja (y se pierde la traza), o la
discusión queda coja. Esta funcionalidad agrega el **modo réplica**: el coordinador le reenvía a un
investigador una respuesta puntual que no recibió, por el mismo canal de siempre y con la traza en la
consulta.

La segunda mitad es de vista: la consulta entera (`web/src/components/Consulta.tsx`) muestra las
respuestas completas pero no da idea de su peso; se agrega el **tamaño de cada respuesta** (y de la
síntesis) junto al texto, para reconocer de un vistazo cuáles son desarrolladas y cuáles cortas.

## Requisitos

### Requisito 1: Modo réplica

**Historia:** Como coordinador de una consulta (persona o sesión), quiero reenviarle a un investigador
una respuesta que no recibió, para que la discusión siga con toda la información a la vista.

#### Criterios de aceptación

1.1. CUANDO se pide `POST /consultas/<id>/replica` con `para` (id de tarjeta), `de` (id del investigador
autor) y `vuelta` (número) ENTONCES el sistema DEBE mandarle a `para`, por el envío de siempre, la
respuesta de `de` en esa vuelta con una marca propia (`[consulta <id> · réplica]`), y dejar la flecha
correspondiente entre las tarjetas.

1.2. SI la consulta no existe (404), no está abierta (409), `para` no es participante, `de` no tiene
respuesta en esa vuelta, o algún id es inválido ENTONCES el sistema DEBE rechazar el pedido con el
motivo, sin mandar nada a nadie.

1.3. La réplica NO DEBE crear un pendiente ni frenar el avance de la consulta: es un reenvío de
contenido. SI `para` ya respondió a la vuelta en curso, su respuesta guardada queda como está.

1.4. SI una tarjeta contesta a una réplica ENTONCES el sistema NO DEBE tomarla como respuesta de la
consulta: la marca de la réplica no es la del pendiente, y `_es_respuesta` no la matchea.

1.5. MIENTRAS la réplica viaja, el envío DEBE usar los mismos caminos que las vueltas (local o
reenviado a la PC dueña, adjunto si es largo), y un envío de réplica roto NO DEBE sacar a nadie de la
consulta (a diferencia de una vuelta, no altera los participantes).

1.6. Cada réplica DEBE quedar anotada en la consulta (para quién, qué respuesta, cuándo) y verse en
`GET /consultas/<id>` y en el resumen del tablero.

### Requisito 2: Tamaño de cada respuesta en la vista

**Historia:** Como Ariel, quiero ver cuánto mide cada respuesta en la vista de la consulta, para darme
cuenta de un vistazo cuáles son desarrolladas y cuáles cortas.

#### Criterios de aceptación

2.1. CUANDO la vista de una consulta muestra una respuesta ENTONCES DEBE mostrar su tamaño en
caracteres junto al texto, formateado legible (por ejemplo «3,2 k»).

2.2. El tamaño DEBE calcularse del texto que ya llegó al frontend (sin pedidos extra al server) y
DEBE mostrarse también para la síntesis.

### Requisito 3: Lo que no cambia

3.1. Las vueltas, la síntesis, la revisión de la síntesis y el cierre DEBEN seguir igual, y las pruebas
existentes DEBEN pasar sin tocarlas.

3.2. La réplica no cambia el tope de turnos (`tope_turnos`) ni la cuenta de pendientes que usa
`rules.fire_on_stop` y `vigilar()`.

## Fuera de alcance

- Reintentos automáticos de envíos fallidos: eso queda como hoy (`_sacar` con su motivo).
- Réplica de la síntesis o de las objeciones (la síntesis ya se guarda en `sintesis.md` y en la memoria).
- Mostrar el tamaño en el chip de la tira de consultas: solo en la vista entera.
