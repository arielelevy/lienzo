# Frente huérfano

Pedido: PENDIENTES.md, ronda 0.6.17; encargo de coordinadora del 2026-10-25.

Cuando desaparece quien encargó o recibía los informes de un frente y no hay coordinadora viva de su repo, la auditoría elige un frente superviviente y le transfiere el rol. La elección usa vínculos `send` y reglas `on_stop`, no el título ni prosa de respuestas. Una PC explícitamente caída invalida sus tarjetas espejadas. Un peer sin snapshot inicial impide tomar el control: ausencia todavía no probada.

La elección es determinista por session_id entre los frentes relacionados, sin depender del orden de llegada. Sólo la PC dueña de la elegida ejecuta el cambio. Antes de promover, el servidor relee sus sesiones, espejo y relaciones y repite la elección bajo un lock específico de traspaso. Una coordinadora viva bloquea la promoción. No se eligen procesos externos, tarjetas detenidas, muertas o identidades provisionales.

Se marca coordinadora y se titula `<repo> | coordinadora - continuidad`. Se redirigen sólo reglas `on_stop` cuyos orígenes pertenecen al repo de la elegida. Su propia regla de informe no se convierte en autoenvío: se deshabilita. Se conserva el estado previo de reglas apagadas o estacionadas. No se heredan envíos pendientes ni reglas de salida de la coordinadora desaparecida como si fueran una sucesora restaurada.

El recableado entre PCs reutiliza `/rules/retarget` con una operación acotada al repo. Si un peer no responde, el traspaso queda pendiente y se reintenta en la siguiente auditoría. La PC caída se omite hasta que vuelva; las reglas locales de una PC que vuelve se reconciliarán por el traspaso pendiente. No se promete consenso durante una partición de red: la elección usa la vista disponible y no desplaza una coordinadora viva conocida.

Pruebas: muerte, cierre/ausencia, PC caída con tarjeta stale, dos candidatos, coordinadora viva local/remota, origen de otro repo, exclusión de headless/detenidos, idempotencia, preservación de reglas y no autoenvío, revalidación y fallos de recableado. Explorer por APIs reales; casos destructivos sólo con fixtures aisladas. No se mata ninguna sesión productiva para probar.

Tareas (se mantienen pendientes):
- [ ] Selector determinista y operación acotada de reglas.
- [ ] Acción protegida del servidor e integración con auditoría.
- [ ] Cinco roles, revisión focal, commit y push; avisar antes de reinicio.
