# Revisión 0.5.3: PC visible aunque sea única

Alcance: PcStrip.tsx, pruebas pcs/updates, README y versionado. Requisito explícito de Ariel:
la etiqueta de PC debe verse con una sola, porque desaparecen las opciones de su menú derecho.

Se elimina el guard que ocultaba la tira con menos de dos PCs; sólo se oculta sin datos de PCs.
La identidad viene de /peers, sin inventar IDs. Con una PC el chip queda activo y con menú; no se
ofrece Todas ni se guarda un filtro inútil al pulsarlo. Con varias sigue el comportamiento anterior.
El hook ya desactivaba filtros con una PC; esa regla se conserva, evitando ocultar tarjetas.

Verificación final: 32 Chromium aprobadas en build aislado, con escrituras bloqueadas. Comprueban
etiqueta y menú únicos, POST del target local correcto, apertura del detalle, tablero sin filtrar,
móvil390 sin desborde y filtros multi-PC. Captura del menú único inspeccionada. Lint, TypeScript
y build código 0; aviso conocido del bundle >500 kB. Runner lint/unit igual al baseline.

Fallo inicial de una prueba nueva: esperaba 10 tarjetas por 10 sesiones. La fixture y los casos
existentes muestran 8 tarjetas; se corrigió el oráculo a 8 antes y después de pulsar el chip.
No se cambió el producto para ocultar ese fallo ni se actualizó un baseline.

Sin hallazgos bloqueantes en el alcance revisado. Sin cambios backend, dependencias o instalaciones;
no se publica web/dist ni se aplica la actualización. El motor ya está separado y publicado:
origin/main y tag v0.1.0 coinciden en 35b10e5, repo público, árbol limpio (verificado por lectura).
No se acredita una nueva aceptación global ni se marcan tareas como completadas.
