/** Tests de la geometria pura de las flechas. No hay runner en package.json: corren con Node solo,
 *  sin dependencias, desde web/:
 *
 *    node --experimental-strip-types src/arrows-geometry.test.ts
 *
 *  (Node 22.18+ ya quita los tipos sin el flag; el flag no molesta.) El import lleva extension .ts
 *  porque Node ESM la exige; tsc la rechaza sin allowImportingTsExtensions, por eso el ts-ignore.
 *  Sale con codigo 1 y el nombre del test si algo falla. */

import assert from "node:assert/strict";
// @ts-ignore TS5097: extension .ts en el import, necesaria para que Node lo resuelva
import { buildItems, channelX, clearance, colOf, computeSegs, cubic, freeAt, groupColumns, layoutEnds, periodLabel, sideArc, type Formatters, type Rect } from "./arrows-geometry.ts";
import type { Link, Rule } from "./types";

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
const R = (l: number, t: number, r: number, b: number): Rect => ({ l, t, r, b });
/** formateadores deterministas: no dependen del reloj ni de la zona horaria */
const fmt: Formatters = { ago: (iso) => `ago(${iso})`, hhmm: (iso) => iso.slice(11, 16) };
const rule = (p: Partial<Rule> & Pick<Rule, "id" | "from" | "to">): Rule => ({ kind: "on_stop", text: "", at: null, repeat: false, max_fires: 1, fired: 0, enabled: true, ...p });
const link = (p: Partial<Link> & Pick<Link, "id" | "from" | "to" | "ts">): Link => ({ text: "hola", ...p });

// tablero tipo: dos columnas abiertas de 300 px con un canal de 28 px, y una tira colapsada a la derecha
const A1 = R(0, 0, 300, 120);
const A2 = R(0, 140, 300, 260);
const B1 = R(328, 0, 628, 120);
const B2 = R(328, 140, 628, 300);
const STRIP = { l: 640, r: 668 };
const W = 700;

test("groupColumns agrupa por borde izquierdo, ordena y estira el borde derecho", () => {
  const cols = groupColumns([B2, A2, R(10, 300, 320, 400), A1, B1]);
  assert.deepEqual(cols, [
    { l: 0, r: 320 },
    { l: 328, r: 628 },
  ]);
  assert.deepEqual(groupColumns([]), []);
});

test("colOf tolera 40 px y devuelve -1 fuera de toda columna", () => {
  const cols = groupColumns([A1, B1]);
  assert.equal(colOf(cols, R(30, 0, 100, 10)), 0);
  assert.equal(colOf(cols, R(340, 0, 400, 10)), 1);
  assert.equal(colOf(cols, R(640, 0, 668, 400)), -1);
});

test("channelX es el medio del hueco entre columnas vecinas, o el fallback si no hay vecina", () => {
  const cols = groupColumns([A1, B1]);
  assert.equal(channelX(cols, 0, 1, -1), 314);
  assert.equal(channelX(cols, 1, -1, -1), 314);
  assert.equal(channelX(cols, 1, 1, 999), 999);
  assert.equal(channelX(cols, 0, -1, 999), 999);
  assert.equal(channelX(cols, 7, 1, 5), 5);
});

test("freeAt mide hasta la columna vecina, la tira colapsada o el borde del tablero", () => {
  const cols = groupColumns([A1, B1]);
  assert.equal(freeAt(cols, [STRIP], W, 0, -1), 0); // pegada al borde izquierdo
  assert.equal(freeAt(cols, [STRIP], W, 0, 1), 28); // el canal
  assert.equal(freeAt(cols, [STRIP], W, 1, 1), 12); // hasta la tira, no hasta el borde
  assert.equal(freeAt(cols, [], W, 1, 1), 72); // sin tira: hasta el borde del tablero
  assert.equal(freeAt(cols, [], W, 5, 1), 0); // columna inexistente
});

test("sideArc elige el costado con mas lugar y limita la panza a HALF_GAP", () => {
  const cols = groupColumns([A1, B1]);
  // columna 0: izquierda 0, derecha 28 -> derecha, panza max(20, 14) = 20
  assert.deepEqual(sideArc(cols, [STRIP], W, 0), { side: "r", x: 320 });
  // columna 1: izquierda 28, derecha 12 -> izquierda
  assert.deepEqual(sideArc(cols, [STRIP], W, 1), { side: "l", x: 308 });
  // empate (28 y 28): gana la derecha
  const cols3 = groupColumns([A1, B1, R(656, 0, 900, 100)]);
  assert.equal(sideArc(cols3, [], 1000, 1).side, "r");
});

test("clearance es la distancia al borde mas cercano, negativa adentro de una tarjeta", () => {
  const cards = [A1, B1];
  assert.equal(clearance(cards, 314, 60), 14); // medio del canal
  assert.equal(clearance(cards, 150, 60), -60); // centro de A1: 60 al borde mas cercano
  assert.equal(clearance(cards, 150, 130), 10); // 10 px debajo de A1
  assert.equal(clearance(cards, 400, 200), 80); // debajo de B1
  assert.equal(clearance([], 0, 0), Infinity);
});

test("cubic arma el path y pone el glifo en el punto mas despejado; los glifos puestos se esquivan", () => {
  const cards = [A1, B1];
  const taken: [number, number][] = [];
  const p = cubic(cards, taken, [300, 60], [314, 60], [314, 60], [328, 60]);
  assert.equal(p.d, "M 300 60 C 314 60, 314 60, 328 60");
  assert.ok(Math.abs(p.y - 60) < 1e-9);
  assert.ok(Math.abs(p.x - 314) < 1.5, `glifo en el medio del canal, x=${p.x}`);
  assert.equal(taken.length, 1);
  // segunda curva por el mismo canal: el glifo se corre para no pisar al primero
  const q = cubic(cards, taken, [300, 60], [314, 60], [314, 400], [328, 400]);
  assert.ok(Math.hypot(q.x - p.x, q.y - p.y) > 22, `se separa del anterior: (${q.x},${q.y}) vs (${p.x},${p.y})`);
  assert.equal(taken.length, 2);
  // con una sola tarjeta lejos, todo punto de la curva mejora al alejarse: el glifo cae en la punta
  // mas lejana (t=0.95), no en el centro
  const c = cubic([R(-100, -100, -50, -50)], [], [0, 0], [0, 0], [100, 100], [100, 100]);
  assert.ok(c.x > 95 && c.y > 95, `punta lejana: (${c.x},${c.y})`);
});

test("cubic es determinista: misma entrada, misma salida", () => {
  const cards = [A1, A2, B1, B2];
  const a = cubic(cards, [], [300, 60], [314, 60], [314, 220], [328, 220]);
  const b = cubic(cards, [], [300, 60], [314, 60], [314, 220], [328, 220]);
  assert.deepEqual(a, b);
});

test("buildItems agrupa los links por par y sentido, el mas nuevo manda, y separa el canal nativo", () => {
  const anchors = new Map([["a", A1], ["b", B1]]);
  const links = [
    link({ id: "1", from: "a", to: "b", ts: "2026-09-05T10:00:00Z", text: "primero" }),
    link({ id: "2", from: "a", to: "b", ts: "2026-09-05T12:00:00Z", text: "ultimo" }),
    link({ id: "3", from: "b", to: "a", ts: "2026-09-05T11:00:00Z", text: "vuelta" }),
    link({ id: "4", from: "a", to: "b", ts: "2026-09-05T09:00:00Z", kind: "native", text: "nativo" }),
    link({ id: "5", from: "a", to: "zzz", ts: "2026-09-05T09:00:00Z", text: "destino sin tarjeta" }),
  ];
  const items = buildItems(links, [], anchors, fmt);
  assert.equal(items.length, 3);
  assert.deepEqual(items[0].ids, ["2", "1"]); // mas nuevo primero
  assert.equal(items[0].kind, "link");
  assert.equal(items[0].glyph, "×2");
  assert.equal(items[0].title, "último envío hace ago(2026-09-05T12:00:00Z) (2 en total)\n• 12:00 ultimo\n• 10:00 primero\n(click para quitar la flecha)");
  assert.equal(items[1].glyph, "↪");
  assert.equal(items[1].title.split("\n")[0], "enviado hace ago(2026-09-05T11:00:00Z)");
  assert.equal(items[2].kind, "native");
  assert.equal(items[2].glyph, "⇄");
  assert.match(items[2].title, /^canal nativo Claude↔Claude abierto hace /);
  assert.ok(items.every((it) => it.old === false && it.fresh === undefined));
});

test("buildItems corta los textos a 90 y lista como mucho 5 mensajes", () => {
  const anchors = new Map([["a", A1], ["b", B1]]);
  const links = Array.from({ length: 7 }, (_, i) => link({ id: `l${i}`, from: "a", to: "b", ts: `2026-09-05T0${i}:00:00Z`, text: "x".repeat(100) }));
  const [it] = buildItems(links, [], anchors, fmt);
  const lines = it.title.split("\n");
  assert.equal(lines.length, 8); // cabecera + 5 + "… y 2 más" + pie
  assert.equal(lines[6], "… y 2 más");
  assert.equal(lines[1], `• 06:00 ${"x".repeat(90)}…`);
});

test("buildItems solo dibuja reglas activas, con origen, no reflexivas y con los dos extremos", () => {
  const anchors = new Map([["a", A1], ["b", B1]]);
  const rules = [
    rule({ id: "r1", from: "a", to: "b" }),
    rule({ id: "r2", from: "a", to: "b", repeat: true, fired: 2, max_fires: 5 }),
    rule({ id: "r3", from: "a", to: "b", kind: "at", at: "2026-09-05T23:00:00Z", text: "Continuar" }),
    rule({ id: "r4", from: "a", to: "b", kind: "at", at: null, text: "sin hora" }),
    rule({ id: "off", from: "a", to: "b", enabled: false }),
    rule({ id: "auto", from: null, to: "b" }),
    rule({ id: "self", from: "a", to: "a" }),
    rule({ id: "lost", from: "a", to: "nadie" }),
  ];
  const items = buildItems([], rules, anchors, fmt);
  assert.deepEqual(items.map((i) => i.ids[0]), ["r1", "r2", "r3", "r4"]);
  assert.equal(items[0].title, "cuando termine → manda su respuesta (una vez)\n(click quita · doble click edita)");
  assert.equal(items[1].title.split("\n")[0], "cuando termine → manda su respuesta (2/5)");
  assert.equal(items[2].glyph, "⏰");
  assert.equal(items[2].title.split("\n")[0], 'a las 23:00 → "Continuar"');
  assert.equal(items[3].title.split("\n")[0], 'a las ? → "sin hora"');
});

test("periodLabel: minutos, hora, horas y dia; nunca menos de un minuto", () => {
  assert.equal(periodLabel(300), "cada 5 min");
  assert.equal(periodLabel(1800), "cada 30 min");
  assert.equal(periodLabel(3600), "cada hora");
  assert.equal(periodLabel(7200), "cada 2 h");
  assert.equal(periodLabel(86400), "cada día");
  assert.equal(periodLabel(172800), "cada 2 días");
  assert.equal(periodLabel(90), "cada 90 s");
  assert.equal(periodLabel(10), "cada 1 min");
  assert.equal(periodLabel(null), "cada 1 min");
});

test("buildItems: una regla at periodica lleva ↻ y dice periodo, cuenta y proxima hora; sin at, solo la cuenta", () => {
  const anchors = new Map([["a", A1], ["b", B1]]);
  const rules = [
    rule({ id: "p1", from: "a", to: "b", kind: "at", at: "2026-09-06T09:30:00Z", text: "Continuá", every_s: 1800, max_fires: 5, fired: 1, repeat: true }),
    rule({ id: "p2", from: "a", to: "b", kind: "at", at: null, text: "ping", every_s: 3600, max_fires: 2, fired: 0, repeat: true }),
    rule({ id: "once", from: "a", to: "b", kind: "at", at: "2026-09-06T09:30:00Z", text: "una vez", every_s: null }),
  ];
  const items = buildItems([], rules, anchors, fmt);
  assert.equal(items[0].glyph, "↻");
  assert.equal(items[0].title, 'cada 30 min → "Continuá" (1/5, próx. 09:30)\n(click quita · doble click edita)');
  assert.equal(items[1].glyph, "↻");
  assert.equal(items[1].title.split("\n")[0], 'cada hora → "ping" (0/2)');
  assert.equal(items[2].glyph, "⏰");
  assert.equal(items[2].title.split("\n")[0], 'a las 09:30 → "una vez"');
});

test("layoutEnds: columnas distintas salen por el lado que mira al destino; misma columna usan el arco", () => {
  const anchors = new Map([["a1", A1], ["a2", A2], ["b1", B1]]);
  const cols = groupColumns([A1, A2, B1]);
  const items = buildItems([], [rule({ id: "x", from: "a1", to: "b1" }), rule({ id: "y", from: "b1", to: "a1" }), rule({ id: "z", from: "a1", to: "a2" })], anchors, fmt);
  const { sideOf, endY } = layoutEnds(items, anchors, cols, [STRIP], W);
  assert.deepEqual(sideOf[0], { exit: "r", enter: "l", same: false, arcX: 0 });
  assert.deepEqual(sideOf[1], { exit: "l", enter: "r", same: false, arcX: 0 });
  assert.deepEqual(sideOf[2], { exit: "r", enter: "r", same: true, arcX: 320 });
  // a1 tiene tres extremos por la derecha (sale x, entra y, sale z): se apilan a 14 px centrados
  // en 60, ordenados por la altura del otro extremo (b1 a 60 dos veces, orden estable; a2 a 200)
  assert.equal(endY[0].from, 46);
  assert.equal(endY[1].to, 60);
  assert.equal(endY[2].from, 74);
  // b1 tiene dos por la izquierda (entra x, sale y): 53 y 67; a2 recibe z sola, al medio
  assert.equal(endY[0].to, 53);
  assert.equal(endY[1].from, 67);
  assert.equal(endY[2].to, 200);
});

test("layoutEnds no desborda una tarjeta baja: el apilado se comprime a alto-20", () => {
  const low = R(0, 0, 300, 30);
  const anchors = new Map([["a", low], ["b1", B1], ["b2", B2], ["b3", R(328, 320, 628, 400)]]);
  const cols = groupColumns([low, B1, B2]);
  const rules = ["b1", "b2", "b3"].map((to) => rule({ id: to, from: "a", to }));
  const { endY } = layoutEnds(buildItems([], rules, anchors, fmt), anchors, cols, [], W);
  const ys = endY.map((e) => e.from);
  assert.deepEqual(ys, [10, 15, 20]); // span = min(28, 10) = 10, centrado en 15
});

test("computeSegs: una regla entre columnas vecinas viaja por el canal, con el glifo en el medio", () => {
  const rects = new Map([["a", A1], ["b", B1]]);
  const segs = computeSegs({ rects, anchors: rects, strips: [STRIP], boardWidth: W, links: [], rules: [rule({ id: "r", from: "a", to: "b" })], fmt });
  assert.equal(segs.length, 1);
  const s = segs[0];
  assert.equal(s.d, "M 300 60 C 314 60, 314 60, 328 60");
  assert.ok(Math.abs(s.x - 314) < 1.5);
  assert.ok(Math.abs(s.y - 60) < 1e-9);
  assert.equal(s.kind, "rule");
  assert.equal(s.glyph, "⏹");
});

test("computeSegs: una flecha hacia una tira colapsada usa el anchor sin contarla como columna", () => {
  const rects = new Map([["a", A1], ["b", B1]]);
  const vlabel = R(640, 100, 668, 220);
  const anchors = new Map([...rects, ["t", vlabel]]);
  const segs = computeSegs({ rects, anchors, strips: [STRIP], boardWidth: W, links: [], rules: [rule({ id: "r", from: "b", to: "t" })], fmt });
  assert.equal(segs.length, 1);
  // sale por la derecha de B1 y entra por la izquierda de la tira; la tira no tiene columna vecina,
  // asi que el control de llegada usa el fallback (x2 - half, con half = min(20, 12/2) = 6)
  assert.equal(segs[0].d, "M 628 60 C 634 60, 634 160, 640 160");
});

test("computeSegs: misma columna, arco por el costado; y sin extremos visibles, nada", () => {
  const rects = new Map([["a1", A1], ["a2", A2], ["b", B1]]);
  const segs = computeSegs({ rects, anchors: rects, strips: [STRIP], boardWidth: W, links: [], rules: [rule({ id: "r", from: "a1", to: "a2" })], fmt });
  assert.equal(segs[0].d, "M 300 60 C 320 60, 320 200, 300 200");
  assert.ok(segs[0].x > 300 && segs[0].x <= 320, `glifo en la panza, x=${segs[0].x}`);
  const none = computeSegs({ rects: new Map(), anchors: new Map(), strips: [], boardWidth: 0, links: [], rules: [rule({ id: "r", from: "a1", to: "a2" })], fmt });
  assert.deepEqual(none, []);
});

test("computeSegs es puro: no muta la entrada y repite la salida", () => {
  const rects = new Map([["a", A1], ["b", B1], ["a2", A2]]);
  const links = [link({ id: "1", from: "a", to: "b", ts: "2026-09-05T10:00:00Z" }), link({ id: "2", from: "a", to: "b", ts: "2026-09-05T11:00:00Z" })];
  const before = JSON.stringify(links);
  const input = { rects, anchors: rects, strips: [STRIP], boardWidth: W, links, rules: [rule({ id: "r", from: "b", to: "a2" })], fmt };
  const s1 = computeSegs(input);
  const s2 = computeSegs(input);
  assert.deepEqual(s1, s2);
  assert.equal(JSON.stringify(links), before);
  assert.equal(s1.length, 2);
  assert.notDeepEqual([s1[0].x, s1[0].y], [s1[1].x, s1[1].y]); // dos glifos en el mismo canal, separados
});

if (failed) {
  console.log(`\n${failed} test(s) fallaron`);
  throw new Error(`${failed} test(s) fallaron`);
}
console.log("\ntodo ok");
