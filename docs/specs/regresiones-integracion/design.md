# Dos regresiones de integración

Encargo del 2026-10-25 16:28. Base integrada: 6a3beef. Sin cambios en las dos pruebas originales.

Explorer: se reprodujeron las dos fallas en esa base. El handler HTTP de coordinadora escribía por segunda vía mediante sessions.touch después de llamar al setter; esa vía escapaba del contrato usado por ambos listeners. El filtro TEMP impedía incluso resolver un proyecto existente por su remote explícito.

Analyser: conservar la paridad HTTP y la persistencia de preferencias/propuestas aunque el rol no cambie. La exclusión temporal protege las escrituras y la asociación por carpeta; no debe impedir una consulta por remote conocido. No se crea memoria ni se habilitan carpetas por leer contexto.

Designer: reutilizar intactos los dos casos denunciados y sus módulos de integración. Añadir persistencia real en disco para el mismo rol true/false y un recorrido de contexto por remote seguido de intentos de escritura denegados. Ampliar a federación, rechazo manual, Desktop, campos por PC, servidor y conocimiento. Sin servicios pagos ni mutaciones de producción.

Implementación: sessions.set_coordinator concentra la persistencia; el handler no hace I/O adicional. resolver_proyecto omite candidatas por carpeta excluida, pero conserva la búsqueda por remote existente. Los guardas de proyecto_de_carpeta, registrar_sesion y capturar quedan vigentes.

Executor y Detective conservan salida y veredicto en pruebas-agenticas/resultados/regresiones-integracion. Son pruebas HTTP con fixtures locales y persistencia aislada; no una prueba visual ni de una PC remota. No se fija baseline ni se aprueban mutaciones. Las fallas ajenas de xfer, deadline y rendimiento quedan fuera del encargo.
