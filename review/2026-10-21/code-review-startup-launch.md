# B05/B07: arranque y carpetas permitidas

Alcance: `lienzo/startup_update.py`, guardia de `lienzo/launch.py` y regresiones relacionadas.
Revisión focal propia con code-audit; el informe Codex total mantiene su evidencia original.

B07 confirmado con pull fallido y marcador previo: antes retornaba 0 sin compilar, incluso si
la compilación debía fallar. Ahora el fallback local respeta el marcador; compila o devuelve
el error conservándolo. Sin marcador se mantiene arranque offline sin build. No se instala nada.

B05 confirmado por regresión con resolución física redirigida. Ahora se exige pertenencia
lógica y física; realpath estricto falla cerrado ante inexistencia, permisos o resolución inválida.
Una raíz configurada explícitamente puede ser una junction; sus descendientes deben quedar
dentro de su destino físico. La guardia no promete atomicidad contra cambios posteriores.

Los fixtures previos de launch/tmux simulaban carpetas existentes: se extendió esa simulación
a la resolución física. Las nuevas regresiones usan carpetas reales, incluyendo una junction
de Windows creada sólo entre directorios temporales y retirada con rmdir no recursivo.
La prueba independiente de symlink se omite cuando el sistema requiere privilegios; no se
modifican permisos para ejecutarla.

Rojo funcional: 3 fallos, 2 aprobadas, 1 omitida. El primer intento en sandbox falló por WinError5,
sin valor funcional. Un primer fixture sin raíces normcase no reproducía correctamente el
contrato y se corrigió antes de acreditar el rojo. Verde ampliado: 101 aprobadas, 1 omitida,
2.69s. Ruff sobre los cinco archivos modificados dio0 antes del último añadido de pruebas;
se repite tras el cierre. Evidencia de roles/config en `.temp/coordinacion/2026-10-21/root-paths/`.

Se revisaron controles positivos, propagación de códigos, conservación del marcador, orden
de la guardia antes de lanzar y manejo de error físico. No hay nuevos procesos de producto,
dependencias, red ni instrucciones ejecutadas desde datos. La omisión de symlink y la carrera
entre validación y lanzamiento quedan explícitas. Falta integración con la suite global final.
No se acepta baseline ni se marcan tareas completadas.

Runner agéntico focal ejecutado: caso `startup-launch-review` código0, 101 aprobadas y1
omitida en4.16s. Runner código1 porque no existe baseline en su carpeta propia; no se fijó.
Logs completos en `.temp/coordinacion/2026-10-21/root-paths/resultados/`. Validador:0 errores,
1 aviso por ausencia de mutaciones. Ruff final:0. El rojo previo verifica que los oráculos
detectan los dos defectos, pero no se convierte en un puntaje de mutación ni aprobación global.

## Revisión independiente por B — 2026-10-21

Se conserva arriba la revisión propia de raíz. B revisó en modo solo lectura `_physical_path`, `_cwd_allowed`, sus consumidores `launch/open_vscode`, el fallback de startup, los scripts de arranque y las regresiones/fixtures de launch y tmux. No ejecutó suites, comandos git, navegadores, lanzamientos, junctions ni updates. No se usaron agentes adicionales ni `/review`.

**Resultado del delta:** no identifico un nuevo bloqueante de release en las correcciones específicas B05/B07. `realpath(strict=True)` más `commonpath` rechaza redirecciones físicas estables fuera de la raíz y falla cerrado ante errores de resolución. La comprobación ocurre antes de construir/lanzar el proceso. Las junctions configuradas como raíz se aceptan por su destino físico explícito; no es un escape. Startup ya no retorna éxito inmediatamente ante pull rc1: consulta el marcador y devuelve el código de build, conservándolo si falla. Sin marcador mantiene el comportamiento offline anterior. Un timeout/excepción de subprocess sigue devolviendo 1, como antes.

### SL01 — [P2, preexistente] Una raíz de volumen no permite sus descendientes

`lienzo/launch.py:144` usa `norm.startswith(root + os.sep)`. `_allowed_roots()` normaliza una raíz Windows de volumen a `D:\`, por lo que construye el prefijo `D:\\`. Un cwd normal `D:\proyecto` no coincide y se rechaza antes de evaluar contención física. En Unix ocurre lo mismo con raíz `/` y prefijo `//`. La raíz exacta sí pasa, lo que vuelve inconsistente el contrato raíz/hijo. Este defecto ya estaba en la guardia lógica y no fue introducido por el chequeo físico.

Corrección propuesta: normalizar el separador de frontera sin duplicarlo, preservando comparación exacta y contención física; cubrir raíz de volumen/raíz Unix, hijo y hermana. No se ejecutó esa reproducción en esta revisión. No es un bypass ni un bloqueo del arreglo de escape para raíces ordinarias como `D:/Apps`; sí es un fallo funcional para esa configuración admitida por la API.

### SL02 — [P2, pruebas] Dos pruebas de startup leen el marcador del checkout real

`tests/test_startup_update.py:test_current_checkout_does_not_build` y `test_failed_pull_keeps_local_version_and_reports` sustituyen subprocess pero no `updater.ROOT`. Consultan por tanto el `web/.startup-build-pending` real. Si ese marcador existe, intentan un build adicional y agotan los resultados del mock (`results.pop(0)`), con un `IndexError` ajeno al contrato que querían verificar. El nuevo caso offline de `tests/test_review_startup_paths.py` sí aísla ROOT correctamente.

Corrección propuesta: aislar ROOT y crear `web/` temporal en todos los tests de startup, incluida la combinación sin marcador. La señal es una dependencia estática comprobable en los fixtures; no se creó un marcador real ni se ejecutó el escenario para reproducirla. No se presenta el verde de raíz como falso: significa que pasó bajo el estado de checkout observado en esa corrida.

### Evidencia y cobertura

Se leyó completo el log `.temp/coordinacion/2026-10-21/root-paths/resultados/salidas/startup-launch-review.log`: **101 passed, 1 skipped in 4.16s**. `actual.json` registra caso `startup-launch-review`, `codigo: 0`. Los 101/1 de la ejecución focal anterior y runner rc1 por falta de baseline están registrados por raíz en este informe/roles; no se confunden con una compuerta aprobada. B no repitió esas ejecuciones. El log resumido no demuestra individualmente cuál fue el skip; la atribución a symlink y el paso de junction real provienen de la entrega de raíz. El código de la prueba sí distingue symlink condicionado a privilegios y junction real con limpieza no recursiva.

Los fixtures de `tests/test_launch.py` y `tests/test_tmux_distros.py` sustituyen tanto existencia como resolución física de sus carpetas ficticias. Esa coherencia mantiene sus oráculos de argv/routing; **esas pruebas no ejercen el realpath real**. La nueva regresión usa directorios reales, prueba rechazo físico simulado, raíz/hijo/hermana, symlink condicionado, junction Windows y error de resolución. Falta probar con raíz configurada como enlace, resolución que cambia entre check/spawn, montajes particulares de WSL y todos los sistemas nativos. No se promete atomicidad TOCTOU; el lanzamiento conserva el path lógico después del check y puede demorar en actualizar el harness.

En startup no se validó instalación de dependencias si cambia el lock, dist efectivo tras build, corte de energía ni build fallando por excepción. La ruta `npm run build` no incorpora instalación del nuevo lock; ese riesgo preexistente está fuera del arreglo puntual del retorno temprano. `test_real_git_pull_updates_checkout` contiene git real sobre repositorios temporales locales: B lo leyó, no lo ejecutó. Los scripts `.cmd` y `.sh` respetan la salida no cero antes de iniciar el server.

Se aplicaron Explorer/Analyser/Designer/Executor/Detective secuencialmente como revisión: reconstrucción de contratos por lectura, contraste con requisitos B05/B07, evaluación de oráculos, consumo de evidencia existente sin ejecutar suites y clasificación de defectos/límites. No hay aceptación de propuestas, baseline, mutaciones o PASS global. Producto de raíz sin cambios de B.

ESTADO: revisión independiente entregada; correcciones focales B05/B07 coherentes, sin nuevo bloqueante de seguridad identificado en el delta. SL01 funcional preexistente y SL02 de aislamiento de pruebas quedan señalados; cobertura live y gate global pendientes de raíz.

### Corrección posterior de SL01/SL02 por raíz

Se reprodujo SL01 con una raíz de volumen real: 1 fallo antes del ajuste. El prefijo ahora
evita duplicar el separador final de la raíz; no cambia la validación física estricta.
SL02: los unit tests de startup usan un checkout temporal por defecto; la prueba de git
real sigue sustituyéndolo por sus repositorios temporales propios. No dependen del marcador real.
Después del ajuste: 102 aprobadas, 1 symlink omitido, 3.95s. Ruff final rc0 y Black aplicó
formato exclusivamente a launch.py. El reporte independiente anterior conserva su fecha y evidencia;
esta nota no le atribuye a B ejecución posterior ni aprobación de los cambios nuevos.
