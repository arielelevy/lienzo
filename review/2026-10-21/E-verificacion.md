# E — verificación 0.6.0

Estado: repetición pytest medida; pendiente de GLOBAL FINAL con todo el árbol congelado.

## Corrida global medida

ID: `2026-10-21T03-07-10.227Z-45952`.
Inicio UTC: `2026-10-21T03:07:10.1719792Z`.
Fin UTC: `2026-10-21T03:10:16.3916149Z`.
Duración del runner: 186.2195494 s. Código: 1.
Validador: código 0, 0 errores y 0 avisos.
Compuerta: **FAIL**, código 1; 4 de 7 casos con código 0.

| Caso | Código | Duración |
|---|---:|---:|
| backend-pytest | 1 | 96.726 s |
| frontend-lint | 0 | 12.619 s |
| frontend-build | 0 | 8.149 s |
| frontend-unit | 0 | 0.222 s |
| frontend-playwright | 1 | 60.145 s |
| memoria-focal | 1 | 5.811 s |
| memoria-e2e | 0 | 2.023 s |

Backend: `3 skipped, 2867 errors in 94.72s (0:01:34)`.
Memoria focal: `153 errors in 4.57s`.
Ambos quedaron impedidos por preparación defectuosa de E: `PYTEST_ADDOPTS` contenía barras inversas y pytest produjo la ruta `C:\UsersARIELL~1AppDataLocalTemp\lienzo-E-global-20261021-26320`, con `FileNotFoundError: [WinError 3]`. No se atribuye ese resultado al producto.

Playwright: `135 passed (59.6s)`, 1 failed, `tests-ui/humo.spec.ts:33`.
Esperado: `scroll 0px, nada fuera de pantalla`.
Recibido: `scroll 93px, span.right se sale 91px · button.kebab se sale 91px · button.grip se sale 58px · span.chip se sale 13px`.
F está asignado al arreglo; E no repite UI/build hasta su entrega y congelamiento.
La traza preservada se abrió para inspección de metadatos: 3 entradas trace, 1 error, 24 frames y 18 snapshots. No se copian conversaciones al informe.

Memoria e2e: 16 comprobaciones OK, veredicto True. Al cierre no había listeners en 7391/7392; sólo el servicio propio fue iniciado por el caso y cerrado por su finally.
Build pasó con aviso de chunk mayor a 500 kB; no se alteró el umbral.

## Identidad y límites de la compuerta

Huella antes: `0060a9361ab93d93`.
Huella después: `ecc182e0d8b80880`.
La huella cambió. Los Markdown seguían en edición autorizada; no se atribuye la diferencia completa a una causa sin inventario adicional.
La compuerta informa mutación anterior de otro estado. No se ejecutaron mutaciones nuevas; su cifra histórica de 5 de 6 no acredita esta release.
No se acepta baseline, no se fusionan parciales y no hay PASS global.

## Repetición autorizada

La primera corrida terminó antes de lanzar la repetición.
Sólo `backend-pytest,memoria-focal`, con config original intacta.
Ruta corregida: `--basetemp=C:/Users/ARIELL~1/AppData/Local/Temp/lienzo-E/global-20261021-39872`.
El padre `C:/Users/ARIELL~1/AppData/Local/Temp/lienzo-E` fue creado y su existencia comprobada.
Resultado: código 0, 2 de 2 casos iguales al baseline.
ID: `2026-10-21T03-10-45.515Z-15520`.
Duración del runner: 532.7517016 s.
Backend: código 0, 496.281 s; `2867 passed, 3 skipped in 493.92s (0:08:13)`.
Memoria focal: código 0, 35.865 s; `153 passed in 33.98s`.
Es una corrida selectiva; no reemplaza la global. La configuración original sigue sin cambios.
Huella antes: `b2037d9ef0137fcd`; después: `431a699e9b238250`. El árbol siguió en edición autorizada; estos resultados no certifican una global congelada.
Al cierre no había listeners en 7391/7392.

## Compuerta posterior real

Ejecutada después de terminar pytest, sobre la configuración original, sin fusionar `actual.parcial.json`.
Resultado: **FAIL**, código 1. Conserva 4 de 7 casos globales con código 0.
Detecta `actual.json es de otro estado del código`, los tres códigos fallidos de la global anterior y `mutacion.json` de otro estado.
Los dos códigos corregidos están en la corrida selectiva; la compuerta no los incorpora automáticamente y E no modifica resultados para hacerla pasar.
Log completo y metadatos: `.temp/coordinacion/2026-10-20/E-verificacion/compuerta-posterior.log` y `compuerta-posterior.json`.
No se ejecutará otra global hasta recibir **GLOBAL FINAL** de raíz. El orden acordado para esa corrida es build antes de UI, con producto, reviews y docs congelados. E no ejecutó UI/build después de la asignación a F.

## Evidencia

- `.temp/coordinacion/2026-10-20/E-verificacion/global-20261021/ADVERTENCIA.md`: primer intento impedido por `spawn EPERM`, con evidencia anterior claramente invalidada para esta medición.
- `.temp/coordinacion/2026-10-20/E-verificacion/global-20261021-030709/`: argv, tiempos, códigos, config de ejecución, huellas, actual global, compuerta y cierre.
- `.temp/coordinacion/2026-10-20/E-verificacion/global-20261021-031044/`: repetición autorizada con basetemp corregido.
- `pruebas-agenticas/resultados/intentos/2026-10-21T03-07-10.227Z-45952/salidas/`: logs íntegros por caso de la global.
- `.temp/coordinacion/2026-10-20/E-verificacion/roles.json`: cinco roles en una misma sesión, con límites temporales explícitos.
- `review/2026-10-21/code-review-E-verificacion.md`: revisión del script propio, separada de B.

AGY sigue pendiente de PROBAR AGY. No se envió texto, no se cerró PID20088 y no se abrió otro agy.

ESTADO: backend corregido 2867 passed y 3 skipped; memoria focal 153 passed; repetición código 0. Compuerta real FAIL, sin fusionar parciales ni aceptar baseline. Pendiente GLOBAL FINAL y PROBAR AGY.
