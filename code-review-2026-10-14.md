# Code Review: puente con un orquestador externo local

## Revisión adicional: consultas Git entre peers emparejados

Alcance: `lienzo/remote_run.py`, `tests/test_mejoras.py`, `README.md`.
Se incorporan `status` y `log` con argv fijos para peers autenticados; se mantienen `launch_roots`, rechazo de argumentos y precedencia del bloqueo local explícito. No hay ejecución de shell ni push incorporado.
Hallazgo de imports corregido. Ruff pasa; 22 pruebas focales pasan tras la corrección. Runner backend-pytest: exit 0, 285365 ms, evidencia en `pruebas-agenticas/resultados/intentos/2026-10-14T19-54-01.448Z-14052/`. Compuerta ESCALAR: evidencia integral y mutación anteriores. Sin verificación del despliegue remoto. Sin nuevos hallazgos pendientes en los tres archivos.

**Fecha**: 2026-10-14
**Alcance**: PR review de cambios sin commitear
**Archivos**:
- Módulo nuevo del puente en `lienzo/`, con su tira en `web/src/components/` y sus pruebas en `tests/` y `pruebas-agenticas/`.
- `lienzo/procinfo.py`, `lienzo/procs.py`, `lienzo/backend.py`, `lienzo/sessions.py`, `lienzo/rules.py`, `lienzo/server.py`
- `web/src/components/Card.tsx`, `web/src/components/SendBox.tsx`, `web/src/App.tsx`, `web/src/types.ts`, `web/src/styles.css`, `web/tests-ui/tablero-fijo.ts`

**Fuera de alcance**: `.rea-review/`, que es ajeno.

## Resumen

| Severidad | Encontrados | Corregidos |
| --- | --- | --- |
| CRITICAL | 0 | — |
| HIGH | 2 | 2 |
| MEDIUM | 3 | 3 |
| LOW | 2 | queda 1 |

## HIGH

### 1. La marca `external` nunca se limpiaba (corregido)

- **Qué pasaba:** `claim_pid` y `adopt_process` solo agregaban la marca. Además, el puente re-marcaba por `session_id` en cada vuelta, aun con la corrida terminada.
- **Riesgo:** al retomar con `claude --resume` en una terminal propia una sesión que había corrido en el orquestador, la tarjeta quedaba en solo lectura para siempre.
- **Arreglo:**
  - Un proceso nuevo decide de cero (`claim_pid` y `adopt_process`).
  - El puente solo marca corridas en curso.
  - Hay pruebas para las dos cosas.

### 2. Rutas armadas con el nombre interno de la capability (corregido)

- **Qué pasaba:** con un alias de playlist, el nombre interno puede diferir de la clave del listado de sesiones, y las rutas de estado darían 404.
- **Arreglo:** se usa la clave del listado, con su prueba.

## MEDIUM (corregidos)

1. **Orden de locks:** el puente tomaba su lock dentro de `state.lock`, al revés que en el sondeo, con riesgo de deadlock. Ahora `state.lock` nunca toma el del puente adentro.
2. **Contraste:** el link a la UI del orquestador usaba el azul por defecto del navegador sobre fondo oscuro, y el `textarea` quedaba blanco, fuera del tema. Ahora usan los tokens `--acc`, `--bg` y `--fg`.
3. **Log engañoso:** el reinicio del orquestador se logueaba como "cambió el proyecto". El epoch cambia en cada arranque (medido); ahora el mensaje distingue el reinicio del cambio de proyecto.

## LOW

1. **PEB por evento:** `claim_pid` recorre hasta 6 padres con lecturas de PEB en cada evento de hook, y lo hace con el lock tomado. El costo medido en pruebas es despreciable. **Queda como está.**
2. **Lectura de config por pedido:** el snapshot del puente lee `config.json` en cada pedido. Es aceptable para un poll de 3 s.

## Seguridad

- Solo loopback, sin proxies ni redirecciones: el token no puede salir a otro host.
- El token se lee de una variable de entorno o de un archivo, y no aparece en respuestas ni en logs. Lo verifican una prueba unitaria y el e2e.
- Las mutaciones exigen `X-Lienzo` (CSRF), y el orquestador recibe el epoch para rechazar actuar sobre otro proyecto.
- La cancelación exige repetir el `run_id` y verificar la corrida vigente, porque el orquestador contesta 200 a un id inexistente.
- No hay ruta para aprobar gates.

## Verificación

- Ruff, ESLint y `tsc` limpios.
- Pruebas unitarias del puente: 34 casos en verde.
- Suite del runner: 7 de 7.
- e2e contra el binario real, con su ejecutor de prueba: 26 de 26.
- Compuerta: ESCALAR, por la mutación desactualizada.

---

# Addendum: límite por frecuencia de `on_stop` y confirmación de envío

**Archivos:**
- `lienzo/rules.py`, `lienzo/rules_api.py`, `lienzo/send.py`, `lienzo/sessions.py`
- `skills/lienzo/coordinar.py`, `skills/lienzo/SKILL.md`
- `web/src/{types.ts, api.ts, nl.ts, names.ts, arrows-geometry.ts}`, `web/src/components/{Forward, Arrows, Panel}.tsx`
- Pruebas: `tests/test_rules_frecuencia.py` y `tests/test_envio_confirmado.py` (nuevas); `tests/test_server.py`, `tests/test_integration_guards.py` y `web/src/arrows-geometry.test.ts` (ajustadas)

## HIGH (encontrado en la revisión y corregido)

### 1. Un aviso diferido se podía perder

- **Qué pasaba:** en la primera versión, `fire_rule` limpiaba `deferred` al terminar de enviar. Un Stop que llegara mientras ese envío seguía en curso quedaba anotado en `deferred`, y el final del envío lo borraba.
- **Arreglo:**
  - La espera se consume al reservar la entrega (`entregas_diferidas`), no al terminar de enviar.
  - Un Stop con un envío en curso también se difiere. Antes solo se logueaba y se descartaba.
  - Pruebas: `test_un_stop_durante_la_entrega_diferida_abre_otra_espera` y `test_stop_con_envio_en_curso_no_se_pierde`.

## MEDIUM

1. **Cambio de contrato, aceptado y documentado:** una `on_stop` repetida sin `limit` ignora `max_fires`. Era lo pedido, porque el 30 venía del default de `coordinar.py`, no de una elección. `SKILL.md` documenta `limit:"total"` para quien quiera un tope total. Tres pruebas que fijaban el comportamiento viejo se ajustaron, con comentario.
2. **Envío pendiente de confirmación:** una tarjeta con hooks queda en su estado anterior hasta el `UserPromptSubmit`, que en la práctica llega en 1 o 2 s. No hay un indicador "enviando…" en la tarjeta. **Queda como mejora de UI.**
3. **Reposo antes del Enter:** `send.py` suma 1 s de reposo a todo envío con texto. Es el costo de no mezclar el Enter con el pegado. Si la terminal no consume el texto en 10 s:
   - en Codex se mantiene el error de siempre;
   - en el resto el Enter sale igual (como antes) y el server lo marca `sin_consumo` para el aviso.

## LOW

1. **Defaults duplicados en el front:** `rate_max` y `rate_window_s` se guardan como `null` cuando no se piden, y el front repite el 10/600 para mostrarlos. Si el server cambia el default, hay que cambiarlo en dos lugares.
2. **Prueba que no se reprodujo:** en una corrida del runner apareció una `F` en backend-pytest, sin salida que la identifique, y además se excedió el timeout de 300 s. Una corrida aislada dio 1651 de 1651 en 240 s. Queda como posible prueba inestable por carga; no se tocó el timeout aprobado.

## Verificación

- Ruff, ESLint y `tsc` limpios.
- Pruebas nuevas en verde: 8 de reglas y 8 de envío.
- Batería backend aislada: 1651 de 1651.
- Pruebas unitarias del front (`nl` y `arrows-geometry`) en verde.

---

## Addendum: catálogo de integraciones y panel de mejoras

Revisión focal de todos los cambios del catálogo: `lienzo/tools/`, preferencias,
lanzamiento local y reenviado, API, ensayo RTK, scripts operativos, panel, menú,
selector de modo y pruebas modificadas. No se cambian dependencias ni permisos.

### Hallazgos corregidos

- Las mejoras generales se omitían en ingeniería reversa. RTK y respuestas breves
  se habilitan en ambos modos; REA conserva su modo específico.
- REA de Windows podía anunciarse para una distro. WSL queda explícitamente sin
  verificar y no recibe una ruta de Windows.
- RTK en WSL devolvía `rtk` pese a prometer una ruta absoluta. Ahora consulta
  `command -v rtk` en la distro elegida y rechaza rutas relativas o múltiples.
- La huella del ensayo RTK y la validación previa al reinicio omitían los módulos
  nuevos. Ambas incluyen `lienzo/tools/*.py`.
- El frontend nuevo recibía el formato anterior del servidor vivo. Se verificó
  por API y se reinició usando `POST /restart`; el catálogo real devolvió 5 entradas.
- El menú podía salir del viewport. Se mide su tamaño, se ajusta la posición y
  se conserva el foco sin desplazamiento automático. Los eventos sin coordenadas
  usan el elemento de origen. El caso del borde genera un MouseEvent real.
- Los dobles de lanzamiento y las fixtures del panel usaban el contrato previo.
  Se actualizan sin quitar las aserciones de error, preferencias ni distro.

### Evidencia y límites

- Pruebas backend focales: 151 de 151, código 0, en
  `pruebas-agenticas/resultados/tools-backend-focal.log`.
- Panel: 6 de 6, código 0, en `tools-mejoras-ready.log`; API paga simulada,
  ninguna llamada a modelos ni escritura en preferencias reales.
- Browser real: catálogo 5 de 5 y selección de modo sin lanzar agentes;
  captura `tools-real.png` y registro `tools-explorer.json`.
- Primera suite: 3 dobles backend desactualizados y dos errores ENOENT en trazas
  de navegador por corridas simultáneas propias. Los intentos quedan preservados.
- Suite final y compuerta: consultar `tools-suite-final.log`, `actual.json` y
  `tools-compuerta.log`. No se aprueban baselines ni se reutiliza la medición
  anterior de mutaciones como evidencia del código nuevo.

Sin hallazgos de seguridad abiertos dentro de este cambio. La disponibilidad
del catálogo comprueba presencia/configuración, no conectividad ni la versión
ejecutada de cada binario. REA en WSL no está certificada. Una PC con backend
viejo puede ignorar el modo reenviado: actualizar las PCs antes de usarlo.
No se ejecuta una auditoría global de dependencias ni se afirma cobertura
funcional de una CLI realmente lanzada. La certificación del cambio depende
del veredicto registrado por el runner.

---

# Code Review: actualización de Codex y arranque sin handles heredados

**Fecha**: 2026-10-14
**Alcance**: PR review del diff sin commitear
**Archivos**: `lienzo/harness_updates.py`, `lienzo/startup_update.py`, `pyproject.toml`,
`tests/test_harness_updates.py`, `tests/test_startup_update.py`, `tests/test_launch_improvements.py`

## Resumen

| Severidad | Cantidad | Estado |
|-----------|----------|--------|
| CRITICAL | 1 | Corregido |
| HIGH | 2 | Corregidos |
| MEDIUM | 0 | — |

## CRITICAL

1. **`latest_version` podía matar el hilo de actualizaciones.** `json.load(r).get(...)` sobre una
   respuesta que no fuera objeto tiraba `AttributeError`, que no se atrapaba en `ensure` y terminaba
   `Updater.loop`: ningún harness volvía a actualizarse hasta reiniciar. Ahora se valida el tipo.

## HIGH

1. **Fallo silencioso en `up_to_date`.** Un error de red o de `--version` devolvía `None` sin
   registro. Ahora cada caso que vuelve a `codex update` deja en el log el motivo.
2. **Comparación por igualdad.** Si el instalador publica antes que npm, la versión instalada es
   más nueva que `latest` y se reinstalaba en cada ciclo: el mismo bug que se quería arreglar.
   Ahora se compara como tupla y una versión igual o más nueva cuenta como al día.

## Verificado sin hallazgos

- `startup_update.py`: `git` ya no hereda stdin/stdout/stderr. `git pull` con stdin nulo no puede
  pedir credenciales por consola; el Git Credential Manager pide por ventana, así que no cambia el uso real.
  La salida del pull se imprime al terminar en vez de en vivo (tope de 60 s).
- `testpaths = ["tests"]`: fuera de `tests/` sólo se juntaban reproducciones ignoradas por git.
- Pruebas nuevas: al día, más nueva que npm, desactualizada, registro caído. Suite completa: 1672 passed
  antes de estas correcciones; focal después: 16 passed. `ruff check`: sin hallazgos.

---

# Code Review: traer archivos desde otra PC

**Fecha**: 2026-10-14
**Alcance**: PR review — `lienzo/xfer.py` (`traer`, `enviar_a_pedido`, `mas_nuevo`), `lienzo/server.py`
(`POST /xfer/traer`, `GET /xfer/<id>?pc=`, `POST /peer/xfer/traer`, `GET /peer/xfer/<id>`), `tests/test_xfer.py`

Sin hallazgos que corregir. Revisado:
- Confianza: una PC emparejada ya podía escribir en `copy_roots`, lanzar sesiones y reiniciar. Ahora
  también puede pedir que le manden algo, pero sólo desde `copy_roots` de la PC que manda, y con firma
  verificada (401 sin firma). El destino lo valida la PC que pide antes de reenviar y otra vez al recibir.
- Errores: carpeta ilegible o vacía vuelven como 500/404 con motivo; una PC con el código viejo contesta 404.
- Pruebas: archivo más nuevo (ignora `.parte`), firma y copy_roots, validación local del destino.
  Suite completa: 1677 passed.
