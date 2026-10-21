# Foto consistente del origen legacy

Alcance: _importar_una en conocimiento.py y regresión en test_captura.py.

La conexión mode=ro efectuaba consultas separadas sin transacción explícita.
Un escritor WAL podía actualizar el origen entre la copia de nodos y la lectura
del historial. La regresión determinista observó nodo anterior con cuatro cambios,
incluido el de la revisión posterior. Se añade BEGIN antes de leer el esquema.
Filas, historial y cursor salen ahora de la misma foto SQLite del origen.

La conexión continúa en modo sólo lectura y se cierra en finally, liberando su
transacción. El savepoint y la transacción central conservan su funcionamiento.
En WAL el escritor de la prueba hace commit mientras el importador retiene su
foto; no hay esperas ni sleeps para provocar la carrera. En rollback journal
una lectura prolongada puede demorar el commit del escritor hasta su timeout;
es una consecuencia de mantener la coherencia, sin ampliar permisos o bloqueos.

Explorer: inventario real local sólo lectura:0bases legacy activas,1registro en
importada. La lectura real se repitió fuera del sandbox después de un bloqueo de
apertura, sin immutable=1 que pudiera omitir WAL. No se ejecutó migración real.
Analyser: separar snapshot SQL de la procedencia/CAS pendiente.
Designer: commit concurrente WAL después de copiar nodos y antes del historial;
oráculo conjunto de nodo/historial/cursor, conservando la revisión nueva del escritor.
Executor: rojo1failed, verde1passed. Plugin ejecutar.mjs, caso aprobado
memoria-focal, sin --fijar:154passed,0failed,0skipped; runner rc0 igual al baseline.
Ruffcheck/formato y diff-checkrc0.
Detective: revisión independiente E sin bloqueantes en este delta; fuente y
prueba corresponden a los hashes abajo. No es PASS global ni cierra reimportación.

Corrida:2026-10-21T14-58-33.524Z-14416, estadoa10a5f8b53a33bff.
Evidencia ignorada:.temp/coordinacion/2026-10-21/legacy-snapshot-{red,green,plugin}.log,
legacy-snapshot-plugin.xml y legacy-snapshot-actual.parcial.json.
Informe independiente:.temp/resultados/E-legacy-snapshot-review.md.

Pendientes reales: aplicar actualizaciones de entidades con procedencia/CAS,
fuentes ya importadas sin snapshot histórico, prosa externa que no pertenece a la
foto SQLite y coordinación del rename con escritores vivos. No se comparan fechas
para autorizar sobrescrituras ni se aceptan actores declarados por una base vieja.
No se fijaron baselines ni se cerraron casillas. Cambio local, no desplegado.

SHA256 conocimiento.py:B43A850BCE1ECCAE9FAAAEF54575FD7372D246F33E8014E3213BC26D575B8281.
SHA256 test_captura.py:420F0CA174A9CB7F99C98E71CDF86BC5F1AC2263A2A98197A8F3D8D1CEBEAFAC.
