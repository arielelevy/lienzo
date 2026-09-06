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
import { LANE_CLEAR, LANE_H, LANE_MAX, TRACK_GAP, allowed, buildItems, channelX, clearance, colOf, computeSegs, cubic, cubicAt, cubicHits, cut, ejectGlyph, freeAt, freeLanes, groupColumns, inside, laneHeight, layoutEnds, periodLabel, runAllowed, segHits, sideArc, slotAt, topRoute, tracks, type Band, type Formatters, type Lane, type Pt, type Rect, type Seg } from "./arrows-geometry.ts";
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
/** formateadores deterministas: no dependen del reloj, de la zona horaria ni del registro de sesiones */
const fmt: Formatters = {
  ago: (iso) => `ago(${iso})`,
  hhmm: (iso) => iso.slice(11, 16),
  name: (sid) => `n(${sid})`,
  when: (iso) => `a las ${iso.slice(11, 16)}`,
};
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
  // el titulo es de una linea y dice que hace el click; lo que es la flecha va en `desc`, que se
  // muestra mientras esta seleccionada y siempre termina diciendo que hace el doble click
  assert.equal(items[0].title, "2 envíos de n(a) a n(b), el último hace ago(2026-09-05T12:00:00Z) · click para seleccionarla");
  assert.equal(items[0].desc, "n(a) le mandó 2 mensajes a n(b). El último, hace ago(2026-09-05T12:00:00Z). Doble click para verlos o mandar de nuevo.");
  assert.ok(items.every((it) => !it.title.includes("\n")), "el title va en una linea");
  assert.ok(items.every((it) => /Doble click para /.test(it.desc)), "la descripcion enseña el gesto");
  assert.equal(items[1].glyph, "↪");
  assert.equal(items[1].title, "envío de n(b) a n(a), hace ago(2026-09-05T11:00:00Z) · click para seleccionarla");
  assert.equal(items[2].kind, "native");
  assert.equal(items[2].glyph, "⇄");
  assert.match(items[2].title, /^canal nativo entre n\(a\) y n\(b\), abierto hace /);
  assert.match(items[2].desc, /^n\(a\) y n\(b\) tienen abierto el canal nativo desde hace /);
  assert.ok(items.every((it) => it.old === false && it.fresh === undefined));
});

test("buildItems: varios envios se cuentan en la descripcion; los textos se leen en la vista", () => {
  const anchors = new Map([["a", A1], ["b", B1]]);
  const links = Array.from({ length: 7 }, (_, i) => link({ id: `l${i}`, from: "a", to: "b", ts: `2026-09-05T0${i}:00:00Z`, text: "x".repeat(100) }));
  const [it] = buildItems(links, [], anchors, fmt);
  assert.equal(it.glyph, "×7");
  assert.equal(it.desc, "n(a) le mandó 7 mensajes a n(b). El último, hace ago(2026-09-05T06:00:00Z). Doble click para verlos o mandar de nuevo.");
  assert.equal(cut("x".repeat(100)), `${"x".repeat(90)}…`);
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
  assert.equal(items[0].title, "cuando n(a) termine → su respuesta a n(b) · click para seleccionarla");
  assert.equal(items[0].desc, "Cada vez que n(a) cierre un turno, su respuesta se manda a n(b). Una sola vez. Doble click para editarla.");
  assert.equal(items[1].desc, "Cada vez que n(a) cierre un turno, su respuesta se manda a n(b). Van 2 de 5. Doble click para editarla.");
  assert.equal(items[2].glyph, "⏰");
  assert.equal(items[2].title, "a las 23:00 → «Continuar» a n(b) · click para seleccionarla");
  assert.equal(items[2].desc, "A las 23:00 se le escribe «Continuar» a n(b). La programó n(a). Doble click para editarla.");
  assert.equal(items[3].desc, "Sin hora fijada, se le escribe «sin hora» a n(b). La programó n(a). Doble click para editarla.");
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
  assert.equal(items[0].title, "cada 30 min → «Continuá» a n(b) (1/5, próx. 09:30) · click para seleccionarla");
  assert.equal(items[0].desc, "Cada 30 min se le escribe «Continuá» a n(b). Van 1 de 5. La próxima, a las 09:30. Se saltea si está trabajando. La programó n(a). Doble click para editarla.");
  assert.equal(items[1].glyph, "↻");
  assert.equal(items[1].title, "cada hora → «ping» a n(b) (0/2) · click para seleccionarla");
  assert.equal(items[2].glyph, "⏰");
  assert.equal(items[2].title, "a las 09:30 → «una vez» a n(b) · click para seleccionarla");
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

/** los cuatro puntos de un path "M x y C x y, x y, x y" */
function cubicPts(d: string): [Pt, Pt, Pt, Pt] {
  const n = d.match(/-?\d+(\.\d+)?/g)!.map(Number);
  assert.equal(n.length, 8, `path cubico: ${d}`);
  return [[n[0], n[1]], [n[2], n[3]], [n[4], n[5]], [n[6], n[7]]];
}

test("inside, segHits y ejectGlyph: el glifo nunca queda adentro de una tarjeta", () => {
  assert.ok(inside([A1], 10, 10));
  assert.ok(!inside([A1], 300, 60)); // el borde no cuenta
  assert.ok(segHits(B1, [300, 60], [656, 60])); // horizontal que atraviesa B1
  assert.ok(!segHits(B1, [300, -14], [656, -14])); // por arriba, libre
  assert.ok(!segHits(B1, [150, 0], [150, -14])); // vertical en otra columna
  assert.deepEqual(ejectGlyph([A1], 150, 10), [150, -6]); // arriba es el borde mas cercano
  assert.deepEqual(ejectGlyph([A1], 290, 60), [306, 60]); // a la derecha
  assert.deepEqual(ejectGlyph([A1], 150, 60), [150, -6]); // centro exacto: empata arriba y abajo, gana arriba (orden estable)
  assert.deepEqual(ejectGlyph([A1], 150, 61), [150, 126]); // apenas mas cerca del piso: abajo
  assert.deepEqual(ejectGlyph([A1], 400, 60), [400, 60]); // afuera, no se toca
  // filas pegadas: arriba de A2 esta A1 a 20 px; el punto sale igual arriba (el hueco es libre)
  assert.deepEqual(ejectGlyph([A1, A2], 150, 145), [150, 134]);
});

test("mismo par en la misma columna: la cubica no pasa por una tercera tarjeta y el glifo cae en el hueco", () => {
  const A3 = R(0, 280, 300, 400);
  const rects = new Map([["a1", A1], ["a2", A2], ["a3", A3], ["b", B1]]);
  const [s] = computeSegs({ rects, anchors: rects, strips: [STRIP], boardWidth: W, links: [], rules: [rule({ id: "r", from: "a1", to: "a3" })], fmt });
  const pts = cubicPts(s.d);
  for (let i = 1; i < 20; i++) {
    const [x, y] = cubicAt(...pts, i / 20);
    assert.ok(!inside([A2, B1], x, y), `punto ${i}/20 (${x.toFixed(1)}, ${y.toFixed(1)}) adentro de una tercera tarjeta`);
  }
  assert.ok(!inside([A1, A2, A3, B1], s.x, s.y), `glifo adentro de una tarjeta: (${s.x}, ${s.y})`);
  assert.ok(!s.dim);
});

test("columnas no vecinas: la S cruzaria la del medio, asi que va por arriba con esquinas redondeadas", () => {
  const C1 = R(656, 0, 956, 120);
  const rects = new Map([["a", A1], ["b", B1], ["c", C1]]);
  // la S por defecto atraviesa B1
  assert.ok(cubicHits([B1], [300, 60], [314, 60], [642, 60], [656, 60]));
  const [s] = computeSegs({ rects, anchors: rects, strips: [], boardWidth: 1000, links: [], rules: [rule({ id: "r", from: "a", to: "c" })], fmt });
  assert.ok(s.d.startsWith("M 150 0 L 150 -6 Q 150 -14, 158 -14 L 798 -14 Q 806 -14, 806 -6 L 806 0"), s.d);
  assert.equal(s.y, -14); // corrida por el margen superior del tablero
  assert.ok(!inside([A1, B1, C1], s.x, s.y));
  assert.ok(!s.dim);
  // dos flechas que salen por arriba de la misma tarjeta se reparten en x y no ponen el glifo en el mismo lugar
  const two = computeSegs({ rects, anchors: rects, strips: [], boardWidth: 1000, links: [], rules: [rule({ id: "r1", from: "a", to: "c" }), rule({ id: "r2", from: "c", to: "a" })], fmt });
  assert.equal(two.length, 2);
  assert.notEqual(two[0].d, two[1].d);
  assert.ok(Math.hypot(two[0].x - two[1].x, two[0].y - two[1].y) > 20, "glifos separados");
});

test("topRoute prefiere el hueco entre filas al margen si es mas corto, y marca dim cuando no hay camino limpio", () => {
  // origen en la fila 2 de la columna A, destino en la fila 2 de la columna C, con B2 en el medio:
  // el hueco entre filas (y = 140 - 4 = 136) esta libre y es mas corto que el margen superior
  const B2b = R(328, 140, 628, 260);
  const C2 = R(656, 140, 956, 260);
  const cards = [A1, A2, B1, B2b, R(656, 0, 956, 120), C2];
  const o = topRoute(A2, C2, 150, 806, cards);
  assert.ok(o.clean);
  assert.equal(o.y, 130); // el carril va al medio del hueco entre las dos filas (120..140)
  assert.deepEqual([o.exit, o.enter], ["t", "t"]);
  // encerrada: tarjetas pegadas arriba y abajo del origen y una torre en el medio. Ningun hueco
  // sirve: se dibuja igual y avisa
  const tower = R(328, -2000, 628, 2000);
  const above = R(0, -2000, 300, -8);
  const below = R(0, 128, 300, 2000);
  const C1 = R(656, 0, 956, 120);
  const d = topRoute(A1, C1, 150, 806, [A1, C1, tower, above, below]);
  assert.ok(!d.clean);
  assert.ok(d.d.startsWith("M 150"), d.d);
  const rects = new Map([["a", A1], ["c", C1], ["t", tower], ["u", above], ["d", below]]);
  const [s] = computeSegs({ rects, anchors: rects, strips: [], boardWidth: 1000, links: [], rules: [rule({ id: "r", from: "a", to: "c" })], fmt });
  assert.equal(s.dim, true);
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

// --- carriles, techo de la columna y area util ------------------------------------------------

/** tablero como el real a 1440x900: encabezado hasta y=92 y la primera tarjeta en y=102 */
const BANDS: Band[] = [
  { l: 16, r: 316, t: 92, b: 578 },
  { l: 344, r: 644, t: 92, b: 578 },
  { l: 672, r: 972, t: 92, b: 578 },
];
const CA = R(28, 102, 304, 375);
const CB = R(356, 102, 632, 270);
const CC = R(684, 102, 960, 270);
/** los tres carriles de la misma columna, con el titulo a y=40 y tres filas de tarjetas */
const ROWS: Band[] = [{ l: 16, r: 316, t: 40, b: 600 }];

test("slotAt, allowed y runAllowed: debajo del encabezado y dentro de las columnas", () => {
  assert.deepEqual(slotAt([], 999), [-Infinity, Infinity]); // sin columnas medidas, sin restriccion
  assert.deepEqual(slotAt(BANDS, 100), [92, 578]); // adentro de una columna
  assert.deepEqual(slotAt(BANDS, 330), [92, 578]); // en el canal entre dos: manda la mas baja
  assert.deepEqual(slotAt(BANDS, 5), [Infinity, -Infinity]); // el padding del tablero: nada
  assert.deepEqual(slotAt(BANDS, 990), [Infinity, -Infinity]);
  assert.ok(!allowed(BANDS, 100, 80), "por encima del encabezado");
  assert.ok(allowed(BANDS, 100, 92), "el borde del encabezado ya vale");
  assert.ok(!allowed(BANDS, 1, 200), "fuera de toda columna");
  assert.ok(runAllowed(BANDS, 100, 900, 400));
  assert.ok(!runAllowed(BANDS, 100, 900, 80), "cruzaria los encabezados");
  assert.ok(!runAllowed(BANDS, 5, 900, 400), "arranca en el padding del tablero");
  assert.ok(runAllowed([], 5, 900, 80), "sin columnas medidas, todo vale");
});

test("freeLanes: uno arriba, uno entre filas y uno abajo, apoyados en las tarjetas", () => {
  const cards = [R(28, 102, 304, 200), R(28, 240, 304, 320)];
  const ls = freeLanes(ROWS, cards);
  assert.equal(ls.length, 3);
  assert.deepEqual(ls[0], { y: 102 - LANE_H / 2, room: 62, t: 40, b: 102 }); // arriba: se apoya en la primera fila
  assert.deepEqual(ls[1], { y: 220, room: 40, t: 200, b: 240 }); // entre las dos filas: al medio
  assert.deepEqual(ls[2], { y: 320 + LANE_H / 2, room: 280, t: 320, b: 600 }); // abajo: se apoya en la ultima
  // franja mas fina que el carril: se usa igual, centrada (el aire que hay hoy sin reservar nada)
  const tight = freeLanes(BANDS, [CA, CB, CC]);
  assert.deepEqual(tight[0], { y: 97, room: 10, t: 92, b: 102 });
  assert.ok(tight[0].room < 2 * LANE_CLEAR, "10 px no alcanzan para un carril");
  // sin columnas medidas, arriba y abajo quedan a medio carril de la primera y la ultima fila
  assert.deepEqual(freeLanes([], cards).map((l) => l.y), [102 - LANE_H / 2, 220, 320 + LANE_H / 2]);
  assert.deepEqual(freeLanes(ROWS, []), []);
});

/** puntos muestreados de un path, sea cubica ("C") u ortogonal (tramos "L"/"Q") */
function pathPts(d: string, n = 60): Pt[] {
  if (d.includes(" C ")) {
    const p = cubicPts(d);
    return Array.from({ length: n + 1 }, (_, i) => cubicAt(...p, i / n));
  }
  const nums = d.match(/-?\d+(\.\d+)?/g)!.map(Number);
  const corners: Pt[] = [];
  for (let i = 0; i + 1 < nums.length; i += 2) corners.push([nums[i], nums[i + 1]]);
  const out: Pt[] = [];
  for (let i = 0; i + 1 < corners.length; i++) {
    for (let k = 0; k <= n; k++) {
      const t = k / n;
      out.push([corners[i][0] + (corners[i + 1][0] - corners[i][0]) * t, corners[i][1] + (corners[i + 1][1] - corners[i][1]) * t]);
    }
  }
  return out;
}

/** y de la corrida horizontal de un camino ortogonal: el tramo largo del medio */
function runY(d: string): number {
  const pts = pathPts(d, 8);
  let best = 0;
  let bestLen = -1;
  for (let i = 1; i < pts.length; i++) {
    const len = Math.abs(pts[i][0] - pts[i - 1][0]);
    if (Math.abs(pts[i][1] - pts[i - 1][1]) < 0.01 && len > bestLen) {
      bestLen = len;
      best = pts[i][1];
    }
  }
  return best;
}

/** ningun punto del camino ni el glifo quedan por encima del techo, fuera de las columnas o adentro
 *  de una tarjeta que no sea una de las dos puntas */
function checkSeg(s: Seg, bands: Band[], cards: Rect[]) {
  const others = cards.filter((c) => c !== s.ends[0] && c !== s.ends[1]);
  const left = Math.min(...bands.map((b) => b.l));
  const right = Math.max(...bands.map((b) => b.r));
  for (const [x, y] of pathPts(s.d)) {
    assert.ok(y >= Math.max(...bands.map((b) => b.t)) - 0.01, `(${x.toFixed(0)},${y.toFixed(0)}) por encima del encabezado`);
    assert.ok(x >= left - 0.01 && x <= right + 0.01, `(${x.toFixed(0)},${y.toFixed(0)}) fuera de las columnas`);
    assert.ok(!inside(others, x, y), `(${x.toFixed(0)},${y.toFixed(0)}) adentro de una tercera tarjeta`);
  }
  assert.ok(allowed(bands, s.x, s.y), `glifo (${s.x}, ${s.y}) fuera del area util`);
  assert.ok(!inside(cards, s.x, s.y), `glifo (${s.x}, ${s.y}) adentro de una tarjeta`);
}

test("sin carril reservado arriba, la flecha baja: no cruza el titulo ni roza una tarjeta", () => {
  const rects = new Map([["a", CA], ["b", CB], ["c", CC]]);
  const [s] = computeSegs({ rects, anchors: rects, strips: [], boardWidth: 1000, bands: BANDS, links: [], rules: [rule({ id: "r", from: "a", to: "c" })], fmt });
  assert.equal(s.lane, 375 + LANE_H / 2);
  assert.ok(!s.dim);
  // arriba solo hay 10 px entre el encabezado y la primera fila: el carril de abajo, que si tiene
  // aire, gana aunque el camino sea mas largo
  assert.equal(s.y, 375 + LANE_H / 2);
  checkSeg(s, BANDS, [CA, CB, CC]);
  // el glifo queda centrado en el carril: medio carril por debajo de la fila de tarjetas
  assert.equal(s.y - 375, LANE_H / 2);
});

test("con el carril reservado arriba, la flecha cruza por arriba y no toca el encabezado", () => {
  // el tablero reservo el carril: la primera fila arranca 40 px debajo del encabezado
  const A = R(28, 132, 304, 405);
  const B = R(356, 132, 632, 300);
  const C = R(684, 132, 960, 300);
  const rects = new Map([["a", A], ["b", B], ["c", C]]);
  const [s] = computeSegs({ rects, anchors: rects, strips: [], boardWidth: 1000, bands: BANDS, links: [], rules: [rule({ id: "r", from: "a", to: "c" })], fmt });
  assert.equal(s.lane, 132 - LANE_H / 2);
  assert.ok(!s.dim);
  assert.equal(s.y, 132 - LANE_H / 2, "corre por el carril de arriba, apoyado en la primera fila");
  assert.ok(s.y > 92, "por debajo del encabezado");
  checkSeg(s, BANDS, [A, B, C]);
});

test("tracks: pistas paralelas centradas en el carril, siempre con aire, comprimidas si no entran", () => {
  const ancho: Lane = { y: 400, room: 200, t: 300, b: 500 };
  assert.deepEqual(tracks(1, ancho), [400]); // una sola: por el medio del carril
  assert.deepEqual(tracks(4, ancho), [389.5, 396.5, 403.5, 410.5]); // 7 px entre pistas, centradas
  assert.deepEqual(tracks(2, ancho), [396.5, 403.5]);
  // el carril se apoya arriba y las pistas no se salen de la franja: nunca a menos de LANE_CLEAR
  const apoyado: Lane = { y: 314, room: 200, t: 300, b: 500 };
  const ys = tracks(4, apoyado);
  assert.ok(ys[0] >= 300 + LANE_CLEAR, `primera pista en ${ys[0]}`);
  assert.ok(ys[3] <= 500 - LANE_CLEAR);
  // franja angosta: se comprimen en vez de desbordar
  const angosto: Lane = { y: 101, room: 18, t: 92, b: 110 };
  const cuatro = tracks(4, angosto);
  assert.equal(cuatro.length, 4);
  assert.ok(cuatro[0] >= 100 && cuatro[3] <= 102, `comprimidas: ${cuatro.join(", ")}`);
  assert.ok(cuatro[3] - cuatro[0] <= 3 * TRACK_GAP);
  // sin lugar ni para el aire minimo: todas en la misma y, que es lo que hay
  assert.deepEqual(tracks(3, { y: 50, room: 4, t: 48, b: 52 }), [50, 50, 50]);
});

test("laneHeight: el carril crece con lo que lleva, con tope", () => {
  assert.equal(laneHeight(1), 2 * LANE_CLEAR + TRACK_GAP);
  assert.equal(laneHeight(4), 2 * LANE_CLEAR + 4 * TRACK_GAP);
  assert.equal(laneHeight(40), LANE_MAX);
});

test("cuatro flechas en el mismo carril van en cuatro pistas, no encimadas", () => {
  const CD = R(1012, 102, 1288, 270);
  const bands: Band[] = [...BANDS, { l: 1000, r: 1300, t: 92, b: 578 }];
  const rects = new Map([["a", CA], ["b", CB], ["c", CC], ["d", CD]]);
  const rules = [
    rule({ id: "r1", from: "a", to: "c" }),
    rule({ id: "r2", from: "a", to: "d" }),
    rule({ id: "r3", from: "b", to: "d" }),
    rule({ id: "r4", from: "c", to: "a" }),
  ];
  const segs = computeSegs({ rects, anchors: rects, strips: [], boardWidth: 1320, bands, links: [], rules, fmt });
  assert.equal(segs.length, 4);
  assert.ok(segs.every((s) => s.lane !== undefined), "las cuatro cruzan una tercera tarjeta: van por carril");
  const ys = segs.map((s) => runY(s.d));
  assert.equal(new Set(ys).size, 4, `cuatro corridas distintas, no una sola barra: ${ys.join(", ")}`);
  // cada carril reparte a los suyos en pistas separadas; dos carriles distintos ya no se pisan
  const porCarril = new Map<number, number[]>();
  segs.forEach((sg) => porCarril.set(sg.lane!, [...(porCarril.get(sg.lane!) ?? []), runY(sg.d)]));
  assert.ok([...porCarril.values()].some((g) => g.length > 1), "algun carril lleva mas de una flecha");
  for (const g of porCarril.values()) {
    const orden = [...g].sort((a, b) => a - b);
    for (let i = 1; i < orden.length; i++) assert.ok(orden[i] - orden[i - 1] >= TRACK_GAP - 0.01, `pistas a ${orden[i] - orden[i - 1]} px`);
  }
  for (const s of segs) checkSeg(s, bands, [CA, CB, CC, CD]);
  // el orden es estable: los mismos datos dan las mismas pistas
  const otra = computeSegs({ rects, anchors: rects, strips: [], boardWidth: 1320, bands, links: [], rules, fmt });
  assert.deepEqual(otra.map((s) => runY(s.d)), ys);
});

test("el arco de la misma columna no se mete en el padding del tablero", () => {
  // columna pegada al borde izquierdo del tablero: sin columnas medidas la panza se iba a x=8,
  // fuera de toda columna (el glifo aparecia suelto arriba a la izquierda)
  const cols = groupColumns([R(28, 76, 304, 196)]);
  assert.equal(sideArc(cols, [{ l: 316, r: 344 }], 400, 0).x, 8);
  const band: Band[] = [{ l: 16, r: 316, t: 40, b: 600 }];
  const arc = sideArc(cols, [{ l: 316, r: 344 }], 400, 0, band);
  assert.deepEqual(arc, { side: "r", x: 314 });
  assert.ok(arc.x >= band[0].l && arc.x <= band[0].r);
  const a1 = R(28, 76, 304, 196);
  const a2 = R(28, 216, 304, 336);
  const rects = new Map([["a1", a1], ["a2", a2]]);
  const [s] = computeSegs({ rects, anchors: rects, strips: [{ l: 316, r: 344 }], boardWidth: 400, bands: band, links: [], rules: [rule({ id: "r", from: "a1", to: "a2" })], fmt });
  for (const [x] of pathPts(s.d)) assert.ok(x >= 16 && x <= 316, `x=${x.toFixed(1)} fuera de la columna`);
  assert.ok(s.x >= 16 && s.x <= 316, `glifo en x=${s.x}`);
});

if (failed) {
  console.log(`\n${failed} test(s) fallaron`);
  throw new Error(`${failed} test(s) fallaron`);
}
console.log("\ntodo ok");
