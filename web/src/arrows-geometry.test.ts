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
import { GLYPH_HIT, LANE_CLEAR, LANE_H, LANE_MAX, TRACK_GAP, allowed, buildItems, channelX, clearance, colOf, computeSegs, cubic, cubicAt, cubicHits, cut, ejectGlyph, freeAt, freeLanes, groupColumns, inside, laneHeight, layoutEnds, periodLabel, runAllowed, segHits, sideArc, slotAt, topRoute, tracks, type Band, type Formatters, type Lane, type Pt, type Rect, type Seg } from "./arrows-geometry.ts";
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
/** reloj fijo para los tests: unos minutos despues de los links de prueba, que son de esa fecha */
const AHORA = new Date("2026-09-05T12:05:00Z").getTime();
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
    link({ id: "1", from: "a", to: "b", ts: "2026-09-05T12:00:00Z", text: "primero" }),
    link({ id: "2", from: "a", to: "b", ts: "2026-09-05T12:03:00Z", text: "ultimo" }),
    link({ id: "3", from: "b", to: "a", ts: "2026-09-05T12:02:00Z", text: "vuelta" }),
    link({ id: "4", from: "a", to: "b", ts: "2026-09-05T09:00:00Z", kind: "native", text: "nativo" }),
    link({ id: "5", from: "a", to: "zzz", ts: "2026-09-05T09:00:00Z", text: "destino sin tarjeta" }),
  ];
  const items = buildItems(links, [], anchors, fmt, AHORA);
  assert.equal(items.length, 3);
  assert.deepEqual(items[0].ids, ["2", "1"]); // mas nuevo primero
  assert.equal(items[0].kind, "link");
  assert.equal(items[0].glyph, "×2");
  // el titulo es de una linea y dice que hace el click; lo que es la flecha va en `desc`, que se
  // muestra mientras esta seleccionada y siempre termina diciendo que hace el doble click
  assert.equal(items[0].title, "2 envíos de n(a) a n(b), el último hace ago(2026-09-05T12:03:00Z) · click para seleccionarla");
  assert.equal(items[0].desc, "n(a) le mandó 2 mensajes a n(b). El último, hace ago(2026-09-05T12:03:00Z). Doble click para verlos o mandar de nuevo.");
  assert.ok(items.every((it) => !it.title.includes("\n")), "el title va en una linea");
  assert.ok(items.every((it) => /Doble click para /.test(it.desc)), "la descripcion enseña el gesto");
  assert.equal(items[1].glyph, "↪");
  assert.equal(items[1].title, "envío de n(b) a n(a), hace ago(2026-09-05T12:02:00Z) · click para seleccionarla");
  assert.equal(items[2].kind, "native");
  assert.equal(items[2].glyph, "⇄");
  assert.match(items[2].title, /^canal nativo entre n\(a\) y n\(b\), abierto hace /);
  assert.match(items[2].desc, /^n\(a\) y n\(b\) tienen abierto el canal nativo desde hace /);
  // `old` y `fresh` se fueron: el primero nunca era true y el segundo nunca se seteaba
});

test("buildItems: varios envios se cuentan en la descripcion; los textos se leen en la vista", () => {
  const anchors = new Map([["a", A1], ["b", B1]]);
  const links = Array.from({ length: 7 }, (_, i) => link({ id: `l${i}`, from: "a", to: "b", ts: `2026-09-05T12:0${i}:00Z`, text: "x".repeat(100) }));
  const [it] = buildItems(links, [], anchors, fmt, AHORA);
  assert.equal(it.glyph, "×7");
  assert.equal(it.desc, "n(a) le mandó 7 mensajes a n(b). El último, hace ago(2026-09-05T12:06:00Z). Doble click para verlos o mandar de nuevo.");
  assert.equal(cut("x".repeat(100)), `${"x".repeat(90)}…`);
});

test("buildItems dibuja las reglas activas con los dos extremos en el tablero, y las reflexivas como bucle", () => {
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
  // "auto" (sin origen, la programa el server) y "self" (mismo origen y destino) ahora se dibujan
  // como bucle sobre su propia tarjeta; "off" (deshabilitada) y "lost" (destino que no esta) no
  assert.deepEqual(items.map((i) => i.ids[0]), ["r1", "r2", "r3", "r4", "auto", "self"]);
  const auto = items[4];
  assert.equal(auto.from, auto.to);
  assert.equal(auto.desc, "Cada vez que n(b) cierre un turno, su respuesta se manda a sí misma. Una sola vez. Doble click para editarla.");
  assert.equal(items[5].from, "a");
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
  // sirve: se dibuja igual y avisa. El tapon de arriba y el de abajo llegan hasta la torre a
  // proposito: si dejaran abierto el canal que hay entre medio, la flecha se metaria por ahi y
  // saldria de costado, que es justo lo que tiene que poder hacer cuando el canal existe
  const tower = R(328, -2000, 628, 2000);
  const above = R(0, -2000, 628, -8);
  const below = R(0, 128, 628, 2000);
  const C1 = R(656, 0, 956, 120);
  const d = topRoute(A1, C1, 150, 806, [A1, C1, tower, above, below]);
  assert.ok(!d.clean);
  assert.ok(d.d.startsWith("M 150"), d.d);
  const rects = new Map([["a", A1], ["c", C1], ["t", tower], ["u", above], ["d", below]]);
  const [s] = computeSegs({ rects, anchors: rects, strips: [], boardWidth: 1000, links: [], rules: [rule({ id: "r", from: "a", to: "c" })], fmt });
  assert.equal(s.dim, true);
});

test("un envio de mas de 10 minutos se va del tablero; el canal nativo y las reglas se quedan", () => {
  const anchors = new Map([["a", A1], ["b", B1]]);
  const viejo = new Date(AHORA - 11 * 60_000).toISOString();
  const fresco = new Date(AHORA - 2 * 60_000).toISOString();
  const items = (ls: Link[], rs: Rule[] = []) => buildItems(ls, rs, anchors, fmt, AHORA).map((i) => i.ids[0]);
  assert.deepEqual(items([link({ id: "v", from: "a", to: "b", ts: viejo })]), []);
  assert.deepEqual(items([link({ id: "f", from: "a", to: "b", ts: fresco })]), ["f"]);
  // el canal nativo no caduca: es un vinculo abierto, no un hecho puntual
  assert.deepEqual(items([link({ id: "n", from: "a", to: "b", ts: viejo, kind: "native" })]), ["n"]);
  // una regla pendiente tampoco: todavia no paso
  assert.deepEqual(items([], [rule({ id: "r", from: "a", to: "b" })]), ["r"]);
  // con uno viejo y uno fresco del mismo par, la flecha queda y los cuenta a los dos
  const dos = buildItems([link({ id: "v", from: "a", to: "b", ts: viejo }), link({ id: "f", from: "a", to: "b", ts: fresco })], [], anchors, fmt, AHORA);
  assert.equal(dos.length, 1);
  assert.equal(dos[0].glyph, "×2");
});

test("computeSegs es puro: no muta la entrada y repite la salida", () => {
  const rects = new Map([["a", A1], ["b", B1], ["a2", A2]]);
  const links = [link({ id: "1", from: "a", to: "b", ts: new Date(Date.now() - 60_000).toISOString() }), link({ id: "2", from: "a", to: "b", ts: new Date(Date.now() - 30_000).toISOString() })];
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
  assert.deepEqual(ls[2], { y: 320 + LANE_H / 2, room: 280, t: 320, b: 600, under: true }); // abajo: se apoya en la ultima
  // franja mas fina que el carril: se usa igual, centrada (el aire que hay hoy sin reservar nada)
  const tight = freeLanes(BANDS, [CA, CB, CC]);
  assert.deepEqual(tight[0], { y: 97, room: 10, t: 92, b: 102 });
  assert.equal(tight[0].room, 2 * LANE_CLEAR, "10 px son justo un carril: una pista con su aire");
  const finito = freeLanes(BANDS.map((b) => ({ ...b, t: 96 })), [CA, CB, CC]);
  assert.ok(finito[0].room < 2 * LANE_CLEAR, "6 px no alcanzan ni para el aire de una pista");
  // el ultimo carril es el de abajo de todo, y viene marcado: es el que la flecha usa ultimo
  assert.equal(ls[2].under, true);
  assert.equal(ls[0].under, undefined);
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

test("sin carril reservado arriba la flecha igual va por arriba: abajo de todo es ultimo recurso", () => {
  const rects = new Map([["a", CA], ["b", CB], ["c", CC]]);
  const [s] = computeSegs({ rects, anchors: rects, strips: [], boardWidth: 1000, bands: BANDS, links: [], rules: [rule({ id: "r", from: "a", to: "c" })], fmt });
  // arriba hay 10 px entre el encabezado y la primera fila: justo un carril. El de abajo de todo
  // tiene mas aire pero deja la corrida y el glifo por debajo de la ultima tarjeta, en el vacio,
  // asi que pierde contra cualquier carril que este entre las tarjetas
  assert.equal(s.lane, 97);
  assert.equal(s.y, 97);
  assert.ok(!s.dim);
  checkSeg(s, BANDS, [CA, CB, CC]);
  assert.ok(s.y > Math.max(...BANDS.map((b) => b.t)), "por debajo del encabezado");
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
  assert.deepEqual(tracks(4, ancho), [392.5, 397.5, 402.5, 407.5]); // TRACK_GAP entre pistas, centradas
  assert.deepEqual(tracks(2, ancho), [397.5, 402.5]);
  // el carril se apoya arriba y las pistas no se salen de la franja: nunca a menos de LANE_CLEAR
  const apoyado: Lane = { y: 314, room: 200, t: 300, b: 500 };
  const ys = tracks(4, apoyado);
  assert.ok(ys[0] >= 300 + LANE_CLEAR, `primera pista en ${ys[0]}`);
  assert.ok(ys[3] <= 500 - LANE_CLEAR);
  // franja angosta: se comprimen en vez de desbordar
  const angosto: Lane = { y: 101, room: 18, t: 92, b: 110 };
  const cuatro = tracks(4, angosto);
  assert.equal(cuatro.length, 4);
  assert.ok(cuatro[0] >= 97 && cuatro[3] <= 105, `comprimidas: ${cuatro.join(", ")}`);
  assert.ok(cuatro[3] - cuatro[0] <= 3 * TRACK_GAP);
  // sin lugar ni para el aire minimo: todas en la misma y, que es lo que hay
  assert.deepEqual(tracks(3, { y: 50, room: 4, t: 48, b: 52 }), [50, 50, 50]);
});

test("laneHeight: el carril crece con lo que lleva, con tope", () => {
  // una sola pista no necesita ninguna separacion: solo el aire de los dos costados
  assert.equal(laneHeight(1), 2 * LANE_CLEAR);
  assert.equal(laneHeight(4), 2 * LANE_CLEAR + 3 * TRACK_GAP);
  assert.equal(laneHeight(40), LANE_MAX);
});

test("cuatro flechas en el mismo carril van en cuatro pistas, no encimadas", () => {
  // el tablero ya reservo el carril de arriba (la primera fila arranca 40 px debajo del
  // encabezado): sin esa reserva no hay franja donde repartir cuatro pistas y se encimarian
  const A4 = R(28, 132, 304, 405);
  const B4 = R(356, 132, 632, 300);
  const C4 = R(684, 132, 960, 300);
  const CD = R(1012, 132, 1288, 300);
  const bands: Band[] = [...BANDS, { l: 1000, r: 1300, t: 92, b: 578 }];
  const rects = new Map([["a", A4], ["b", B4], ["c", C4], ["d", CD]]);
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
  for (const s of segs) checkSeg(s, bands, [A4, B4, C4, CD]);
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

test("el bucle sale del costado, baja LOOP_SPAN y se va a la izquierda si no entra a la derecha", () => {
  // una regla de una tarjeta hacia si misma: la panza a 20 px del borde, del techo + 16 al + 42
  const r = R(0, 0, 300, 120);
  const rects = new Map([["a", r]]);
  const solo = rule({ id: "r1", from: null, to: "a", text: "seguir" });
  const [s] = computeSegs({ rects, anchors: rects, strips: [], boardWidth: 700, links: [], rules: [solo], fmt });
  assert.equal(s.d, "M 300 16 C 328 16 328 42 300 42");
  assert.deepEqual([s.x, s.y], [320, 29]);
  assert.deepEqual(s.ends, [r, r]);
  // el tablero termina justo al lado de la tarjeta: el bucle se dibuja del otro lado
  const [z] = computeSegs({ rects, anchors: rects, strips: [], boardWidth: 320, links: [], rules: [solo], fmt });
  assert.equal(z.d, "M 0 16 C -28 16 -28 42 0 42");
  assert.deepEqual([z.x, z.y], [-20, 29]);
});

test("si bajar derecho cruzaria la tarjeta de encima, la flecha baja por el canal y entra de costado", () => {
  // tres columnas; la del medio es una sola tarjeta alta, asi que la S la atraviesa y el item va
  // por arriba. Para llegar a la de abajo de la tercera no hay ninguna x que esquive a la que tiene
  // encima (ocupa toda la columna), ni yendo por arriba ni por abajo: antes se dibujaba igual,
  // apagada, metiendose 140 px adentro de esa tarjeta
  const a1 = R(0, 60, 300, 200);
  const a2 = R(0, 215, 300, 380);
  const bb = R(335, 60, 635, 380);
  const c1 = R(670, 60, 970, 200);
  const c2 = R(670, 215, 970, 380);
  const rects = new Map([["a1", a1], ["a2", a2], ["bb", bb], ["c1", c1], ["c2", c2]]);
  const bands: Band[] = [{ l: -10, r: 980, t: 30, b: 430 }];
  const [s] = computeSegs({ rects, anchors: rects, strips: [], bands, boardWidth: 1000, links: [], rules: [rule({ id: "r", from: "a1", to: "c2" })], fmt });
  assert.equal(s.dim, undefined, "hay camino limpio: no tiene que quedar apagada");
  const otras = [a2, bb, c1];
  for (const [x, y] of pathPts(s.d)) assert.ok(!inside(otras, x, y), `(${x.toFixed(0)},${y.toFixed(0)}) adentro de otra tarjeta`);
  // el ultimo tramo entra en horizontal por el costado del destino, no por su borde de arriba
  const pts = pathPts(s.d, 8);
  const fin = pts[pts.length - 1];
  const antes = pts[pts.length - 2];
  assert.ok(Math.abs(fin[0] - c2.l) < 0.01 && Math.abs(fin[1] - (c2.t + c2.b) / 2) < 0.01, `entra en (${fin[0]}, ${fin[1]})`);
  assert.ok(Math.abs(fin[1] - antes[1]) < 0.01, "el ultimo tramo es horizontal");
  // y baja por el canal entre la segunda y la tercera columna, no por encima de una tarjeta
  assert.ok(pathPts(s.d).some(([x, y]) => Math.abs(x - (bb.r + c1.l) / 2) < 0.01 && y > 200), "baja por el canal");
});

/** Tablero de prueba parecido al real: tres columnas de dos filas, una tira colapsada a la derecha
 *  y una flecha por cada par ordenado de anclas (envio, canal nativo y regla), mas los bucles. Es
 *  la cama de las dos invariantes que se rompieron una vez: puntas sueltas y glifos en el vacio. */
function tableroDePrueba() {
  const cards: Record<string, Rect> = {
    a1: R(28, 132, 304, 300), a2: R(28, 315, 304, 470),
    b1: R(332, 132, 608, 300), b2: R(332, 315, 608, 520),
    c1: R(636, 132, 912, 300), c2: R(636, 315, 912, 430),
  };
  const bands: Band[] = [
    { l: 16, r: 316, t: 92, b: 560 },
    { l: 320, r: 620, t: 92, b: 560 },
    { l: 624, r: 924, t: 92, b: 560 },
    { l: 932, r: 966, t: 12, b: 560 },
  ];
  const rects = new Map(Object.entries(cards));
  const anchors = new Map([...rects, ["z", R(938, 30, 960, 150)]]); // sesion sin tarjeta, en la tira
  return { rects, anchors, bands, strips: [{ l: 932, r: 966 }], boardWidth: 980 };
}

/** los segmentos de todas las flechas posibles del tablero de prueba */
function todasLasFlechas() {
  const { rects, anchors, bands, strips, boardWidth } = tableroDePrueba();
  const ids = [...anchors.keys()];
  const links: Link[] = [];
  const rules: Rule[] = [];
  let n = 0;
  for (const from of ids) {
    for (const to of ids) {
      if (from === to) continue;
      links.push(link({ id: `l${n}`, from, to, ts: new Date(AHORA - 60_000).toISOString() }));
      links.push({ ...link({ id: `n${n}`, from, to, ts: new Date(AHORA - 60_000).toISOString() }), kind: "native" });
      rules.push(rule({ id: `r${n}`, from, to }));
      n++;
    }
    rules.push(rule({ id: `b${from}`, from, to: from })); // bucle
  }
  return { segs: computeSegs({ rects, anchors, strips, boardWidth, bands, links, rules, fmt, now: AHORA }), anchors, bands };
}

test("ninguna punta suelta: las dos puntas de cada camino caen sobre el borde de su ancla", () => {
  const { segs } = todasLasFlechas();
  assert.ok(segs.length > 100, `${segs.length} flechas`);
  /** el punto esta sobre uno de los cuatro bordes del rect (no adentro ni afuera) */
  const enElBorde = (c: Rect, [x, y]: Pt, tol = 0.6) =>
    x >= c.l - tol && x <= c.r + tol && y >= c.t - tol && y <= c.b + tol &&
    Math.min(Math.abs(x - c.l), Math.abs(x - c.r), Math.abs(y - c.t), Math.abs(y - c.b)) <= tol;
  for (const s of segs) {
    const pts = pathPts(s.d);
    const [p, q] = [pts[0], pts[pts.length - 1]];
    assert.ok(enElBorde(s.ends[0], p), `${s.ids[0]}: sale de (${p}) y su ancla es ${JSON.stringify(s.ends[0])}`);
    assert.ok(enElBorde(s.ends[1], q), `${s.ids[0]}: entra en (${q}) y su ancla es ${JSON.stringify(s.ends[1])}`);
  }
});

test("ningun glifo en el vacio: ni por debajo de la ultima ancla ni por encima del techo", () => {
  const { segs, anchors, bands } = todasLasFlechas();
  const piso = Math.max(...[...anchors.values()].map((r) => r.b));
  const techo = Math.min(...bands.map((b) => b.t));
  for (const s of segs) {
    assert.ok(s.y <= piso, `glifo de ${s.ids[0]} en (${s.x.toFixed(0)},${s.y.toFixed(0)}), por debajo de todo (piso ${piso})`);
    assert.ok(s.y >= techo, `glifo de ${s.ids[0]} en (${s.x.toFixed(0)},${s.y.toFixed(0)}), por encima del techo (${techo})`);
    assert.ok(allowed(bands, s.x, s.y), `glifo de ${s.ids[0]} fuera del area util`);
  }
});

test("el area sensible del glifo: se recorta contra la tarjeta, con un piso, y nunca supera el dibujo", () => {
  const a1 = R(0, 60, 300, 200);
  const a2 = R(0, 215, 300, 380);
  const b1 = R(335, 60, 635, 200);
  const b2 = R(335, 215, 635, 380);
  const rects = new Map([["a1", a1], ["a2", a2], ["b1", b1], ["b2", b2]]);
  const cards = [a1, a2, b1, b2];
  const bands: Band[] = [{ l: -10, r: 645, t: 30, b: 430 }];
  const ids = [...rects.keys()];
  const rules = ids.flatMap((from, i) => ids.filter((to) => to !== from).map((to, k) => rule({ id: `r${i}${k}`, from, to })));
  const segs = computeSegs({ rects, anchors: rects, strips: [], bands, boardWidth: 700, links: [], rules, fmt });
  assert.ok(segs.length >= 12);
  for (const s of segs) {
    const libre = clearance(cards, s.x, s.y);
    assert.ok(s.hit !== undefined, "computeSegs le pone hit a todos");
    assert.ok(s.hit! >= 0 && s.hit! <= GLYPH_HIT, `hit ${s.hit} fuera de [0, ${GLYPH_HIT}]`);
    // el recorte contra la tarjeta vale mientras deje un blanco usable; con menos que el piso
    // manda el piso, que igual es menor que los 11 px de radio del circulo que se ve, asi que el
    // area sensible nunca se pasa de lo que el usuario ve pintado como glifo
    assert.ok(s.hit! <= Math.max(8, libre) + 1e-9, `hit ${s.hit} se pasa de lo libre (${libre.toFixed(1)}) y del piso`);
    assert.ok(s.hit! >= Math.min(8, libre) - 1e-9, `hit ${s.hit} por debajo del piso con ${libre.toFixed(1)} libres`);
  }
});

if (failed) {
  console.log(`\n${failed} test(s) fallaron`);
  throw new Error(`${failed} test(s) fallaron`);
}
console.log("\ntodo ok");
