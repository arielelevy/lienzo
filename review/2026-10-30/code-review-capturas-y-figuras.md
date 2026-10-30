# Revisión del encargo de capturas y figuras

Alcance: generadores de documentación (`web/tests-ui/capturas.spec.ts`, nuevo helper de
`tablero-fijo.ts`, seis generadores de SVG), sus imágenes, README y referencia de Chrome.
Revisión estática en la misma sesión, con `code-review`; sin agentes adicionales ni commit.

## Hallazgos y decisiones

- Corregido: las capturas heredaban `route.fallback()` para lecturas desconocidas. El helper
  `aislarCapturas` permite sólo los documentos y assets locales; bloquea otras lecturas y
  WebSockets. Se instala antes de los fixtures; Service Workers deshabilitados en estos casos.
  El caso tablero verifica 404 para GET desconocido y 403 para POST desconocido. Los demás
  usuarios del fixture mantienen su comportamiento previo.
- Corregido: dos coordinadoras del mismo proyecto en el escenario de captura. Se conserva
  sólo la que declara el tablero fijo.
- Corregido: Aprendizaje y celular cortaban contenido al pie. La primera usa un viewport
  más alto y la segunda una captura de página completa. El tablero se recorta antes del pie.
- Corregido: hojas de salida de la prensa y ficha del selector tapaban rótulos. Se separaron.
- La antigua captura de Chrome se reemplazó por la UI real del visor alimentada con un frame
  inventado. La página de la huerta y su decoración de navegador son un fixture, no evidencia
  de una conexión a una PC. El texto alternativo lo declara.
- Pendiente de UI, fuera del generador: placeholder del buscador recortado a 390 px. Registrado
  en `PENDIENTES.md`, con fuente y reproducción. No se ocultó mediante CSS de captura.

## Validación y límites

- Build web correcto; aviso existente de Vite por chunk mayor de 500 kB.
- Primera ejecución de las diez capturas: 10 aprobadas. Ejecución ampliada: 10 aprobadas y un
  error de sistema de archivos al escribir `lanzar.png`. Repetición focalizada de tablero y
  lanzar: 2 aprobadas, incluyendo el oráculo nuevo de aislamiento. Once PNG generados y mirados.
- Se revisaron las diez metáforas. Fábrica, aprendizaje y pasos FDD se rediseñaron; delegar,
  Jev y medición FDD perdieron la losa común. Central, fichero, plugins y scheduler conservan
  su mecanismo. La medición conserva sus números y proporciones originales.
- Enlaces: 53 referencias locales y 18 anclas de README/Chrome, cero roturas. `git diff --check`
  sin errores. Los SVG se generan con el kit local, sin scripts ni publicación a galerías.
- El runner de `pruebas-agenticas` terminó con código 1: timeout en `infografias-build`, luego
  de dos pruebas (`..` en el log); tampoco existe baseline. No hay PASS certificado, no se
  fijó referencia ni se corrieron mutaciones. Log:
  `pruebas-agenticas/resultados/infografias/intentos/2026-10-30T12-57-54.419Z-27080/salidas/infografias-build.intento-1.log`.
- Los chequeos directos de las diez figuras, en ambos temas, dieron consola limpia y cero
  extremos sueltos; se repitieron las variantes ajustadas. Las tres metáforas nuevas también
  se renderizaron a 390 px. No se hizo una auditoría
  geométrica volumétrica ni una suite completa de la aplicación: el alcance es documentación.

El borrado previo de `code-review-2026-10-27.md` no pertenece a este encargo y no se tocó.
