# Revisión de Lienzo — 2026-09-20

## Alcance y resultado

Revisión de los cambios de integración Pi, transporte, manejo HTTP y simplificación de frontend/backend. No constituye una auditoría exhaustiva de todo el sistema ni una certificación del transporte Win32 con terminales reales.

**Estado de la primera validación:** build y pruebas automatizadas correctos. La aceptación de Pi en producción queda pendiente de una prueba con terminales dedicadas. Al consultar `127.0.0.1:7321` durante la validación, no había servidor escuchando (`ECONNREFUSED`). No se arrancó el servidor ni se reiniciaron agentes de trabajo.

## Actualización: advertencias React y detección de logs Pi

- ESLint ejecutado con `--max-warnings=0`: **0 errores y 0 advertencias**, sin desactivar reglas.
- Eliminadas las 17 advertencias: selecciones invalidadas antes de pintar, refs sincronizados tras commit, temporizadores de columnas separados del estado derivado, geometría del panel sin mutar refs durante render, callback de pantalla con dependencias completas, reloj de tarjetas con timer y notificaciones sin ref mutable redundante.
- Python: **189 tests pasan**; UI: **48 tests pasan** en preview aislado, más **1 humo real aprobado** contra 7321 (sólo lectura); build TypeScript/Vite, Ruff, Black y tests Node correctos.
- Pi: confirmados los archivos de ambas TUIs activas mediante `PI_SESSION_ID`/`PI_SESSION_FILE` de sus shells, no por fecha. Se agregó detección automática en el barrido y validación contra la cabecera del JSONL. Sólo se devuelven esas dos variables; no se exponen otras variables de entorno. Los hijos con identidades contradictorias se rechazan.
- La identificación por entorno necesita un shell hijo vivo, pero Pi puede estar trabajando sólo con `read`/`write`. Se agregó un respaldo automático para una única Pi por proyecto: JSONL con actividad más reciente posterior al nacimiento del proceso, cabecera/cwd/ID validados y rechazo de empates. Es heurístico y puede confundir otros escritores del mismo proyecto; no se usa con varias TUIs Pi en el mismo cwd. Un log ya vinculado se conserva, y la extensión sigue siendo la fuente exacta para ramas y finalización. Los estados inferidos no disparan reenvíos ni reintentos automáticos de Pi.
- El panel ya no confunde una Pi sin log vinculado con una sesión nueva: muestra diagnóstico y cómo activar la extensión. Prueba UI de regresión incluida.
- La extensión se cargó también con **el loader real del paquete Pi instalado**, sin errores y con todos los handlers registrados. Esto no sustituye probar recepción de teclas en una TUI real.
- Verificación final contra 7321: **ambas Pi (chess y Lienzo) vinculadas**, cada digest devuelve turnos y textos del asistente; ambas tarjetas tienen pedido y respuesta. El usuario también confirmó la visualización. No se forzó reinicio ni se interrumpieron las dos Pi.

## Validación inicial ejecutada

| Comprobación | Resultado |
|---|---|
| Python 3.14.7, `pytest -q` | 181 pruebas pasan |
| `compileall` de backend e instalador | Correcto |
| Ruff | Sin errores |
| Black | 19 archivos conformes |
| TypeScript + Vite (`npm --prefix web run build`) | Correcto |
| Extensión Pi, `node --test extensions/pi-lienzo.test.mjs` | 1 prueba pasa; API simulada |
| Parser de frases, `node web/src/nl.test.ts` | Correcto |
| Geometría, `node web/src/arrows-geometry.test.ts` | Correcto |
| Playwright en preview aislado, sin humo real | 47 pruebas pasan |
| Humo real | Bloqueado: servidor 7321 no disponible |
| ESLint frontend | 0 errores; 17 advertencias React pendientes |
| `npm audit --omit=dev` | 0 vulnerabilidades reportadas en dependencias de producción |
| `pip check` | Sin incompatibilidades declaradas |
| `git diff --check` | Sin errores de whitespace |

La primera corrida de Playwright incluyó por error el humo real contra Vite preview: pasó 43 pruebas y falló ese humo porque preview no provee API. La segunda corrida excluyó explícitamente el humo real, agregó las cuatro pruebas Pi y pasó 47/47. El intento separado contra 7321 confirmó que el servidor no estaba disponible. No se oculta ese límite como un test aprobado.

## Corregido en esta ronda

- `lienzo/procinfo.py`, `lienzo/procs.py`: detección específica de Pi nativo o Node ejecutando su CLI; exclusión de RPC/print/JSON y comandos administrativos. No clasificar cualquier Node como agente.
- `lienzo/transcripts.py`: lectura de JSONL de Pi por rama activa, herramientas/resultados, errores, uso, mensajes y digest; propagación opcional de `leaf_id`.
- `extensions/pi-lienzo.ts`: eventos locales atómicos, PID y ruta exactos; fin de turno únicamente con `agent_settled` e idle. Diálogos informativos, sin aprobación automática.
- `install.py`: registro idempotente de la extensión, backups y respeto de `PI_CODING_AGENT_DIR`; `--pi-only` y selección mutuamente excluyente.
- `lienzo/sessions.py`: bloquear envíos mientras Pi tiene diálogo abierto; no inferir finalización desde una respuesta intermedia; validar código de salida, JSON y booleano `ok` de `send.py` antes de anunciar éxito.
- `lienzo/server.py`: preparación HTTP compartida; rechazar Content-Length inválido/duplicado, Transfer-Encoding, cuerpos incompletos y excesivos; errores de JSON como errores de cliente. Canje del token de alta bajo un único lock.
- `lienzo/sessions.py`: adjuntos con sufijo aleatorio y creación exclusiva.
- `web/src/api.ts`, `web/src/hooks/useLienzoData.ts`: errores explícitos ante respuestas no JSON y protección frente a snapshots HTTP atrasados respecto de SSE.
- `web/src/agents.ts`, componentes: catálogo de agentes, capacidades compartidas, comandos de reanudación y menor duplicación. Evitar actualizar el ancla del panel durante render.
- Formato Python normalizado con Black; sin cambios semánticos en `auth.py`, `hook.py` y `state.py` por ese formateo.

## Copiar y pegar: qué está probado

`web/tests-ui/pi.spec.ts` ejercita Ctrl+C, Ctrl+V, vista previa y envío de trabajo en las cuatro direcciones: Pi → Claude, Pi → Codex, Claude → Pi y Codex → Pi. Las peticiones de envío se interceptan: ninguna prueba escribe en terminales de trabajo.

`tests/test_integration_guards.py` cubre las cuatro direcciones en el transporte del backend con subprocess simulado, errores de envío, bloqueo por diálogo, ciclo de eventos Pi y framing HTTP inválido. `tests/test_pi.py` cubre detección, parser y registro. Esto **no prueba que la TUI destino haya recibido las teclas reales**.

## Hallazgos y pendientes

### Alta — Falta aceptación real de Pi

- **Ubicación:** `lienzo/send.py:inject`, `extensions/pi-lienzo.ts`.
- **Riesgo:** tests de API simulada y HTTP interceptado no detectan incompatibilidades de entrada Win32/ConPTY o carga real de la extensión.
- **Acción:** levantar Lienzo de forma coordinada; abrir terminales dedicadas de Pi/Claude/Codex; comprobar recepción en las cuatro direcciones, texto largo/adjuntos y reenvío al finalizar. No probar contra sesiones productivas activas.
- Extensión registrada en `~/.pi/agent/settings.json` con backup. Las TUIs abiertas requieren `/reload` o una nueva sesión. No se forzó recarga.

### Resuelto en la actualización — Advertencias de ciclo de render React

- **Ubicaciones:** `web/src/components/Arrows.tsx`, `Board.tsx`, `Card.tsx`, `Forward.tsx`, `Panel.tsx`, `web/src/hooks/useNotifications.ts`.
- ESLint señala referencias modificadas durante render, `Date.now()` durante render, actualizaciones de estado en efectos y dependencias de hooks.
- **Resolución:** separados estado derivado/efectos y revisados callbacks, dependencias, geometría y temporizadores; lint estricto y 48 pruebas UI pasan. No se silenciaron las advertencias.

### Media — Deuda de contraste conocida

- **Ubicación:** prueba `web/tests-ui/salud.spec.ts` y estilos de `span.f` / `button.copy`.
- El test informa excepciones conocidas de 3.91:1 y 2.55:1. Que pase la suite no significa conformidad WCAG AA completa.
- **Acción:** corregir esos colores y eliminar las excepciones de la prueba.

### Cobertura pendiente

- Prueba concurrente específica del canje de alta de un solo uso.
- Typecheck específico de la extensión contra los tipos Pi. La carga con el loader real ya se verificó.
- Auditoría de vulnerabilidades Python y dependencias npm de desarrollo: `pip check` no sustituye `pip-audit`.

## Runtime y limpieza

- Python por defecto: **3.14.7**. `python`, `py` y `pip` resueltos y PATH de usuario restaurado a partir del inventario conservando las herramientas ajenas a Python.
- Desinstalados Store Python 3.13, Python clásico 3.13.7 y Launcher antiguo, y runtimes uv 3.13.0/3.13.5/3.12.12. La instalación clásica requirió reparar su desinstalador faltante y luego desinstalar correctamente.
- Eliminados los remanentes identificados `C:\Python313`, `%APPDATA%\Python\Python313`, y el instalador descargado para la desinstalación.
- `py list` muestra únicamente Python 3.14.7. Paquetes del inventario Store migrados; no faltan nombres del inventario comparado. Conservado `octostar-chat` editable y migradas herramientas PDF.
- **Node se mantuvo en 24.19.0.** No se reemplazó por Node 26.
- Se conservan inventarios y logs en `%LOCALAPPDATA%\lienzo\runtime-migration\20260920-025420`; no se borraron sesiones, credenciales ni entornos virtuales de otros proyectos. No se afirma haber eliminado toda referencia histórica a 3.13 en el disco.

## Puesta en marcha pendiente

1. Iniciar `lienzo-server.cmd` cuando corresponda operar las reglas guardadas.
2. Abrir nuevas sesiones Pi o cargar la extensión con `/reload` en un momento seguro.
3. Completar la recepción de teclas en terminales dedicadas. El humo final contra el backend ya pasó.
