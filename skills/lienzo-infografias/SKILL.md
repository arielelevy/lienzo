---
name: lienzo-infografias
description: Dibujar infografías estáticas del lienzo (SVG isométrico, tema oscuro y claro) para el README y docs/, con el kit de la skill anatomy. Usar al pedir una infografía, figura, diagrama o ilustración de cómo funciona algo del lienzo, o al rehacer las que ya están en docs/img/infografias.
---

# Infografías del lienzo

Las figuras explican un mecanismo del lienzo con un objeto físico que funciona igual: el tablero es
una coordinadora, cada sesión un jack con su lámpara, cada conexión un cordón. Se dibujan con el kit
de la skill `anatomy` (`~/.claude/skills/anatomy`, o `ANATOMY_DIR`), sin copiarlo al repo.

Es opcional: el lienzo no la usa para nada. Sin `anatomy`, o sin Chrome para `--check`, el
lienzo funciona igual y sus pruebas de esta herramienta se saltean.

## Reglas propias del lienzo

Estas mandan sobre lo que diga `anatomy`:

- **Estáticas.** Sin script, sin animación, sin tour ni lectura en vivo: el SVG queda en reposo.
  No pases `kitScript()` ni `live`. GitHub muestra el SVG como `<img>` y no correría nada.
- **En español rioplatense**, como el resto del repo: título, pista, lectura, leyenda y `label`.
- **Datos verdaderos.** Cada número sale del código o del README (60 s del hook de permisos,
  30 s del barrido de procesos, hasta 4 PCs). Si no lo encontrás, no lo inventes.
- **Tamaño Figure** de `anatomy` (40 a 80 piezas). Una figura más grande se consulta antes.
- No uses `publish.mjs` de `anatomy`: sube a una galería pública.

## Cómo se agrega una

1. Leé `SKILL.md` de `anatomy` (pasos 2 a 8 y las reglas de oficio) y `figuras/coordinadora.mjs`,
   que es el ejemplo de referencia.
2. Creá `figuras/<nombre>.mjs` que importe `{ k, tubePieces, tubeSvg, write }` de `../kit.mjs` y
   exporte `build()`, que devuelve `write("<nombre>", { width, height, label, body, card })`.
3. Armala y revisala:
   ```
   node skills/lienzo-infografias/build.mjs <nombre> --check
   ```
   Escribe `docs/img/infografias/<nombre>-dark.svg` y `-light.svg`, y en la carpeta temporal
   `lienzo-infografias` deja la página con su tarjeta, las capturas y el chequeo de líneas. Mirá las
   PNG en los dos temas, y con `capture.mjs --zoom` de `anatomy` los detalles, antes de darla por buena.
4. Para el README, usá las dos variantes con `<picture>` y poné la explicación en el texto de al
   lado, porque la tarjeta (título, leyenda) no viaja en el SVG:
   ```html
   <picture>
     <source media="(prefers-color-scheme: dark)" srcset="docs/img/infografias/<nombre>-dark.svg">
     <img alt="…" src="docs/img/infografias/<nombre>-light.svg">
   </picture>
   ```

## Figuras

| Figura | Qué explica |
|---|---|
| `coordinadora` | Sesiones como jacks con lámpara de estado, conexiones como cordones (una cruza a la PC 2), un permiso esperando y el reloj de 60 s del hook |
