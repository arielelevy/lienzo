/** Tests del acomodo de la vista por proyecto. Sin runner: desde web/,
 *    node --experimental-strip-types src/project-pack.test.ts
 */
import assert from "node:assert/strict";
// @ts-ignore TS5097: extension .ts en el import, necesaria para que Node lo resuelva
import { cardCell, packProjects } from "./project-pack.ts";

// la captura del 2026-10-23: 8 subcolumnas, opensyync 4, lienzo 3, source 2, Pepsico 1. Antes iba
// un proyecto por fila; ahora opensyync y lienzo comparten el estante y Pepsico entra en el hueco
{
  const p = packProjects(
    [
      { key: "opensyync", n: 4, coordinator: false },
      { key: "lienzo", n: 3, coordinator: false },
      { key: "source", n: 2, coordinator: false },
      { key: "pepsico", n: 1, coordinator: false },
    ],
    8,
  );
  assert.deepEqual(p.get("opensyync"), { col: 1, k: 4, row: 1, rows: 1 });
  assert.deepEqual(p.get("lienzo"), { col: 5, k: 3, row: 1, rows: 1 });
  assert.deepEqual(p.get("pepsico"), { col: 8, k: 1, row: 1, rows: 1 });
  assert.deepEqual(p.get("source"), { col: 1, k: 2, row: 3, rows: 1 });
}

// un proyecto con más frentes que subcolumnas usa todo el ancho y varias filas; el siguiente
// arranca debajo de su caja entera
{
  const p = packProjects([{ key: "a", n: 5, coordinator: false }, { key: "b", n: 1, coordinator: false }], 2);
  assert.deepEqual(p.get("a"), { col: 1, k: 2, row: 1, rows: 3 });
  assert.deepEqual(p.get("b"), { col: 1, k: 1, row: 5, rows: 1 });
}

// la coordinadora va sola en la última fila de su caja, a lo ancho de la caja
{
  const p = packProjects([{ key: "a", n: 3, coordinator: true }], 4);
  const a = p.get("a")!;
  assert.deepEqual(a, { col: 1, k: 2, row: 1, rows: 2 });
  assert.deepEqual(cardCell(a, 0, 3, true), { col: "1", row: 2 });
  assert.deepEqual(cardCell(a, 1, 3, true), { col: "2", row: 2 });
  assert.deepEqual(cardCell(a, 2, 3, true), { col: "1 / span 2", row: 3 });
}

// sólo la coordinadora: una subcolumna, su fila debajo del título
{
  const a = packProjects([{ key: "a", n: 1, coordinator: true }], 4).get("a")!;
  assert.deepEqual(a, { col: 1, k: 1, row: 1, rows: 1 });
  assert.deepEqual(cardCell(a, 0, 1, true), { col: "1 / span 1", row: 2 });
}

// el estante es tan alto como su caja más alta: el siguiente no se superpone
{
  const p = packProjects(
    [{ key: "a", n: 2, coordinator: true }, { key: "b", n: 1, coordinator: false }, { key: "c", n: 4, coordinator: false }],
    3,
  );
  assert.equal(p.get("b")!.row, 1);
  assert.equal(p.get("c")!.row, 1 + 1 + p.get("a")!.rows);
}

// sin dato de subcolumnas (NaN) no rompe la grilla: una subcolumna
assert.deepEqual(packProjects([{ key: "a", n: 2, coordinator: false }], Number.NaN).get("a"), { col: 1, k: 1, row: 1, rows: 2 });

console.log("project-pack: ok");
