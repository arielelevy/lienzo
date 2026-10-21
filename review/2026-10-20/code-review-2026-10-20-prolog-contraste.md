# Code review: contraste lógico de candidatos (frente D)

**Fecha:** 2026-10-20
**Alcance:** PR review de los archivos autorizados.

| Archivo | Cambio |
|---|---|
| `lienzo/prolog_contraste.py` (nuevo) | Snapshot en solo lectura, reglas `contraste-1`, validación del contrato 3 con verificación de pruebas, oráculo Python y `contrastar` |
| `lienzo/aprendizaje_api.py` | Ruta `POST <p>/candidatos/contraste` (+5 líneas) |
| `web/src/components/Learning.tsx` | Botón «Contrastar candidatos», validación de la respuesta, sección con prueba por observación, diferencias y errores (sobre la versión de C con hash `d46c895cf240de4f`) |
| `tests/test_prolog_contraste.py` (nuevo) | Pruebas del módulo y de la ruta |
| `web/tests-ui/contraste-candidatos.spec.ts` (nuevo) | Spec de UI |
| `docs/APRENDIZAJE.md` | Sección «Contraste lógico de candidatos» |

**Motor externo:** `D:/Apps/motor-logico` (commit `ff08a08`, contrato 3) solo se leyó y ejecutó. No se modificó.

## Recorrido agéntico (secuencial, en esta sesión)
- **Explorer.** Se leyeron:
  - el contrato 1 congelado (`learning.pl`) y los contratos 2 y 3;
  - `prolog_learning.py`, `conocimiento.py` (TIPOS, TRANSICIONES y RELACIONES) y los productores de candidatos (`optimization_research.record`, `optimization_memory`, `optimizacion_trabajo`, `creencias`).

  También se midió el grafo real en solo lectura (`.temp/coordinacion/2026-10-20/D-antigravity/prolog/inventario.json`).
- **Analyser.** El contrato 1 no admite candidatos ni oposiciones. El contrato 3, sin almacén, sí, sin tocar el motor.
  - En los datos reales hay 0 reglas, 0 veredictos con resultado y 1 fuente caída. Además, todos los candidatos están sin evidencia de una persona.
  - El router `conocimiento_api` no deriva `candidatos/` (ver Límites).
- **Designer.**
  - 22 casos dirigidos por observación y por independencia.
  - Un diferencial de 25 grafos aleatorios contra el oráculo.
  - Snapshot sin escrituras, fallos visibles, validación estricta y verificación de pruebas.
  - UI con fixtures.
- **Executor.**
  - `pytest tests/test_prolog_contraste.py tests/test_prolog_learning.py tests/test_aprendizaje.py`: **102 passed**, rc 0, con SWI-Prolog 9.0.4 real en WSL y 0 salteos (`-rs`), basetemp fuera del repo. Incluye el despacho por el router real `conocimiento_api` (línea aplicada por la raíz) y su rechazo del actor `server`. Las pruebas reales del motor superan la verificación estructural. Evidencia en `contraste-6.log`.
  - Playwright `contraste-candidatos.spec.ts` + `aprendizaje.spec.ts` de C, 1 worker, Vite propio (PID 24540, ya cerrado): **12 passed**, rc 0 (`playwright-2.log`).
  - `tsc` rc 0, eslint rc 0, ruff check y format rc 0.
  - Contraste real sobre lienzo, opensyync, chess, globant y teorema (`contraste-real.log` y, después del hallazgo 7, `contraste-real-2.log`): concluyente, 0 diferencias, huella del grafo idéntica antes y después, 0,2–0,3 s en caliente y 7,2 s el primer arranque de WSL.
  - La UI no se volvió a correr después del hallazgo 7: el cambio fue solo de backend y la forma de la respuesta no cambió.
- **Detective.**
  1. La primera corrida tuvo un error de oráculo en la prueba: el hallazgo fuente también es candidato. Se corrigió la prueba, no el código.
  2. En la UI, una aserción chocaba con el texto del aviso; se corrigió la prueba.
  3. `aprendizaje.spec.ts:94` falló una vez por `ENOENT` en `node_modules/.playwright-artifacts`, que comparten las corridas: es infraestructura. Con `--output` propio pasó.
  4. **Ajeno, corregido:** las 11 fallas de `test_captura.py` y `test_conocimiento.py` las atribuí primero a cambios de C, sin evidencia. Según la raíz, son un artefacto de mi `--basetemp` dentro del repo: `proyecto_de` sube al git raíz y `temporal()` espera el Temp real. La raíz las repite con basetemp fuera del git. No se tocó código de captura ni expectativas.

## Hallazgos de la review (incluida la provisional de la raíz)
| # | Severidad | Hallazgo | Estado |
|---|---|---|---|
| 1 | HIGH | Un `results` ausente o `None` contaba como vacío y `count=False` como 0 | Corregido: exige una lista y un `int` que no sea `bool`. Tiene regresión |
| 2 | HIGH | Se pedía `explain`, pero se descartaban las pruebas | Corregido: cada observación y cada «listo» llevan su prueba y sus fuentes. Se verifica que cada hoja sea un hecho enviado y cada paso una regla propia. El recorte se informa |
| 3 | HIGH | La evidencia de clase desconocida contaba como independiente | Corregido: solo cuenta la de una persona; la de un agente o de clase desconocida queda «no verificada». Tiene regresión |
| 4 | MEDIUM | `listo_para_revision` se mostraba aunque Python difiriera | Corregido: `concluyente: false` y `listo: null`. Tiene regresión |
| 5 | MEDIUM | `any([...])` validaba todo, pero con TRY004 y C419. Pasarlo a generador habría cortocircuitado | Corregido con un loop explícito: valida todas las premisas y después agrega. Regresión con una premisa truncada seguida de una inválida |
| 6 | LOW | Al cambiar de proyecto podía quedar un contraste anterior | Corregido: se aborta y se limpia al cambiar `base`. Tiene spec |
| 7 | HIGH (raíz) | Se aceptaba `candidato(c)` con `rule=caida_hallazgo_rechazado` y sin premisas: solo se miraba el ID de la regla | Corregido (`pruebas-rojo.log`: 5 rojos antes). Cada paso se contrasta con su regla de `RULES`: cabeza igual, una premisa por elemento del cuerpo, unificación coherente de variables y constantes, negación donde el cuerpo la pide. Cada negación tiene que ser falsa en los hechos o en el modelo Python (las negaciones de predicados derivados se apoyan en el oráculo). Un «listo» con prueba recortada queda sin conclusión. No se resuelve de nuevo |

No quedan hallazgos abiertos dentro del alcance.

## Límites
- **Router.** La raíz aplicó `"candidatos"` en `conocimiento_api._dispatch`, y la regresión pasa por ese router.
- El server vivo no se reinició y `web/dist` no se regeneró: la función no aparece en 7321 hasta un release coordinado.
- La utilidad medida es acotada. Con los datos actuales, la única señal es que los 60 candidatos no tienen evidencia de una persona. Las observaciones estructurales se cubren con pruebas, pero hoy no aparecen en datos reales.
- La review es de autor. La revisión independiente y el gate global quedan para la raíz.
