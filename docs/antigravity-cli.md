# Antigravity CLI (Windows)

[Volver al README](../README.md)

Se puede elegir **Antigravity** en «Lanzar CLI». Lienzo detecta `agy.exe` y busca la instalación
oficial en `%LOCALAPPDATA%/agy/bin`, aunque la terminal todavía tenga un PATH anterior.
La API de lanzamiento acepta `agent: "antigravity"` y `model`; `resume` usa `--conversation`
cuando se proporciona un identificador válido. Los comandos de mantenimiento y el modo `--print`
no se muestran como tarjetas interactivas.

Esta integración permite pantalla y envío de texto a la terminal. Chat puede consultar historial
visible parcial de SQLite bajo demanda, si la propiedad nativa del archivo de presencia y la
fecha de creación del proceso identifican una sola conversación. No ofrece coordinadora, reglas `on_stop`,
cuotas ni restauración automática de esas tarjetas. El estado de actividad no se confirma por
transcripción. Los permisos se contestan en la terminal; con ☠ Auto-aprobar TODO prendido, el
lienzo contesta crear o editar archivos, correr comandos y el acceso puntual fuera del workspace
(ver [Las automatizaciones](../README.md#las-automatizaciones)).
El inicio de sesión se hace en Antigravity; WSL no está soportado por esta integración.
La tarjeta muestra «actividad sin confirmar»: el estado operativo de la API lleva
`state_source: "unverified"` y no certifica que esté trabajando o que haya terminado.
`screen_observation` declara fuente, hora y disponibilidad de la lectura; el modelo del pie
Gemini verificado en agy 1.4.3 es una etiqueta visible, no un ID canónico. No se extraen respuestas
de la pantalla. Una lectura fallida o un pie no reconocido deja el modelo sin observar.
La hora pertenece a la última muestra publicada: sondeos idénticos no actualizan esa hora ni
persisten la tarjeta, emiten SSE o generan otra captura de memoria.
Los IDs de `--conversation` se validan como UUID, formato observado en la caché local de agy.
`resumed: true` sólo indica que se agregó ese argumento al comando; no confirma que agy haya
recuperado la conversación. La reanudación real no se verificó en esta tanda.
La API rechaza crear o reactivar reglas `on_stop` desde un agente de terminal sin lector de turnos,
también si el origen es remoto o su agente no puede verificarse. Las reglas `at` siguen disponibles.

El lector inicial usa `mode=ro`, `query_only` y snapshots compatibles con WAL; vuelve a verificar
identidad al terminar y descarta toda la lectura ante ambigüedad, rotación o formato no soportado.
También exige el SHA-256 del ejecutable observado en esta tanda: una actualización desconocida
cierra el lector hasta revisar su compatibilidad. La API informa `codec_contract` y `executable_sha256`.
Decodifica únicamente campos conocidos de `gemini_coder.Step` observados en agy 1.4.3, sin nueva
dependencia protobuf. Omite razonamiento, firmas, argumentos y resultados de herramientas;
aplica el filtro habitual de secretos a los textos visibles. Ese filtro reconoce patrones conocidos,
no garantiza detectar secretos arbitrarios escritos como texto libre. Máximos por consulta:
512 pasos, 1 MiB por BLOB, 4 MiB de BLOB acumulado y 250 ms de lectura SQLite más espera por bloqueo.
La ventana truncada se declara en `meta.truncated`; un cursor fuera de ella se rechaza explícitamente.
El panel consulta al abrir o cambiar de vista; no es seguimiento continuo del historial.
El historial no adopta IDs ni modifica estado o respuestas persistidas. Todos sus turnos llevan
`history_only: true`, `ended: false` y «fin sin confirmar». Aún falta validar la máquina de estados
con transiciones reales; `terminalOnly` y el bloqueo de `on_stop` se conservan.
