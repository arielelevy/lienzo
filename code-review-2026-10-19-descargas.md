# Traer descargas entre PCs

Revisión del delta de descargas: origen, receptor, rutas HTTP, menú de PC,
modal y pruebas. Alcance fijado por el pedido de Ariel. Misma sesión, sin delegación.

## Recorrido secuencial

- Explorer: se recorrió el tablero compilado con Chromium y API fixture: clic
  derecho sobre la PC, lista, selección y confirmación. Captura local ignorada:
  `pruebas-agenticas/resultados/downloads/confirmacion.png`.
- Analyser: requisitos del pedido: últimos archivos, carpeta Descargas real,
  permiso explícito y elección antes de sobrescribir. Se conserva el transporte
  firmado y cifrado existente. No requiere mantener Chrome abierto.
- Designer: siete casos backend y tres recorridos UI; se reutilizan 19 casos de
  PCs. Se amplió el E2E del puente para copiar 400 KB y rechazar sobrescrituras
  sin confirmar, con dos servidores aislados y navegador cerrado.
- Executor: 25 pruebas backend y 22 UI con salida 0; Ruff, lint y build con salida
  0. E2E `node web/tests-ui/tailchrome-e2e.mjs` con salida 0. El helper y la red
  Tailscale están sustituidos en ese E2E; HTTP, cifrado, firmas y disco son reales.
- Detective: se corrigió la identidad de archivos en Windows usando os.stat en
  vez de DirEntry.stat; se corrigió la protección de destinos nuevos aparecidos
  durante la copia y el tipo del foco en TypeScript. Se repitieron los controles
  afectados. Se inspeccionó la captura de confirmación.

## Revisión de código

Se revisaron límites de bloques, tokens HMAC, nombres relativos, permisos de
copy_roots, rutas locales, CSRF, integridad SHA-256, identidad del origen y destino,
limpieza de temporales y respuestas tardías. El origen permite sólo la carpeta
Descargas detectada por Windows. Habilitarla conserva las otras opciones y rechaza
configuración corrupta. La lista vence y la selección se consume una sola vez.

Los archivos nuevos se publican con creación exclusiva. Los existentes requieren
confirmación y se vuelven a comprobar antes del reemplazo. No se agregan dependencias.
No se detectaron hallazgos críticos o altos abiertos en el delta revisado.

## Límites reales

La prueba entre las dos PCs del usuario y la descarga de sus notas siguen pendientes
de actualizar el destino. Los trabajos viven en memoria: continúan al cerrar el
modal, pero no sobreviven al reinicio del servidor. No se midieron mutaciones ni
se aceptaron casos o baselines: las ejecuciones directas anteriores no equivalen
a un PASS certificado por la compuerta agéntica.

## Ajuste del estado final

Reporte real de Ariel: los archivos llegaron y el contador alcanzó el total,
pero la barra permanecía visible. Explorer revisó el componente y el reporte;
Analyser distinguió transferencia activa y resultado terminal; Designer amplió
los recorridos existentes para exigir mensaje final, ausencia de barra y cierre;
Executor ejecutó los tres recorridos Chromium sobre la UI compilada (3 con salida
0), lint y build (salida 0); Detective contrastó el resultado y revisó el delta.
La barra se renderiza sólo en waiting/copying, también desaparece ante error y se
conservan los errores por archivo. El estado recibido ofrece Cerrar y volver a la
lista; se oculta la instrucción de selección durante el trabajo. Sin cambios al
transporte ni escrituras adicionales a los archivos. Sin hallazgos abiertos en
este delta. Se reutilizó el diseño previo sin aceptar casos ni baselines nuevos;
esta ejecución directa no certifica PASS de la compuerta.
