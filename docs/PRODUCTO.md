# Lienzo: producto y decisiones

Decisiones de Ariel del 2026-10-16, consolidadas en esta conversación.
Este documento define la dirección del producto. La existencia de una decisión no acredita su implementación.

## Propósito

Lienzo es el espacio de Ariel para coordinar agentes, integrar sistemas y mejorar cómo se trabaja.
Además de mostrar sesiones y permitir intervenir, debe aprender de los flujos reales y desarrollar
su propia capacidad de mejorarlos: sus herramientas, memoria, coordinación, arquitectura e integraciones.

## Proceso flexible, calidad no negociable

FTD (Fast-Track Development) reemplaza a SDD por decisión de Ariel del 2026-10-26.
Se mantiene la documentación proporcional: una feature o un trabajo con decisiones,
dependencias o varios frentes necesita una ficha con objetivo, alcance, criterios de
aceptación, tareas, evidencia y próximo paso. Un cambio puntual, claro y de bajo impacto
se ejecuta y verifica directamente, dejando evidencia en el registro existente.
Cada trabajo conserva la arquitectura, los contratos y las tareas que correspondan
a su alcance y riesgo, dentro de las reglas duraderas del proyecto (su constitución).
El detalle operativo vive en [el flujo FTD](../skills/lienzo/references/ftd.md).
Un bug pequeño, una funcionalidad nueva, un refactor, una investigación y una integración no siguen
necesariamente el mismo recorrido. Tampoco se prescribe una secuencia universal de olas.
Si el trabajo crece, se amplía la misma ficha FTD; SDD deja de ser una alternativa.

La flexibilidad no elimina la verificación. En código propio se conservan las pruebas agénticas,
la revisión y la auditoría exigidas por las instrucciones del usuario y del proyecto.
El review local de Claude y el skill de auditoría son controles complementarios que el aprendizaje
debe poder registrar. Su ejecución, sus hallazgos y las correcciones verificadas son datos distintos.
Una revisión ejecutada no equivale a ausencia de defectos. Un cierre de turno no completa una tarea.

## Capacidad de mejorarse

El objeto de análisis es el flujo completo: llamadas y resultados de herramientas; contexto,
memoria y recuperación; arquitectura, construcción, planes y tareas; iteraciones entre olas;
coordinación y esperas; pruebas, review, auditoría y retrabajo; documentación y capacidades ausentes.
También interesa lo que todavía no existe y podría hacerse mejor.

La meta es encontrar causas y alternativas comprobables. Una lectura repetida, una respuesta larga
o un número alto de llamadas no demuestran por sí solos desperdicio.

## Jev y el agente de fondo

Jev se conserva como evaluador barato. Codex u otra CLI en segundo plano debe potenciarlo.
La división propuesta es: Jev detecta señales y prioriza; el agente investiga código, trazas y
alternativas; las pruebas aportan resultados; Lienzo conserva la evidencia y presenta propuestas.
La valoración posterior de Jev tampoco sustituye un oráculo independiente de calidad.

Usar una CLI no implica inferencia local ni consumo gratuito. El adaptador debe declarar sus
límites, autenticación, consumo, tiempo de ejecución y comportamiento ante pausa y fallos.
La autonomía para experimentar sin intervención humana todavía requiere una política concreta;
la pregunta planteada en esta conversación no recibió una autorización específica.

## Creencias y checklist

La memoria debe conservar observaciones, hipótesis, experimentos, evidencia, creencias y refutaciones.
El checklist es una vista operativa corta y contextual derivada de lo suficientemente respaldado.
No es un segundo almacén independiente ni una lista universal que se inyecta en todas las sesiones.

Cada creencia necesita fuentes, alcance, contexto, confianza, excepciones y vigencia.
Debe poder revisarse, refutarse o reemplazarse sin borrar su historia.
Una propuesta no se convierte automáticamente en regla. La propuesta actual de implementación
requiere veredicto humano con evidencia para promoverla; eso no demuestra por sí solo su eficacia.

## Patrones de desarrollo

Las comparaciones deben conservar el tipo de trabajo y las condiciones que cambian el resultado:
proyecto, tecnología, área, agente, modelo, fase y versiones cuando estén disponibles.
No se extrapola una mejora de un tipo de trabajo a todos los demás.

Lo desconocido debe seguir identificado como desconocido. Agrupar trabajos por etiquetas explícitas
es un primer mecanismo descriptivo, no una detección completa de patrones ni una medición de calidad.
La inferencia de patrones desde flujos reales requiere validación propia y evidencia trazable.

## Tools, plugins y formas de trabajo

Una tool sirve para una tarea concreta. Un plugin extiende Lienzo: puede integrar sistemas,
incorporar una forma de trabajo, aportar herramientas o combinar esas capacidades.
No es obligatorio que un plugin contenga tools. La forma de empaquetarlo no determina su función.

El catálogo debe permitir descubrir ambas clases sin confundirlas: qué aporta cada entrada,
para qué sirve, qué necesita, su origen, disponibilidad y límites. Un plugin puede ser local,
privado y estar fuera de GitHub. Las relaciones con tools se declaran sólo cuando existen.
El contrato técnico y su evolución están en [Plugins](PLUGINS.md).

## Anatomy

Anatomy ya existe como herramienta de Ariel para documentación visual de Lienzo.
La integración está en `skills/lienzo-infografias/`; sus figuras SVG claras y oscuras están en
`docs/img/infografias/`. Debe aparecer en el catálogo como capacidad de documentación.
Su aporte a la claridad documental no sustituye pruebas, review o auditoría del código.

Verificado en Git: `ef14cc8` incorporó la integración el 2026-10-16; `815c9e7`, `d406b00`
y `1283928` agregaron figuras de memoria/delegación, scheduler y Jev.
También se consultaron capturas de actividad de ese día: registran construcción y verificación.
Que no figure en el catálogo actual no significa que falte la integración.

## Stepwise

Stepwise es una integración existente entre sistemas y formas de trabajo, mediante un plugin local.
Su backend está en `lienzo/extensiones/stepwise.py` y su interfaz en
`web/src/extensiones/stepwise.tsx`; esas carpetas están excluidas de Git.
No se debe publicar ni copiar esa integración al repositorio para hacerla visible en el catálogo.

El puente consulta ejecuciones, estados y logs, permite guidance humana y cancelación por su API.
Los gates se revisan en Stepwise. La documentación del puente registra pruebas con ejecutor MOCK;
no se presenta ese dato como prueba actual con agentes reales.

## Investigación de la comunidad

Lienzo debe poder investigar periódicamente herramientas, integraciones y formas de trabajo de la
comunidad, relacionadas con necesidades observadas. La propuesta debe explicar qué problema
resuelve, evidencia, alternativas, costo, permisos, mantenimiento y riesgos relevantes.
Ariel decide si se incorpora. Descubrir o proponer no autoriza instalar, activar ni modificar proyectos.
La frecuencia y el presupuesto de esa investigación todavía no están definidos.

## Estado al consolidar

| Área | Situación verificada |
|---|---|
| Tablero, coordinación, memoria y análisis local | Código existente; operación en README y arquitectura |
| Jev | Cliente y piloto existentes; sujeto a cotización, presupuesto y condiciones vigentes |
| Anatomy | Integración existente y ficha incorporada al código del catálogo; pendiente activación del backend |
| Stepwise | Plugin local existente; fuera de GitHub |
| Creencias y checklist contextual | Código y contratos locales; checklist como vista sin reglas duplicadas; pendiente aceptación y activación |
| Patrones por tipo de desarrollo | Borrador basado en etiquetas explícitas; no investigación completa de flujos |
| Codex/CLI como investigador de fondo | Implementado localmente con vista en el panel; inactivo hasta reiniciar el backend. Corre con suscripción mientras quede >= 20 % del semanal; pendiente primera ejecución real y aceptación |
| Investigación periódica de comunidad | Dirección acordada; política e implementación pendientes |
| Catálogo ampliado y contrato uniforme | Fichas y contrato de manifiesto v1 implementados localmente; UI publicada; backend sin reiniciar; Better Claude sin instalar |

La evidencia reproducible está en los runners `pruebas-agenticas/creencias.json` y
`pruebas-agenticas/catalogo-comunidad.json`, con logs, intentos y registros de roles.
Se conserva la falla inicial del doble de base de datos y las corridas posteriores de su corrección.
El checklist se deriva al consultar: no persiste una regla que pueda sobrevivir a una refutación.
Los casos ejecutados no sustituyen la aceptación: no hay baseline nuevo aprobado ni PASS certificado.
No se activó el backend principal ni se instalaron los plugins de Better Claude.

## Dónde continuar

- [Arquitectura](../DISENO.es.md): componentes y límites del sistema.
- [Aprendizaje](APRENDIZAJE.md): contratos de evidencia, ejecución y evaluación.
- [Plugins](PLUGINS.md): mecanismo y contrato uniforme v1.
- [Pendientes](../PENDIENTES.md): única lista de trabajo; casillas sin cerrar por esta consolidación.
