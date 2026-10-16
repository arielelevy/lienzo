// Fig 1 del lienzo: el tablero como una coordinadora.
import { k, tubePieces, tubeSvg, write } from "../kit.mjs";

const WIDTH = 640;
const HEIGHT = 440;

// Mundo: x a lo largo del panel, y hacia el operador, z arriba.
const DESK = { x: -150, y: -60, w: 300, d: 132, r: 6 };
const SHELF = 44;
const FOOT_H = 6;
const PANEL = { x: -146, y: -60, w: 292, d: 14, r: 2 };
const FACE = PANEL.y + PANEL.d; // -46
const PANEL_TOP = 166;
const COLS = [-112, -74, -36, 36, 74, 112];
const ROWS = [114, 74];
const BUSH = 2.6; // lo que sobresale el buje del jack
const PLUG = 9.5;
const BOOT = 3;

// Sesiones: [columna, fila]. C coordina, A trabaja en la misma PC, D le habla a B en la otra PC.
const JACK = { C: [0, 0], A: [2, 1], D: [1, 1], B: [4, 0] };
const LIT = "A"; // permiso esperando respuesta
const at3 = ([c, r]) => [COLS[c], FACE, ROWS[r]];
const TIMER = { x: 104, y: 36, r: 21, h: 8 };
const WAITED = 23; // segundos de los 60 que espera el hook

const P = k.fitProjection(
  [...k.boxCorners(DESK, -FOOT_H, SHELF), ...k.boxCorners({ ...PANEL, x: -150, w: 300, y: -62, d: 18 }, SHELF, PANEL_TOP + 6)],
  WIDTH,
  HEIGHT,
  { pad: 26, azimuth: 58, elevation: 32 },
);

const at = (p) => k.iso(p, P);
const S = (paths, style) => k.solidSvg(paths, style);
const L = (d, style) => k.lineSvg(d, style);
const D = (points, style) => k.dotsSvg(points, style);
const depth = (p) => k.depthOf(p, P);

function cabinet() {
  const out = [`<path class="iso-halo" d="${k.haloOf(DESK, -FOOT_H, SHELF + FOOT_H, P)}"/>`];
  const feet = k.corners(DESK, 14).sort((a, b) => depth([...a, 0]) - depth([...b, 0]));
  for (const [x, y] of feet) {
    out.push(S(k.cylinder(x, y, 6, -FOOT_H, 1.4, P, 24), { tone: "lo" }));
    out.push(S(k.cylinder(x, y, 4.6, -FOOT_H + 1.4, FOOT_H - 1.4, P, 24), { tone: "mid" }));
  }
  // Cuerpo con una costura a media altura y el canto del estante encima.
  out.push(S(k.slabOf(DESK, 0, SHELF - 4, P, 8, 0.6), { tone: "mid", inner: L(k.sideSeam(DESK, 16, P), { tone: "faint" }) }));
  const lip = k.insetPlan(DESK, -1.5);
  out.push(S(k.slabOf(lip, SHELF - 4, 4, P, 8, 1.2), { tone: "mid" }));
  // Placa del fabricante en el frente, con sus tres renglones.
  const plateY = DESK.y + DESK.d - 1.5;
  const badge = { x: -24, y: plateY + 1.5, w: 48, d: 1, r: 0.5 };
  out.push(S(k.slabOf(badge, 22, 12, P, 2), { tone: "lo", crease: "none" }));
  for (const z of [31, 28, 25]) out.push(L(k.segment([badge.x + 5, badge.y + 1, z], [badge.x + (z === 25 ? 30 : 43), badge.y + 1, z], P), { tone: "faint", free: true }));
  out.push(D([at([badge.x + 2.2, badge.y + 1, 32]), at([badge.x + badge.w - 2.2, badge.y + 1, 32]), at([badge.x + 2.2, badge.y + 1, 24]), at([badge.x + badge.w - 2.2, badge.y + 1, 24])], { size: 0.4 }));
  return out.join("");
}

function shelfTop() {
  const out = [];
  const top = { x: DESK.x + 6, y: FACE + 4, w: DESK.w - 12, d: DESK.y + DESK.d - FACE - 10, r: 3 };
  out.push(L(k.planOutline(top, SHELF, P), { tone: "faint" }));
  const screws = k.corners(top, 5);
  out.push(L(screws.map(([x, y]) => k.ring(x, y, 1.8, SHELF, P, 14)).join(""), { tone: "lo" }));
  out.push(D(screws.map(([x, y]) => at([x, y, SHELF])), { size: 0.45 }));
  // Regla de minutos a lo largo del frente del estante.
  const strip = { x: -126, y: DESK.y + DESK.d - 14, w: 180, d: 6, r: 1 };
  out.push(S(k.slabOf(strip, SHELF, 0.6, P, 3), { tone: "lo", crease: "none" }));
  const ticks = k.topTicks(strip.x + 3, strip.x + strip.w - 3, 4, 5, strip.y + 0.6, SHELF + 0.6, [1.8, 3.4], P);
  out.push(L(ticks.minor, { tone: "lo" }), L(ticks.major, { tone: "mid" }));
  return out.join("");
}

function panel() {
  const out = [];
  out.push(S(k.slabOf(PANEL, SHELF, PANEL_TOP - SHELF, P, 3, 0.5), { tone: "mid" }));
  const cap = { x: -150, y: -62, w: 300, d: 18, r: 3 };
  out.push(S(k.slabOf(cap, PANEL_TOP, 6, P, 4, 0.8), { tone: "mid" }));
  out.push(D(k.corners(cap, 5).map(([x, y]) => at([x, y, PANEL_TOP + 6])), { size: 0.45 }));
  // Un parante entre las dos PCs.
  out.push(S(k.slabOf({ x: -2.5, y: FACE, w: 5, d: 2, r: 0.6 }, SHELF + 2, PANEL_TOP - SHELF - 4, P, 2), { tone: "mid", crease: "none" }));
  // Una placa de rótulo por PC, arriba de cada sección, y un marco rebajado alrededor de los jacks.
  for (const [cx, name] of [[-74, "PC 1"], [74, "PC 2"]]) {
    const frame = [cx - 60, cx + 60];
    out.push(L(k.pathOf([[frame[0], FACE, 52], [frame[1], FACE, 52], [frame[1], FACE, 136], [frame[0], FACE, 136]].map(at), true), { tone: "faint" }));
    const plate = { x: cx - 18, y: FACE, w: 36, d: 1, r: 0.5 };
    out.push(S(k.slabOf(plate, 142, 14, P, 2), { tone: "lo", crease: "none" }));
    out.push(k.faceTextSvg(k.sideMatrix([cx, FACE + 1], 147.5, P, "left"), name, { size: 6, tone: "mid", anchor: "middle" }));
    out.push(D([at([plate.x + 2, FACE + 1, 154]), at([plate.x + plate.w - 2, FACE + 1, 154]), at([plate.x + 2, FACE + 1, 144]), at([plate.x + plate.w - 2, FACE + 1, 144])], { size: 0.4 }));
  }
  return out.join("");
}

function jack(cx, cz, { lamp = "off", plugged = false } = {}) {
  const out = [];
  // Lámpara de estado sobre el jack.
  const lens = { x: cx - 4.5, y: FACE, w: 9, d: 3.2, r: 1.4 };
  out.push(S(k.slabOf({ x: cx - 6, y: FACE, w: 12, d: 1.2, r: 0.6 }, cz + 7, 9, P, 2), { tone: "lo", crease: "none" }));
  out.push(S(k.slabOf(lens, cz + 8.5, 6, P, 3, 0.4), lamp === "lit" ? { tone: "hi", lit: true } : { tone: lamp === "on" ? "mid" : "lo" }));
  // Buje del jack con su boca.
  const bush = { x: cx - 5, y: FACE, w: 10, d: BUSH, r: 2.2 };
  out.push(S(k.slabOf(bush, cz - 5, 10, P, 4, 0.4), { tone: "mid" }));
  out.push(L(k.sideRing([cx, FACE + BUSH, cz], 3.1, "y", P, 20), { tone: "lo" }));
  if (!plugged) out.push(D([at([cx, FACE + BUSH, cz])], { size: 1.5, tone: "lo" }));
  return out.join("");
}

function plug(cx, cz) {
  const out = [];
  const y0 = FACE + BUSH;
  out.push(S(k.slabOf({ x: cx - 2.6, y: y0, w: 5.2, d: PLUG, r: 2.2 }, cz - 2.6, 5.2, P, 4, 0.4), { tone: "hi", crease: "lo" }));
  out.push(L(k.segment([cx - 2.6, y0 + 3, cz + 2.6], [cx + 2.6, y0 + 3, cz + 2.6], P), { tone: "faint" }));
  out.push(S(k.slabOf({ x: cx - 1.9, y: y0 + PLUG, w: 3.8, d: BOOT, r: 1.6 }, cz - 1.9, 3.8, P, 3), { tone: "mid" }));
  return out.join("");
}

// Cordón entre dos jacks: sale de cada fiche hacia el operador y cuelga entre los dos.
function cordRoute(from, to, reach, sag) {
  const [x1, , z1] = from;
  const [x2, , z2] = to;
  const y0 = FACE + BUSH + PLUG + BOOT;
  const low = Math.max(SHELF + 10, Math.min(z1, z2) - sag);
  const ctrl = [
    [x1, y0, z1], [x1, y0 + 6, z1 - 1], [x1 + (x2 - x1) * 0.12, reach - 6, z1 - 18],
    [(x1 + x2) / 2, reach, low],
    [x2 - (x2 - x1) * 0.12, reach - 6, z2 - 18], [x2, y0 + 6, z2 - 1], [x2, y0, z2],
  ];
  const out = [];
  for (let i = 0; i < ctrl.length - 1; i++) {
    const p0 = ctrl[Math.max(0, i - 1)], p1 = ctrl[i], p2 = ctrl[i + 1], p3 = ctrl[Math.min(ctrl.length - 1, i + 2)];
    for (let s = 0; s < 10; s++) {
      const t = s / 10, t2 = t * t, t3 = t2 * t;
      out.push([0, 1, 2].map((j) => 0.5 * (2 * p1[j] + (-p0[j] + p2[j]) * t + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * t2 + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * t3)));
    }
  }
  out.push(ctrl[ctrl.length - 1]);
  return out;
}

function lever(x, y, thrown) {
  // Llave de conversación: base, cuello y una perilla; tirada hacia atrás si el mensaje salió.
  const out = [];
  out.push(S(k.slabOf({ x: x - 5, y: y - 7, w: 10, d: 14, r: 2 }, SHELF, 2, P, 3, 0.4), { tone: "lo" }));
  out.push(L(k.lineOnTop([x, y - 7], [x, y + 7], SHELF + 2, P), { tone: "faint" }));
  out.push(D([at([x - 3, y - 5, SHELF + 2]), at([x + 3, y + 5, SHELF + 2])], { size: 0.4 }));
  const dy = thrown ? -3.5 : 3.5;
  out.push(S(k.slabOf({ x: x - 1.2, y: y + dy - 1.2, w: 2.4, d: 2.4, r: 0.8 }, SHELF + 2, 9, P, 2), { tone: "mid", crease: "none" }));
  out.push(S(k.cylinder(x, y + dy, 2.6, SHELF + 11, 3.6, P, 18), { tone: thrown ? "hi" : "mid" }));
  return out.join("");
}

function timer() {
  const out = [];
  const { x, y, r, h } = TIMER;
  const top = SHELF + h;
  out.push(S(k.cylinder(x, y, r + 2, SHELF, 2, P, 56), { tone: "lo" }));
  out.push(S(k.cylinder(x, y, r, SHELF + 2, h - 2, P, 64, 0.8), { tone: "hi", crease: "lo" }));
  out.push(L(k.knurl(x, y, r, top - 3, top, 72, P, 0.3), { tone: "lo" }));
  out.push(L(k.ring(x, y, r - 2, top, P, 64), { tone: "lo" }));
  const ticks = k.radialTicks(x, y, r - 3, 60, 5, top, [1.2, 2.8], P);
  out.push(L(ticks.minor, { tone: "lo" }), L(ticks.major, { tone: "mid" }));
  // Arco recorrido: lo que ya esperó el hook.
  const swept = [];
  for (let i = 0; i <= 24; i++) {
    const a = (i / 24) * (WAITED / 60) * Math.PI * 2;
    swept.push([x + Math.sin(a) * (r - 7.5), y - Math.cos(a) * (r - 7.5)]);
  }
  out.push(L(k.onTop(swept, top, P), { tone: "hi" }));
  const a = (WAITED / 60) * Math.PI * 2;
  out.push(`<path class="iso-line" data-tone="hi" data-free="start" d="${k.lineOnTop([x - Math.sin(a) * 3, y + Math.cos(a) * 3], [x + Math.sin(a) * (r - 4), y - Math.cos(a) * (r - 4)], top + 0.2, P)}" style="stroke-width:1.1"/>`);
  out.push(L(k.ring(x, y, 1.5, top, P, 16), { tone: "mid" }));
  out.push(k.faceTextSvg(k.topMatrix([x, y + 10], top, P, "x"), "60 s", { size: 4.2, tone: "mid", anchor: "middle" }));
  return out.join("");
}

// Ensamble.
const jacks = [];
const named = Object.fromEntries(Object.entries(JACK).map(([n, cr]) => [cr.join(","), n]));
COLS.forEach((cx, c) => ROWS.forEach((cz, r) => {
  const name = named[`${c},${r}`];
  const lamp = name === LIT ? "lit" : name ? "on" : (c + r) % 3 === 0 ? "on" : "off";
  jacks.push(jack(cx, cz, { lamp, plugged: Boolean(name) }));
}));
const plugs = Object.values(JACK).map((cr) => { const [x, , z] = at3(cr); return plug(x, z); });

const items = [];
const cords = [
  cordRoute(at3(JACK.C), at3(JACK.A), FACE + 30, 40),
  cordRoute(at3(JACK.D), at3(JACK.B), FACE + 44, 30),
];
for (const route of cords) {
  for (const piece of tubePieces(route, 1.5, P, { maxLength: 12 })) items.push({ key: depth(piece.mid), svg: tubeSvg(piece, { tone: "mid" }) });
}
for (const [x, thrown] of [[-96, true], [-84, false], [-60, false], [-48, true]]) items.push({ key: depth([x, 22, SHELF]), svg: lever(x, 22, thrown) });
items.push({ key: depth([TIMER.x, TIMER.y, SHELF]), svg: timer() });
items.sort((a, b) => a.key - b.key);

const label =
  "El tablero de Lienzo dibujado como una coordinadora. Cada jack del panel es una sesión de un agente, con su lámpara de estado arriba. " +
  "El panel tiene dos secciones, una por PC. Un cordón une a la coordinadora con una sesión de la misma PC y otro cruza a la PC 2. " +
  "Una lámpara resaltada marca un permiso esperando respuesta, y el reloj del estante muestra que lleva 23 de los 60 segundos que espera el hook.";

const body = [cabinet(), panel(), shelfTop(), ...jacks, ...plugs, ...items.map((item) => item.svg)];

export function build() {
  return write("coordinadora", {
    width: WIDTH,
    height: HEIGHT,
    label,
    body,
    card: {
      fig: "Fig 1",
      title: "La coordinadora",
      hint: "Cada jack es una sesión",
      readout: `1 permiso esperando · ${WAITED} s de 60`,
      keys: [
        { mark: "lit", label: "Lámpara encendida: un permiso esperando respuesta en el tablero" },
        { mark: "raised", label: "Fiches y cordones: conexiones entre sesiones, también entre PCs" },
        { mark: "flat", label: "Reloj de 60 s: lo que espera el hook de permisos antes de volver a la terminal" },
      ],
      caption:
        "Lienzo como coordinadora: cada jack es una sesión de Claude Code, Codex, Pi, CODA o Kiro, y su lámpara muestra el estado. " +
        "Un cordón conecta dos sesiones; el de la derecha cruza a la otra PC por la LAN. En Claude Code, Codex y CODA, si nadie contesta el permiso en 60 s, el pedido vuelve a la terminal.",
    },
  });
}
