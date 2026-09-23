/** Tests del parser de la referencia (/docs). Como los de la geometria, corren con Node solo, desde web/:
 *
 *    node --experimental-strip-types src/docs-parse.test.ts
 *
 *  y contra los dos documentos reales del repo, que es donde se rompe si alguien agrega un caso raro. */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
// @ts-ignore TS5097: extension .ts en el import, necesaria para que Node lo resuelva
import { hits, markRe, parseDoc, slugify, terms } from "./docs-parse.ts";

let failed = 0;
function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`ok   ${name}`);
  } catch (e) {
    failed++;
    console.log(`FAIL ${name}\n     ${(e as Error).message}`);
  }
}

test("el ancla es la de GitHub: minusculas, sin puntuacion, con acentos", () => {
  assert.equal(slugify("Cómo funciona"), "cómo-funciona");
  assert.equal(slugify("4.3 El script de hook (`lienzo-hook.py`)"), "43-el-script-de-hook-lienzo-hookpy");
  assert.equal(slugify("Por qué Windows, y qué haría falta para Mac"), "por-qué-windows-y-qué-haría-falta-para-mac");
});

test("un # dentro de un bloque de codigo no es encabezado, y las anclas repetidas llevan sufijo", () => {
  const b = parseDoc("# T\nintro\n## Uno\n```sh\n# comentario\n```\n### Sub\nx\n## Uno\ny");
  assert.deepEqual(b.map((x) => x.title), ["T", "Uno", "Sub", "Uno"]);
  assert.deepEqual(b.map((x) => x.slug), ["t", "uno", "sub", "uno-1"]);
  assert.deepEqual(b.map((x) => x.section), [0, 1, 1, 3]);
  assert.ok(b[1].body.includes("# comentario"));
});

test("buscar pide todos los terminos y no le importan los acentos", () => {
  const [b] = parseDoc("## Diseño\nla pestaña de la tarjeta");
  assert.equal(hits(b, terms("diseno PESTANA")), 2);
  assert.equal(hits(b, terms("diseno celular")), 0);
  assert.deepEqual("la pestaña y la PESTANA".match(markRe(terms("pestana"))!), ["pestaña", "PESTANA"]);
});

for (const f of ["README.md", "DISENO.es.md"]) {
  test(`${f}: todo link #ancla del documento cae en un encabezado`, () => {
    const md = readFileSync(new URL(`../../${f}`, import.meta.url), "utf8");
    const blocks = parseDoc(md);
    assert.ok(blocks.length > 10, `${blocks.length} bloques`);
    const slugs = new Set(blocks.map((b) => b.slug));
    const rotos = [...md.matchAll(/\]\(#([^)]+)\)/g)].map((m) => m[1]).filter((s) => !slugs.has(decodeURIComponent(s)));
    assert.deepEqual(rotos, []);
  });
}

if (failed) {
  console.log(`\n${failed} test(s) fallaron`);
  process.exit(1);
}
console.log("\ntodo ok");
