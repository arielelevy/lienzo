# Consultas entre investigadores

Contrato consolidado de consultas, réplicas y vista. Sustituye las specs intermedias de ambos temas.
Código de referencia: `lienzo/consulta.py`, rutas en `server.py`, `skills/lienzo/coordinar.py`
y `web/src/components/Consulta.tsx`. La consolidación documental no declara nuevas pruebas.

## Uso

Una consulta permite que dos o tres investigadores existentes estudien un problema, contrasten
respuestas y produzcan una síntesis con acuerdos y desacuerdos. Pueden leer fuentes y código;
construir cambios se gestiona como un encargo, con arquitectura, plan y tareas según el alcance.
No exige SDD. El lanzamiento de investigadores no forma parte de abrir la consulta.

## Apertura y límites

`POST /consultas` recibe pregunta, investigadores y opciones de vueltas, sintetizador/revisor,
coordinador, espera, enfoques y revisión de síntesis. Usa el envío existente, local o a la PC dueña.
Dos vueltas por defecto, máximo tres; espera por defecto de 30 minutos.
Rechaza participantes repetidos, desconocidos, detenidos u ocupados en otra consulta.
Los investigadores deben estar quietos al abrir: uno corriendo produce conflicto.
La consulta devuelve su identificador y el tope de turnos; ese tope no es una cotización monetaria.

## Avance

Cada cierre de turno guarda autor, agente, modelo, hora y texto de la respuesta.
Al completar una vuelta se envían las respuestas de los demás, atribuidas, y se pide aceptar,
sostener o refutar con evidencia. Los enfoques opcionales permiten diversidad deliberada.
La marca del pedido identifica qué respuesta pertenece a cada pendiente; una intervención humana
por la caja no se confunde automáticamente con una respuesta de la consulta.

Todos los cruces los media Lienzo, con flechas de consulta y límites de vueltas.
No se crean reglas A↔B permanentes. La toma de respuestas es idempotente entre el hook y la vigilancia.
La vigilancia periódica cubre tarjetas remotas y respuestas llegadas con el servidor caído.

## Síntesis y cierre

`SIN CAMBIOS` de todos permite convergencia antes del tope. Un investigador sintetiza las posturas
con atribución y desacuerdos visibles. Por defecto los otros revisan con `REPRESENTA BIEN` o su
corrección; las objeciones quedan junto a la síntesis. La revisión puede deshabilitarse explícitamente.

La muerte, detención, salida o vencimiento de un investigador permite continuar si quedan al menos
dos; en caso contrario la consulta se cancela con motivo. Si sale el sintetizador, se reasigna.
Cancelar conserva lo producido y no envía vueltas nuevas.
La corrección de síntesis tiene su etapa propia cuando corresponde; no reducir todos los estados
a abierta/cerrada. El código vigente es la referencia para las transiciones concretas.

## Persistencia y memoria

El estado operacional vive en `~/.lienzo/consultas/<id>/`: JSON, respuestas y síntesis en Markdown.
Se recupera al reiniciar. La síntesis se captura en la memoria como observación con su origen;
no convierte acuerdos de modelos en reglas vigentes ni en una verdad probada.
El coordinador puede recibirla mediante el canal ya existente.

## Réplica puntual

`POST /consultas/<id>/replica` con `para`, `de` y `vuelta` reenvía una respuesta que faltó leer.
Valida consulta existente/abierta, participantes y respuesta fuente. Usa una marca de réplica,
deja flecha y registro de destinatario, autor, vuelta y fecha.
No crea un pendiente, no modifica respuestas guardadas ni altera el tope o avance de vueltas.
Su respuesta no se toma como la respuesta del pendiente de discusión.
Un error de reenvío no expulsa al participante ni habilita reintentos infinitos.

## Interfaz

Las tarjetas y flechas de consulta tienen un aspecto propio y muestran participación/vuelta.
La vista completa permite leer vueltas, síntesis y objeciones; el historial conserva consultas cerradas.
El tamaño de respuestas y síntesis se calcula con el texto recibido por el frontend y se muestra
en caracteres; no es una medida de calidad ni de tokens facturados.

## API y cliente

| Acción | Interfaz |
|---|---|
| Abrir | `POST /consultas` |
| Listar | `GET /consultas` |
| Leer | `GET /consultas/<id>` |
| Cancelar | `POST /consultas/<id>/cancelar` |
| Reenviar | `POST /consultas/<id>/replica` |
| Python | `coordinar.consulta`, `consulta_estado`, `consulta_replica` |

El cliente de coordinación resuelve la sesión coordinadora y usa el canal de Lienzo.
Las firmas y nombres opcionales actuales se consultan en ese cliente antes de armar un pedido.

## Verificación y pendientes

Las suites `test_consulta*.py`, las pruebas del cliente y los recorridos UI cubren apertura,
límites, marcas, idempotencia, vuelta, síntesis, recuperación, réplica y errores.
No confundir fixtures con una consulta real entre agentes. La consolidación no da por realizadas
pruebas que sólo estaban planteadas en las antiguas tareas.
Los pendientes generales de coordinación continúan en [Pendientes](../PENDIENTES.md).
