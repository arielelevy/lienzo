# FTD: cambios con documentación proporcional

Decisión de Ariel, 2026-10-26: FTD (Fast-Track Development) reemplaza a SDD como
proceso de desarrollo de Lienzo. Se mantiene el criterio de exigir documentación
según alcance, riesgo, coordinación y necesidad de retomar el trabajo.

## Cuándo usar una ficha

- Una pregunta, lectura o investigación sin cambios no abre una feature por sí sola.
- Un cambio puntual, claro y de bajo impacto se ejecuta y verifica directamente;
  basta registrar el resultado y su evidencia en el informe o pendiente existente.
- Una feature, un cambio con varias decisiones o dependencias, o trabajo que se
  reparte entre sesiones necesita una ficha FTD breve antes de implementar.
- Si aumenta la complejidad, ampliar esa misma ficha con arquitectura, contratos,
  riesgos y tareas pertinentes. No cambiar de metodología ni abrir una cadena SDD.

No decidir solo por cantidad de archivos. La ficha tiene que ayudar a entender,
repartir, verificar o retomar el cambio; no se crean documentos por ceremonia.

## Reglas del proyecto

La constitución es el conjunto de reglas duraderas vigentes: instrucciones de Ariel,
AGENTS.md cuando exista, decisiones de producto y contratos técnicos aplicables.
FTD trabaja dentro de esas reglas; no exige crear otro archivo de constitución
ni duplicar instrucciones. Ante una contradicción, resolverla antes del cambio afectado.

## Una ficha por feature

Usar una ficha existente si ya contiene el encargo. Si falta, crear
`.temp/coordinacion/<AAAA-MM-DD>/ftd-<nombre>.md` para el trabajo en curso. Las decisiones
duraderas se incorporan después a la documentación del proyecto. PENDIENTES.md sigue
siendo la única lista de trabajo; la ficha enlaza el pendiente y no crea otro backlog.

```markdown
# <Feature>
Estado: pendiente
Pendiente: <referencia en PENDIENTES.md>
## Objetivo
Qué cambia y por qué.
## Alcance
Qué incluye y qué queda afuera.
## Criterios de aceptación
Comportamientos observables y cómo comprobarlos.
## Trabajo y decisiones
Tareas pendientes, dependencias y responsables si hay varios frentes.
Agregar arquitectura o contratos solo cuando el cambio los necesite.
## Evidencia
Resultados observados, condiciones, archivos y commits de referencia.
Registrar también pruebas fallidas, no ejecutadas y límites de la verificación.
## Próximo paso
Una acción concreta para continuar.
```

Actualizar la ficha en hitos útiles, no después de cada herramienta. Una sucesora
debe distinguir lo propuesto, lo implementado en una rama y lo integrado.
En varias PCs, compartir el encargo por el canal de Lienzo; no asumir que un archivo
local de la otra PC está disponible ni hacer un push solo para transportar notas.

## Verificación y cierre

Mantener revisión, auditoría y pruebas exigidas para el cambio. FTD no agrega una
batería universal ni elimina controles existentes: elegirlos por impacto y evidencia.
Una afirmación del agente, un turno terminado, un test aislado o un merge no cierran
una tarea automáticamente. Las tareas se crean pendientes y solo se marcan
completadas por pedido explícito de Ariel. Registrar evidencia no equivale a cerrarlas.

Referencia del enfoque investigado:
https://github.com/ericrisco/rsc-harness/blob/main/skills/ftd/SKILL.md
Esta es la adaptación de Lienzo; no instala RSC ni copia sus cierres automáticos.
