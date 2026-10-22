# Code review U — 2026-10-22

Alcance: delta del encargo U en `lienzo/registro_niveles.py`, `lienzo/mirror.py`,
`lienzo/sessions.py`, `tests/test_encargo_u.py`, `pruebas-agenticas/resguardos_U.py`
y `pruebas-agenticas/resguardos-U.json`. Revisión estática local, secuencial por Codex U.
Se aplicó el skill code-review y su catálogo de antipatrones/checklist. No es revisión independiente.

## Resultado de la revisión estática

- Sin hallazgos críticos o altos abiertos en el delta.
- SQL parametrizado (`lienzo/registro_niveles.py:122`): conteo y borrado usan la misma selección y parámetros dentro de la transacción.
- Conserva rowid máximo, lotes, retención de 30 días, sin VACUUM ni borrados de transcripciones.
- El cursor se normaliza a UTC con milisegundos. Fecha inválida o sin zona impide borrar y devuelve error.
- Se corrigió durante la revisión el import global del investigador: su import recíproco del nivel 2
  exige import local en `_depurar_capturas` para no depender del orden de arranque.
- La emergencia (`lienzo/mirror.py:387`) se calcula fuera del lock. Una conexión nueva sin diagnóstico conserva su estado previo;
  una caída diagnosticada ofrece canal aunque `last_seen` sea nulo. Reutiliza `pm.health` si existe.
- La limpieza batch (`lienzo/sessions.py:1878`) sólo alcanza la marca genérica exacta del mismo proceso Claude Windows.
  No limpia escritorio, orquestador, batch real, otro PID/backend ni comando ilegible.
  Revalida proceso y marca al tomar el lock antes de persistir y emitir el evento.
- Wrapper de pruebas sin shell, argv fijo, `stdin=subprocess.DEVNULL`, temporales U-18848
  fuera del repo y propagación del código de salida.
- Sin dependencias nuevas ni cambios de permisos, hooks, server.py, configuración o archivos de Q.

## Límites pendientes de decisión

1. La propuesta S explícitamente mantiene depuración normal sin cursor y usa un resumen de ventana 72 h.
   Este delta protege lo posterior a un cursor existente. No certifica que huecos anteriores al cursor
   estén resumidos. Ya se informó a la coordinadora; mejorar el investigador queda fuera de U.
2. Tras un arranque sin salud previa no se conoce el canal remoto. Se ofrece el canal local disponible
   mediante el contrato existente de `emergencia.canal`. No se inventa una salud remota ni se declara
   online un nodo de la tailnet. La conexión real con ar-it33940 caída no se verificó.
3. La compuerta requiere aprobaciones/baseline humanos y mutaciones. No se fija ninguno en este frente.

## Verificación

Ruff check y format --check focales limpios en las cinco rutas Python.
Rojo guardado en `.temp/resultados/2026-10-22-U/rojo.log`: retención sin resguardo,
cursor inválido que permitía borrar, emergencia nula y batch antiguo sin reparar.
Se corrigieron antes del verde dos errores de preparación del test (esquema reducido y comparación
de sqlite3.Row con tuple); no se cuentan como defectos del producto.

- Focal directo: **80 passed in 6.06s**, código 0.
- Runner `resguardos-backend-U`: **80 passed in 5.25s**, caso código 0.
- Runner global: código 1 por ausencia de baseline, sin fallas en el caso.
- Compuerta: código **2**, `No hay baseline.json: fijarlo a mano con ejecutar.mjs --fijar`.
- No se fijó baseline ni se ejecutaron mutaciones. No hay PASS de compuerta.
- Config válida sin errores; aviso de ausencia de mutaciones.
- Delta/requisitos/propuestas de casos válidos, sin aceptación humana. Trazabilidad agrupada
  señala falta de casos positivos/negativos separados y nodos sin casos; los 10 tests nuevos
  incluyen esos caminos pero no se presentan como una certificación formal de cobertura.
- Uso real: observado /peers antes del arreglo con ar-it33940 caída, last_seen y emergencia nulos.
  Sin reinicio, despliegue ni prueba de conectividad real de emergencia.

Las focales y el runner se ejecutaron con autorización explícita de la coordinadora para saltear
la espera del turno global ocupado por R0/OpenSyync. El intento inicial dentro del sandbox falló por
permisos de temporales; los resultados medidos se obtuvieron con temporales propios autorizados.
