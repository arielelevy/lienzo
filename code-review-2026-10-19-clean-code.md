# Revisión y simplificación de Lienzo — 2026-10-19

Alcance solicitado: todo el código. Se realizó un barrido estático del inventario
versionado completo: 396 archivos de Python, TypeScript/TSX, JavaScript/MJS y CSS,
98.170 líneas, incluidas las pruebas, antes del delta. La revisión profunda se centró
en los cambios y en identidad, acceso HTTP, parámetros de API, memoria/aprendizaje,
coordinación y QR. Un barrido no equivale a verificar manualmente cada rama.

## Correcciones y simplificaciones

- Parámetros de conocimiento y aprendizaje: dos lectores idénticos y tres conversiones
  de enteros pasan a `conocimiento_params.py`; sin cambiar los valores por defecto ni
  el contrato de errores.
- Servidor: se retiran 14 condiciones redundantes. `_is_local()` ya rechaza túneles;
  `_authed()` ya contempla acceso local. Permanecen las guardias de Origin, firma,
  autenticación y aprobación de las rutas. Pruebas de seguridad focales verificadas.
- QR: Setup y UrlQr usan un único hook. Una respuesta tardía no sustituye el QR de otro
  texto/tamaño, y un resultado anterior no se muestra para un texto nuevo o vacío.
- Lectura Codex: las CLI nuevas delegan el rollout al daemon. Se coteja el nombre
  completo del pie visible contra el índice SQLite en modo de sólo lectura. Se exige
  un único hilo TUI en la misma carpeta física, cabecera del rollout válida, dos
  observaciones iguales del pie y la misma creación del proceso. Rutas `\\?\` y
  normales se comparan por identidad de carpeta. La conexión SQLite se cierra
  explícitamente. Esto produce observación de lectura, nunca autorización de queue.
- Panel: una sesión detectada sin transcripción explica que falta identificar la
  conversación. No se etiqueta libre una sesión corriendo ni una tarjeta de barrido
  sin historial identificado.
- Aprendizaje: el alta de encargos, API y cliente transportan contexto y controles
  declarados. La validación ocurre antes de crear nodos o cuerpos. Tipo desconocido,
  contexto inválido y controles no admitidos se rechazan; los repetidos se deduplican.
  Las pruebas recorren alta normal → consulta de patrones y conservan estado pendiente,
  creencias vacías y checklist sin adopción automática.
- Limpieza menor: diccionarios equivalentes, condición de texto y los 15 hallazgos de
  Ruff en dos archivos de pruebas. No se reemplazaron capturas de errores por suppress
  de forma masiva ni se agregaron capas sin uso.

## Evidencia previa al corte final

- `/status`: commit d6db531 pusheado. 44 pruebas focales y 73 del caso agéntico de cola;
  su configuración aislada carece de baseline. Reporte específico conservado.
- Backend afectado antes de ampliar el productor de aprendizaje: 238 pruebas pasan.
- Identidad tras cerrar explícitamente SQLite: 13 pruebas pasan.
- Aprendizaje, coordinación, conocimiento, identidad y transferencia: 114 pruebas pasan.
  Una corrida previa de los casos nuevos tenía una aserción incorrecta que trataba la
  respuesta paginada como lista; se corrigió contra su contrato `total/nodos`.
- UI focal: 8 pruebas Chromium pasan con escrituras interceptadas; 136 recorridos del
  caso global también pasan. Las capturas y trazas quedan bajo node_modules.
- Ruff global, ESLint y TypeScript pasan; build de producción pasa, con aviso existente
  de bundle de 613 kB. `npm audit --omit=dev`: 0 vulnerabilidades informadas. El backend
  de producción declara sólo biblioteca estándar; no se auditó todo el Python global.
- Primera global: backend agotó 450 s; frontend lint/build/unit/UI dieron código 0.
  El timeout se elevó a 900 s para la siguiente medición; no se alteraron baselines.
  La evidencia final del runner y su compuerta prevalecen sobre estas mediciones
  parciales. No se afirma PASS de aceptación con mutaciones antiguas o sin aprobación.
- Medición viva: después de reiniciar el servidor, `/sessions` asocia PID 9100 con el
  UUID correcto y `/turns` devuelve un turno real. La terminal siguió trabajando.

## Hallazgos que permanecen pendientes

Hallazgo adicional al contrastar el antecedente de GIST: la prueba heredada
`test_real_adapter_reconnects_after_its_launcher_exits` copiaba `cmd.exe` bajo el
nombre `claude.exe`. La primera global la incluía. Se detuvo el árbol de procesos de
la segunda corrida tras verificar su comando y luego se verificó que los seis PID
del árbol ya no estaban vivos. Se retiraron la copia y el launcher específico. La
prueba nueva usa el Python original y verifica con procesos/FILETIME reales que un
registro no convierte ese proceso en un Claude autorizado. Los demás contratos de
reconexión mantienen sus dobles explícitos. No se atribuye a esa cobertura una
reconexión positiva real; esa medición requiere un entorno autorizado con Claude.
Una búsqueda posterior no encontró copias de binarios en las pruebas Python.

1. Aprendizaje real: 0 creencias, 5 encargos sin clasificar y 0 patrones en `lienzo` al
   medir. El transporte corregido permite alimentar nuevos encargos, pero no sustituye
   clasificación histórica, investigación causal, evidencia ni veredictos humanos.
2. Prolog: propuesta localizada en ChatGPT, principalmente para Chesstudia. No existe
   implementación de Prolog en este repo; una prueba comparativa y su integración
   requieren definir el alcance. No se instaló nada ni se cambió el motor de creencias.
3. Complejidad estructural: el inventario inicial encontró `_dispatch` de conocimiento
   con 211 líneas, `do_GET` con 183 y parsers con 134–147. Son puntos para refactorizar
   por contratos en tandas posteriores; no se reescribieron durante esta corrección.
4. Identidad de envío Codex tras `/new` o `/clear`: sigue sin garantía autoritativa.
   La asociación por pie sólo sirve para lectura y no levanta el bloqueo de queue.
5. Calidad: quedan pendientes aceptación de propuestas y mutaciones vigentes. No se
   ejecutó mutación sobre el árbol compartido. Bandit, Radon y Vulture no están
   instalados; las métricas AST propias no son una medición de cobertura ni un informe
   de complejidad ciclomática formal.
6. Acceso celular: Tailscale permite prescindir del túnel público, pero el listener web
   actual se liga por defecto a loopback y Tailscale no se considera LAN sin login.
   No se debilitaron esas guardias ni se retiró la alternativa Cloudflare.
7. Cartel de `git.exe`: no se pudo atribuir a Lienzo con el log ni los eventos revisados.
   Falta el texto exacto o una captura del error; no se lo relacionó con `/status`.

No se cerraron tareas, promovieron creencias, aprobaron baselines ni ejecutaron
investigaciones con costo. El informe refleja revisión y alcance, no certificación
absoluta del producto ni aprobación humana.
