# Requisitos: Descubrir y direccionar varias distros de WSL

## Introducción

Hoy el tablero de Windows ve y escribe los agentes de WSL por `wsl.exe` sin distro: usa la distro
por defecto (`lienzo/tmux.py`, `_PREFIX = ["wsl.exe"]`), así que si hay más de una distro instalada
solo ve el tmux de la default y las demás quedan invisibles. Esta funcionalidad descubre las distros
de WSL de la PC, muestra de qué distro viene cada agente y permite elegir la distro al lanzar y al
escribir, sin romper el caso de una sola distro ni el de Mac/Linux nativo.

Origen: `PENDIENTES.md`, «Multiplataforma», ítem «Descubrir y direccionar varias distros de WSL»
(origen histórico `docs/porting-linux-2026-09-08.md`, gravedad baja).

## Requisitos

### Requisito 1: Descubrir las distros de WSL

**Historia:** Como usuario del tablero en Windows con varias distros de WSL, quiero que el lienzo
descubra automáticamente qué distros hay instaladas, para saber qué puede ver y manejar sin
configurar nada a mano.

#### Criterios de aceptación

1.1. CUANDO el server corre en Windows ENTONCES el sistema DEBE listar las distros de WSL instaladas
parseando `wsl.exe -l -q` (salida UTF-16, sin entradas vacías ni el placeholder «Windows Subsystem
for Linux»), y exponer esa lista en `/health` (campo `distros_wsl`).

1.2. SI `wsl.exe -l -q` falla, no existe o devuelve una lista vacía ENTONCES el sistema DEBE reportar
`distros_wsl: []` y seguir funcionando con el resto de las fuentes (win32, tmux nativo), sin errores
en el log más allá de uno informativo.

1.3. MIENTRAS el server corre en Mac/Linux (sin WSL) el sistema DEBE reportar `distros_wsl: []` y
todo el comportamiento de distros DEBE quedar inactivo (sin llamadas a `wsl.exe`).

1.4. CUANDO la lista de distros se consulta más de una vez dentro de un mismo ciclo de barrido
ENTONCES el sistema DEBE cachearla (no ejecutar `wsl.exe -l -q` por cada agente), refrescándola como
mínimo una vez por barrido o al vencer un TTL.

### Requisito 2: Etiquetar cada agente con su distro

**Historia:** Como usuario del tablero, quiero ver de qué distro de WSL viene cada agente, para
saber a cuál le estoy escribiendo cuando hay más de una.

#### Criterios de aceptación

2.1. CUANDO el barrido encuentra agentes en el tmux de una distro ENTONCES cada tarjeta DEBE llevar
el nombre de esa distro (campo `distro`), además de `backend: "tmux"`.

2.2. SI el agente corre en el tmux de la distro por defecto ENTONCES la tarjeta DEBE llevar igual el
nombre de la distro (no queda vacía ni «default»), para que el direccionamiento no dependa de
suposiciones.

2.3. SI el agente no corre en WSL (proceso de Windows o tmux nativo en Mac/Linux) ENTONCES la
tarjeta DEBE ir sin campo `distro` (o vacío), y la UI no DEBE mostrar etiqueta de distro.

2.4. CUANDO la UI muestra una tarjeta con `distro` ENTONCES DEBE mostrar el nombre de la distro de
forma visible pero discreta (junto al indicador de backend tmux), sin romper los recorridos
existentes de tarjetas win32 y tmux nativo.

### Requisito 3: Direccionar por distro al escribir y leer

**Historia:** Como usuario del tablero, quiero que los comandos de tmux lleguen al tmux de la distro
correcta, para leer y escribir agentes de cualquier distro, no solo la default.

#### Criterios de aceptación

3.1. CUANDO el server envía texto, teclas o captura la pantalla de una tarjeta con `distro` ENTONCES
el sistema DEBE ejecutar los comandos de tmux con `wsl.exe -d <distro>` (y sin prefijo si no hay
distro), preservando el comportamiento actual de `send-keys`, `capture-pane` y `list-panes`.

3.2. SI una tarjeta no tiene `distro` y el server corre en Windows ENTONCES el sistema DEBE seguir
usando la distro por defecto (prefijo `wsl.exe` sin `-d`), que es el comportamiento de hoy.

3.3. CUANDO el server lista panes para el barrido ENTONCES el sistema DEBE consultar el tmux de cada
distro descubierta (una llamada por distro) y unir los resultados, de modo que aparezcan los agentes
de todas las distros.

3.4. SI el tmux de una distro no responde o la distro no está corriendo ENTONCES el sistema DEBE
saltear esa distro (sin panes, sin excepción) y seguir con las demás, dentro del timeout actual de
15 s por comando.

3.5. CUANDO se compone un mensaje con adjuntos para un agente de WSL ENTONCES el sistema DEBE seguir
traduciendo las rutas con `ruta_wsl` (comportamiento actual, ahora con la distro de la tarjeta).

3.6. CUANDO el server lee transcripciones de agentes de WSL ENTONCES el sistema DEBE resolver la
home UNC de la distro correcta (`\\wsl.localhost\<distro>\home\<user>`), no siempre la de la distro
por defecto.

### Requisito 4: Lanzar agentes eligiendo la distro

**Historia:** Como usuario del tablero, quiero elegir en qué distro de WSL nace un agente nuevo al
lanzarlo, para repartir el trabajo entre distros.

#### Criterios de aceptación

4.1. CUANDO se lanza un agente vía `POST /sessions/launch` en Windows con WSL ENTONCES el pedido
DEBE aceptar un parámetro opcional `distro`; SI se omite ENTONCES el sistema DEBE usar la distro por
defecto (comportamiento actual).

4.2. SI el parámetro `distro` no está en la lista de distros descubiertas ENTONCES el sistema DEBE
rechazar el lanzamiento con un error claro (400 con el motivo), sin crear la tarjeta.

4.3. CUANDO la UI muestra el diálogo de lanzamiento en Windows con más de una distro ENTONCES DEBE
ofrecer un selector de distro (con la default preseleccionada); SI hay una sola distro ENTONCES el
selector no aparece o va fijo, sin fricción extra.

4.4. MIENTRAS el agente lanzado corre ENTONCES su tarjeta DEBE quedar direccionada a la distro
elegida (criterios 3.1 y 2.1 aplican desde el nacimiento).

### Requisito 5: No retroceder en los casos que ya funcionan

**Historia:** Como usuario del lienzo, quiero que el soporte de varias distros no cambie el
comportamiento de una sola distro ni de Mac/Linux, para no arriesgar lo que ya está probado.

#### Criterios de aceptación

5.1. MIENTRAS haya una sola distro de WSL el sistema DEBE dar el mismo resultado que hoy: mismas
tarjetas (ahora con `distro` en la tarjeta, y los comandos de tmux con `wsl.exe -d <distro>`),
mismos tiempos de barrido (la llamada extra de descubrimiento no DEBE sumar más de ~50 ms al ciclo
con la distro ya cacheada).

5.2. MIENTRAS el server corre en Mac/Linux el sistema DEBE ignorar todo el código de distros (sin
cambios de comportamiento, sin llamadas nuevas).

5.3. CUANDO se corre la batería de pruebas del repo ENTONCES todas las pruebas existentes DEBEN
seguir pasando sin cambios, y las nuevas de distros DEBEN cubrir al menos: parseo de `wsl -l -q`
(UTF-16 y vacío), etiquetado de tarjetas, prefijo por distro en los comandos de tmux, unión de panes
de varias distros, y rechazo de lanzamiento con distro desconocida.

## Aclaraciones

Respondidas por Ariel el 2026-10-10:

1. **Barrido de panes con varias distros: ¿en paralelo o en serie?** — En paralelo (un hilo por
   distro, misma forma que `fan_out`); en serie con una sola distro, sin cambio.
2. **¿Cada cuánto se refresca la lista de distros?** — TTL de 60 s; `wsl.exe -l -q` no corre por
   cada agente ni por cada barrido.
3. **Distro por defecto al lanzar: ¿siempre la de WSL, o configurable?** — La default de WSL, y el
   parámetro `distro` del launch manda. Sin clave nueva en `config.json`.
4. **Agentes sueltos (fuera de tmux) con varias distros: ¿buscarlos en todas?** — Correr `ps` en
   todas las distros solo si hay más de una; con una sola, el comportamiento de hoy.
5. **¿El campo `distro` viaja por federación?** — Sí, passthrough con la tarjeta, como ya viaja
   `backend`; sin lógica nueva del lado del peer.
