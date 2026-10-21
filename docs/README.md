# Documentación de Lienzo

Referencia consolidada el 2026-10-16. Cada tema tiene una fuente principal; las decisiones acordadas,
la implementación y la evidencia histórica se identifican por separado.

| Documento | Función |
|---|---|
| [Producto](PRODUCTO.md) | Visión, proceso flexible, calidad, mejora propia, catálogo y decisiones de Ariel |
| [Arquitectura local](../DISENO.es.md) | Documento interno, excluido de Git: componentes y límites |
| [Aprendizaje](APRENDIZAJE.md) | Jev, investigador CLI de fondo, creencias, evidencia, patrones y consumo |
| [Plugins](PLUGINS.md) | Tools, integraciones y formas de trabajo; cargador y contrato uniforme v1 |
| [Consultas](CONSULTAS.md) | Investigadores, vueltas, síntesis, réplica y persistencia |
| [WSL](WSL.md) | Distros, identidad, teclado, pantalla, transcripciones y lanzamiento |
| [Memoria](propuesta-memoria/v5.md) | Esquema, transiciones y contratos detallados del conocimiento |
| [Réplica de memoria](propuesta-memoria/anexo-c-replica.md) | Propiedad, conflictos y recuperación entre PCs |
| [Apps de escritorio](desktop-apps.md) | Monitoreo y envío; interfaces medidas, conexión y límites |
| [Uso e instalación](../README.md) | Entrada operativa para usar Lienzo |
| [Versión 0.6.0](releases/0.6.0.md) | Cambios, verificación y límites de esta versión |
| [Revisiones](../review/README.md) | Auditorías fechadas, evidencia y límites de cobertura |
| [Pendientes](../PENDIENTES.md) | Única lista de trabajo |
| [Mejoras](../PENDIENTES.md#historial-mejoras) | Registro histórico de hechos y decisiones |
| [Pruebas](../pruebas-agenticas/README.md) | Configuración y operación de las verificaciones |

## Qué se unificó

- Las seis specs de requisitos/diseño/tareas de consultas y réplica se reúnen en Consultas.
- Las tres specs de WSL se reúnen en WSL.
- Requisitos, diseño, tareas y benchmark del evaluador se reúnen en Aprendizaje.
- El diseño inicial y los checkpoints de DISENO.es.md se sustituyen por arquitectura vigente.
- Las nuevas decisiones de esta conversación se reúnen en Producto; el contrato ampliado está en Plugins.

Se retiraron 13 documentos intermedios. No se cerraron sus tareas por inferencia.
Los originales de las specs siguen en Git. El diseño interno no estaba versionado y tiene copia local
temporal fuera del árbol documental. Las referencias de navegación y reglas de las configs se actualizaron.
Los comentarios históricos de código que nombran specs antiguas siguen siendo referencias a su historia,
no rutas funcionales ni documentación adicional vigente.

## Qué se conserva

El esquema de memoria y su anexo mantienen contratos específicos que no deben perderse en un resumen.
Los registros de revisión, aceptación, autorización y piloto se conservan como evidencia fechada.
La carpeta specs/evaluador-harness conserva además budget-policy.json, usado por el código;
su ubicación no se cambia como efecto colateral de ordenar Markdown.
Los skills y sus referencias siguen siendo instrucciones de uso, con enlaces al producto cuando corresponde.

Documentar una propuesta no la despliega, no concede presupuesto y no aprueba un baseline.
