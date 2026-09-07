# Encargo A — Pasada de UX y simplificación del front (web/src)

Sos una de tres sesiones trabajando en paralelo sobre `D:\Apps\lienzo`. Tu territorio es
**solo `web/src/`** (front-end). No toques `lienzo/*.py`, `tests/`, ni `docs/` salvo este
archivo. Otra sesión está en el Python y otra en el pentest: no pises esos archivos.

## Qué hacer

1. **Pasada de UX por el navegador, no por el código.** El server está corriendo en
   `http://127.0.0.1:7321`. Abrí un browser con Playwright (Python, `PYTHONIOENCODING=utf-8`)
   y recorré el tablero como un usuario: tablero a 1680/1280/900/390 px, abrir el panel de una
   tarjeta con contenido, las cuatro pestañas (Destacados, Conversación, Pantalla, Conexiones),
   el grupo "sesiones libres", el buscador con `/`, el diálogo Conectar, el menú de la tarjeta y
   el de la cabecera. Sacá capturas al scratchpad y miralas.

2. **Anotá lo que esté flojo** y arreglalo en `web/src/`: jerarquía visual, densidad, estados
   vacíos, foco de teclado, contraste, textos que cortan mal, cosas que no se entienden sin
   contexto. Cambios quirúrgicos, no un rediseño. Respetá las decisiones que ya manda Ariel
   (React; columnas vacías colapsadas; diálogo de conectar flotante; la Pantalla se lee solo
   para las sugerencias; nada automático sin tope).

3. **Simplificá el código del front** mientras estás: componentes largos que se puedan partir,
   lógica repetida que salga a un helper, props o estado muerto, condiciones ilegibles. Sin
   cambiar el comportamiento observable ni romper contratos de `types.ts`.

## Reglas de la ronda

- **No commitees, no reinicies el server, no hagas push, no pises `git`.** Yo (la coordinadora)
  verifico y commiteo. El bundle se recarga solo cuando cambia; si necesitás ver tu cambio,
  `npm run build` en `web/` y recargá el browser.
- Antes de dar por cerrado, corré y dejá en verde:
  - `cd web && node --experimental-strip-types src/arrows-geometry.test.ts`
  - `cd web && node --experimental-strip-types src/nl.test.ts`
  - `cd web && npm run build` (compila TS)
  - `cd web && npm run test:ui` (28 pruebas Playwright; el server tiene que estar andando)
- Si algo no lo podés cerrar, dejalo prolijo y explicá por qué.

## Cuando termines

Respondé con un informe corto: qué encontraste, qué tocaste (lista de archivos), qué tests
corriste y cómo salieron, y lo que dejaste afuera. Ese informe llega solo a mi consola.
