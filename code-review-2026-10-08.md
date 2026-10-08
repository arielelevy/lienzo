# Chrome remoto: apertura, entrada y popups

Alcance: cambios en `browser_window.py`, `RemoteBrowser.tsx`, sus pruebas y uso de PowerShell 7 en el runner. Revisión estática de los cambios, sin auditoría global de dependencias.

## Hallazgos corregidos

- La captura principal no incluía ventanas propiedad de Chrome: se componen los popups visibles del mismo proceso y de la ventana seleccionada, en orden de pintura. No se captura el escritorio ni otras aplicaciones. Los popups quedan recortados al área de la ventana compartida.
- `mouse_event` no informa si Windows acepta el clic: se usa `SendInput` y se comprueba su resultado. La selección de ventana y la comprobación de posición permanecen vigentes.
- Las actualizaciones de imagen cambiaban el callback de error y reiniciaban la cola de entrada. El callback se guarda en una referencia y la cola conserva su ciclo de vida.
- Un arrastre táctil se traducía en selección: ahora el toque envía presionar/soltar y el arrastre envía rueda, sin botón presionado.
- El cursor local permanecía como flecha: el worker transmite cambios de cursor del sistema, incluso sin cambios de imagen; la interfaz acepta sólo formas conocidas.
- Los modificadores se sincronizan antes de una tecla ordinaria, para conservar combinaciones como Ctrl+A aunque falte el evento inicial de Control.
- La apertura automática espera perfiles y catálogo de ventanas; abre sólo cuando ese catálogo está vacío. Recuerda el perfil por PC, cancela resultados tardíos y muestra error si Chrome no abre una ventana.

## Verificación

- 45 pruebas de ventana y canal: código 0.
- Seis recorridos de UI con Chrome y peer simulados: código 0; incluyen perfil recordado, recarga sin duplicar apertura, PC caída, modo por pestañas, canal de ventana, toque, arrastre táctil y cursor de enlace.
- Build TypeScript/Vite y lint de cambios: correctos. Vite conserva el aviso existente de bundle mayor a 500 kB.
- Runner agéntico de build/lint: comandos correctos, pero código 1 por baseline ausente. No se fijó baseline ni se declaró PASS certificado.

## Límites y pendientes

Se comprobó el menú de Chrome real en ar-it33940 después del despliegue, con el perfil globant.com visible. Evidencia ignorada por Git: `pruebas-agenticas/resultados/chrome-popup-real.png`. El popup se compone dentro de la ventana compartida; su sombra conserva un fondo oscuro en PrintWindow.

La verificación con entrada de accesibilidad detectó keyCode=0: se deriva el código para combinaciones conocidas y se envía texto Unicode para caracteres sin modificadores. No se envían teclas desconocidas al worker.

El parpadeo informado en el modo por pestañas no tiene una causa reproducida. La reparación del runtime de Codex permitió ejecutar comandos nuevamente, pero no modifica el binario de Codex ni garantiza que su bug de permisos no reaparezca.

## Revisión documental del README y arquitectura publicada

Se leyó el README completo y se contrastaron los puntos cambiados contra las fuentes. El enlace a DISENO.es.md devolvía 404 porque .gitignore lo mantiene interno; se reemplaza por la arquitectura pública sin publicar ese archivo. Se añade la captura real y el recorrido del modo ventana: WebSocket/TCP, cifrado entre peers, pipes al worker, captura PrintWindow y entrada Win32. No se atribuye UDP, RDP ni una latencia medida al transporte de Chrome.

Se corrigen afirmaciones desactualizadas: cierre remoto Windows existente en server.py/kill_agent.py; fuentes de estado que incluyen diálogos del buffer; agentes admitidos por el lanzador; flechas deshabilitadas hasta 900 px inclusive. Se documentan las rutas de Chrome y cierre forzado, y los módulos incorporados. SendBox deshabilita su editor al enviar; SelectionBar permite editar durante el envío masivo, que conserva el riesgo documentado. El límite de 20.000 sobrantes y la pérdida del diagnóstico genérico de Git siguen presentes en xfer.py y health.py. Las mediciones históricas conservan su fecha y no se presentan como corridas nuevas.

La revisión de las limitaciones es estática, no una reproducción nueva de cada fallo. No se modificó código funcional de Lienzo. La actualización del sitio agrega HTML/SVG y una imagen, conservando sus interacciones existentes y su audiencia pública. Se revisaron enlaces locales, referencias de imagen, IDs y anclas. Las evidencias de las cinco etapas secuenciales quedan en resultados; no se acepta baseline ni se certifica PASS.

## Cuenta de GitHub por repo (`lienzo/cuenta_github.py`, health y auto-aprobar)

Alcance: `cuenta_github.py` (nuevo), `health.py` (medición de `git_auth`), `sessions.py` (`repos_de_remote`), `server.py` (enganche), pruebas nuevas en `tests/test_cuenta_github.py`. Revisión con el skill `code-review` (medium), dos pasadas: una sobre la primera versión y otra sobre las correcciones.

## Hallazgos corregidos

- Sólo se fijaba la primera carpeta viva con ese `origin`: una segunda copia o worktree del mismo repo seguía con el helper global y su push daba 403 mientras la tira decía «ok». Ahora `repos_de_remote` devuelve todas y health las fija todas.
- `asegurar` devolvía la cuenta elegida aunque `git config` fallara (`.git/config.lock` tomado por un git de la sesión): health creía que había cambiado y volvía a medir con el helper viejo. Ahora devuelve la cuenta que quedó.
- `gh auth status` con una cuenta que falló («Failed to log in to ... account B») le colgaba el «Active account: true» a la cuenta anterior. La que falló ya no cuenta ni arrastra sus líneas.
- `gh auth status` (que valida cada token contra la API) corría por cada url y cada vuelta de health: cache de un minuto, y una respuesta vacía no se cachea.
- Con el token vencido de verdad, cada vuelta de health forzaba una re-elección (status + token + api por cada cuenta): una forzada que no encontró nada mejor no se repite hasta `REELECCION_TTL_S`.
- `_decisiones` era estado muerto: se reemplazó por esa memoria de re-elecciones forzadas.
- `_carpeta_para` quedaba sin uso en producción: vuelve a ser quien decide dónde corre el `ls-remote`, sobre la lista de repos vivos.
- Un `GH_TOKEN`/`GITHUB_TOKEN` heredado del entorno hacía que `gh auth token --user X` devolviera ese token para cualquier X: se vacían al consultar a gh y adentro del helper.

## Aceptado sin cambio

- `fijar` escribe dos valores con dos `git config` (la clave lleva un helper vacío que resetea la lista global y el de la cuenta): entre uno y otro el repo queda unos milisegundos sin helper y un push justo ahí falla sin pedir nada, no con 403. Hacerlo atómico pediría un archivo incluido desde `.git/config`; no vale la complejidad para esa ventana.

## Evidencia

- `tests/test_cuenta_github.py` (23 casos) y `tests/test_health.py`, `tests/test_identity.py` en verde; suite completa de backend en verde.
- En vivo: con la cuenta activa de `gh` en `ariel-levy_globant`, `git credential fill` en `D:/Apps/lienzo` responde `username=arielelevy` y `git push --dry-run` pasa; al reiniciar el server, health fijó solo `D:/Apps/Teorema` (origin `erdos-82`) a `arielelevy` y su push en seco pasa.

