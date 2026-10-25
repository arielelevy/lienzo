# Memoria y carpetas temporales

Fuente: PENDIENTES.md «Headless y memoria del proyecto»; encargo 2026-10-25 de Ariel por la coordinadora.

La política común excluye de memoria automática las carpetas bajo cualquiera de TEMP, TMP y tempfile.gettempdir(). Se compara pertenencia de directorio, no prefijos de texto; se normalizan mayúsculas/barras Windows y se resuelven alias físicos, incluyendo rutas cortas y junctions. Se conserva también la pertenencia lógica a TEMP para que un enlace hacia fuera no borre esa condición.

Una ruta física bajo un launch_root explícito puede generar memoria, aunque sea temporal. Un enlace dentro de una raíz permitida que apunte a otra carpeta temporal no hereda el permiso. Configuración ausente, vacía o inválida no concede excepciones. La configuración se reevalúa en cada operación; no hay caché propia de permisos.

La exclusión se aplica antes de resolver la raíz Git/worktree o consultar cachés de proyecto. Cubre el alta/resolución por carpeta, registro de sesión y captura, además de los adaptadores que conocen una tarjeta temporal actual. Los proyectos históricos se conservan y siguen enumerándose; no se ejecuta limpieza ni se alteran capturas anteriores.

El llamador de captura sólo encola; los chequeos físicos y de config ocurren en el worker o en las entradas de conocimiento, fuera del lock de tarjetas. Una vista excluida no queda marcada como ya registrada: una autorización posterior en launch_roots puede funcionar. Revocar una excepción bloquea las operaciones siguientes incluso si ya hay proyecto y caché.

El tablero no se filtra: una sesión temporal puede seguir viva y visible. No se discrimina por marca headless ni CLI: vale por cwd para Claude, Codex, Kiro, coda, Pi y otros agentes.

No se filtra la réplica con el TEMP de la PC receptora ni se borran proyectos que ya llegaron: la política de origen conserva las excepciones autorizadas en su propia configuración. El registro explícito de proyectos y la lectura por ID de proyectos históricos permanecen disponibles.

## Inventario vivo, 2026-10-25 15:23:15 -03

GET /conocimiento/proyectos devolvió cuatro scratch y un proyecto con ruta tmp para revisión. Todos sin remote. Ninguno se borró.

| ID | Carpeta registrada en PC 75727ff74069 |
|---|---|
| scratch-2026-10-17-1ac60b | c:/users/ariellevy/appdata/roaming/claude/scratch-workspaces/a584bfd3-8b55-4721-875f-ff207aaea606/ddbc5652-ef62-4afd-8440-3e3162dcb2dd/scratch-2026-10-17-1ac60b |
| scratch-2026-10-17-33a4b3 | c:/users/ariellevy/appdata/roaming/claude/scratch-workspaces/a584bfd3-8b55-4721-875f-ff207aaea606/ddbc5652-ef62-4afd-8440-3e3162dcb2dd/scratch-2026-10-17-33a4b3 |
| scratch-2026-10-17-38ca50 | c:/users/ariellevy/appdata/roaming/claude/scratch-workspaces/a584bfd3-8b55-4721-875f-ff207aaea606/ddbc5652-ef62-4afd-8440-3e3162dcb2dd/scratch-2026-10-17-38ca50 |
| scratch-2026-10-17-75512c | c:/users/ariellevy/appdata/roaming/claude/scratch-workspaces/a584bfd3-8b55-4721-875f-ff207aaea606/ddbc5652-ef62-4afd-8440-3e3162dcb2dd/scratch-2026-10-17-75512c |
| lienzo-k-proj | d:/var/tmp/lienzo-k-proj |

TEMP, TMP y gettempdir medidos en esta PC apuntan a `C:/Users/ARIELL~1/AppData/Local/Temp` (alias corto). Las cuatro rutas Roaming y D:/var/tmp están fuera de esas raíces. Por eso este encargo no las excluye por nombre: requieren una decisión distinta de Ariel si quiere ampliar la regla o limpiar el inventario. Se informó a la coordinadora antes de implementar.

Pruebas: tres fuentes TEMP separadas, límites de carpeta y raíces permitidas, rutas Windows, resolución de junction simulada, cachés y cambios de config, API de carpeta, captura y adaptadores sobre sesión histórica, tarjeta viva preservada. No se lanzan CLIs pagos para probar ni se escribe memoria sintética productiva.

- [ ] Política común y entradas de memoria.
- [ ] Cinco roles y revisión focal; no aprobar baseline ni mutaciones.
- [ ] Commit, push y aviso previo antes de reiniciar.
