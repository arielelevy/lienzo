# Revisión E — script de verificación

Alcance: revisión focal del único script propio `.temp/coordinacion/2026-10-20/E-verificacion/global.ps1`.
Aplicada skill code-audit, checklist y catálogo de antipatrones. El alcance y directorio están fijados por el encargo; no se amplían a producto ni a dependencias ajenas.

## Hallazgos

1. Evidencia anterior tras fallo de arranque. La primera versión continuó después de `spawn EPERM`, copió un `actual.json` anterior y ejecutó compuerta. Corregido antes de la ejecución fuera del sandbox: se corta ante huella no identificable y se compara `idCorrida` antes de usar resultados. El intento original conserva ADVERTENCIA.md; sus conteos no se atribuyen a esta release.
2. Ruta Windows en `PYTEST_ADDOPTS`. Las barras inversas fueron consumidas por el parseo de pytest y causaron `FileNotFoundError: [WinError 3]` en backend y memoria-focal. Corregido después de terminar la corrida y por instrucción explícita de raíz: padre temporal existente, ruta normalizada con `/`. La primera corrida y sus logs íntegros se conservan. La repetición sólo incluye los dos casos afectados y no reemplaza `actual.json` global.
3. La compuerta del plugin lee `actual.json`, no `actual.parcial.json`. El script no genera compuerta global para una repetición selectiva ni fusiona evidencias a mano. Cualquier compuerta posterior sobre la config original se informa con ese alcance explícito.

## Verificaciones y límites

El validador de config dio 0 errores y 0 avisos. El script conserva argv, cwd, UTC, duración, códigos y logs completos; no usa RTK para comprimir logs de pruebas.
La configuración original conserva SHA256 `AE8AF61A35D4ED64E82AEAF4B9758AC5CB5023D8EF8F6D6F8E43864B70974BC7` al cierre de la corrida global.
La copia de ejecución declara raíz absoluta equivalente y agrega sólo `--output` y evidencia propia de Playwright. No modifica casos, baselines ni umbrales aprobados.
No contiene instalación, mutación, aceptación de baseline, envío AGY ni cambios de producto. Git sólo lo invocan los runners autorizados.
La evidencia de ejecución real, incluida la repetición autorizada, queda en el informe de pruebas E. Esta revisión estática no sustituye esos resultados ni la revisión independiente B del producto.

No se aprueba una release ni se marcan tareas completadas desde este informe.
