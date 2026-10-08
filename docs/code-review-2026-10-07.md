# Revisión: Chrome remoto en Lienzo (perfil habitual pendiente de autorización)

Alcance: los cambios de esta sesión en `lienzo/browser_api.py`, `browser_remote.py`,
`browser_host.mjs`, `browser_profiles.mjs`, `server.py`, `mirror.py`, `protocol.py`, `secretos.py`, la vista
`RemoteBrowser.tsx`, su CSS, integración en App/Header/Vite, mensaje de Git en PcStrip y sus pruebas.
No es una auditoría completa del repositorio. Revisión estática secuencial en la misma sesión.

## Hallazgos corregidos

- Las entradas de teclado y capturas no podían viajar en claro por el transporte HMAC de peers.
  Se reutiliza el cifrado autenticado existente con clave derivada exclusiva y un identificador
  de pedido que impide aceptar una respuesta de otra operación. Se comprueba con pruebas aisladas.
- El generador de bloques de `secretos.py` sumaba todos los bloques en cada vuelta. Se reemplazó
  por un rango de igual cantidad de bloques para mantener formato y costo lineal con capturas.
- La PC elegida queda fijada; una desaparición del peer no cambia automáticamente al Chrome local.
- Los resultados de una vista o pestaña anterior se descartan; los eventos pendientes se vacían
  al desmontar la página. Las acciones incluyen destino y pestaña explícitos.
- No se reintentan automáticamente navegaciones, creación de pestañas ni entradas después de
  un timeout. La reconexión consulta estado. Hay límites de entradas, texto, tamaño y pestañas.
- Se agregó captura del puntero para soltar el mouse aunque el arrastre salga del área visible.
- La UI interpretaba todo `git: error` como red o Git colgado. Ahora conserva la incertidumbre;
  el caso observado era un `Repository not found` usando la cuenta equivocada.

## Controles revisados

La ruta de acciones requiere autenticación/CSRF y acceso local sin túnel. El listener de peers
valida firma antes del descifrado. CDP no se publica ni acepta métodos del cliente. No hay shell
al iniciar Node o Chrome, ni argumentos ejecutables controlados por la URL. Chrome usa perfil
propio, sandbox normal y loopback; alternativamente conecta al Chrome habitual autorizado por
su propio aviso. Se lee sólo nombre e ID de los perfiles. El endpoint se toma de una ruta fija
del usuario y se valida puerto/ruta; nunca admite un host enviado por el cliente. El cierre mata
exclusivamente al Chrome creado por el worker; en el habitual sólo desconecta el socket. Las páginas
usan sesiones multiplexadas sobre una conexión autorizada. Cancelar cierra también la solicitud
pendiente y una respuesta tardía no puede reconectar después de cancelar.
Las capturas y teclas no se escriben al log de peer. No se copiaron credenciales del Chrome personal.

## Evidencia y pendientes reales

- Primera corrida del runner: 1005 pruebas backend pasaron; una falló porque el contrato exacto
  de capacidades no incluía `browser.remote`. Se actualizó ese contrato al agregar la capacidad.
- Verificación posterior de salud, ruteo y cifrado: **61 passed**. Primer conjunto de ruteo/cifrado:
  **28 passed**. Build y unitarias del frontend pasaron.
- Se corrigió el hallazgo de lint sobre selección inicial de PC. La ejecución final queda registrada
  en `pruebas-agenticas/resultados/chrome` (ignorado en Git).
- `npm audit --omit=dev`: cero vulnerabilidades. `npm ci` informó dos de severidad alta en
  dependencias de desarrollo ya existentes; no se hizo un cambio de versiones fuera de alcance.
- En 570f4ac: runner backend **1006 passed**, lint/build/unitarios sin fallas, dos pruebas de UI
  con fixtures pasaron. El frente S ejecutó Chrome real aislado en ar-it33940: nueve controles
  pasaron y revisó la captura (teclado, mouse, navegación, historia, pestañas y cierre).
- Cambio de perfiles: dos pruebas Node de catálogo/endpoint y doce de backend pasaron; lint y
  build pasaron por el runner. Primer intento dentro del sandbox falló por permisos de entorno.
- Falta probar el permiso de conexión en el Chrome habitual de Globant. No se afirma que se
  haya conectado a ese perfil. Abrir un perfil y compartirlo son acciones distintas: Chrome
  elige el perfil predeterminado cuando hay varios activos. La UI informa esa limitación.
- Los requisitos, casos de navegador y mutación son propuestas; no se aprobaron ni fijaron baselines.
- Audio, descargas, selector de archivos, extensiones e IME no están certificados para esta vista.
  La transmisión usa capturas periódicas; no tiene la fluidez de video de un escritorio remoto.

No se identificaron otros bloqueos de seguridad en la revisión estática dentro de este alcance.
Queda pendiente verificar en vivo el Chrome habitual con permiso del usuario. El informe se
conserva en docs por ese pendiente, según el pedido de Ariel.

## Ventana real de Chrome — e137db1

Revisión estática de los diez archivos del cambio: destino explícito, transporte cifrado,
validación del ejecutable chrome.exe y de la ventana activa antes de enviar entrada,
límites de coordenadas, teclas y texto. La vista completa es ahora la opción predeterminada;
no requiere activar remote debugging. El modo por pestañas conserva sus requisitos anteriores.

Evidencia previa al pedido de detener pruebas: 61 casos Python pasaron y se observó una
captura local de la ventana completa de Chrome (1295 × 767). No se verificó la interacción
nativa en ar-it33940 ni el funcionamiento sin monitor. Windows debe mantener la sesión
abierta y desbloqueada. La liberación al salir cubre teclas; queda pendiente cubrir también
un botón del mouse mantenido al desconectarse. No se sincroniza el portapapeles remoto.

Recorrido agéntico secuencial: Explorer identificó las ventanas existentes; Analyser separó
el permiso CDP de la captura nativa; Designer agregó el caso de ventana completa; Executor
registró la evidencia anterior y dejó las restantes pruebas sin ejecutar por el pedido
explícito «sin probar»; Detective conserva esos pendientes. No se aceptaron baselines
ni se declara PASS de aceptación. Build e instalación se ejecutan como parte del despliegue.

Corrección de proporciones: la captura nativa conserva su relación de aspecto con
object-fit: contain. La revisión estática verificó que el mapeo del mouse descuenta las
franjas y usa la misma escala; los clics en franjas no se envían. La liberación de un botón
fuera de la imagen sí se transmite con coordenadas limitadas. Explorer identificó el
estiramiento CSS; Analyser localizó el mapeo asociado; Designer definió escala uniforme
y márgenes; Executor omite pruebas por instrucción del usuario; Detective mantiene
pendiente la verificación visual. Se compila para publicar la corrección de interfaz.

Vista de solapa completa: controles de Lienzo ocultos por defecto y disponibles en ⋮,
superpuestos sin reservar altura. El pedido de captura incluye el tamaño visible; el worker
ajusta solamente la ventana validada de chrome.exe, con límites 320–3840 por 200–2160,
sin moverla ni alterar el orden de ventanas. La captura y el mouse mantienen la misma
geometría. Revisión estática de los tres archivos: parámetros Win32 de 64 bits, límites,
selección explícita de PC/ventana y error visible si Windows rechaza el ajuste.
Explorer: barras ocupaban superficie; Analyser: proporciones remotas distintas; Designer:
menú superpuesto y ajuste de ventana; Executor: build de despliegue, sin nuevas pruebas
por instrucción vigente; Detective: funcionamiento visual y desconexiones aún no certificados.

Observación solicitada de la sesión real: CUA capturó el rechazo de foco de Windows y,
tras recargar, una imagen de 1270 × 609 en una superficie idéntica: ya no hay escalado CSS.
El Chrome capturado seguía sobredimensionado; el worker no declaraba DPI awareness.
Se agrega contexto DPI por monitor, intercambio temporal de foco Win32 con detach en
finally y comprobación posterior de que la ventana activa sigue siendo Chrome.
El error de entrada se informa sobre la captura sin detenerla. Se liberan también botones
de mouse mantenidos. Se elimina el gutter heredado del tablero y la solapa usa el título
de la ventana remota. Revisión estática: no se envía entrada si el foco no coincide, no se
aceptan ventanas de otro ejecutable, no se alteran permisos ni configuración de Chrome.
Explorer y Analyser usan capturas reales; Designer conserva controles mínimos; Executor
registra capturas y build de despliegue; Detective no certifica interacción hasta observarla.

La observación DOM midió devicePixelRatio=1.5: dimensionar Chrome en píxeles CSS producía
otra ampliación al presentar la captura. Ahora se solicita tamaño físico según esa relación,
con los límites anteriores. Si la ventana desaparece o el worker se reinicia, se vuelve a leer
el catálogo sin repetir clics ni teclas. Se conserva el socket CDP hasta desconexión explícita,
cierre de Chrome o reinicio del servidor. No existe en Chrome la opción de persistir el
consentimiento de auto-connect: https://github.com/ChromeDevTools/chrome-devtools-mcp/issues/825.
No se implementa aprobación automática del aviso ni se modifica seguridad de Chrome.
Revisión estática: escala de imagen y coordenadas comparten píxeles de origen; refresco
sólo de lecturas, detenido al cambiar/desmontar vista. Grabación y observación solicitadas
por Ariel constituyen la evidencia de Executor; sin certificación global ni baseline aceptado.

Latencia de mouse: se identificaron dos serializaciones, la cola HTTP del frontend y el
lock del worker que captura. Se separa el worker de capturas del worker de entrada y la
captura deja de ocupar la cola del teclado/mouse. La entrada mantiene su orden; no se
reintentan clics ni teclas. El intervalo de envío nativo pasa de 30 a 8 ms y el de lectura
de imagen de 250 a 80 ms después de cada respuesta, sin solapar capturas de una vista.
El menú muestra latencias de pedidos propios, sin inspeccionar tráfico del navegador.
La inspección de red por CDP fue denegada y no se repitió por otra vía.
Revisión estática: workers y locks independientes, target validado en ambos, liberación
limitada a las teclas/botones enviados por Lienzo; recuperación acotada a tres intentos de
lectura con aviso visible, sin reconectar CDP ni aprobar permisos de Chrome.
Explorer y Analyser localizaron colas; Designer separó canales; Executor guardó diez
capturas reales y una grabación GIF de 14,588 s; Detective deja pendiente la medida
del mouse después de instalar. No se afirma todavía una reducción medida de latencia.

Observación posterior en ar-it33940, e9000fb: clic sobre zona sin acciones de Nueva pestaña
respondió sin aviso de error; el menú mostró Mouse 92 ms e Imagen 172 ms. Una lectura
posterior conservó Mouse 92 ms y mostró Imagen 199 ms. Son tiempos de pedidos propios,
no medida de latencia física ni comparación antes/después. Captura 1920 × 914 presentada
en 1280 × 609 con devicePixelRatio 1.5, controles cerrados y perfil gestionado por globant.com.
Evidencia local ignorada: sesion/latencia.json, 04-latencia.png, 05-final.png y sesion-lienzo.gif.
Detective confirma esa observación puntual y deja pendientes teclado, latencia sostenida,
fluidez con carga y uso sin monitor. No se ejecutaron suites nuevas ni se aprobaron baselines.

Nueva instrucción explícita de Ariel: el Lienzo de la PC que ejecuta Chrome debe pulsar
Permitir automáticamente durante su propio pedido de depuración. Esto reemplaza la
decisión anterior de no implementar el clic. Se invoca el botón mediante UI Automation,
sin coordenadas, sólo en el diálogo nativo con título exacto y proceso Chrome dueño del
listener de loopback. Se exige un único botón visible y habilitado; ante ambigüedad o
timeout se informa error. Cancelación, reinicio y fin de conexión terminan el controlador.
No se cambian preferencias de Chrome ni se autorizan otros diálogos.
Explorer: captura aportada por Ariel y catálogo real confirman el diálogo español.
Analyser: Ariel informa que Tab/Enter funcionan y el clic no; causa del mouse pendiente.
Designer: invocación semántica del botón y estado visible de autorización remota.
Executor: build de despliegue y validación sintáctica; suites omitidas por «sin probar».
Detective: no hay todavía evidencia de conexión automática exitosa en ar-it33940.
Code review estático: limpieza de socket ante fallo, límite temporal y aislamiento por PID;
SetCursorPos deja de ignorar errores de Windows. Pendiente comprobar UIA en Chrome real.

Ariel solicita experiencia tipo escritorio remoto en modo ventana y consulta RDP.
Explorer: documentación primaria Microsoft de entrada fast-path, cursor y gráficos.
Analyser: Lienzo usa HTTP/TCP y PNG completos; captura y transferencia siguen separadas
de la entrada. No se atribuye toda la demora a la LAN sin medición.
Designer: referencia de cuadro, comparación de regiones de 64 píxeles y canvas local.
Executor: build de despliegue; suites no ejecutadas por instrucción anterior de Ariel.
Detective: reducción real de bytes y latencia todavía pendiente de observación remota.
Code review: caché limitada a un cuadro por worker; ventana, tamaño e ID deben coincidir
para producir un parche. Sin cambios se devuelve sólo metadato; referencia perdida,
cambio de ventana/tamaño o error producen cuadro completo. El receptor decodifica y
dibuja antes de pedir el siguiente cuadro; ID sólo avanza tras dibujarlo. No hay pérdida
de resolución ni reintento de entrada. Se desactiva Nagle en servidor y transporte entre
peers para evitar espera de paquetes pequeños. Sigue siendo HTTP/TCP, no RDP ni UDP.

Investigación de clic: Microsoft documenta que SetCursorPos ajusta silenciosamente la
posición al área de ClipCursor aunque devuelva éxito. Es una hipótesis, no una causa
medida en ar-it33940. La captura ahora limita tamaño y posición de Chrome al área útil
del monitor correspondiente; la entrada compara GetCursorPos con el destino pedido y
rechaza un clic que Windows haya desplazado. Handles de monitor y estructuras tipados
para 64 bits. Pendiente medir en vivo; no se afirma arreglado el clic sólo por revisar código.
UDP: WebRTC permite canales no ordenados sin reintentos para movimiento y canales
fiables para clic/teclado. Todavía no implementado; transporte actual HTTP/TCP optimizado.
