# Revisión de código — lector Antigravity, etapa 1

Frente B, revisión focal autorizada del delta. Fecha local: 2026-10-20. Se aplicaron
pruebas-agenticas y code-audit en la misma sesión, sin subagentes ni cambios en tareas compartidas.

## Resultado y alcance

Regresión final: **258 pruebas backend pasaron**, de las cuales 56 pertenecen al lector nuevo.
**6 pruebas UI pasaron**, incluidas 2 nuevas con fixtures. Build, ESLint y Ruff pasaron.
No constituye PASS global ni aceptación de propuestas/baselines. El backend vivo no fue reiniciado
ni activado por B; la activación única queda a cargo de raíz después del gate coordinado.

Nuevos: `lienzo/antigravity_identity.py`, `lienzo/antigravity_codec.py`,
`lienzo/antigravity_store.py`, `tests/test_antigravity_reader.py`,
`web/tests-ui/antigravity-reader.spec.ts`.
Conexiones mínimas: `lienzo/server.py`, `web/src/components/Panel.tsx`,
`web/src/components/Digest.tsx`, `web/src/types.ts`, `README.md`.
Digest y su tipo opcional permiten mostrar «fin sin confirmar», sin cambiar la semántica
de otros agentes. No se editaron sesiones, transcripciones, reglas, capacidades ni dependencias.
Se preservaron los cambios concurrentes; el inventario inicial está en `input-inventory.json`.

El inventario exacto final de estas 10 fuentes y sus SHA-256 está en
`.temp/coordinacion/2026-10-20/B-antigravity/reader-implementation/sources.sha256.json`.
El resto de evidencia mencionada abajo está en esa misma carpeta.
El informe anterior `code-review-2026-10-20-antigravity.md` y el inicial en `.temp` conservan
su carácter histórico; este archivo documenta exclusivamente el delta del lector.

## Contrato revisado

Identidad exige PID y FILETIME compatibles con `started`, proceso vivo con imagen oficial,
hash de ejecutable conocido y un único archivo de presencia cuyo único propietario sea ese PID.
Se consulta NT FileProcessIdsUsingFileInformation con FILE_READ_ATTRIBUTES, sin privilegios extra.
Se rechazan rutas redirigidas, reparse points, IDs de archivo ausentes, propietarios ambiguos,
varias conversaciones, cambio de proceso o reemplazo del archivo. La identidad se verifica antes
y después de la lectura; no se deduce de títulos, caché, mtime o conversación más reciente.

La compatibilidad está cerrada al ejecutable observado:
`b9ebbc8ae00dec96263979d2947124136cdae990811e27eafef1e7f021269192`.
Contrato publicado: `agy-1.4.3-gemini_coder.Step-visible-v1`.
Una actualización desconocida cierra la lectura, sin extraer automáticamente descriptores.

SQLite usa `mode=ro`, `query_only=ON`, `trusted_schema=OFF` y una transacción de lectura.
No usa `immutable`, por lo que contempla WAL y actualizaciones del mismo índice.
Comprueba tabla real, cascade_id y columnas mediante consultas acotadas; un error descarta todo.
Límites explícitos: 512 pasos; 1 MiB por BLOB; 4 MiB acumulados; 512 campos protobuf por mensaje;
250 ms para lectura/decodificación SQLite, con espera de conexión de hasta 100 ms.
El hash del ejecutable y la búsqueda nativa de presencia tienen límites separados:
512 MiB de ejecutable y 256 locks; no están incluidos en los 250 ms.

El codec procesa únicamente el formato observado: user_input, planner_response, system_message
y generic tool. Verifica tipo, status y metadata embebida contra SQLite. Exporta texto visible
y nombres de herramientas identificables; omite pensamiento, firmas, permisos, argumentos,
resultados y generación auxiliar. Aplica `captura.tapar` a texto visible. Los mensajes de error
de SQLite/OS no salen por API ni logs. Los patrones conocidos de secretos se prueban; no se
garantiza reconocer cualquier secreto arbitrario escrito como prosa.

No adopta IDs de sesión, no persiste respuestas ni cambia actividad, `last_reply` o reglas.
Todos los turnos son `history_only: true`, `ended: false`, sin ts_end. `terminalOnly` y el
bloqueo de `on_stop` permanecen. La UI identifica historial parcial y fin sin confirmar.

## Hallazgos y correcciones

1. La primera prueba ejecutable falló por un doble SQLite con parámetro `uri` duplicado:
   43 pasaron y 1 falló. Se corrigió el doble y se conservaron ambos logs.
2. Review provisional de raíz: imagen oficial sin fingerprint permitía decodificar un upgrade
   desconocido. Se agregó SHA-256 exacto, metadata de compatibilidad y regresiones de upgrade
   y reemplazo durante fingerprint. No se afirma compatibilidad con otro binario.
3. Review provisional de raíz: lstat del último componente no cubría ancestros redirigidos.
   Se agregó resolución estricta contra ruta absoluta, rechazo de reparse points y verificación
   de IDs de archivo antes y después. Regresión de ancestro redirigido simulada, sin permisos extra.
4. Revisión propia: paginación fuera de rango, tamaño acumulado, BLOB NULL, identidad cambiante,
   timeout y cursor fuera de ventana rechazan toda la lectura y explicitan el motivo.
5. UI: `ended=false` antes se representaba como «en curso». El campo opcional `history_only`
   lo reemplaza por «fin sin confirmar» únicamente para este historial.

No quedaron hallazgos funcionales de severidad alta conocidos dentro de esta etapa.
La resolución nativa mantiene complejidad superior al ideal de funciones pequeñas del skill;
la separación identity/codec/store acota responsabilidades. No se midió un índice de complejidad
ni se afirma una auditoría de dependencias global. No hay nuevas dependencias.

## Comandos, códigos y regresiones

Detalle reproducible en `commands.json`; todos los logs de pruebas se conservan completos.
Comandos desde `D:/Apps/lienzo`, salvo frontend desde `web`:

| Comando / grupo | RC | Evidencia |
|---|---:|---|
| `py -3.14 -m pytest tests/test_antigravity_reader.py -q -p no:cacheprovider --basetemp=.temp/pytest-B-reader-17736` | 1 | `pytest-initial.log`: WinError 5, no pruebas ejecutables válidas |
| Mismo focal fuera del sandbox, temporal propio | 1 | `pytest-first-executable.log`: 43 passed, 1 failed, doble corregido |
| Regresión lector + antigravity + rules + server + frecuencia + recovery | 0 | `pytest-regression.log`: 246 passed |
| Regresión tras guardias de hash/rutas | 0 | `pytest-final.log`: 254 passed |
| Regresión final con límites adicionales | 0 | `pytest-freeze.log`: 258 passed |
| `node node_modules/@playwright/test/cli.js test --config tests-ui/playwright.config.ts antigravity-reader.spec.ts antigravity.spec.ts --workers 1` | 0 | `playwright.log`: 6 passed, fixtures, sin escrituras reales |
| `npm.cmd run build` en sandbox | 1 | `build.log`: spawn EPERM |
| `npm.cmd run build` fuera del sandbox | 0 | `build-elevated.log`: build correcto, aviso de chunk >500 kB |
| ESLint focal con `--max-warnings=0` | 0 | `eslint.log` |
| Ruff check y format --check sobre los cuatro archivos Python nuevos | 0 | `ruff-final.log`, `ruff-format-final.log` |
| `live_probe.py` en sandbox | 1 | `live-probe-sandbox.json`: identidad correcta, SQLITE_CANTOPEN |
| `live_probe.py` fuera del sandbox | 0 | `live-probe-final.json`: conteos y códigos, sin contenido |
| delta / certificar / trazabilidad del plugin | 1 / 1 / 1 | Propuestas válidas sin aprobación; `*-final.log` |

Hubo fallos iniciales de esquema de propuestas (RC 2), corregidos en los artefactos propios:
URL de estado y forma de huecos. Se conservaron los logs iniciales. No se aceptaron propuestas,
no se fijaron baselines, no se corrieron mutantes sobre el árbol compartido y no hay PASS de compuerta.

## Cinco roles y límites live

`quality/roles.json` registra Explorer → Analyser → Designer → Executor → Detective,
secuencialmente en B. Se reutilizó el descubrimiento real previo de SQLite y protobuf; se añadió
el contrato de identidad y compatibilidad. Los arreglos tras resultados volvieron al rol de diseño,
fuera del rol Executor. No se midieron timestamps de cada rol; no se inventaron.
Los validadores registran 2 estados, 1 transición no observada, 4 requisitos con huecos explícitos
y 8 propuestas positivas/negativas. Los 56 tests nuevos se ejecutaron dentro de la suite focal,
no como ocho ejecuciones independientes certificadas.

Lectura real autorizada contra el único **agy 20088**: identidad y FILETIME verificados,
36 pasos, 3 turnos, 3 bloques de texto, 14 de herramientas, sin truncamiento y todos con fin
sin confirmar. `live-probe-final.json` contiene solo conteos/códigos y compatibilidad.
No se imprimieron mensajes, secretos ni capturas privadas. No hubo nuevos agy, envíos,
cambios de cuentas o permisos, cierres, commit, push ni reinicio del backend.

Pendiente de integración completa: máquina de estados con transiciones reales de pausa,
cancelación, error, auto-continue, tool call y finalización; rotación real concurrente y junctions
reales; entorno remoto real; upgrades; historial completo fuera de la ventana y refresh continuo.
Las transiciones de status y las rotaciones adversas de esta etapa son sintéticas.
Se comprobó WAL con un escritor sintético y cambios del mismo índice, no durante un turno real.
El backend integrado solo se probó mediante `session_view_response` en tests; el proceso vivo
queda a la activación y gate coordinados de raíz. Fuentes de B congeladas tras el manifiesto final.
