# V3 — T5 y T8: log y persistencia

2026-10-22, sesión `pid-41040`. Pedido en adjunto `20261022-213123-5a62e3e2705a-mensaje.md`, después del commit `34e240a` informado por la coordinadora. **T5 y T8 implementados; 120 casos focales aprobados, sin sumar repeticiones.** Revisión estática del delta sin hallazgos altos/medios pendientes en este alcance. Aceptación integral: **ESCALAR (3)**, explícitamente sin ejecutar.

## Archivos exactos propios

- `lienzo/state.py`
- `lienzo/registro_niveles.py`
- `lienzo/rondas.py`
- `lienzo/restore.py`
- `tests/test_registro_retencion.py`
- `tests/test_persistencia_v3.py` (nuevo)
- `review/2026-10-22/code-review-V3.md` (este informe)

Evidencia ignorada: `.temp/resultados/2026-10-22-V3/`, con logs completos, cinco roles, propuestas y compuerta. No modifiqué `hooks_eventos.py`, `sessions.py`, archivos Prolog de AA ni otros cambios concurrentes. No hice git de escritura, reinicios ni cambios de configuración. Sigue la pausa: no Playwright, navegador, builds, Vite, suites amplias, WSL, motor Prolog real ni pedidos de turno.

## T5 — exclusión de rotación y append

`lienzo/state.py:173` define `log_lock`, exclusivo del archivo. `state.log` lo mantiene desde abrir el archivo hasta terminar y cerrar la escritura; su cola/consola queda fuera del lock. `lienzo/registro_niveles.py:151` usa el mismo lock desde leer el archivo hasta copiarlo y reemplazarlo. Así ningún append de esa instancia puede entrar en el archivo viejo entre EOF y `os.replace`. Dos depuraciones de la misma instancia también quedan serializadas. La rotación no toma el lock de sesiones ni llama al logger mientras tiene el lock del archivo.

La prueba nueva `test_rotacion_no_pierde_aviso_concurrente` usa archivos temporales y dos hilos. Detiene `os.replace` con una barrera, intenta un aviso concurrente y comprueba que no termine antes de liberar el reemplazo; al finalizar, el aviso aparece exactamente una vez, se conserva la cola reciente y desaparece lo vencido. La barrera sólo intercepta el destino del log del caso, no reemplazos de otros workers.

- **Rojo:** `T5-rojo.log`, salida 1. El append terminaba mientras replace seguía detenido: `el append no debe entrar entre EOF y replace`.
- **Verde:** archivo `tests/test_registro_retencion.py` completo: 11 aprobadas. También conserva el caso de replace rechazado, que deja el archivo original íntegro y limpia el temporal.
- **Regresión de consola:** dos casos vigentes `consola_trabada` en `tests/test_red_resiliente.py`: 2 aprobadas, 6 no seleccionados, salida 0. Verifican archivo completo, consola acotada y respuesta HTTP local aun con stdout bloqueado. Es un servidor efímero de prueba, sin navegador.

Límite: el lock protege hilos que usan `state.log` en la misma instancia. No se afirma exclusión con append arbitrario de otros procesos. Los appends esperan durante el IO de rotación; no se midió latencia con logs grandes durante la pausa. La consola no forma parte de esa espera.

## T8 — confirmar sólo lo guardado

### Rondas

`lienzo/rondas.py:59` deja de tragar `OSError` en `_guardar`. `_cambio` toma una foto profunda con el lock tomado y revierte el estado en memoria si falla la escritura, incluyendo la poda de avisos. Todos los bloques mutadores que usan el escritor compartido pasan por ese contexto. El adaptador de las API mutadoras devuelve **503** con un error de guardado; no publica el cambio ni informa una concesión/renovación/entrada en cola que no quedó guardada.

La liberación y el pase al próximo dueño se calculan y guardan en **una sola escritura**. `_siguiente` muta sin guardar ni notificar; el llamador confirma la operación completa y luego avisa. El revisor automático también persiste vencimiento, poda de cola y pase juntos, antes de mensajes o SSE. Ante fallo conserva dueño/cola anteriores y deja diagnóstico; no concede al siguiente en memoria ni lo notifica. Un dueño vencido conservado por fallo es una espera conservadora, no una concesión durable falsa.

Al hacer estricto el escritor compartido se cubrieron también creación, ACK, cierre y vencimiento de avisos: rollback ante fallo de guardado y ausencia de publicación/notificaciones falsas. Un envío externo que ya ocurrió antes de guardar su resultado no es reversible; no se inventó un reenvío automático ni una garantía de entrega exactamente una vez.

La revisión del delta corrigió una lectura del dueño mutable fuera del lock: ahora captura el hecho de liberación dentro de la sección protegida. También eliminó `_pasar_turno`, que había quedado sin llamadores después de unificar las escrituras.

### Restauración

`lienzo/restore.py:119` registra y propaga el `OSError`. `_store`, `remember` y `forget` ya no devuelven éxito cuando `_write` falla. `forget` sólo elimina el marcador de debounce tras guardar; `remember_live` sólo avanza los marcadores de tarjetas elegibles después de un guardado exitoso. Un fallo permite reintentar inmediatamente, sin esperar 30 s.

Se verificaron los callers existentes: `sessions.restore_guard` ya captura los errores de mantenimiento; no se editó ese archivo. Los handlers de acciones pueden informar el error de persistencia. Si el caller ya lanzó un proceso antes de intentar olvidar la entrada, este arreglo no revierte ese lanzamiento ni garantiza que un reintento externo no vuelva a lanzarlo; sería un contrato adicional del flujo de restauración, fuera de los cuatro archivos autorizados.

### Pruebas T8

`tests/test_persistencia_v3.py` nuevo, con temporales, `atomic_write` que falla y dobles de sesiones/avisos:

- Conceder, renovar, encolar, liberar, salir de cola y fijar política: 503, memoria y disco sin cambio, sin avisos ni SSE.
- Liberación y pase correctos: una sola escritura, respuesta y disco con el nuevo dueño y un solo aviso posterior al guardado. El doble falla si se intenta una segunda escritura.
- Pase automático con dueño vencido o recurso libre: si guardar falla, no cambia el estado ni notifica.
- `remember`, `remember_live`, `forget`: propagan el error, conservan archivo y debounce; tras recuperar la escritura, `remember_live` reintenta inmediatamente.
- Creación, ACK, cierre y vencimiento de avisos: no quedan cambios en memoria o publicaciones falsas ante el fallo del escritor compartido.

**Rojo funcional:** 13 fallas antes de editar las fuentes, `T8-rojo-aislado.log`, salida 1. Mostraban respuestas 200/202 en vez de 503, doble escritura al pasar el turno, mutaciones/notificaciones pese al fallo y excepciones de restore que no se propagaban. La primera corrida `T8-rojo.log` tenía además cinco fallas de preparación por no crear la carpeta temporal del estado; se conservó y se corrigió únicamente ese fixture antes de repetir el rojo funcional.

**Verde:** 17 casos nuevos; los 13 iniciales más cuatro controles del escritor compartido de avisos. Regresiones existentes: 11 aprobadas en rondas y 79 en restauración, con FakePopen/tmux simulados. No se usaron lanzamientos reales ni WSL.

## Evidencia y cinco roles

Recorrido `pruebas-agenticas` secuencial en esta sesión, sin subagentes. Explorer revisó contratos y rutas de escritura; Analyser contrastó T5/T8 con el adjunto; Designer preparó los rojos, positivos y escenarios de fallos; Executor guardó códigos y logs; Detective contrastó fallas, regresiones y límites. Se reutilizaron las instrucciones de los cinco roles ya leídas en esta sesión. Artefactos formales consolidados al cierre, declarados como propuestas y sin inventar navegación u horarios de etapas no medidos.

| Verificación | Resultado | Evidencia |
|---|---|---|
| `pytest tests/test_persistencia_v3.py tests/test_registro_retencion.py -q -p no:cacheprovider` con `py -3.14 -m` | **28 aprobadas**, código 0 | `final-dos-focales.log` |
| `pytest tests/test_rondas.py -q -p no:cacheprovider` con `py -3.14 -m` | **11 aprobadas**, código 0 | `rondas-regresion.log` |
| `pytest tests/test_restore.py -q -p no:cacheprovider` con `py -3.14 -m` | **79 aprobadas**, código 0 | `restore-regresion.log` |
| `pytest tests/test_red_resiliente.py -k consola_trabada -q -p no:cacheprovider` con `py -3.14 -m` | **2 aprobadas**, 6 no seleccionados, código 0 | `consola-regresion.log` |
| Ruff check, sólo seis archivos propios de código/pruebas | código 0 | comprobación local |
| Ruff format check, mismos archivos | código 0 | comprobación local |
| `git diff --check` | código 0 | comprobación local |

120 aprobadas distintas entre esas cuatro corridas focales, sin contar repeticiones. No equivale a suite global.

Validadores del plugin: `delta`, `certificar` y `trazabilidad`, salidas **1** por propuestas sin aprobación humana. Esquemas válidos; trazabilidad de cuatro casos, positivos y negativos para T5/T8: **«Sin hallazgos»**. Dos mutaciones sólo propuestas, ninguna ejecutada/aprobada. El runner registró `--no-ejecutado` para la aceptación integral, por separado de pytest focal. Compuerta: **ESCALAR (3)**, no PASS. No se fijaron baselines ni se aceptaron propuestas.

`code-review` aplicado al delta propio: orden de locks, consola fuera de la exclusión, rollback bajo lock, propagación de errores, una escritura por pase y efectos posteriores al commit. No hubo auditoría global de dependencias ni cambios de otros frentes.

No cubierto: suite amplia, navegador, despliegue, uso real, fallos físicos de disco, exclusión entre procesos ni rendimiento con logs grandes. La pausa de recursos sigue vigente.

ESTADO: listo para commit de los siete archivos propios enumerados; aceptación integral pendiente.
