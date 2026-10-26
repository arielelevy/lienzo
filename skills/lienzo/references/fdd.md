# FDD: Feature-Driven Development para agentes

Decisión de Ariel, 2026-10-26: Lienzo sigue FDD, la skill `fdd` (repo `arielelevy/fdd`, en piloto).
FDD reemplaza a FTD, que había reemplazado a SDD el mismo día: conserva su ficha proporcional y su
exigencia de evidencia, y le suma de Feature-Driven Development (De Luca y Coad, 1997) el mapa del
dominio, las features con nombre de resultado, los hitos y los archivos con dueño. Este archivo es la
adaptación de Lienzo y alcanza solo, aunque la skill `fdd` no esté instalada en la PC.

## Cuándo usar una ficha

- Una pregunta, lectura o investigación sin cambios no abre una feature por sí sola.
- Un cambio puntual, claro y de bajo impacto se ejecuta y verifica directamente;
  basta registrar el resultado y su evidencia en el informe o pendiente existente.
- Una feature, un cambio con varias decisiones o dependencias, o trabajo que se
  reparte entre sesiones necesita una ficha breve antes de implementar.
- Si aumenta la complejidad, ampliar esa misma ficha con arquitectura, contratos,
  riesgos y tareas pertinentes. No cambiar de metodología.

No decidir solo por cantidad de archivos. La ficha tiene que ayudar a entender,
repartir, verificar o retomar el cambio; no se crean documentos por ceremonia.

## Mapa del dominio

`docs/dominio.md`: una línea por entidad con la ruta donde vive, los flujos principales y las reglas
que no se rompen. Leerlo antes de abrir una ficha. Si una feature cambia una entidad o un flujo, se
corrige en el mismo cambio.

## Constitución y arquitectura: valen para todo cambio

La constitución es el conjunto de reglas duraderas vigentes: instrucciones de Ariel,
AGENTS.md cuando exista, decisiones de producto y contratos técnicos aplicables. La arquitectura es
cómo está hecho Lienzo: DISENO.es.md, `docs/dominio.md`, los módulos y los componentes que ya
existen (estado en `~/.lienzo`, escritura atómica de `atomico.py`, `subproc.py` para procesos
externos, la federación firmada para hablar con otra PC, la API de reglas para las reglas).

**Nada se sale de ellas, por chico que sea el cambio** (pedido de Ariel, 2026-10-26). Un cambio
puntual se salta la ficha, nunca estas reglas. Se sale, aunque sean tres líneas, el cambio que mete
otro almacenamiento, otro método de autenticación o de firma, una dependencia para algo que ya está
resuelto (el server es de biblioteca estándar), o que no reusa lo que ya existe y escribe uno
paralelo. Reusar antes de agregar. Si lo existente no alcanza, se le propone a Ariel y se espera la
decisión antes de implementar.

FDD trabaja dentro de esas reglas; no exige crear otro archivo de constitución
ni duplicar instrucciones. Ante una contradicción, resolverla antes del cambio afectado.

## Una ficha por feature

El nombre es el resultado para el usuario: «acción + resultado + objeto» («avisar cuando una regla
de informe queda apagada», no «arreglar rules.py»). Si no entra en una frase así, son varias fichas.

Usar una ficha existente si ya contiene el encargo. Si falta, crear
`.temp/coordinacion/<AAAA-MM-DD>/fdd-<nombre>.md` para el trabajo en curso. Las decisiones
duraderas se incorporan después a la documentación del proyecto. PENDIENTES.md sigue
siendo la única lista de trabajo; la ficha enlaza el pendiente y no crea otro backlog.

```markdown
# <acción + resultado + objeto>
Hito: diseñado | implementado | verificado | integrado
Pendiente: <referencia en PENDIENTES.md>
## Objetivo
Qué cambia para el usuario y por qué.
## Alcance
Qué incluye y qué queda afuera.
## Criterios de aceptación
Comportamientos observables y cómo comprobarlos.
## Dominio
Entidades y flujos de docs/dominio.md que toca, y si cambia alguno.
## Archivos y dueños
`<ruta>`: <frente dueño>. Nadie más lo edita mientras la ficha esté abierta.
## Trabajo y decisiones
Tareas, dependencias y decisiones con su motivo.
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

## Hitos y cierre

| Hito | Se marca cuando |
|---|---|
| diseñado | objetivo, alcance, criterios, dominio y dueños escritos |
| implementado | el cambio está hecho en el árbol o en una rama |
| verificado | cada criterio tiene evidencia observada, no afirmada |
| integrado | lo marca Ariel, nunca el agente |

Mantener revisión, auditoría y pruebas exigidas para el cambio. FDD no agrega una
batería universal ni elimina controles existentes: elegirlos por impacto y evidencia.
Una afirmación del agente, un turno terminado, un test aislado o un merge no cierran
una tarea automáticamente. Las tareas se crean pendientes y solo se marcan
completadas por pedido explícito de Ariel. Registrar evidencia no equivale a cerrarlas.

## Varios frentes

Los archivos de cada frente se escriben en la ficha antes de repartir; si dos fichas abiertas nombran
el mismo archivo, se resuelve antes. Lo que un frente encuentra fuera de sus archivos lo anota en la
ficha, no lo edita. Commitea sólo la coordinadora.

Fuentes: Feature-Driven Development (De Luca y Coad, 1997; Palmer y Felsing, 2002) y FTD de RSC
(https://github.com/ericrisco/rsc-harness/blob/main/skills/ftd/SKILL.md). No instala RSC ni copia
sus cierres automáticos.
