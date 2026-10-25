# Revisión focal: dos regresiones de integración

Fecha: 2026-10-25. Revisión secuencial por Codex 01a173c8-4826-7d83-bce0-5dd684c7647a; no independiente. Alcance autorizado: cambios en server.py, sessions.py, conocimiento.py y sus pruebas. Base 6a3beef, con los cambios de Prolog de la coordinadora conservados.

## Hallazgos corregidos

1. `server.py:1137`, `sessions.py:1539`: accion_coordinator llamaba al setter y luego hacía una escritura adicional por ses.touch cuando la tarjeta no figuraba en changed. En las pruebas de paridad, el setter inyectado devolvía una lista vacía y la escritura adicional accedía a un almacenamiento no preparado: HTTP 500 en tablero y peer. Se concentra la persistencia en sessions.set_coordinator. La prueba original queda intacta. Un test adicional usa la implementación real y lee el JSON de disco para verificar preferencia manual y propuesta cuando el rol ya coincide, tanto true como false.

2. `conocimiento.py:603`: resolver_proyecto rechazaba TEMP antes de buscar por remote. Eso impedía la consulta de contexto de un proyecto existente por una tarjeta con repo_key conocido. La resolución ahora omite candidatas por carpeta excluida y mantiene la búsqueda por remote explícito. No busca raíz Git desde TEMP. Los tres guardas de escritura en proyecto_de_carpeta, registrar_sesion y capturar permanecen. Un test atraviesa la API de contexto y luego prueba que no se agregan carpetas, nodos ni capturas.

## Revisión de riesgos

Se revisaron llamadores de resolver_proyecto y los dos listeners del handler compartido. No se agregan rutas de escritura, permisos, secretos, comandos shell ni dependencias. El setter conserva lock, guardia de decisión manual ante inferencia automática, unicidad por repo y desmarcado remoto. Se evita la doble persistencia: cada tarjeta cambiada se toca una vez; la seleccionada se toca aparte sólo si su rol no cambió. No hay captura de excepciones ni silenciamiento de errores nuevos.

Los cambios se limitan a dos ramas pequeñas y eliminan I/O del handler. No se hizo una auditoría global de dependencias ni una medición general de complejidad. No se cambian hooks, permisos, baselines, pruebas originales ni los fallos ajenos de xfer/deadline/rendimiento.

## Evidencia y límites

Las dos pruebas originales fallaron antes del arreglo y pasaron sin modificar sus aserciones después. Las 49 pruebas focales adicionales pasaron. El primer intento dentro del sandbox quedó bloqueado por WinError 5 en TEMP; la ejecución autorizada fuera del sandbox pasó.

Ruff check, formato de los cinco archivos Python y git diff --check: código 0. El aviso LF/CRLF no es una falla de diff-check.

Corrida `2026-10-25T19-34-27.922Z-27308`: los dos casos originales pasan; la batería ampliada da 370 pasadas y una falla en test_motor_real_igual_a_python_en_grafos_aleatorios, línea 280, `assert (1 and 0)`. Ese mismo caso falla igual en un worktree limpio de 6a3beef, con LIENZO_PROLOG_ENGINE=D:/Apps/motor-logico/main.pl; no depende de estas correcciones. Sin la ruta explícita se saltaba porque el motor se busca relativo al checkout, por lo que ese primer salto no se contó como evidencia. La falla queda informada a la coordinadora que lleva Prolog, sin modificar su código ni debilitar el test.

Runner código 1. Compuerta código 1 por baseline ausente. Sin baseline ni mutaciones aprobadas, no se declara PASS certificado. Las pruebas HTTP usan servidores locales y fixtures aisladas; no acreditan una prueba visual ni ejecución en la otra PC.
