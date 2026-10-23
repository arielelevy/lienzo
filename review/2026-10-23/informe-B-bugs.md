# Encargo B — informe

2026-10-23. Sin `git add`, commit, pull, push ni reinicio del servidor.
No existe `AGENTS.md` en la raíz: se aplicaron las instrucciones de usuario proporcionadas.

## 1. `/rename` con basura delante

Causa reproducida: `answer_dialog` numérico enviaba el número sin releer la consola; la rama con
flechas sí revalidaba. Un permiso ya contestado seguía en la tarjeta hasta el barrido, de modo que
el auto-aprobar podía escribir `1` en la caja. No se atribuye sin evidencia el incidente exacto a
ese camino ni se afirma haber reproducido los dos reintentos remotos.

Arreglo en `lienzo/sessions.py`: revalidar también el diálogo numérico. `_nombrar_nativo` relee la caja
antes de `/rename` y `/remote-control`; difiere con código `native_deferred` si hay texto, cola,
diálogo, lectura fallida o no reconoce una caja. No descarta texto de Ariel.

Pruebas nuevas en `tests/test_encargo_b_bugs.py`: los cuatro casos iniciales dieron **4 failed**
antes del arreglo, con `200` donde debía haber `409`; pasaron después. Se agregaron lectura vacía
sin caja y envío válido con caja vacía. `tests/test_autoaprobar.py` prepara la revalidación vigente
en el test de transición de columna. Logs iniciales: salida de herramientas de esta sesión; no se
reconstruyó un log crudo retroactivo. Persistencia posterior: runner, `B-resultados/salidas/`.

Fuera: atomicidad entre lectura e inyección contra teclado humano u otro proceso. Revisión detallada
en `code-review-B-bugs.md`.

## 2. `on_stop` de Kiro

La guarda existente en `server.accion_send` ya impide armar `sin_aviso` si `en_turno` es verdadero,
también para Kiro. No requirió otro arreglo productivo.

`tests/test_optimizacion_trabajo.py::test_kiro_dos_turnos_con_envio_y_acuse_intermedio_avisan_ambos`
recorre dos turnos Kiro consecutivos, con su envío y acuse intermedio, leyendo estados mediante
`apply_turn_unhooked` y ejecutando `fire_on_stop`. Ambos informes llegan y `sin_aviso` permanece vacío.
Se avanza el reloj datetime 60 segundos para respetar el enfriamiento normal. El primer diseño del
test difería el segundo aviso por enfriamiento; eso no fue un bug de Kiro.

Contraprueba causal: `py -3.14 .temp/coordinacion/2026-10-23/B-repro-kiro.py` desactiva `en_turno`
sólo en su proceso mediante `patch.object`, sin editar fuentes. El caso falla porque el acuse arma
`sin_aviso`; log `B-kiro-sin-guarda.log`, código 1. Con la guarda vigente pasa. Esto confirma el
mecanismo compartido, aunque no demuestra qué versión ejecutaba la Kiro del incidente original.

Fuera: no se lanzó una TUI Kiro ni se hicieron llamadas pagas. Es una regresión integrada con
transcripción/transporte de fixture.

## 3. Marcas headless viejas

Por aviso de la coordinadora, se reutiliza `2936cde`, sin rehacerlo. La función `limpiar_batch_antiguo`
comprueba el comando del mismo proceso y limpia `external`/`no_console` sólo si es interactivo.

Se ejecutó `tests/test_encargo_u.py::test_barrido_limpia_solo_batch_viejo_interactivo`: sus cinco
variantes verifican TUI viva, `-p`, `--print`, comando no legible y orquestador. La TUI pierde la marca
y el JSON persistido también; las otras conservan la protección. No se modificó ese archivo.

## 4. IP de origen del beacon

Causa confirmada: el HMAC autentica el payload, pero `_recibir` almacena `addr[0]` en las candidatas.
El reproductor `.temp/coordinacion/2026-10-23/B-repro-beacon.py` firma `192.168.1.72`, simula recepción
desde `172.17.240.1` y falla con `AssertionError` porque el receptor elige el origen NAT. Todo el
estado y la persistencia están sustituidos; no se alteraron los pares reales.

Se entrega **diseño, sin código de protocolo**, según la alternativa autorizada. Ver
`diseno-B-beacon-firmado.md`: payload extensible compatible con decoder viejo, candidatas firmadas,
validación, protección contra downgrade y migración por etapas. Un peer viejo no firma sus IPs;
recuperar una dirección desconocida suya desde el origen vuelve a abrir la falla. Falta medir
compatibilidad operativa mixta y recuperación DHCP en las dos PCs antes de implementarlo.

## Pruebas agénticas y revisión

Cinco roles secuenciales en esta sesión. Artefactos aislados en
`.temp/coordinacion/2026-10-23/B-resultados/`; config `B-config.json` en su carpeta superior.
Explorer distingue código leído de UI observada; no hubo navegador ni consola real.
`validar`: 0 errores, 1 aviso por ausencia de mutaciones. `delta` y `certificar`: artefactos válidos,
salida 1 por no estar aprobados. `trazabilidad`: salida 1 con diez señales (faltan clasificaciones
positivas/negativas separadas, asociaciones de nodos y caso ejecutable del diseño de beacon).
No se aceptó nada.
Runner: B-focal OK, salida 1 por baseline ausente. No equivale a PASS de compuerta.
`compuerta --informe`: código de proceso 2, `No hay baseline.json: fijarlo a mano con ejecutar.mjs --fijar`.
Revisión de código guardada en `code-review-B-bugs.md`.

Focales: **110 passed**. `ruff check` limpio; formato aplicado sólo a archivos tocados.
Las ejecuciones dentro del sandbox fallaron con `PermissionError: [WinError 5] Access is denied`;
las verificaciones válidas se hicieron con escalación autorizada.

## Suite completa y Git

Suite única ejecutada: `py -3.14 -m pytest tests -q -p no:cacheprovider`.
Log completo: `.temp/coordinacion/2026-10-23/B-suite-completa.log`.
Resultado: **3644 passed, 11 skipped in 888.74s (0:14:48)**, código de salida **0**.
No se volvió a ejecutar la suite completa. Los 11 omitidos no se informan como aprobados.

Estado final de `git status --short`:

```text
 M PENDIENTES.md
 M lienzo/sessions.py
 M tests/test_autoaprobar.py
 M tests/test_optimizacion_trabajo.py
 M web/src/components/Board.tsx
 M web/src/styles.css
 M web/tests-ui/proyectos-cluster.spec.ts
?? review/2026-10-23/
?? tests/test_encargo_b_bugs.py
?? web/src/project-pack.test.ts
?? web/src/project-pack.ts
```

`PENDIENTES.md` y los archivos de `web/` fueron modificados por otros trabajos del árbol compartido:
este encargo no los escribió ni revisó.
Los tres documentos de B están bajo `review/2026-10-23/`. La evidencia temporal está ignorada.
`git diff --check` sin errores. No hubo commits ni reinicio del servidor.

ESTADO: listo
