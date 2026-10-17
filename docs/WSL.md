# WSL y direccionamiento de sesiones

Contrato consolidado de descubrimiento y direccionamiento entre distros.
Reúne el alcance funcional y las decisiones de las specs anteriores, sin conservar una lista paralela
de tareas. Hay cambios de código en curso en `tmux.py` y `backend.py`; este texto no los certifica.

## Identidad

Una tarjeta de WSL debe conservar la distro dueña del proceso y del pane de tmux.
Un número de PID o un target como `%0` no identifica por sí solo a la sesión entre distros.
Windows nativo y tmux nativo conservan su backend sin inventar una distro de WSL.
El campo `distro` viaja con la tarjeta a los peers; los comandos se ejecutan en la PC dueña.

## Descubrimiento

`tmux.distros()` descubre mediante `wsl.exe -l -q`, trata la salida UTF-16 y descarta vacíos
 y placeholders. El contrato acordado usa caché de 60 s, no una consulta por agente.
Una distro sin tmux no impide consultar las demás. En plataformas sin WSL no se ejecuta `wsl.exe`.
Las distros del sistema no se filtran sólo por nombre.

## Barrido

Consultar las distros descubiertas y unir sus panes, conservando la distro en cada resultado.
El acuerdo de diseño usa paralelismo entre distros y evita sumar demoras en serie.
Los agentes fuera de tmux se buscan en las distros que correspondan.
El tratamiento concreto de una lista vacía o una distro no disponible debe conservar el resto
de las fuentes y la visibilidad de errores; no se certifica disponibilidad por una lista histórica.

## Lectura y escritura

Los comandos de una tarjeta con distro usan `wsl.exe -d <distro>`.
Sin una selección explícita, el camino compatible usa la default de WSL donde corresponda.
Validar target y PID en la misma distro antes de teclear.
Pantalla, teclado, proceso, directorio y transcripciones deben resolver el mismo entorno.
La home UNC se obtiene para la distro correcta, no se reutiliza la home de otra.
Los adjuntos siguen la traducción de rutas admitida por el backend.

## Lanzamiento

`POST /sessions/launch` admite `distro` opcional y rechaza una desconocida con motivo.
El diálogo ofrece la elección cuando hay varias distros; con una sola evita fricción innecesaria.
El agente y su tarjeta deben nacer en el entorno elegido.
La disponibilidad de un binario en Windows no acredita instalación en una distro.

## Límites y recuperación

Los comandos externos usan `subproc.correr`, con límite y limpieza del árbol propio cuando vence.
Un fallo de una distro no debe colgar el servidor ni ocultar las restantes.
La caché se invalida cuando corresponde; no se persiste una lista vieja como verdad del arranque.
Los números de rendimiento de las specs eran objetivos de diseño, no mediciones actuales.

## Verificación

El alcance de pruebas incluye parseo UTF-16/vacíos, caché, plataformas sin WSL, prefijos de comandos,
identidad entre distros, unión de panes, ruta UNC, validación de targets y rechazo de launch inválido.
Las pruebas con tmux simulado no equivalen a lanzar o controlar un agente real.
Los pendientes de medición entre PCs y lanzamiento real se conservan en [Pendientes](../PENDIENTES.md).
