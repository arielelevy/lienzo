# Revisión de copia desde Chrome remoto

Alcance: cambios de `lienzo/browser_window.py`, `web/src/components/RemoteBrowser.tsx` y sus pruebas. Revisión focal autorizada por el pedido de corregir el portapapeles y las instrucciones de usuario.

Causa: la vista nativa reenviaba Ctrl+C a Windows remoto y tenía `onCopy` vacío. El texto nunca volvía al visor.

El cambio agrega un pedido explícito `copy` al canal existente y una respuesta `clipboard`. El worker activa y valida Chrome, copia y espera un cambio del número de secuencia antes de leer CF_UNICODETEXT. No devuelve el contenido anterior si no cambia. La memoria y el portapapeles se liberan con `finally`; las firmas Win32 conservan los handles de 64 bits y la lectura se limita a 2 MB. Los errores se muestran como avisos de entrada y no desconectan la captura.

La interfaz consume Ctrl+C en ambos modos y escribe el texto en el portapapeles del visor. En HTTP sin Clipboard API usa la operación de copia del documento con un textarea temporal y restaura el foco. No hay sincronización periódica ni lectura de otros formatos.

Verificación: 53 pruebas Python focales, 6 recorridos Playwright con PC/Chrome simulados, build y ESLint focal ejecutados con código 0. Ruff y `git diff --check` sin hallazgos. El build advierte por el tamaño del bundle. No se aprobaron baselines ni se midió mutación.

Límite: no se verificó Windows remoto real ni el pegado en una aplicación de la otra PC. El worker nuevo debe estar disponible en la PC que ejecuta Chrome y abrirse una conexión nueva; la compilación local no distribuye ese archivo al peer. No se publicó ni se reinició ningún servidor.

Sin hallazgos pendientes dentro del diff revisado. La validación entre PCs queda pendiente.
