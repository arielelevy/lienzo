# Auditoría Codex del árbol completo de Lienzo — 2026-10-21

**Veredicto: hay bloqueantes concretos de release.** Se identificaron por lectura estática tres P1 y cinco P2. No se modificó producto ni se ejecutaron suites, entradas, envíos, pagos, reinicios o procesos del producto. Los escenarios siguientes son deducciones del código, no reproducciones ejecutadas. No se declara PASS global ni se marcan tareas completadas.

## Alcance y evidencia

El alcance es todo el árbol propio, incluidos archivos sin cambios y nuevos; no se usó `--uncommitted` como límite. Se inventariaron 540 archivos existentes: 513 rutas versionadas y 29 nuevas, con dos rutas versionadas ausentes por la reorganización de informes (`MEJORAS.md`, `code-review-2026-10-20-clipboard.md`). Se analizaron sintácticamente 300 archivos Python sin importar producto. El inventario contiene 5.829 definiciones, 2.758 importaciones, 990 ocurrencias de rutas, 328 condiciones de enrutamiento y 337 llamadas de frontera. Son índices, no pruebas de corrección ni una lectura semántica de cada línea.

La lectura manual cruzó entradas, guardias, consumidores y oráculos de pruebas. El registro por archivo distingue 49 rutas de lectura manual de profundidad variable, 26 de lectura parcial y las restantes con inventario/índices únicamente. **No equivale a certificar semánticamente los 540 archivos.** El informe entrega defectos sustentados y deja esa cobertura restante explícita, en lugar de convertir el inventario en una aprobación.

Artefactos preservados en `.temp/coordinacion/2026-10-21/B-review-total/`:

- `archivos.json`, `resumen.json`, `simbolos.json`, `imports.json`, `rutas-literales.json`, `rutas-condiciones.json`, `fronteras-llamadas.json`, `persistencia-tablas.json`, `entorno-nombres.json`: foto inicial e índices.
- `evidencia-estatica.txt`: fragmentos numerados y SHA256 de las fuentes de los hallazgos.
- `cobertura.json`: cobertura individual, sin atribuir ejecución a ninguna ruta.
- `hashes-cierre.json`, `cambios-desde-inventario.json`, `cierre.json`, `cierre.log`: comparación de los 540 archivos y límites de la foto no atómica.
- El inventario anterior de `.temp/coordinacion/2026-10-20/B-review-total/` permanece histórico.

La revisión nativa anterior devolvió solamente «¿Qué necesitás revisar?». No produjo hallazgos ni cobertura. Este informe es auditoría estática realizada por Codex; no una ejecución de `/review`. No se volvió a invocar `/review`, conforme a coordinación. No se afirma que la revisión nativa admita únicamente diff: esa capacidad no fue comprobada.

## Hallazgos

### B01 — [P1] Los auxiliares de transferencia permiten escribir fuera de `copy_roots`

**Ubicación:** `lienzo/xfer.py:432`, `lienzo/xfer.py:498`; relacionado con `:379`, `:399`, `:527`.

`unir()` comprueba la ruta final y sus ancestros, pero no sus hermanos `<archivo>.parte` y `<archivo>.parte.diario`. `_asegurar_parte()` reutiliza un `.parte` existente si encuentra un diario válido. Después `open(..., "r+b")` sigue el enlace sin comprobar su destino físico.

**Condición concreta:** dentro de una raíz autorizada existe `foo.parte`, enlace a un archivo exterior escribible por el backend; `foo` no es enlace y `foo.parte.diario` contiene una primera línea válida `bs 1048576`. Un bloque válido dirigido a `foo` pasa `unir()`, reutiliza el auxiliar y escribe en el archivo exterior. No requiere ganar una carrera. El diario también se abre sin confinamiento y puede apuntar afuera. `r_cerrar()` puede truncar el destino del auxiliar antes de verificar sus bytes.

**Impacto:** se viola el límite de escritura prometido por `copy_roots`. Requiere un auxiliar previamente preparado y un pedido de transferencia autorizado; no se presenta como acceso remoto anónimo. Es distinto del TOCTOU general ya registrado en pendientes: aquí el enlace preexistente nunca se valida.

**Corrección mínima propuesta:** aplicar confinamiento físico y rechazo de enlaces a todos los auxiliares antes de leer, reutilizar, escribir o truncar; conservar la garantía durante la apertura mediante handles apropiados. No borrar o truncar el destino externo al rechazar.

**Regresión propuesta, no ejecutada:** raíz y víctima temporales; preparar auxiliar enlazado más diario válido; pedir bloque y cierre; esperar rechazo y víctima intacta. Cubrir también diario enlazado y junction/symlink según plataforma. El rojo/verde de este escenario queda pendiente.

### B02 — [P1] Rehabilitar una regla elude la prevención de bucles

**Ubicación:** `lienzo/rules_api.py:399`, `:431`, `:434`; contrastar con creación `:225`, `:246`, `:344`.

El alta comprueba inversas locales, bucles globales y conflictos/reservas remotos. `edit_rule()` valida el agente origen al habilitar, pero no repite esos controles de topología antes de escribir `enabled=True`. También existe una rehabilitación implícita al pasar una regla repetitiva a límite por frecuencia.

**Secuencia concreta:** crear A→B, deshabilitarla, crear B→A y rehabilitar A→B por PUT. La inversa deshabilitada no impide el alta de B→A; el test `tests/test_rules_federadas.py:396` confirma ese contrato. El PUT acepta después el ciclo. No hace falta Antigravity: dos agentes con origen permitido alcanzan. Con repetición por frecuencia, respuestas variables o deduplicación desactivada, el ciclo puede generar trabajo y consumo recurrentes; el cooldown no rechaza la topología.

**Corrección mínima propuesta:** validar el candidato completo en cada transición deshabilitada→habilitada, explícita o implícita, con controles locales y federados equivalentes al alta. Evitar carreras entre validación y habilitación. Un rechazo debe conservar regla e informes pendientes sin mutaciones parciales. No extender este cambio a la semántica de `at` sin un alcance separado.

**Regresión propuesta, no ejecutada:** alta/deshabilitación/inversa/rehabilitación local y federada, más rehabilitación implícita por frecuencia. Esperar 409, regla aún deshabilitada e informes intactos. Control positivo: habilitar una conexión sin conflicto. No se enviaron mensajes ni se activaron reglas reales.

### B03 — [P1] La caché de hashes puede certificar un destino alterado

**Ubicación:** `lienzo/xfer.py:329`, `:368`, `:424`, `:1061`.

`CacheHashes.get()` considera vigente un hash por ruta, tamaño, mtime y tamaño de bloque. Si cambia el contenido conservando tamaño y mtime, `_hashes_final()` devuelve el hash anterior. El emisor puede declarar el archivo salteado sin releer sus bytes. El cierre sin `.parte` también usa esos hashes (`:522`).

**Secuencia concreta:** completar una copia, alterar un byte del destino sin cambiar longitud, restaurar su mtime y volver a copiar con la caché caliente. La respuesta de estado anuncia hashes anteriores y el archivo pequeño puede quedar intacto pero contado como ya correcto. No requiere colisión criptográfica.

**Brecha del oráculo:** `tests/test_xfer.py:199` expresa que tamaño y fecha no bastan, pero en `:208–209` cierra y borra `hashes.db` antes de repetir la copia. Por eso solo verifica la situación con caché fría y no este camino.

**Corrección mínima propuesta:** no usar esa clave de caché como evidencia suficiente de integridad. Rehashear antes de afirmar igualdad o incorporar una garantía de cambios realmente fiable. Añadir identidad del archivo por sí sola no resuelve modificaciones in situ.

**Regresión propuesta, no ejecutada:** conservar explícitamente la caché entre las dos copias del escenario anterior y comprobar bytes finales, contador de salteados y resultado de cierre. Cubrir archivo pequeño y varios bloques. Se considera bloqueante por falsa garantía de integridad, aunque no implique que toda copia falle.

### B04 — [P2] Una réplica atrasada puede reactivar un vínculo retirado más recientemente

**Ubicación:** `lienzo/conocimiento.py:1331`; consumidor `lienzo/replica.py:392`, `:407`.

La retirada local cambia `activo` pero deja la `fecha` antigua de la fila. El evento histórico sí tiene fecha de cambio. La recepción de una réplica compara la fecha del evento recibido con la fecha de la fila y actualiza incluso si el evento es anterior a la retirada local real.

**Secuencia concreta:** vínculo creado en t0; activación remota de t1 pendiente de llegar; retirada local en t2, con t0<t1<t2. La fila queda inactiva con fecha t0. Al recibir t1, `_aplicar_vinculo()` la considera posterior y la reactiva. La retirada puede seguir en el historial mientras el grafo activo queda incorrecto. El camino automático de retirada en `conocimiento.py:1913` necesita el mismo criterio.

**Corrección propuesta:** actualizar la marca temporal de la fila junto con la retirada y su evento, dentro de la misma transacción; revisar todos los productores de retiradas. No cambiar el ordenamiento federado de forma parcial.

**Regresión propuesta, no ejecutada:** dos bases aisladas con relojes controlados; entregar una activación antigua después de una retirada nueva y comprobar que permanece inactiva. Cubrir retirada manual y automática y convergencia tras intercambiar cambios.

### B05 — [P2] `launch_roots` verifica prefijos lógicos, no el directorio físico

**Ubicación:** `lienzo/launch.py:131–136`.

`_cwd_allowed()` normaliza caracteres y comprueba existencia y prefijo, pero no resuelve enlaces/junctions. Un directorio `permitido/redireccion` enlazado a un árbol exterior conserva el prefijo autorizado y pasa el control; el proceso se inicia físicamente afuera. Afecta a consumidores de esta guardia, incluidos lanzamientos y apertura de proyecto.

**Corrección propuesta:** definir y comprobar contención física de raíz y cwd, rechazando redirecciones no autorizadas antes de cualquier actualización o subprocess. Mantener el rechazo de comillas, `%` y saltos de línea.

**Regresión propuesta, no ejecutada:** raíz temporal con enlace a otra carpeta temporal; esperar rechazo sin invocar ejecutables. Cubrir raíz exacta permitida, hermana con prefijo parecido y junction Windows. No se crearon enlaces ni se lanzaron aplicaciones durante esta auditoría.

### B06 — [P2] Reintentar un envío múltiple repite también los destinos ya entregados

**Ubicación:** `web/src/components/SelectionBar.tsx:61`, `:85–89`.

Después de éxito parcial se conservan texto y selección. El siguiente clic vuelve a recorrer todos los `sids`; no existe un conjunto de destinatarios pendientes del lote. Por ejemplo, con dos entregas y un rechazo, reintentar manda de nuevo a los dos que ya recibieron. El estado incierto también conserva ese camino, aunque la propia UI diga «No reenvíes el texto». No hay una garantía universal de idempotencia entre todos los agentes y transportes.

`web/tests-ui/seleccion.spec.ts:191` comprueba dos éxitos y un fallo, y conserva el texto «para reintentar» (`:212`), pero no pulsa una segunda vez ni comprueba destinatarios duplicados.

**Corrección propuesta:** conservar resultados por destinatario y lote; ofrecer reintento solo de rechazos que garantizan no entrega. Los inciertos necesitan resolución, no reenvío ciego. Un envío nuevo al conjunto completo debe ser una acción distinguible.

**Regresión propuesta, no ejecutada:** fixture con dos entregados y un rechazado, segundo clic y verificación de que los entregados no reciben otra llamada; variante con `sin_confirmacion`. Solo mocks, sin sesiones reales.

### B07 — [P2] Un pull fallido permite arrancar con una compilación pendiente

**Ubicación:** `lienzo/startup_update.py:32–34`, antes de consultar el marcador en `:43`.

Un fallo previo de build deja `web/.startup-build-pending` para impedir el arranque y reintentar. Si el siguiente `git pull --ff-only` devuelve código no cero, `update()` retorna 0 antes de consultar ese marcador. Así habilita iniciar el checkout actualizado con UI anterior o ausente.

**Secuencia concreta:** primer inicio actualiza `web/`, falla build y deja marcador; segundo inicio sin conectividad o con conflicto de pull retorna 0 por la rama de fallback local. No depende de un cambio nuevo entre ambos intentos. Las pruebas de `tests/test_startup_update.py` separan el pull fallido del reintento de build; falta esta combinación.

**Corrección propuesta:** comprobar y respetar el build pendiente también en el fallback local; compilar satisfactoriamente o devolver error conservando el marcador. Conservar la posibilidad de arrancar offline cuando el árbol local está preparado.

**Regresión propuesta, no ejecutada:** fixture temporal con marcador y pull rc1; exigir build exitoso antes de rc0, o rc distinto de cero si falla; controlar que no arranque el servidor. La instalación de dependencias cuando cambia el lock también necesita cobertura específica: esta ruta solo llama `npm run build`.

### B08 — [P2] La guardia de tamaño de Chrome compara contra una geometría cacheada

**Ubicación:** `lienzo/browser_host.mjs:420–424`; fuente de la caché `:165–170`.

En modo `existing`, `realViewport()` actualiza `cdp.css` al observar el viewport. Al recibir entrada, la guardia compara `basis` con esa caché y despacha sin consultar las métricas actuales. Si la ventana real cambia de tamaño desde el último cuadro y aún no hay otro snapshot, la base vieja coincide con la caché y pasa; el input puede alcanzar otra posición del layout actual. La ventana entre cuadros existe también mientras se espera un ACK.

`tests/browser_host.test.mjs:255` contrasta una base deliberadamente distinta de la caché; no cambia las métricas reales entre cuadro e input. No prueba el caso descrito.

**Corrección propuesta:** refrescar métricas reales inmediatamente antes de validar una entrada dependiente de geometría en `existing` y rechazar bases obsoletas sin despachar eventos. No emular tamaño, activar ventanas ni navegar para hacer esa comprobación. Esto reduce el desfase observado; no promete atomicidad frente a cualquier cambio posterior.

**Regresión propuesta, no ejecutada:** fixture CDP devuelve tamaño A al cuadro y B antes del input, sin nuevo cuadro; base A debe devolver 409 y ninguna llamada `Input.dispatchMouseEvent`. Mantener pruebas de aceptación de una base actual y liberación segura de teclas/botones.

## Cobertura de superficies y contratos

| Superficie | Revisión realizada | Límite pendiente |
|---|---|---|
| HTTP, WS, SSE, auth y túnel | Rutas/condiciones indexadas; lectura de auth, WS y segmentos del handler, controles locales/remotos y errores | No se ejercieron red, túnel, reconexión, concurrencia ni cada rama del handler |
| Peers y emparejamiento | Lectura de pairing y secretos; índices y segmentos de federation/mirror/forward; validación de origen remoto de reglas | Sin dos PCs, pérdida/reordenamiento real, auditoría criptográfica especializada ni revisión manual íntegra de federation |
| Archivos, descargas y copias | Fuentes/validadores, confinamiento final, diarios, caché, bloques y salto por igualdad | B01/B03; aperturas simultáneas y garantías de handles por plataforma sin probar |
| Lanzamiento, identificación, cierre, permisos y envíos | launch, procs, hook, kill, autoaprobar, pantalla, aprobador, codex_queue y guardias de reglas | B02/B05/B06; sin tocar procesos, permisos ni sesiones reales; procinfo y send no tienen certificación íntegra línea por línea |
| Estado y persistencia | Guardado atómico, listas/config y fragmentos de sesiones/transcripciones; índices de SQL | Sin crash recovery real, archivos bloqueados o carrera de guardado; sesiones/transcripts tienen lectura parcial |
| Memoria, réplica e importación | Replica, segmentos de conocimiento y contratos del grafo, rutas y modelos | B04; importadores/ops inventariados, sin revisión semántica individual completa ni datos reales |
| Aprendizaje, costes, scheduler y Prolog | Contratos de cola/cancelación, política/runner de investigación, actividad, contraste y parámetros; scheduler parcial | Sin proveedor, ejecución de Prolog, presupuesto vivo o validación de cada algoritmo del motor |
| Chrome y apps | API, remoto, host/stream por rangos, transporte y bases de coordenadas; separación de identidad/entrada | B08; sin acceso a Chrome real, red, cámaras de plataforma ni revisión integral del host nativo |
| Frontend React/TS | Hooks de datos/acciones, clipboard, selección, login/pairing, updates/downloads; panel/envío y nuevos contratos por rangos | Sin ejecutar build/lint/UI; navegación, todos los diálogos, lectores de pantalla y todas las combinaciones no certificados |
| Instalación y actualizaciones | install.py, startup_update, updates/harness y restore; dependencias declaradas y scripts de arranque | B07; sin instalación, upgrade, descarga o escaneo vigente de vulnerabilidades |
| Tests y documentación | Inventario íntegro, lectura dirigida de oráculos relacionados, contratos de release/README y reportes de coordinación | No todas las pruebas fueron leídas manualmente; ninguna ejecutada por B en esta etapa; docs antiguas no certificadas exhaustivamente |

La guardia `check_on_stop_source()` consulta `find_session`, rechaza perfiles desconocidos y `terminalOnly`; la rehabilitación explícita e implícita pasa por ella. No se encontró aquí una nueva brecha del agente Antigravity. El historial parcial no acredita cierre de turno, adopción de IDs, resume fiable ni una respuesta estructurada persistida. Esas garantías siguen fuera de alcance. No se alteró la semántica de otros agentes, reglas `at` o informes pendientes.

Los plugins locales ignorados y datos privados no se incorporaron al corpus ni se imprimieron mensajes o secretos. La ausencia de un hallazgo en una superficie no equivale a un resultado seguro.

## Delta F incorporado después de la congelación

Se leyó `.temp/coordinacion/2026-10-20/F-overflow/entrega.md` y el diff de CSS/prueba. Se verifican estos hashes en la foto de cierre:

- `web/src/styles.css`: `6ac73f62feb6002dfedad7ed121d5299cdec77cb55c1571d4e6d2ed85fc1a35e`.
- `web/tests-ui/tablero.spec.ts`: `2fd69fad3e92a425b2fe9cbe8bdba8a7edb29b72d57aac15d595c8b0ab1f8284`.

El wrap de `.card .top` y `.right`, ancho máximo y eliminación del nowrap del grupo son coherentes con la causa descrita. La regresión comprueba límites de tarjeta y texto, 1440→960→1440, acceso por teclado y restauración de foco. No identifico un bloqueante estático nuevo en ese bloque.

**Evidencia ajena, no reejecutada por B:** F registra rojo rc1 con `scroll 93px` y verde 10/10 rc0, además de ESLint focal rc0. La primera roja del caso nuevo tenía un fixture incorrecto; F lo distingue de la segunda roja válida. Los validadores delta/certificar/trazabilidad quedaron rc1; no se transforma ese resultado en PASS. El verde usa Vite fuente y no certifica `dist` ni release. Ya no queda una espera por la entrega de F.

En la comparación final también cambió `docs/releases/0.6.0.md`, SHA256 `f36148a8885a74149ede492af6ea024e5357d78d909111503e446fbe5650f6b9`. Se releyó: incorpora la regresión CSS y mantiene los límites del historial parcial. Su afirmación general de rechazo de geometría obsoleta necesita el ajuste descrito en B08. La foto no es atómica; este cambio documental queda registrado, sin atribuirlo a B.

Coordinación informa backend E rc0 tras 496 s y memoria aún en curso. Se conserva como dato comunicado, no como suite corrida o logs auditados por B. El global final sigue pendiente de integración/congelación coordinada.

## Comandos, códigos y recorrido de verificación

Lecturas/búsquedas compatibles usaron `C:\Users\ArielLevy\.lienzo\bin\rtk.exe` con `read`, `rg` y `git status/diff`. Cuando RTK recortó contexto se recuperaron rangos con `Get-Content` numerado. No se filtraron logs de pruebas porque no se corrieron pruebas.

| Operación real de B | rc / resultado | Evidencia y límites |
|---|---|---|
| `py -3.14 .temp/coordinacion/2026-10-21/B-review-total/inventariar.py` | 0 | `inventario.log`, JSON de inventario; lectura y AST, no suite |
| `py -3.14 .temp/coordinacion/2026-10-21/B-review-total/cerrar_evidencia.py` | 0 | `cierre.log`, hashes/cobertura/evidencia; no importa producto |
| RTK `git status --short` | 0 | Advierte `warning: could not open directory '.pytest_cache/': Permission denied`; no se cambiaron permisos |
| RTK `read lienzo/install.py` | 1 | Ruta inexistente; se recuperó leyendo `install.py` en raíz, rc0 |
| RTK `read ... --start-line ... --end-line ...` | 1 | `Binary 'read' not found on PATH`; se recuperó contexto original con `Get-Content`, rc0 |
| Lecturas de hallazgos y diff F | 0 | Fragmentos conservados en `evidencia-estatica.txt`; salida de herramientas de la sesión |
| Suites, build, lint, mutación, baselines y `/review` | No ejecutados por B | Prohibición explícita de ejecutar suites y coordinación serial; sin rc ni PASS inventados |

El registro no reconstruye una transcripción exhaustiva de cada comando histórico: los logs indicados contienen las operaciones de inventario y cierre, y los resultados de lecturas permanecen en la sesión. Hubo intentos de `apply_patch` rechazados por contexto sobre artefactos de auditoría; se aplicaron después con contexto correcto y no afectaron producto.

Recorrido secuencial de pruebas agénticas aplicado a esta auditoría: **Explorer**, inventario de superficies y contratos; **Analyser**, cruce de productores/consumidores y oráculos; **Designer**, ocho escenarios aislados con resultado esperado; **Executor**, escenarios y suites no ejecutados por restricción explícita, solo extracción estática; **Detective**, clasificación de evidencia, brechas de oráculos y límites. Esto no sustituye una ejecución del runner ni una compuerta aprobada. Las regresiones nuevas no tienen rojo/verde medido y no se crearon pruebas de producto en esta etapa.

## Gate de release y siguiente paso

**Bloqueantes recomendados:** B01 por escritura fuera de la raíz autorizada; B02 por reactivar ciclos prohibidos; B03 por declarar integridad con contenido incorrecto. Corregirlos y demostrar regresiones aisladas antes de liberar. Son preexistentes o transversales: no se atribuyen automáticamente al delta de Antigravity.

B04–B08 requieren resolución o aceptación de riesgo explícita, especialmente si se incluyen réplica, envíos múltiples o control de Chrome en el release. No se hicieron cambios porque este frente es de solo lectura.

Falta ejecutar los escenarios propuestos, incorporar el global final de E con sus logs/rc y confirmar que el build distribuido corresponde al árbol congelado. También falta ampliar la lectura semántica individual de los archivos que `cobertura.json` deja solo inventariados, más pruebas live autorizadas de dos PCs, Windows/WSL, recuperación y accesibilidad. No hay aprobación global, ausencia de CVE comprobada ni certificación de todas las plataformas.

Las únicas escrituras de B en esta etapa son este informe y artefactos propios bajo `.temp/coordinacion/2026-10-21/B-review-total/`. Las fuentes de producto quedan intactas y congeladas desde B. Cualquier activación del backend corresponde exclusivamente a raíz. No se abrió ni se cerró agy; no se repitieron sus pruebas.

**ESTADO: informe entregado; tres bloqueantes P1 y cinco defectos P2 sustentados por lectura estática. F incorporado con hashes coincidentes. Producto sin modificaciones de B; suites y global final pendientes de coordinación.**

## Resolución posterior B02/B04 — 2026-10-21

El encargo `.temp/coordinacion/2026-10-21/encargo-B-correcciones.md` autorizó reproducir y corregir exclusivamente B02/B04. Se conservan arriba los hallazgos y límites originales. Rojo aislado: 14 fallan y dos controles pasan; verde de los mismos casos: 16 pasan. Contratos vecinos: 174 pasan. Tras la revisión y un ajuste para conservar la precedencia de validación 400/404, la corrida final focal dio 78 pasan, rc0. No son suites globales ni operaciones live.

B02 queda corregido para la rehabilitación explícita/implícita por PUT, con guardias locales/federadas, sin mutaciones parciales ni pérdida de informes. B04 queda corregido en las retiradas manual/automática y activaciones locales nuevas mediante fecha causal compartida por fila y evento; no se migraron datos históricos ni se modificó replica.py.

Evidencia, comandos/rc, revisión propia y hashes congelados: `.temp/coordinacion/2026-10-21/B-correcciones/informe.md`, `code-review.md` y `hashes-finales.json`. La primera corrida falló por permisos del sandbox antes de los casos; el rojo externo sí reprodujo los defectos. Sin git, nuevos agentes, prueba AGY, baselines o compuerta aprobada. La resolución de B01/B03 y de otros frentes requiere sus entregas y el gate coordinado por raíz; este agregado no aprueba el release.

ESTADO: B02/B04 con corrección focal comprobada y fuentes congeladas desde B; auditoría original preservada; integración y verificación global a cargo de raíz.

### Ampliación posterior: B02 en la migración de arranque

El encargo `encargo-B-migracion.md` incorporó la otra transición deshabilitada→habilitada de `rules.py`. Rojo: 11 fallos y un positivo; verde focal: 136 pasan; revisión final de migración: 13 pasan, todos rc0 salvo el rojo. La migración ahora rechaza inversas/duplicados, origen terminalOnly/desconocido y puntas no acreditadas. Mantiene deshabilitada con motivo visible cualquier regla cuya topología remota no pueda acreditarse antes de conectar peers. Conserva informes y permite un intento explícito posterior mediante la API validada. No modificó `at`, server.py o protocolo ni activó reglas reales.

Evidencia y revisión propia: `.temp/coordinacion/2026-10-21/B-correcciones/arranque/informe.md` y `code-review.md`. Hashes finales consolidados en `.temp/coordinacion/2026-10-21/B-correcciones/hashes-finales.json`; la primera entrega permanece histórica. La revisión independiente B05/B07 está agregada a `review/2026-10-21/code-review-startup-launch.md`, sin repetir suites de raíz.

ESTADO: B02 cubierto en API y migración de arranque con regresiones focales comprobadas; B04 corregido; fuentes B congeladas. Sin aprobación global o de release.
