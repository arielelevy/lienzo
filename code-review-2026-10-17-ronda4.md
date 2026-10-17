# Revisión de la ronda de cuatro Codex

Alcance inicial de raíz: skills/lienzo/coordinar.py y tests/test_ronda4_root_coordinar.py. Los frentes documentan sus propios deltas en .temp/coordinacion/2026-10-17/ronda-cuatro/A-D.

Defecto reproducido en vivo: al lanzar B, A cambió de pid-25000 a UUID. El cliente consideró el UUID nuevo como proceso nuevo, le cambió el título e intentó entregarle B. El envío fue rechazado y no se reinterpretó como entrega; B se recuperó en la consola nueva, identificada y leída. El título de A se restauró y se comprobaron cuatro reglas de retorno activas.

Corrección: el inventario anterior al lanzamiento conserva las tarjetas y compara mediante reubicar (ID o pc/pid/cwd), de modo que el cambio de ID de un proceso previo no sea candidato. La prueba incluye una pasada con sólo A renombrada y una posterior con B nueva; sólo B recibe título y cableado. Seleccionar por PID aquí expresa identidad de proceso durante una operación de lanzamiento; el reparto sigue siendo por nombre.

20 pruebas del cliente pasan. El runner aislado conserva el resultado y sale 1 porque no hay baseline aprobado. Ruff detectó C408 en el test nuevo; corregido, Ruff final 0. Diff focal sin errores. Revisión estática del delta: sin hallazgos pendientes. No se añaden dependencias ni se cambian permisos, hooks o transporte.

Límites: la guardia nueva no hace atómico el lanzamiento; con dos lanzamientos independientes simultáneos en la misma carpeta el API aún no devuelve una identidad de proceso correlacionada. Esta ronda serializa lanzamientos y usa carpetas propias para C/D. No se afirma que los snapshots parciales de handles estén resueltos. La compuerta requiere baseline humano y no se publica PASS.

## Integración y revisión de las cuatro entregas

Se leyeron informes y fuentes estables: codex_identity.py (UUID canónico y segunda observación); patrones_desarrollo.py/patrones_evidencia.py (consulta por lote, vínculo activo y mismo proyecto, declaración y resultado separados); rondas.py (emisor resuelto a identidad vigente); Knowledge.tsx/knowledge.css (GET, encodeURIComponent/URLSearchParams, validación, cancelación, foco y contexto explícito). Cada frente conservó cinco roles y revisión propia. No se auditó como propio el delta anterior de otros frentes ni dependencias globales.

El catálogo fallido de conocimiento.spec.ts dependía de exactamente una petición antes del reintento. Ahora una fase explícita conserva 503 durante el montaje y cambia antes del click de Actualizar proyectos. Se mantienen las aserciones de error, recuperación vacía y desaparición del alert. Evidencia fallida preservada; sin alterar baseline.

Integración final: 247 passed in 32.57s backend; 16 passed (20.3s) UI; ESLint/build/unitarias 0. Ruff focal 0 y diff-check global 0 con avisos CRLF. Runner y compuerta aislados 1 por baseline ausente. Logs completos en .temp/coordinacion/2026-10-17/ronda-cuatro/raiz/integracion. No PASS global ni publicación.

## P0 confirmada pendiente

Prueba real de /new: después de elegir Use current Git worktree, consola vacía, el probe devolvió el hilo anterior como verificado y la API marcó entregado. En ese rollout anterior se contaron un mensaje y un ACK; la consola nueva siguió vacía. UUID/snapshot corrige defectos locales pero NO resuelve continuidad tras /new. Evidencia en raiz/new-envio.json, new-verificacion.json y new-conteo.json. /clear y carrera con queue siguen pendientes. No se debilitó una guardia ni cambió transporte para esconderlo.

Probe medido con cuatro CLI propias bajo carga: 372,83–489,63 ms por PID; una muestra, sin inferir reposo. Las cuatro CLI se cerraron después de leer entregas y sus PID no existen. Reglas retiradas conservando informes pendientes. Python nuevo pendiente de activación coordinada; UI compilada. Decisiones/hardware y aceptación conservados en PENDIENTES.md.
