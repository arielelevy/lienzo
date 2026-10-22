# Code review — noche E (vista por pestañas con screencast), 2026-10-21

Alcance: `lienzo/browser_host.mjs`, `lienzo/browser_stream.py` (sólo el tope de TabWorker),
`web/src/components/RemoteBrowser.tsx`, `tests/browser_host.test.mjs`, `tests/fixtures/browser_host_socket.mjs`,
`tests/test_browser_tabs_stream.py`, `web/tests-ui/chrome.spec.ts`. Skill `code-review`, nivel medio, sobre el árbol.

| # | Hallazgo | Qué se hizo | Prueba |
|---|---|---|---|
| 1 | Cuadro de antes de un resize informado con el tamaño nuevo (existing) | `takeFrame` compara `metadata.deviceWidth/Height` con el tamaño leído (±1); si no coincide, se acusa, se descarta y se captura a pedido. `cast.last` guarda su tamaño y sólo se repite si coincide | node «un cuadro de antes de un resize…» |
| 2 | Lo mismo en modo lienzo tras `setDeviceMetricsOverride` | `castShot` recibe el tamaño emulado y aplica el mismo chequeo | ídem (mismo camino) |
| 3 | Rueda en pestaña oculta → 409 → la UI bloquea toda la entrada | La UI no manda la rueda mientras `hidden` (el aviso lo dice); el 409 del host queda como resguardo | eslint/tsc; Playwright del aviso |
| 4 | Sin tope de px: 4K a DPR 2 pasa los 4 MiB | Screencast con `maxWidth 2560 / maxHeight 1600`; la captura a pedido baja a calidad 50 si pasa 4 MiB | — (sin pantalla 4K para medir) |
| 5 | `cast.waiters` crecía con cada espera vencida | `Set` y se borra el resolver y el timer al terminar la espera | node (sin fuga observable en fixture) |
| 6 | Oculta: captura 10 veces/s indefinidamente | Si la imagen no cambia, el intervalo se duplica hasta 1 s; una entrada lo vuelve a 100 ms | node «oculta y sin cambios…» |
| 7 | `Runtime.evaluate` en el mundo principal: la página puede falsear tamaño/visibilidad | Lectura en un mundo aislado (`Page.createIsolatedWorld`, se recrea tras navegar; reintento sólo de la lectura). Una página con el hilo principal ocupado sigue pudiendo demorarla: **pendiente** | node (traza fría con `getFrameTree` + `createIsolatedWorld`); e2e real |
| 8 | `stop()`/salida de Chrome no paraban los casts (timers sobre socket muerto) | `dropPages()` suelta timers y esperas sin mandar nada; la poda de pestañas usa `stopCast(cdp, false)` | node completo |
| 9 | Página quieta: tras 2 s recapturaba bytes distintos | Se repite el último del mismo tamaño mientras sea visible; sin `CAST_STALE` | node «frame caliente no captura a pedido» |
| 10 | El release descartaba el último move de un arrastre | Antes de cualquier otra entrada sale el último move guardado (sin esperarlo); los errores de move siguen sólo en stderr: **aceptado** | node «el clic sale enseguida, detrás del último move guardado» |

## Verificación tras las correcciones

- Node `browser_host` + `browser_profiles`: 33/33 (`.temp/resultados/noche-E/node-host-3.log`).
- pytest `test_browser_tabs_stream.py` + `test_browser_remote.py`: 41/41 (`pytest-2.log`).
- Playwright `chrome.spec.ts` en vite dev propio: 37/38 antes de las correcciones (`playwright-1.log`). La falla
  «worker ocupado al leer perfiles» es previa (falla igual con el `RemoteBrowser.tsx` de HEAD en dev, pasa contra dist).
  **No re-corrido** tras el filtro de rueda.
- e2e con Chrome real (`e2e-nuevo-con-2.json`, `e2e-nuevo-sin-2.json`): sin errores en los tres estados.
- ruff, eslint y tsc limpios en estos archivos.

## Pendientes reales

- Prueba con la PC bloqueada (espera el OK de Ariel).
- Hilo principal ocupado demora la lectura de tamaño (8 s → 504) igual que antes con `getLayoutMetrics`.
- Tope 4K sin medir en pantalla real.

---

## Segunda ronda (23:50–00:20): pestañas restauradas, visor duplicado y calidad por scroll

### Revisión 1 (detach, visor duplicado, traza), 8 hallazgos
| Hallazgo | Qué se hizo |
|---|---|
| `_wait_owner` dormía con `selection_lock` tomado | Se espera en `_inputs` antes de tomar el lock; `_tab_lock` pasa a `Condition` con `notify_all` al liberar |
| 3 s < 8 s del CDP del visor viejo | Plazo de 10 s para un dueño ya cerrado |
| `cdp.gone` sin uso | `send` de una sesión soltada rechaza con 409 sin mandar nada; `evaluate` no reintenta |
| Mensaje «reemplazó» también para pestañas cerradas | Mensaje neutro: «Chrome soltó la pestaña (se cerró, se recargó o estaba sin cargar)» |
| `detachFromTarget` a una sesión ya soltada | Sólo si no está `gone` (prueba: 0 detach) |
| La traza no llega al stream | Comentario corregido: está en la respuesta del host |
| `cdp.source` compartido | Sólo se arma con TIMING; carrera entre pedidos concurrentes **aceptada** (sólo perfilado) |
| Sondeo cada 50 ms | `Condition.wait` |

### Revisión 2 (calidad por scroll), 10 hallazgos
| Hallazgo | Qué se hizo |
|---|---|
| `recast` fallido dejaba la vista congelada | El cast se descarta y el próximo pedido lo arranca de cero (prueba con fallo inyectado) |
| Visor lento: «quieta» en cada cuadro, cambio de modo en cada cuadro | Quieta sólo sin cuadro pendiente; medido con acuse a 350 ms: 194 KB por cuadro sostenido |
| Modo scroll sin tope de px | `Math.min(css, MAX_PX)` |
| Dueño vivo aún no cerrado en reconexión | Se le da 1 s antes de rechazar |
| Entrada del visor nuevo detrás del `open` | **Aceptado**: la UI no manda entrada antes del primer cuadro |
| `tabs()` podaba sin cortar lo pendiente | La poda usa `detached()` (409 inmediato, cast suelto) |
| Cuadro 1× atrasado tomado como refinado | Se lee el ancho del JPEG (encabezado SOF) y se descarta uno más angosto que el nítido |
| TIMING compartido | Ídem arriba, aceptado |
| Chequeo de nitidez duplicado | Queda uno |
| `detached()` sólo paraba el cast si seguía en `pages` | Siempre `stopCast(cdp, false)` |

### Verificación
- Node: 36/36 (`.temp/resultados/noche-E/node-host-7.log`). Rojo previo: pestaña reemplazada daba 504
  (`replaced-tab`); reconexión rápida daba «ya tiene un visor abierto» (pytest).
- pytest pestañas + remoto: 42/42 (`pytest-5.log`). Playwright `chrome.spec.ts` en vite dev propio: 37/38
  (`playwright-2.log`); la falla es la previa de vite dev.
- ruff, eslint y tsc limpios.
- Medido con Chrome real aislado (`perf-antes-local.json` → `perf-despues-local-3.json`, `perf-despues-rtt350.json`).
