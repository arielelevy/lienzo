# Codex CLI: envío a la consola visible

Alcance: `lienzo/sessions.py`, `lienzo/send.py`, las regresiones de envío y la documentación del transporte. Revisión focal con el skill code-review/code-audit. Los cinco roles de pruebas agénticas se trabajaron secuencialmente en esta sesión; el registro y las propuestas quedan en `.temp/coordinacion/2026-10-17/codex-console-evidencia/`. No se aceptaron casos, baselines ni mutaciones, ni se marcaron tareas completadas.

## Problema y comportamiento

Una CLI normal quedaba bloqueada porque `codex queue` no puede acreditar que el UUID del rollout siga siendo el hilo visible después de `/new` o `/clear`. El proceso podía mantener abierto el archivo anterior y la cola ejecutar un turno oculto. No se quitó esa guardia de queue.

La fachada elige ahora la consola para Codex CLI y mantiene queue para Codex Desktop. El envío nativo usa el PID y FILETIME observados en la tarjeta; el subproceso abre y conserva un handle del proceso, verifica su creación y clasificación Codex, comprueba la pertenencia a la consola y rechaza otra TUI en la misma consola. Comprueba que el dueño siga vivo antes de cada escritura, incluido Enter. Los panes tmux conservan su comprobación de destino. Las ejecuciones externas, sesiones detenidas, permisos y diálogos mantienen sus guardas.

Un envío nativo reserva su recibo antes de escribir y no repite el mismo texto cuando el resultado sigue pendiente o incierto. La aceptación de las teclas se publica como encolada. La entrega requiere un turno posterior y el hash completo del mensaje; también se admite la confirmación correlacionada del hook. Los acuses viejos de queue se conservan como historial y sus resultados tardíos no sustituyen el envío nativo actual. El sondeo de queue no intenta confirmar recibos de consola.

El cambio no acredita la identidad del hilo para queue CLI. Es un transporte por consola, dirigido al proceso actual. La escritura puede quedar sin confirmación si no se observa el turno receptor; no se convierte ese estado en entrega ni se reenvía automáticamente.

## Hallazgos corregidos durante la revisión

- La marca general de origen compara sólo 120 caracteres. La confirmación nueva exige además SHA-256 del texto completo y tiempo del turno posterior al recibo. Una prueba con prefijo idéntico y sufijo diferente impide el falso acuse.
- `WriteConsoleInputW` requiere unidades UTF-16; la conversión de un carácter fuera del BMP fallaba con `ctypes.ArgumentError`. La representación de eventos ahora conserva esas unidades. La prueba real mostró que Codex no presenta el emoji en el editor aunque Windows acepte los eventos. Por eso `compose_send` conserva esos mensajes y rutas en un archivo UTF-8 y sólo escribe su referencia. El inyector Codex rechaza texto fuera del BMP antes de escribir nada, para evitar una pérdida parcial silenciosa.
- Se conserva el recibo al cambiar el identificador de hilo dentro del mismo proceso. La copia de un recibo histórico de queue no se interpreta como entrega del mensaje nuevo.

No se añadieron dependencias, excepciones de permisos, cambios de seguridad ni envíos a conversaciones ajenas. Se revisaron errores, cierres de handles y consola, doble envío, resultados tardíos y compatibilidad Desktop/tmux. Ruff y `git diff --check` aprobaron el corte focal.

## Evidencia medida

- Focal final: 147 pruebas aprobadas en 6,07 s, incluyendo consola y recibos, adopción de transcripciones, queue Desktop, reglas de identidad, guardas comunes y recepción.
- Interfaz: 10 pruebas aprobadas. Se agregó una CLI con transporte tecleo al recorrido de formulario, resultado encolado y actualización de entrega por SSE. La API/SSE son fixtures declarados; no envían mensajes reales.
- ESLint focal y TypeScript: código 0.
- Antes de cargar el parche, el tablero real publicó para PID 12328 `envio.puede: false` y ninguna caja de envío. Evidencia: `codex-console-before.json/png`.
- CLI real descartable, PID 31728: `/status` observó `01a14c94-8f57-76d2-b2fd-43743cf81a85`; después de `/new` y elegir el worktree actual observó `01a14c94-b5fa-7d21-9a4b-420264a86ec2`; después de `/clear`, `01a14c94-ce51-7ba2-a7ec-e840809c3957`. El PID y FILETIME no cambiaron. Todos los comandos se enviaron por el inyector fijado al proceso. No se invocó queue.
- En esa CLI, el archivo UTF-8 conservó exactamente `revisión 🙂` y su referencia quedó visible en el editor sin enviar Enter. No se llamó a modelos. El proceso propio se cerró al terminar. Salida completa: `.temp/coordinacion/2026-10-17/codex-console-live-final.log` y capturas de consola en `codex-console-live/*.json`.

Las primeras reproducciones descartables detectaron `TERM=dumb`, el selector de worktree y la pérdida del emoji. Se conservaron como hallazgos, se ajustó el entorno del proceso de prueba y se incorporaron las acciones reales del selector. No se alteraron permisos para superar esos resultados.

Dos corridas globales iniciadas se detuvieron antes de cambiar fuentes: la primera por el acuse de 120 caracteres y la segunda por la pérdida real del emoji. Se terminaron exclusivamente los árboles de los runners propios identificados por PID/comando; el backend real no se reinició durante ellas. No se atribuye un PASS a esos intentos. Se ejecuta una regresión ampliada seleccionando los archivos que consumen envío, capacidad y adopción; el resultado se registra debajo.

## Límites

La prueba real acredita comandos locales y texto visible en una CLI; no constituye un turno de modelo enviado desde la UI de producción. El fallo intermitente previo de transferencias no se modificó en este parche. La compuerta global anterior contiene evidencia de otra versión y no certifica este corte. Los validadores de las propuestas informan falta de aceptación humana y huecos de cobertura formal de los estados; no se aceptaron referencias para ponerlos en verde.

## Cierre medido

La selección de archivos que consumen `send_to_session`, `puede_enviar`, `run_send`, `adopt_process` o `attach_transcript` dio **883 pruebas aprobadas en 67,34 segundos**, código 0. Log completo: `.temp/coordinacion/2026-10-17/codex-console-regresion-cierre.log`. Este conjunto incluye y se solapa con las 147 focales; no se suman como pruebas únicas. No es la suite global del repositorio.

La primera ampliada dio 882 aprobadas y una falla: `test_bootstrap_only_for_new_process_card[True]` exigía precisamente bloquear la consola después de un turno previo. Se actualizó el contrato a consola disponible tanto al iniciar como después de trabajar, sin consultar queue. Al editarlo quedó una segunda aserción antigua; se detuvo ese intento antes de corregirla. Las dos versiones previas de los logs se conservan. No se modificaron baselines ni se atribuye PASS a esos intentos.

Con la autorización de reinicio vigente, se avisó a Ariel y se ejecutó `POST /restart`, que devolvió `{"ok":true,"reinicia":true}`. La raíz volvió a responder HTTP 200. `GET /sessions` publicó para PID 12328, hilo `01a14c6f-f6af-7593-a0c3-63e77928b4ae`, `codex_console_start: 134367573677105611`, `envio: {puede: true, motivo: null, transporte: tecleo}`. El tablero real pasó de cero a una caja de mensaje; se inspeccionó visualmente la captura con el botón Enviar visible. Evidencia posterior: `codex-console-after.json/png`. No se mandó un mensaje de prueba a la conversación de producción.

Ruff final, `git diff --check`, ESLint focal y TypeScript aprobaron. Se conserva la autorización de push del mismo encargo; el commit registra sólo estos cambios, sus pruebas y documentación. El estado de release global continúa separado de esta corrección de envío.
