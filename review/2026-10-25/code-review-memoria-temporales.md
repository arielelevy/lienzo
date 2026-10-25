# Revisión focal: memoria de carpetas temporales

Fecha: 2026-10-25. Revisión secuencial por Codex `01a173c8-4826-7d83-bce0-5dd684c7647a`, no independiente.

## Alcance

memory_policy.py, entradas de conocimiento, captura y pruebas. No se cambian agentes, visibilidad del tablero, launch_roots, permisos, hooks instalados ni proyectos históricos. No se marca completada la casilla de PENDIENTES.md.

## Hallazgos y decisiones

- La política anterior sólo miraba gettempdir y no normalizaba mayúsculas con normcase ni contemplaba launch_roots. Además, el alta por carpeta podía entrar directamente por conocimiento_api y omitir captura.temporal.
- La nueva política cubre TEMP/TMP/gettempdir y usa pertenencia de directorios, no startswith de texto. La excepción se valida contra el destino físico de launch_roots. Una resolución inválida se registra y se excluye; no concede permiso.
- Se evalúa antes de resolver Git/worktrees y antes de cachés de proyecto. Registro de sesión y captura también verifican la política; adaptadores con tarjeta temporal actual no agregan incidentes ni cambian su nodo histórico.
- No hay caché propia de permisos. Se corrigieron dos bordes encontrados al revisar: no cachear un proyecto None si cambia la configuración entre chequeos; liberar la marca de vista registrada si el segundo chequeo deniega la sesión. Se añadieron regresiones para ambos.
- El worker realiza el I/O físico/config. El llamador de vista sigue encolando y no oculta ni cambia el estado de la tarjeta. No se alteran la réplica ni el registro explícito de proyectos; se preservan datos históricos y excepciones autorizadas en origen.
- Las fixtures de captura que usan tmp_path ahora autorizan explícitamente su raíz de prueba. Los escenarios de exclusión usan tres raíces distintas y configuración controlada; no se parchea la política para aprobarlos.

## Evidencia

Primer conjunto ampliado: 132 pasadas y una falla de autoría del test nuevo (faltaba herramienta en incidente_operativo). Se corrigió ese argumento requerido y pasaron las 16 focales de política.

Primera integración del runner: 255 pruebas pasan en API/captura/conocimiento/réplica/servidor. Las dos regresiones de cambios de config se ejecutan en la corrida final, conservada en `pruebas-agenticas/resultados/memoria-temporales/`. Ruff, formato focal y diff-check verificados. Sin baseline ni mutaciones aprobadas: no hay PASS certificado de compuerta.

Corrida final `2026-10-25T18-27-09.772Z-21424`: 257 pruebas pasan en 33,05 s. Caso código 0; runner código 1 por referencia ausente; compuerta código 2. No se fijan baselines ni se cambian resultados anteriores.

Evaluación viva de sólo lectura en esta PC: cwd bajo TEMP, TMP y gettempdir se excluye; D:/Apps/lienzo se conserva; scratch-workspaces de Roaming queda fuera del alcance de esas raíces. No se crearon proyectos sintéticos en producción para probar.

El inventario completo de los cuatro scratch y lienzo-k-proj está en `docs/specs/memoria-temporales/design.md`, con ID y carpeta. Se informó a la coordinadora que están fuera del TEMP actual; no se eliminan ni se amplía la regla sólo por nombre.

## Límites

Las junctions se ejercitan mediante resolución física simulada, sin cambiar privilegios del SO. La política es local a cada servidor; la réplica no reinterpreta TEMP de otra PC. Los proyectos fuera de las tres raíces actuales, aunque su nombre diga scratch o su ruta incluya tmp, requieren otra decisión de Ariel. No hay limpieza histórica ni una clasificación general de todo lanzamiento headless fuera de TEMP.

Avisar antes de reiniciar para activar.
