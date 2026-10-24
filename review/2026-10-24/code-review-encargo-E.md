# Revisión de cambios del encargo E

Fecha: 2026-10-24. Alcance: cambios de `lienzo/rules.py`, `lienzo/state.py`,
`tests/test_encargo_E_informes.py` y `web/tests-ui/backlog-informes.spec.ts`.
Revisión estática focal según code-review; no auditoría general de dependencias.

## Hallazgos corregidos

- `lienzo/rules.py:1132`: varios recordatorios a una coordinadora podían sobrescribir
  `sin_aviso`. Se conserva cualquier silencio vigente y se limita a un destino por pasada.
- `lienzo/rules.py:1156`: un rechazo explícito del transporte dejaba `sin_aviso` activo.
  La prueba `test_transporte_falla_no_reintenta_y_conserva_informe` falló con AssertionError
  antes de corregirlo. Ahora sólo se limpia el silencio que corresponde al recordatorio rechazado.
- `tests/test_encargo_E_informes.py`: import directo de fixture generaba I001/F811.
  Reutilización mediante `pytest_plugins`; ruff queda sin hallazgos.

## Invariantes revisadas

- Reserva durable bajo RLock antes del efecto externo; error de disco impide envío.
- La marca por informe evita duplicados entre hilos y tras recarga desde disco.
- Sólo estado entregado, sin marca previa, con fecha válida y destino en termino,
  sin stopped_by; umbral de 1200 segundos incluido. No depende de enabled: un informe
  sigue requiriendo integración aunque su regla haya agotado disparos.
- El recordatorio no modifica estado del informe ni ejecuta acuses implícitos.
- Transporte remoto reenvía from y sin_aviso a la PC dueña; transporte local reserva
  sin_aviso antes de enviar. El test del cierre posterior prueba que no vuelve on_stop al frente.
- No se agregan shell, credenciales, HTML dinámico ni nuevos endpoints.
- Las excepciones de transporte quedan en el log; el resultado recibido se conserva en la regla.

## Verificación y límites

Ruff check y format --check: código 0 sobre los tres archivos Python propios.
47 pruebas focales pasaron antes de la última corrección; luego pasaron las 14 nuevas
(`encargo-E-focal-final.log`, 4.23 s, código 0), incluida la regresión del silencio rechazado.
Interfaz: 1 passed, con los tres estados visibles por separado y dos acuses explícitos.
Runner vigente entrega-contratos: código 0, coincidencia con baseline.
Compuerta vigente: ESCALAR, código real 1; referencias humanas faltantes y estado de código
sin acreditar. La salida menciona 5/5 mutantes históricos: no son una medición de esta entrega.

No se corrieron mutaciones nuevas sobre el árbol compartido sin commit ni se reinició el
servidor real. El contrato es como máximo un intento de recordatorio por informe:
si el proceso cae entre reserva y transporte, o el transporte falla, queda constancia para
diagnóstico y no hay reintento automático. El recordatorio solicita continuidad; no prueba
por sí mismo que un modelo real integra o verifica. No se aprueban tareas ni baselines.

No quedan hallazgos críticos o altos identificados en el alcance revisado.
Suite completa ejecutada una vez: incompleta, proceso detenido, código -1.
Log final alcanza 97% más siete casos; no hay resumen de pytest. La espera larga
coincidió con una demora anómala de clock; no se confirma bloqueo de producto.
La coordinadora tiene pendiente una corrida completa terminada. Detalle en el informe E.
