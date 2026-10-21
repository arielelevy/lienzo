# Revisión de integración de 0.6.0

Estado: release pendiente; no PASS global. La auditoría total conserva sus hallazgos originales
en [code-review-codex-total.md](code-review-codex-total.md). Esta revisión de raíz cruza las
correcciones con sus pruebas y no convierte el inventario de archivos en certificación exhaustiva.

| Hallazgo | Evidencia de corrección | Pendiente |
|---|---|---|
| B01, auxiliares fuera de raíz | Rojo con hardlinks y junction reales; focal47 aprobadas/6 omitidas, incluyendo10 cierres inmediatos WSL y6 symlinks POSIX por UNC | Global ded319d6b detectó WinError2 en primer bloque WSL; compatibilidad inestable; receptor POSIX no ejecutado en Linux |
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

La global de239b0f5 cerró6/7 casos aprobados:2939 backend/10 omitidas,153 memoria,16 controles
E2E y138 UI aprobadas/1 fallida. La tarjeta crecía23,5px con «enviando…». Se preservó el FAIL,
no se ejecutaron mutaciones y se corrigió el agrupamiento de repo/rama. La focal posterior
pasó47 pruebas originales sin debilitar sus oráculos. [Revisión del ajuste](code-review-cabecera-envio.md).
Debe repetirse la global del commit que incluya ese ajuste; este resultado no se fusiona con ella.

La global ded319d6b corrigió la regresión visual:139 UI aprobadas. Cerró6/7 casos, con backend
2938 aprobadas/1 fallida/10 omitidas: el primer bloque del primer archivo de la tanda WSL recibió
500/FileNotFoundError WinError2. El log no preserva la API nativa causante; no se atribuye una
causa retrospectiva. La huella se mantuvo85d504549833223e y la configuración no cambió.
Se detuvo la mutación por guardia. E continúa diagnóstico de primera operación en carpetas nuevas,
sin calentamiento, relajación de guardias, nuevos permisos ni reintentos hasta obtener verde.
La publicación sigue pendiente de corregir el fallo funcional y validar otra foto estable.

Diagnóstico posterior: 20 carpetas WSL nuevas dieron bloque 200/cierre 200 y bytes correctos;
no reprodujeron el fallo original. El delta de tests conserva la excepción original y la
respuesta 500, agrega traceback antes de atender_peer y persiste los diez resultados sólo
después del cierre. No modifica xfer.py, guardias, apertura, retries ni oráculos. El caso
inyectado acredita observabilidad, no una corrección del fallo de transferencia.
La primera focal diagnóstica dio 46 aprobadas/2 fallidas/6 omitidas y atravesó suspensión:
Kernel-Power 42 a 01:41:31 por batería y reanudación 09:39:20. Se conserva rc1; no se atribuyen
los dos fallos a una causa interna sin medir. Se autorizó una focal nueva por esa interferencia,
sin omitir ni reintentar operaciones. Un verde posterior no resolverá por sí solo la intermitencia.
La focal nueva terminó rc1: 47 aprobadas, 1 fallida y 6 omitidas en 250,22 s. WSL pasó;
el espejo siguió copiando al vencer su espera, sin errores registrados. Se abrió diagnóstico
acotado de ese caso con stacks y progreso, manteniendo el plazo y el oráculo originales.
No se inicia otra global ni se publica antes de contrastar esa evidencia.
La reproducción única de espejo pasó en 45,36 s. Ambas esperas comenzaron en `listando`;
la segunda duró 40,99 s y terminó con 302 archivos. No reproduce el fallo ni demuestra
su causa. La lectura de `arrancar` detectó una carrera independiente: devolvía control
antes de publicar un estado activo. Una barrera antes de `_fases` produjo dos rojos,
con `pausado` y `confirmar_espejo` aún visibles. El cambio publica `listando` antes de
iniciar el hilo, después de comprobar que no hay uno vivo y de limpiar pausa. Los tres
controles pasaron: ambos estados anteriores y preservación de hilo vivo/pausa/error.
No cambia plazos, prioridad, filesystem, transferencia ni manejo de errores de `_correr`.
Se revisó el delta y sus regresiones; falta focal completa y validación global de esta foto.
La carrera corregida no explica ni cierra retrospectivamente el WinError 2 de WSL.
La focal de esta foto terminó rc1: 50 aprobadas, 1 fallida, 6 omitidas en 299,76 s.
Espejo y las tres regresiones de estado pasaron. WSL produjo bloque 200 y cierre 409 en
`inocuo-0.bin`: faltaba el bloque 0 y la lectura posterior conservó 37 bytes cero,
distintos de los esperados. Los otros nueve cierres dieron 200 y bytes correctos.
No hubo OSError capturada: es evidencia de pérdida de contenido, no del WinError 2 anterior.
Se preservaron respuestas y bytes completos en `.temp/resultados/E-wsl-frio/` y se abrió
observación acotada de las decisiones de existencia, preparación y truncado. No se repite
la global ni se publica mientras este fallo funcional permanezca abierto.

Decisión posterior de Ariel, 2026-10-21: «libera release y sigue con este bug después».
Autoriza publicar con el fallo WSL conocido, revocando la espera de publicación anterior.
Se conserva el FAIL y se documenta que no hay global ni mutación nueva del commit publicado.
No se modifica la evidencia, no se acepta baseline y no se cierra el pendiente.

Dependencias frontend: raíz ejecutó `npm audit --omit=dev --json` y `npm audit --json` desde
web, ambos rc0 y0 vulnerabilidades declaradas. Inventario npm:348 dependencias totales.
Es consulta de advisories, no prueba de ausencia de defectos desconocidos ni auditoría de las
herramientas Python instaladas fuera del proyecto. No se actualizaron dependencias.
