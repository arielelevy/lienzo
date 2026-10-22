import assert from "node:assert/strict";
import { test } from "node:test";
// @ts-ignore TS5097: Node ejecuta TypeScript directamente.
import { computeSegs, cubicHits, type Pt, type Rect } from "./arrows-geometry.ts";

test("las curvas entre frentes y coordinadora escalonados no entran en sus propias tarjetas", () => {
  const rects = new Map<string, Rect>([
    ["front-a", { l: 132, t: 137, r: 345, b: 267 }],
    ["front-b", { l: 371, t: 137, r: 584, b: 251 }],
    ["coord", { l: 251, t: 319, r: 464, b: 469 }],
  ]);
  for (const from of ["front-a", "front-b"]) {
    const [seg] = computeSegs({ rects, anchors: rects, strips: [], boardWidth: 1440, links: [],
      rules: [{ id: "report", kind: "on_stop", from, to: "coord", text: "informe", at: null, repeat: false, max_fires: 1, fired: 0, enabled: true }],
      fmt: { ago: x => x, hhmm: x => x, name: x => x, when: x => x } });
    assert.ok(seg && !seg.dim, "hay un camino limpio entre el frente y su coordinadora");
    if (seg.d.includes(" C ")) {
      const n = seg.d.match(/-?\d+(?:\.\d+)?/g)!.map(Number);
      const pts = [[n[0], n[1]], [n[2], n[3]], [n[4], n[5]], [n[6], n[7]]] as [Pt, Pt, Pt, Pt];
      assert.equal(cubicHits([...rects.values()], ...pts, 200, 0.5), false, `${from}: ${seg.d}`);
    }
  }
});
