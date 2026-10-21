# Revisión de integración de 0.6.0

Estado: release pendiente; no PASS global. La auditoría total conserva sus hallazgos originales
en [code-review-codex-total.md](code-review-codex-total.md). Esta revisión de raíz cruza las
correcciones con sus pruebas y no convierte el inventario de archivos en certificación exhaustiva.

| Hallazgo | Evidencia de corrección | Pendiente |
|---|---|---|
| B01, auxiliares fuera de raíz | Rojo con hardlinks y junction reales; final47 aprobadas/6 omitidas, incluyendo10 cierres inmediatos WSL y6 symlinks POSIX por UNC | Global final; rama del receptor POSIX no ejecutada en Linux |
| B02, rehabilitación de ciclos | API prepara candidato, consulta fuera del lock y revalida; arranque comprueba origen/topología o conserva apagada con motivo | Global final; sin probar peers reales |
| B03, caché que certifica bytes viejos | Rojo con caché caliente y tamaño/mtime conservados; hashes frescos y contador que exige una sola lectura, con y sin alteración | Global final; releer destinos tiene costo deliberado |
| B04, réplica revive retirada posterior | Fila e historial comparten fecha causal; retirada automática reutiliza transacción | Global final; no reparación retroactiva acreditada |
| B05, launch lógico sin control físico | Realpath estricto, pertenencia lógica y física; junction real rechazada | Global final; TOCTOU posterior no resuelto |
| B06, reintento múltiple duplica éxitos | Lote con resultados y texto, sólo rechazos seguros; nuevo lote explícito | Global final; sólo mocks de envíos |
| B07, pull fallido ignora build pendiente | Se respeta marcador offline; conserva error/marcador si build falla | Global final; sin instalar un lock nuevo |
| B08, entrada compara tamaño cacheado | Métricas actuales antes de validar basis; no dispatch ante base antigua | Global final y Chrome remoto real; resize posterior aún puede competir |

Se leyó el código congelado de B02/B04 y sus pruebas: candidato privado, informes pendientes
sin sustituir objetos, revalidación ante edición concurrente, guardia de agente y topología.
La retirada usa una sola fecha para fila/evento y conserva la conexión transaccional en el camino
automático. Se contrastaron las reservas federadas existentes; no se acredita transacción distribuida.
B registra174 pruebas vecinas antes de su ajuste final y78 sobre las partes finales; no se suman
como cobertura independiente ni se atribuyen a una misma foto final.
La extensión al arranque reprodujo11 fallos y1 control positivo, después pasó136 pruebas
focales y13 del estado final. Se leyó su código congelado: lectura de peers fuera del lock,
guardia pura compartida de origen y habilitación secuencial bajo el mismo lock. No hay red
al arrancar; con federación aún no acreditada conserva disabled_at e informes, y muestra
disabled_reason/last_result. Entrega local: `.temp/coordinacion/2026-10-21/B-correcciones/arranque/informe.md`.

Se leyó el delta de F y sus oráculos B06/B08: segundo clic sólo recorre los rechazos del lote;
inciertos quedan excluidos, incluyendo error de red. El control running impide corridas simultáneas.
En Chrome la comparación usa la lectura local recién devuelta por CDP, y release-input mantiene
su camino de liberación. F midió22 UI y25 Node, con rojas previas y lint0. No son mediciones LAN.

B revisó independientemente el delta B05/B07 de raíz. SL01 raíz de volumen y SL02 tests que
dependían del checkout real se corrigieron con regresión y fixtures aislados. Resultado final:
102 aprobadas,1 omitida por symlink; junction real cubierta. Ruff0. Runner focal caso0 y runner1
por ausencia de baseline, sin --fijar. [Detalle y revisión independiente](code-review-startup-launch.md).

Antigravity se activó sólo localmente sobre el árbol sin publicar. E realizó una prueba autorizada:
respuesta exacta en consola/API/Chat, turnos4→5, cero herramientas, PID20088 estable. Los5 turnos
siguen history_only y ended=false. No acredita turnos estructurados, cierre, resume ni on_stop.

La primera global E falló por ruta temporal mal escapada y desborde93px. La repetición corrigió
el entorno:2867 aprobadas,3 omitidas y153 de memoria. El desborde pasó10 pruebas con teclado.
Estos resultados preceden a las correcciones B01–B08; falta la global final del conjunto estable.
No se fusionan resultados ni se aprueban propuestas, baselines o tareas.

Revisión adicional B de handles Windows: no identificó fuga/doble cierre concreto en el
ownership actual; directorios a cargo de ExitStack y archivos transferidos al descriptor CRT.
La sonda nativa temporal de E midió NTSTATUS0xC000000D sin SYNCHRONIZE y éxito al incluirlo;
OBJ_DONT_REPARSE rechazó junction con0xC000050B/4395. No se amplía FILE_SHARE_DELETE.
Ese análisis no acredita todos los sistemas de archivos. La entrega final de E conserva el
primer409 WSL sin atribuirle una causa no medida. Una tanda posterior identificó WinError2
en GetFileInformationByHandleEx clase9; se sustituyó esa consulta por GetFileInformationByHandle
sin degradar guardias. La fuente final pasó10 cierres inmediatos WSL con bytes correctos y6
symlinks POSIX por UNC. Los6 omitidos son symlinks nativos Windows por WinError1314.
El contador también acredita una sola relectura con caché caliente, incluso al invalidarla.
Raíz comprobó los SHA256 de ambos archivos contra la entrega: idénticos. Focal final de E:
47 aprobadas,6 omitidas, rc0,290.68s. No constituye PASS global ni ejecución del receptor en Linux.

Calidad de formato: raíz aplicó Ruff sobre302 archivos Python explícitos, excluyendo los2 de E.
56 cambiaron sólo formato: comparación AST antes/después sin diferencias en los302, e inventario
idéntico. E formateó sus2 archivos. Ruff check y Ruff format --check globales dieron rc0;
no se presenta el chequeo exploratorio de Black como aprobado. El manifiesto de formato se
conserva en `.temp/coordinacion/2026-10-21/root-paths/formato-despues.json`.

Esta revisión es la foto previa al commit y a la global final. Los resultados finales se guardan
fuera del árbol versionado y se publicarán con la release, para no cambiar la huella probada.

Dependencias frontend: raíz ejecutó `npm audit --omit=dev --json` y `npm audit --json` desde
web, ambos rc0 y0 vulnerabilidades declaradas. Inventario npm:348 dependencias totales.
Es consulta de advisories, no prueba de ausencia de defectos desconocidos ni auditoría de las
herramientas Python instaladas fuera del proyecto. No se actualizaron dependencias.
