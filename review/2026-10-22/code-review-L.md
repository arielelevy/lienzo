# Code review — encargo L (2026-10-22)

Alcance: `lienzo/conocimiento.py` (sólo el delta L: etapas del encargo), `tests/test_etapas_encargo.py` (nuevo),
`web/src/components/Etapas.tsx` (nuevo), `web/src/etapas.css` (nuevo), `web/tests-ui/etapas.spec.ts` y
`etapas-real.spec.ts` (nuevos). Skill `code-review`, nivel medium, sobre el delta previo a estos arreglos.

| # | Hallazgo | Resultado |
|---|---|---|
| 1 | La evidencia citada en `origen.evidencia` sólo se comprobaba como nodo `evidencia`: sin proyecto ni fecha, la misma aprobaba revisión y verificación | Corregido: tiene que ser del proyecto y recibida desde que el encargo entró en la etapa que deja; acepta id o lista (veredictos). Tests `test_evidencia_citada_es_del_proyecto_y_de_esta_etapa` (rojo→verde) y `test_aprobado_no_vuelve_atras_ni_salta_etapas` ajustado. |
| 2 | En un veredicto el respaldo se mira después de mover `estado_fecha`: medía desde la etapa nueva y el resultado dependía del orden de los ítems | Corregido: si el nodo ya está en el estado nuevo, el comienzo de la etapa que deja sale del `anterior` del último cambio de estado. Test `test_veredicto_vincula_y_avanza_en_el_mismo_lote` (rojo→verde). |
| 3 | `vincular` es idempotente: un `apoya` viejo a la misma evidencia conserva su fecha y no respalda la etapa nueva | Resuelto por diseño: cada etapa trae evidencia nueva. La UI ya no vincula: cita la evidencia en el cambio de estado y sólo ofrece la recibida en la etapa actual. |
| 4 | `coordinar.entregar` usa `revision=1` por defecto; tras una devolución hay que entregar una revisión mayor | Sin cambio en `skills/lienzo/coordinar.py` (lo está tocando otro frente): propuesta en el informe para la coordinadora. El comportamiento de 409 con la misma revisión y otro contenido ya existía. |
| 5 | La entrega tardía (`sin_entrega` → `entregado`) no miraba `devuelto_revision` | Corregido: también exige un informe posterior a la devolución. Test `test_entrega_tardia_del_informe_viejo_no_vuelve_a_revision` (rojo→verde). |
| 6 | Carrera entre la devolución y una entrega concurrente | Sin cambio: la conexión es DEFERRED y la lectura de la última revisión corre después del UPDATE de estado, dentro de la transacción de escritura; `entregar` toma BEGIN IMMEDIATE y espera. Que una revisión llegada durante la revisión quede cubierta por la devolución es intencional (documentado en el código). |
| 7 | Tras releer, un «Ver evidencia» abierto quedaba en «Leyendo…» | Corregido: se recuerdan los abiertos y `load()` los vuelve a leer. Spec `aprobar … relee la evidencia abierta`. |
| 8 | El vínculo `apoya` se creaba en otra petición antes del cambio de estado y no se deshacía si éste fallaba | Corregido: una sola escritura, `POST /nodos/<id>/estado` con `origen.evidencia` (transaccional). |
| 9 | El formulario arrastraba evidencia y motivo de la etapa anterior | Corregido: `Actions` lleva `key` por estado y fecha de estado. |
| 10 | `etapa()` del front mandaba los estados desconocidos a «pendiente» | Corregido: los devuelve tal cual, como `conocimiento.etapa_encargo`. |

Verificación después de los arreglos: `tests/test_etapas_encargo.py` 12 pasan; focales de conocimiento, veredictos,
captura, réplica, memoria, aprendizaje y rondas: 215 pasan. Ruff check y format limpios en mis rutas. `tsc` y `eslint`
limpios. UI: ver `.temp/resultados/2026-10-22-L/`.
