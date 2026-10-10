# Requisitos: consulta entre investigadores

## Introducción

Para un problema difícil, Ariel quiere que dos o tres agentes de modelos de frontera (por ejemplo un
Claude y un Codex, con esfuerzo alto) lo piensen juntos: que cada uno conteste por su cuenta, lea lo
que dijeron los otros, corrija lo suyo, y que al final quede una conclusión con los acuerdos y los
desacuerdos a la vista.

Hoy se puede hacer a mano (`send` y reglas `on_stop` con `{respuesta}`), pero hay que mediar cada vuelta
y en el tablero el cruce se ve igual que un encargo cualquiera. Esta funcionalidad agrega la consulta:
el lienzo media las vueltas por el canal de siempre (lo que se mandan se ve, se teclea y deja flecha), y
el tablero la muestra con un aspecto propio, para distinguir de un vistazo una discusión entre
investigadores de un reparto de trabajo.

Pedido de Ariel del 2026-10-10: el canal entre los dos o tres investigadores con «otro look and feel»
(no un canal escondido), y la skill como parte del lienzo. No es A2A: los agentes son terminales que el
lienzo ya maneja.

## Requisitos

### Requisito 1: Abrir una consulta

**Historia:** Como coordinador (persona o sesión), quiero abrir una consulta con una pregunta y dos o
tres investigadores, para que la piensen juntos sin que yo tenga que mediar cada vuelta.

#### Criterios de aceptación

1.1. CUANDO se pide `POST /consultas` con `pregunta`, `investigadores` (2 o 3 ids de tarjeta) y
`vueltas` (1 a 3; 2 por defecto) ENTONCES el sistema DEBE crear la consulta con un id, guardarla,
mandarle la pregunta a cada investigador por el envío de siempre, y responder 200 con el id.

1.2. SI hay menos de 2 o más de 3 investigadores, uno repetido, uno que no existe, uno detenido
(`stopped_by`) o uno ya ocupado en otra consulta abierta ENTONCES el sistema DEBE rechazar el pedido con
400 y el motivo, sin mandar nada a nadie.

1.3. SI un investigador está `corriendo` al abrir ENTONCES el sistema DEBE rechazar con 409: la consulta
empieza con todos quietos, para que la primera respuesta sea a la pregunta y no a otra cosa.

### Requisito 2: Las vueltas, mediadas por el lienzo

**Historia:** Como coordinador, quiero que el lienzo pase las respuestas entre los investigadores y
ponga el tope, para que discutan sin que yo esté en el medio y sin que se contesten para siempre.

#### Criterios de aceptación

2.1. CUANDO un investigador termina su turno dentro de una consulta ENTONCES el sistema DEBE guardar su
respuesta entera en la consulta (vuelta, investigador, agente, modelo, hora).

2.2. CUANDO todos terminaron la vuelta N y quedan vueltas ENTONCES el sistema DEBE mandarle a cada uno,
por el envío de siempre (adjunto si es largo, como hoy), las respuestas de los otros y el pedido de
revisar la suya: qué acepta, qué refuta y su respuesta corregida. Cada envío deja su flecha entre las
tarjetas, marcada como de la consulta.

2.3. El sistema NO DEBE crear reglas A↔B entre investigadores: los cruces los arma el lienzo, con el tope
de vueltas fijado al abrir.

2.4. CUANDO se pide `GET /consultas/<id>` ENTONCES el sistema DEBE devolver la pregunta, el estado
(`abierta`, `sintetizando`, `cerrada`, `cancelada`), los investigadores y las respuestas por vuelta.

2.5. La consulta DEBE guardarse en `~/.lienzo/consultas/<id>/` (un JSON y un `.md` por respuesta) y
sobrevivir a un reinicio del server: una consulta abierta sigue desde la vuelta en que estaba.

2.6. MIENTRAS una tarjeta está en una consulta abierta, lo que la persona le escriba por la caja va por
el canal de siempre y no cuenta como respuesta de la consulta.

### Requisito 3: Converger y cerrar

**Historia:** Como coordinador, quiero que la consulta termine sola con una síntesis, para recibir una
conclusión y no tres textos sueltos.

#### Criterios de aceptación

3.1. SI en una vuelta todos los investigadores declaran que no cambian su respuesta (`SIN CAMBIOS` en la
primera línea) ENTONCES el sistema DEBE darla por convergida antes del tope de vueltas.

3.2. CUANDO se llega al tope o a la convergencia ENTONCES el sistema DEBE pedirle la síntesis al
`sintetizador` (el primer investigador por defecto) con todas las respuestas: acuerdos, desacuerdos con
quién sostiene qué, y la conclusión recomendada.

3.2b. CUANDO llega la síntesis y `revisar_sintesis` no es falso ENTONCES el sistema DEBE mandársela a
los demás investigadores para que contesten en una línea `REPRESENTA BIEN` o su corrección, y agregar
las correcciones a la síntesis como «Objeciones» antes de cerrar.

3.3. CUANDO la síntesis está completa ENTONCES el sistema DEBE cerrar la consulta, guardarla en
`~/.lienzo/consultas/<id>/sintesis.md` y en la memoria del proyecto de la carpeta del sintetizador (como
captura `observado`, ver `lienzo/captura.py`), y mandársela al `coordinador` de la consulta si tiene uno.

3.4. SI un investigador muere, queda detenido o no cierra su turno en `espera` minutos (30 por defecto)
ENTONCES el sistema DEBE seguir con los que quedan si son al menos dos, o cerrar la consulta como
`cancelada` con el motivo, y avisarle al coordinador.

3.5. CUANDO se pide `POST /consultas/<id>/cancelar` ENTONCES el sistema DEBE dejarla `cancelada` sin
mandar nada más; lo que ya respondieron queda guardado.

### Requisito 4: Otro look and feel en el tablero

**Historia:** Como Ariel, quiero que una consulta se vea distinta de un encargo, para reconocer de un
vistazo qué tarjetas están discutiendo un problema y en qué va la discusión.

#### Criterios de aceptación

4.1. MIENTRAS una tarjeta participa de una consulta abierta ENTONCES su tarjeta DEBE verse con el
estilo de investigador (un color y un ícono propios, distintos de coordinadora y frente) y la vuelta en
que está («vuelta 2 de 3», «esperando a Codex»).

4.2. Las flechas de la consulta DEBEN dibujarse con un estilo propio (distinto del de encargos y del
canal nativo), y las tarjetas de una misma consulta DEBEN verse agrupadas, con la pregunta como título
del grupo.

4.3. CUANDO se toca el grupo ENTONCES DEBE abrirse la consulta: cada vuelta con la respuesta de cada
investigador lado a lado y, al final, la síntesis.

4.4. CUANDO la consulta se cierra ENTONCES las tarjetas DEBEN volver a su aspecto de siempre y la
consulta DEBE quedar consultable desde el tablero (las últimas, con su síntesis).

### Requisito 5: Usarla desde una sesión

**Historia:** Como sesión coordinadora, quiero abrir y seguir una consulta desde Python, para usarla en
un encargo sin escribir HTTP a mano.

#### Criterios de aceptación

5.1. `coordinar.consulta(pregunta, investigadores, vueltas=2, sintetizador=None)` DEBE abrir la consulta
(con `YO` como coordinador) y devolver su id; `coordinar.consulta_estado(id)` DEBE devolver el estado.

5.2. La skill `lienzo` DEBE explicar cuándo usar una consulta (un problema difícil cuyas respuestas se
pueden criticar) y cuándo no (un trabajo con archivos: eso es SDD o un frente).

### Requisito 6: Lo que no cambia

6.1. Una tarjeta no puede estar en dos consultas abiertas a la vez (1.2).

6.2. Los encargos, las reglas, las flechas y el envío de siempre DEBEN seguir igual para las tarjetas
fuera de una consulta, y las pruebas existentes DEBEN pasar sin tocarlas.

6.3. Los investigadores pueden estar en otra PC de la federación; el envío y la lectura de su respuesta
usan los mismos caminos que hoy (`send` transparente y el transcript espejado).

## Fuera de alcance

- Que los investigadores editen archivos del repo: una consulta es para pensar, no para construir.
- Lanzar los investigadores: se eligen tarjetas que ya existen (antes, con `lanzar_y_titular`).
- A2A u otro protocolo externo.

## Aclaraciones

Contestadas por Ariel el 2026-10-10 («todas tus recomendaciones»):

1. **Síntesis:** la hace un investigador, el primero si no se elige otro (`sintetizador`), no la
   coordinadora, que no participó de la discusión.
2. **Vueltas:** 2 por defecto, 3 como máximo (1.1).
3. **Nombres:** cada investigador ve las respuestas de los otros con nombre de agente y modelo
   («Claude (opus)», «Codex (gpt-5.x)»), para ver dónde difieren los modelos.
4. **Tablero:** la vista de la consulta muestra las respuestas enteras; la tarjeta, la última línea
   como hoy.
5. **Herramientas:** pueden leer el repo y buscar en la web; no editar archivos (va en el pedido de
   cada vuelta).
