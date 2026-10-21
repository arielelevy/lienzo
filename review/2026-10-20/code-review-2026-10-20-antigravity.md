# Revisión Antigravity — frente B — 2026-10-20

Resultado: cambios implementados y verificados en alcance focal. **431 pruebas backend pasaron**, **9 pruebas UI pasaron**, build y lint sin errores. Contraste del filtro activo: **5,30:1**. Las fuentes de B quedan congeladas para integración de la coordinadora. No hay activación del backend por B ni certificación global de toda la aplicación.

Revisión estática con skill `code-audit`; pruebas con los cinco roles de `pruebas-agenticas`, secuenciales en esta sesión. Auditoría independiente D leída y atendida. Los registros iniciales bajo `.temp` quedan históricos.

## Alcance y comportamiento

- `procinfo.py`: reconoce subcomandos después de opciones con valor, modos print/help/version y binarios `agy.exe.*`. `login/logout` y `-v` se excluyen conservadoramente; no figuran como capacidades verificadas en el help 1.4.3. Nunca se ejecutaron acciones de cuentas para comprobarlos.
- `agentes.py`: UUID completo para `--conversation`, cotejado con la caché local real de agy. El comando de reanudación se prueba con `Popen` simulado. `resumed: true` sólo acredita el argumento generado; **no se verificó reanudación viva**.
- `Launch.tsx`: la capacidad `windowsOnly` oculta WSL y evita enviarlo aunque la distro se haya elegido antes en Codex. La elección de Codex se conserva al volver a ese agente. Los cambios Chrome de A se preservan y sus tres pruebas UI pasan.
- `sessions.py`: `screen_observation` contiene fuente `screen`, hora de muestra publicada, disponibilidad, etiqueta visible del pie Gemini verificado y actividad `unverified`. No escribe modelo canónico, respuesta ni fin de turno. La API publica `state_source: "unverified"`; el estado operativo existente se conserva.
- Pantalla estable: sólo publica/persiste/captura cuando cambia `source`, `available`, `model_label` o `activity`. Un sondeo idéntico no cambia la hora publicada. Una lectura fallida publica indisponibilidad y limpia la etiqueta observada.
- `Card.tsx`: presenta actividad sin confirmar y observación parcial con fuente/hora. No muestra el icono de corriendo o terminado para una CLI de terminal. Una etiqueta observada no se convierte en salida estructurada.
- `SendBox.tsx`: oculta y bloquea la creación automática de avisos al terminar para Antigravity. La huérfana sugiere `agy`, sin inventar un ID para `--conversation`.
- `rules_api.py`: POST `on_stop` y PUT de reactivación explícita o implícita verifican el origen con **`find_session` local/remoto**, antes de reenviar o modificar reglas. Terminal-only devuelve 409 `unsupported_on_stop`; agente desconocido, ausente o no verificable devuelve 409 `unverified_on_stop_source`. Es una decisión explícita de raíz mantener cerrado el origen desconocido. No se debilita para hacer pasar fixtures.
- Reglas: las `at` y los cinco agentes conocidos restantes conservan creación/reactivación. Se permite deshabilitar reglas antiguas; los rechazos no cambian informes pendientes. No se hizo un barrido destructivo de reglas existentes. Raíz deshabilitó la inicial `5d8392adff44`; B no la reactivó.
- Accesibilidad: color Antigravity en variable de tema y fondo propio del chip activo; tinta oscura sobre azul medida en navegador a 5,30:1. No se aceptaron baselines.

## Regresiones antes/después

| Caso | Antes / evidencia | Después / evidencia |
|---|---|---|
| WSL heredado | Selector visible para agy, backend lo rechazaba; auditoría D | UI cambia Codex/Ubuntu → agy → Codex y comprueba payload sin `distro` para agy |
| Resume inválido | `deadbeef` y 40 ceros generaban `--conversation`; D `bordes.log` | Se rechazan IDs incompletos; UUID observado genera argumentos; sin prueba de reanudación real |
| Detección | `--model x models`, `-v`, login podían aparecer como tarjeta | Parametrización negativa y positiva; valores de `--model`/`-i` no se confunden con subcomandos |
| Modelo/actividad | API real: `model: null`, `state: corriendo` después de responder | Contrato parcial probado con fixtures y replay de tres capturas reales; no se afirma que el backend activo ya lo publique |
| Contraste | A midió `button.chip.antigravity.on` a 1,17:1 | 5,30:1 en Playwright; WCAG AA supera 4,5:1 |
| Sondeo sin cambios | D: tres pantallas iguales dieron `touch=3`; `revision2/screen-churn.log` | Test real de `touch`: tres sondeos iguales dan save=1, broadcast=1, capture=1; cambio de modelo y fallo de lectura agregan exactamente dos de cada uno |
| `on_stop` agy | `check_rule` sólo comprobaba existencia | 409 local/remoto al crear/reactivar; sin reenvío ni modificación de informes |
| Fixtures remotos antiguos | Primera corrida de guardia: 2 failed, 237 passed; faltaba identidad de agente en dos fixtures | Se agregó Claude conocido a los fixtures de reenvío, conservando sus expectativas 200/502 |
| Fixtures de reactivación | D revisión 2: origen no registrado o sin `agent` en frecuencia/recovery | Fixture de frecuencia usa su entorno Claude existente; recovery declara agente Claude; unknown sigue rechazado por regresión propia |

La batería final incluye frecuencia, deduplicación, recuperación, API de reglas y preservación de informes, además de las pruebas de Antigravity/Chrome y las rutas de pantalla/envío existentes.

## Comandos, códigos y logs

Todas las rutas de log de esta sección son relativas a **`.temp/coordinacion/2026-10-20/B-antigravity/`**. Se conservaron salidas completas, incluidos fallos iniciales. Los comandos de pytest/Playwright que requerían procesos o carpetas temporales se ejecutaron por la vía de aprobación fuera del sandbox; no se cambiaron permisos ni hooks.

| Comando / cwd | rc | Resultado | Log |
|---|---:|---|---|
| `py -m pytest tests/test_antigravity.py -q -p no:cacheprovider --basetemp=.temp/coordinacion/2026-10-20/B-antigravity/pytest-temp` / raíz | 1 | Sandbox: `PermissionError: [WinError 5] Access is denied` | `pytest.log` |
| Mismo caso, `--basetemp=.temp/coordinacion/2026-10-20/B-antigravity/pytest-elevated` / raíz | 0 | 17 passed in 0.13s, versión inicial | `pytest-elevated.log` |
| Playwright `antigravity.spec.ts`, comando completo abajo, intento sandbox / web | 1 | `Error: spawn EPERM` | `playwright.log` |
| Playwright inicial fuera de sandbox / web | 0 | 1 passed (2.5s) | `playwright-elevated.log` |
| Pytest de implementación previo a guardia / raíz | 0 | 278 passed in 13.52s | `pytest-implementation.log` |
| `npm.cmd run build` / web, sandbox | 1 | Vite/esbuild: `Error: spawn EPERM` | `build.log` |
| `npm.cmd run build` / web, fuera del sandbox | 0 | TypeScript + Vite; aviso de chunk >500 kB, sin error | `build-elevated.log` |
| Playwright Antigravity + Chrome + salud / web, comando completo abajo | 0 | 9 passed (15.5s); 630 textos medidos en 4 pantallas del chequeo global de contraste | `playwright-implementation.log` |
| Pytest primera guardia / raíz, comando completo abajo | 1 | 2 failed, 237 passed in 19.14s; fixtures de identidad incompletos | `pytest-rules.log` |
| Pytest posterior a esa corrección / raíz | 0 | 399 passed in 22.93s; anterior al hallazgo de churn | `pytest-final.log` |
| **Pytest freeze / raíz, comando completo abajo** | **0** | **431 passed in 34.05s**, posterior al hallazgo de churn y fixtures de D | **`pytest-freeze.log`** |
| ESLint focal, comando completo abajo / web | 0 | Sin errores | `eslint.log` |
| Ruff focal freeze, comando completo abajo / raíz | 0 | `All checks passed!` | `ruff-freeze.log` |
| Playwright `--grep 'la tarjeta declara'` / web | 0 | 1 passed (2.3s); captura visible y contraste 5,30:1 | `playwright-capture.log`, `ui-parcial.png` |
| Replay del parser sobre JSON guardados, comando abajo / raíz | 0 | Tres capturas reales reconocidas; todas conservan actividad sin verificar | `parser-replay.json` |
| `git diff --check` / raíz | 0 | Sin errores de whitespace | Salida de herramienta; sin archivo de log |
| Validadores del plugin, comandos abajo / raíz | 1 cada uno | Propuestas válidas; faltan aceptaciones humanas. Trazabilidad final: 6 casos, 3 requisitos, **sin hallazgos** | `delta.log`, `certificar-final.log`, `trazabilidad-final.log` |

Comando final backend:

```powershell
py -m pytest tests/test_antigravity.py tests/test_antigravity_rules.py tests/test_rules_frecuencia.py tests/test_avisos_dedupe.py tests/test_release_recovery.py tests/test_ola2_server.py tests/test_server.py tests/test_launch.py tests/test_procs.py tests/test_ola2_agentes.py tests/test_providers.py tests/test_chrome_claude.py tests/test_mejoras.py tests/test_autoaprobar.py tests/test_harness_updates.py -q -p no:cacheprovider --basetemp=.temp/coordinacion/2026-10-20/B-antigravity/pytest-freeze
```

Primera corrida de guardia, antes de corregir fixtures:

```powershell
py -m pytest tests/test_antigravity_rules.py tests/test_server.py tests/test_ola2_server.py tests/test_antigravity.py -q -p no:cacheprovider --basetemp=.temp/coordinacion/2026-10-20/B-antigravity/pytest-rules
```

UI, desde `web`:

```powershell
node node_modules/@playwright/test/cli.js test --config tests-ui/playwright.config.ts antigravity.spec.ts launch-chrome.spec.ts salud.spec.ts --workers 1
node node_modules/@playwright/test/cli.js test --config tests-ui/playwright.config.ts antigravity.spec.ts --grep 'la tarjeta declara' --workers 1
node node_modules/eslint/bin/eslint.js src/agents.ts src/types.ts src/components/Card.tsx src/components/Launch.tsx src/components/SendBox.tsx tests-ui/antigravity.spec.ts --max-warnings=0
```

Backend lint:

```powershell
py -m ruff check lienzo/rules_api.py lienzo/sessions.py lienzo/procinfo.py lienzo/agentes.py lienzo/procs.py tests/test_antigravity.py tests/test_antigravity_rules.py tests/test_server.py tests/test_rules_frecuencia.py tests/test_release_recovery.py
```

Ruff format sobre `procinfo.py`, el test de Antigravity, `rules_api.py` y el test nuevo de reglas. No se reformatearon enteros `sessions.py` ni `procs.py`: el chequeo encontró formato previo ajeno al delta. Se corrigió el formato del bloque agregado por B. No se ejecutó un formateo global compartido.

Replay sin leer ninguna TUI viva:

```powershell
py -c "import sys,json;from pathlib import Path;sys.path.insert(0,'lienzo');import sessions;p=Path('.temp/coordinacion/2026-10-20/B-antigravity');r={n:sessions.antigravity_screen_observation(json.loads((p/n).read_text(encoding='utf-8-sig'))) for n in ['screen-before.json','screen-after-help.json','existing-after.json']};assert all(v['model_label']=='Gemini 3.8 Flash · high' and v['activity']=='unverified' for v in r.values());(p/'parser-replay.json').write_text(json.dumps(r,indent=2),encoding='utf-8');print(json.dumps(r,indent=2))"
```

Los timestamps de `parser-replay.json` corresponden al replay, **no** a una lectura nueva de la terminal.

Plugin instalado en `C:/Users/ArielLevy/.codex/plugins/cache/pruebas-agenticas/pruebas-agenticas/0.5.26`:

```powershell
node C:/Users/ArielLevy/.codex/plugins/cache/pruebas-agenticas/pruebas-agenticas/0.5.26/runner/delta.mjs .temp/coordinacion/2026-10-20/B-antigravity/quality.json
node C:/Users/ArielLevy/.codex/plugins/cache/pruebas-agenticas/pruebas-agenticas/0.5.26/runner/certificar.mjs .temp/coordinacion/2026-10-20/B-antigravity/quality.json
node C:/Users/ArielLevy/.codex/plugins/cache/pruebas-agenticas/pruebas-agenticas/0.5.26/runner/trazabilidad.mjs .temp/coordinacion/2026-10-20/B-antigravity/quality.json
```

## Cinco roles y veredicto real

1. Explorer: inspección de diff, help y TUI real; navegador con fixtures para Launch/Card/SendBox. Blueprint propuesto declara expresamente esa diferencia.
2. Analyser: requisitos ligados a citas de los encargos y README. Incluye la decisión cerrada para origen desconocido. Tres requisitos válidos, sin huecos en el diseño focal presentado.
3. Designer: seis agrupaciones propuestas con positivo/negativo, casos parametrizados para backend y tres casos UI nuevos; pruebas de churn e informes añadidas por hallazgos reales. Mutante propuesto, **no ejecutado** sobre el árbol compartido.
4. Executor: comandos deterministas, códigos y logs anteriores. No se aceptaron propuestas ni baselines. No se hizo una mutación in-place del árbol sucio compartido.
5. Detective: comparación de logs, capturas, auditorías D y regresiones antes/después. Se corrigieron los hallazgos del alcance autorizado. Los fallos iniciales permanecen registrados.

`quality/roles.json` contiene el registro de esta iteración. No se midieron inicio/fin por rol; no se inventan timestamps. **No hay PASS de compuerta del plugin**: el catálogo/baseline nuevos no fueron aceptados por una persona y no se corrieron mutaciones ni una certificación global. Los 431/9 son resultados efectivos de los comandos focales, no una declaración de cobertura total.

## Inventario exacto de B y SHA-256

HEAD observado: `4f1bc4b34bd51e685bab769dae15237bdb4a7a08` (`Optimize remote Chrome tab streaming and input`). El árbol contiene también cambios de A/C/D; este inventario identifica **19 archivos tocados por B** y sus bytes al freeze, no pretende adjudicarse el diff completo del repo.

| Archivo | SHA-256 |
|---|---|
| `README.md` | `74704fa7ea50dcc358a5c3492d7640d4f4c452834e2dabe0959eb54f8518054c` |
| `lienzo/agent-capabilities.json` | `ed14c25df784441fe3ad391167651368cf2faac57970593f012a4ec42df83901` |
| `lienzo/agentes.py` | `272103daa38fdd3ec0c203bc99ad680ba8b4da7bd7f2d7e37fb800df5d4a69dc` |
| `lienzo/procinfo.py` | `a85faace7564301ae54c3c0862f986c0d8a958aea2f7a647a682f38ba2aaa421` |
| `lienzo/procs.py` | `927a65b9e0203604dcd15bbe0acfae36447fc25394f93d588f0134ee970ab774` |
| `lienzo/sessions.py` | `6c51baeee93877c8d20b356ae8314a6632db6284ad77528e0aaf69c17dc69845` |
| `lienzo/rules_api.py` | `7f5b2265539c49a07b04d95e7b735f9a150210069793c12295264dcc15bd172a` |
| `web/src/agents.ts` | `67fade5c1ad0e7abc4f5b7c00d5fee8f42c8907b322ad90431c5ffd9d1030210` |
| `web/src/components/Card.tsx` | `86f9895135551cea7781a2bd09c858a985e5c0cf24615e2d79addf88e39b77b0` |
| `web/src/components/Launch.tsx` | `14a629328dd7bccd87ed630158dc29574818a1fd7e34bd8ca09dcb6a07d16668` |
| `web/src/components/SendBox.tsx` | `86a5f21b846d6462b96810fed2f41013d9d0670fa53538fb371a311b324c383a` |
| `web/src/styles.css` | `45a2ad00c075cf24c7ca3480fcb25f8e211849ce7888ca18f0771e3bef02d10c` |
| `web/src/types.ts` | `03be656347be4382dd5a36db426457b8d55e5002505abd250dd3bdb42463e16c` |
| `tests/test_antigravity.py` | `e0fa92c56b28c598c4c8ac41ea4d57c8571dbdd4903e67f35a5d08db5becc137` |
| `tests/test_antigravity_rules.py` | `672e26568f06699ea357fe34439008700adc15c0893db8355a2b23641811a0b6` |
| `tests/test_server.py` | `3a4388d699e9da1524c06d1964aa14bebb0631bf9908bc4f24dc82c4ce4f3c65` |
| `tests/test_rules_frecuencia.py` | `8257e291e0840b19a8ee36d2c18a6d10acfdcd6e20390176c8459ad7d5b5cc4d` |
| `tests/test_release_recovery.py` | `5b0857b075841ff509ab750fabf460241d462c79684f3afc8d02fb9e240d1d1e` |
| `web/tests-ui/antigravity.spec.ts` | `a9375d91e57f746cb504e74df5f8a50e28a4cdf1e71cb109432c954637f8c580` |

Inventario procesable: `.temp/coordinacion/2026-10-20/B-antigravity/sources.sha256.json`. El informe y artefactos adicionales tienen manifiesto separado para evitar un hash autorreferente. Los archivos de producción previos `launch.py`, `server.py`, `protocol.py`, `transcripts.py`, `harness_updates.py`, y los tests compartidos previos no fueron editados por B; se conservó su contenido preexistente.

## Límites live y entrega

- Una sola sesión agy al cierre: **PID 20088**. B no la cerró. La sesión propia 8284 se cerró limpiamente con `/exit` antes de la nueva instrucción de no abrir/cerrar más agy. No se volvió a abrir una terminal agy.
- Prueba inocua autorizada en 20088: un solo envío y respuesta visible independiente **`LIENZO_B_20088_OK`** (`existing-send.json`, `existing-after.json`). No se repitió.
- Las capturas live confirman pantalla y envío, pero no transcripción, reglas de fin, cuotas, restauración ni reanudación persistida.
- Tras la implementación, lectura GET de la tarjeta activa sigue sin `state_source` ni `screen_observation` (`server-after-implementation.json`): el servidor activo aún sirve el backend anterior. **La coordinadora controla la única activación posterior.** No se afirma validación live del backend nuevo ni de la guardia por HTTP real; se probaron las funciones y handlers en entornos aislados.
- Build de UI generado; pruebas de UI usan datos sintéticos, interceptan escrituras y no son conversaciones reales. La captura `ui-parcial.png` es una fixture.
- No se cambió cuenta, permiso, hook o política. No se hizo git add/commit/pull, no se aceptó baseline ni se reinició el servidor.
- Revisión focal de lógica, validación de entrada, coherencia de rutas local/remota, retención de informes y accesibilidad. No incluye auditoría global de dependencias, suite global del repositorio, pruebas de carga ni certificación de toda la integración combinada de A/C/D.

## Completitud: diagnóstico posterior del almacén real de agy

La primera fase investigó `cache/last_conversations.json` y la pantalla, pero **no había inspeccionado el almacén de pasos**. La investigación adicional de sólo lectura encontró una fuente concreta que merece diseño. Por eso esta entrega es **soporte de terminal parcial**, no integración completa de conversaciones/turnos.

Fuentes medidas en `C:/Users/ArielLevy/.gemini/antigravity-cli`:

| Fuente | Medición sin contenido de registros | Qué prueba / qué falta |
|---|---|---|
| `conversation_summaries.db` | SQLite legible, 20.480 bytes, 5 filas en `conversation_summaries`; campos `conversation_id`, `status`, `not_fully_idle`, `last_user_input_step_index`, `raw_summary` entre otros | Existe índice local de conversaciones. No se leyó ni interpretó el resumen o título ni se atribuyó su estado a un proceso |
| `conversations/751aecc3-a2f6-474e-8029-ef5191048f81.db` | SQLite legible, 819.200 bytes; `trajectory_meta` 1 fila, `steps` 36 filas, `gen_metadata` 17, `executor_metadata` 3 | Hay almacenamiento real de pasos. `steps` tiene `idx`, `step_type`, `status`, `step_format`, `metadata`, `step_payload` y otros BLOB. No se decodificó el contenido |
| `conversations/551ea4e6-21f8-4257-aafc-a5f20376001d.db` | SQLite legible, 393.216 bytes; `trajectory_meta` 1 fila, `steps` 0, `trajectory_metadata_blob` 1 | Corresponde al UUID observado de la sesión propia cerrada, que sólo recibió /help. No aporta ejemplos de turnos |
| `trajectory_meta` de ambos DB | Comparaciones SQL booleanas: `cascade_id == nombre_del_archivo` es true en ambos; `trajectory_id == nombre_del_archivo` es false | Se comprobó el campo que coincide con la identidad del archivo. No prueba qué PID lo usa |
| Agregados de `steps` del DB con 36 filas | Tipos 14 (3), 15 (17), 101 (2), 132 (14); todos `status=3`, `step_format=0`. 36 payloads no nulos, de 688 a 25.819 bytes | Son valores de enums medidos; **no se les asigna significado de usuario/asistente/final** sin esquema verificable |
| `history.jsonl` | 8 registros; campos `display:str`, `timestamp:int`, `workspace:str`, `type:str`, `conversationId:str` | Hay asociación de entrada/historial con ID. No se imprimió `display` ni otro valor, y no hay prueba de respuesta completa o PID |
| `presence/*.lock` | Dos archivos de 0 bytes; el de la sesión propia cerrada se leyó vacío; el de la otra conversación devuelve `PermissionError: [Errno 13] Permission denied` | No contiene metadatos legibles de PID. No se identificó dueño del bloqueo ni se forzó lectura o permiso |
| `cache/conversation_metadata.json` | Objeto con metadata de otras tres conversaciones; sólo se inspeccionó forma y tipos | No se utilizó para atribuir al proceso actual una conversación por carpeta o fecha |
| `.gemini/antigravity/conversations` | Inventario paralelo de archivos `.pb` y un `.db` de la instalación de escritorio | Se distinguió del directorio de CLI; no se mezclaron historias de IDE y CLI ni se decodificaron protobufs |

Comandos diagnósticos, desde raíz:

```powershell
py .temp/coordinacion/2026-10-20/B-antigravity/inspect_agy_storage.py
py .temp/coordinacion/2026-10-20/B-antigravity/inspect_agy_shapes.py
```

Resultados rc=0 en `storage-schema.json` y `storage-shapes.json`. El primer intento del primer script terminó con rc=1 al intentar leer el lock; su traceback está en `storage-schema-initial-error.log`. El script siguiente registra esa denegación y omite el lock, sin elevar privilegios ni cambiar permisos. Sólo ejecuta metadatos de esquema, conteos y comparaciones booleanas. No imprime payloads, mensajes, resúmenes, cuentas o secretos.

SQLite se abrió con `mode=ro&immutable=1` y `PRAGMA query_only=ON`. No había archivos WAL al medir. Estos conteos son una observación puntual; no certifican una instantánea transaccional de todo el conjunto mientras agy vive. No se descifró ni descomprimió ningún archivo.

**Conclusión acotada:** existe un almacén local legible con una estructura candidata para un lector. No se verificaron el contrato de los BLOB/enums ni una vinculación autoritativa PID/FILETIME → conversación. No corresponde afirmar que no hay fuente disponible ni que terminalOnly resuelve toda la integración. Tampoco corresponde activar on_stop a partir de `status=3` sin conocer su significado.

Diseño propuesto, sin ampliación de implementación:

1. Investigar un esquema versionado verificable para `step_payload`, `metadata` y los enums, en un contrato oficial o artefactos de la instalación. Leer SQLite no basta para interpretar un final de turno.
2. Resolver identidad de proceso con prueba explícita ligada a PID y fecha de creación, y con confirmación de la conversación realmente abierta. `last_conversations` por cwd y un lock sin dueño identificado no cumplen ese contrato. Ante duda, no adoptar la historia.
3. Definir un lector separado con modo de apertura sólo lectura, cotas de lectura y pruebas sobre fixtures sanitizadas. Detectar formato/versión no soportada de manera explícita. No inventar equivalencias de enums ni extraer texto arbitrario como respuesta final.
4. Validar usuario, respuesta, tool calls, interrupción y cierre con una sesión de prueba futura **sólo cuando raíz autorice nuevos agy/envíos**. Hasta tener esa prueba, mantener terminalOnly y rechazar informes automáticos.

No se implementó ese lector ni se prometió reanudación fiable o salida estructurada. Las 19 fuentes del inventario se mantienen congeladas; sólo se agregaron diagnóstico y evidencia bajo `.temp` y esta sección del informe.

**ESTADO: fuentes de B congeladas; evidencia focal estable; almacén local identificado para diseño posterior; activación e integración final a cargo de raíz.**
