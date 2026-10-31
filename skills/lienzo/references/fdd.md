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

Cubre el sistema entero, no sólo el tablero: el server y sus hilos, hooks, reglas, memoria y
creencias, federación, lanzamiento y el cliente `coordinar.py`, además de `web/src/`. Un mapa que
sólo indexa la interfaz deja afuera justo lo que tocan las features de backend.

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

Las decisiones de diseño cerradas no se reabren, y el doc manda antes que el código: si el código va a
contradecir un doc, primero se corrige el doc y se avisa.

## Olas, maqueta y estado (lo que funcionó en `cart`, 2026-10-24)

- **Olas**: una feature grande se construye en fases cortas, cada una con un criterio de aceptación
  observable y sus pruebas escritas antes que el código; se cierra con la suite en verde, revisión y una
  nota de estado antes de abrir la siguiente. Las dependencias entre olas van en una tabla.
- **Maqueta primero** si hay pantallas: HTML estático en `maqueta/`, independiente del código, aprobado
  por Ariel antes de construir.
- **`docs/estado.md`** es lo primero que se lee al retomar un proyecto con varias olas; lo mantiene la
  coordinadora.
- Entre frentes: contratos fijados antes de repartir, dependencias fingidas en memoria para no quedar
  quieto, archivos compartidos de la coordinadora (se piden con el diff), recursos aislados por letra,
  informe con forma fija y `ESTADO:`, y revisión cruzada de dinero, seguridad y datos personales.

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
## Efectos compartidos
Lo que el cambio mueve fuera de sus archivos, con quién lo actualiza y cuándo: contratos o formatos
(la API JSON, `contexto-sesion.json`, el esquema de la memoria), pruebas medidas que se invalidan
(rendimiento, la suite completa), pines en pruebas de otros, archivos que el server o las sesiones
cargan en vivo (`coordinar.py`, `hook.py`), y si hace falta reiniciar el server (lo decide Ariel).
## Trabajo y decisiones
Tareas, dependencias y decisiones con su motivo.
## Evidencia
Resultados observados, condiciones, archivos y commits de referencia.
Registrar también pruebas fallidas, no ejecutadas y límites de la verificación.
La ruta de cada evidencia que respalda un hito (logs, mediciones, arneses) queda escrita acá: lo
citado no se borra al limpiar temporales (`c.limpiar_coordinacion`).
## Próximo paso
Una acción concreta para continuar.
```

La ficha no copia el código: apunta a él. Nada de firmas, clases ni diseño detallado que el agente
puede leer en el repo; guarda sólo lo que el código no dice (objetivo, lo que queda afuera, decisiones
con su motivo, evidencia). El cómo lo decide el agente con autonomía, dentro de la constitución y la
arquitectura.

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

**Verificado es por el camino real.** La ficha ordena el trabajo pero no encuentra defectos: los más
caros aparecen corriendo el cambio como corre de verdad. Al menos un criterio de cada feature se
comprueba así: el server arrancado como `lienzo-server.cmd` (una instancia propia en otro puerto, con
`LIENZO_URL`, si el real coordina sesiones), el agente real lanzado por `POST /sessions/launch`, el
envío visto en el transcript o la pantalla, la medición repetida. Un doble o el arnés solo no alcanzan:
un test que recorre una carpeta vacía pasa sin verificar nada. Lo que sólo se probó con dobles se
dice en Evidencia.

Mantener revisión, auditoría y pruebas exigidas para el cambio. FDD no agrega una
batería universal ni elimina controles existentes: elegirlos por impacto y evidencia.
Una afirmación del agente, un turno terminado, un test aislado o un merge no cierran
una tarea automáticamente. Las tareas se crean pendientes y solo se marcan
completadas por pedido explícito de Ariel. Registrar evidencia no equivale a cerrarlas.

## Varios frentes

Antes de repartir una feature: ficha, `docs/dominio.md`, archivos con dueño y efectos compartidos.

- **El encargo de un frente es su ficha.** No se escribe un encargo y además una ficha que dice lo
  mismo: el `.md` del encargo en `.temp/coordinacion/<fecha>/` lleva `Hito:`, archivos con dueño,
  dominio y efectos compartidos, y el frente lo actualiza al pasar de hito. `c.encargo(..., ficha=…)`
  lo enlaza en la memoria.
- Los archivos de cada frente se escriben en la ficha antes de repartir; si dos fichas abiertas
  nombran el mismo archivo, se resuelve antes. Lo que un frente encuentra fuera de sus archivos lo
  anota en la ficha, no lo edita. Commitea sólo la coordinadora.
- **Los efectos compartidos se reparten antes**: quién sube cada versión de un contrato, quién vuelve
  a medir cada prueba medida (una vez, al cierre, con las fuentes congeladas) y quién reemplaza un
  archivo que se carga en vivo. Ese reemplazo es de una sola vez: se edita una copia, se verifica
  (`ast.parse` y las pruebas) y se cambia el archivo entero; nunca queda roto en disco, porque otras
  sesiones lo importan mientras tanto.
- **Recursos aislados**: puerto, base y temporales con la letra del frente. El server de Lienzo y los
  procesos de Ariel no se frenan ni se reinician.
- **Antes de limpiar `.temp/coordinacion/`**: `c.limpiar_coordinacion(repo, dias)` lista lo que se
  puede borrar y protege los días que citan contratos, fichas, informes o docs; un día citado se borra
  sólo nombrándolo en `confirmar`.

Fuentes: Feature-Driven Development (De Luca y Coad, 1997; Palmer y Felsing, 2002) y FTD de RSC
(https://github.com/ericrisco/rsc-harness/blob/main/skills/ftd/SKILL.md). No instala RSC ni copia
sus cierres automáticos.
