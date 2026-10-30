// Fig 3 del lienzo: delegar trabajo como un correo neumático.
import { acento, fillet, k, tubePieces, tubeSvg, write } from "../kit.mjs";

const WIDTH = 640;
const HEIGHT = 440;

// Mundo: x a lo largo de la fila de escritorios, y hacia el frente, z arriba.
const FLOOR = { x: -150, y: -66, w: 300, d: 120, r: 6 };
const STATION = { x: -136, y: -48, w: 54, d: 56, r: 3 };
const STATION_H = 66;
const DESK_TOP = 34;
const DESKS = [
  { x: -36, state: "llega" },
  { x: 34, state: "trabaja" },
  { x: 104, state: "termino" },
];
// Cada tubo sube de su boca en la estación, corre en alto y baja al receptor del escritorio. El del
// escritorio más lejano sale más atrás y corre más alto, así ninguno cruza a otro.
const PORTS = [
  { x: -94, z: 96 },
  { x: -109, z: 108 },
  { x: -124, z: 120 },
];
const RUN_Y = -28;
const TUBE_R = 2.6;

const P = k.fitProjection(
  [...k.boxCorners(FLOOR, -4, 0), [-124, RUN_Y, 124], [104, RUN_Y, 124], [130, 30, 52]],
  WIDTH,
  HEIGHT,
  { pad: 26, azimuth: 52, elevation: 30 },
);

const at = (p) => k.iso(p, P);
const S = (paths, style) => k.solidSvg(paths, style);
const L = (d, style) => k.lineSvg(d, style);
const D = (points, style) => k.dotsSvg(points, style);
const depth = (p) => k.depthOf(p, P);
const receiverOf = (cx) => ({ x: cx - 20, y: -8, w: 13, d: 13, r: 1.5 });


function capsule(x, y, z, clase) {
  const out = [];
  out.push(S(k.cylinder(x, y, 3.6, z, 11, P, 20), { tone: "hi", className: clase }));
  out.push(S(k.cylinder(x, y, 3.9, z + 2, 1.6, P, 20), { tone: "mid" }));
  out.push(S(k.cylinder(x, y, 3.9, z + 7.4, 1.6, P, 20), { tone: "mid" }));
  return out.join("");
}

function station() {
  const out = [];
  out.push(S(k.slabOf(STATION, 0, STATION_H, P, 4, 0.8), { tone: "mid", inner: L(k.sideSeam(STATION, 20, P, 4), { tone: "faint" }) }));
  const cap = k.insetPlan(STATION, -2);
  out.push(S(k.slabOf(cap, STATION_H, 4, P, 4, 0.8), { tone: "mid" }));
  const top = STATION_H + 4;
  out.push(k.faceTextSvg(k.sideMatrix([-109, 8], 16, P, "left"), "Coordina", { size: 5, tone: "hi", anchor: "middle" }));
  // Bocas de los tubos.
  for (const port of [...PORTS].sort((a, b) => depth([a.x, RUN_Y, 0]) - depth([b.x, RUN_Y, 0]))) {
    out.push(S(k.cylinder(port.x, RUN_Y, 5, top, 3, P, 24), { tone: "mid" }));
  }
  // Bandeja de vuelta en el frente: el informe que volvió solo.
  const tray = { x: STATION.x + 8, y: STATION.y + STATION.d - 18, w: 34, d: 14, r: 2 };
  out.push(S(k.slabOf(tray, top, 2.5, P, 3, 0.4), { tone: "lo" }));
  out.push(capsule(tray.x + 17, tray.y + 7, top + 2.5, acento.verde));
  // Panel del despachante en el frente de la estación.
  const panel = { x: STATION.x + 12, y: STATION.y + STATION.d, w: 30, d: 1, r: 0.5 };
  out.push(S(k.slabOf(panel, 30, 22, P, 2), { tone: "lo", crease: "none" }));
  for (const [i, x] of [panel.x + 7, panel.x + 15, panel.x + 23].entries()) {
    out.push(S(k.slabOf({ x: x - 2, y: panel.y + 1, w: 4, d: 1.4, r: 0.6 }, 42, 4, P, 2), { tone: "hi", className: i < 2 ? acento.ambar : acento.verde }));
    out.push(S(k.slabOf({ x: x - 1.6, y: panel.y + 1, w: 3.2, d: 2, r: 0.8 }, 33, 4, P, 2), { tone: "mid" }));
  }
  return out.join("");
}

function desk({ x: cx, state }) {
  const out = [];
  const body = { x: cx - 26, y: -12, w: 52, d: 40, r: 2 };
  for (const [fx, fy] of k.corners(body, 3).sort((a, b) => depth([...a, 0]) - depth([...b, 0]))) {
    out.push(S(k.slabOf({ x: fx - 2, y: fy - 2, w: 4, d: 4, r: 0.8 }, 0, DESK_TOP - 3, P, 2), { tone: "mid" }));
  }
  out.push(S(k.slabOf(k.insetPlan(body, -1.5), DESK_TOP - 3, 3, P, 4, 0.6), { tone: "mid" }));
  // Cajonera debajo del tablero.
  const drawer = { x: cx + 6, y: body.y + 2, w: 18, d: body.d - 4, r: 1 };
  out.push(S(k.slabOf(drawer, 10, DESK_TOP - 13, P, 2, 0.4), { tone: "mid", inner: L(k.sideSeam(drawer, 20, P, 2), { tone: "faint" }) }));
  out.push(S(k.slabOf({ x: cx + 12, y: drawer.y + drawer.d, w: 6, d: 1.2, r: 0.5 }, 24, 1.6, P, 2), { tone: "hi" }));
  // Receptor del tubo con su canasta.
  const rec = receiverOf(cx);
  out.push(S(k.slabOf(rec, DESK_TOP, 10, P, 3, 0.5), { tone: "mid" }));
  out.push(L(k.ring(rec.x + rec.w / 2, rec.y + rec.d / 2, 3.6, DESK_TOP + 10, P, 20), { tone: "lo" }));
  const basket = { x: rec.x, y: rec.y + rec.d + 1, w: rec.w, d: 9, r: 1.5 };
  out.push(S(k.slabOf(basket, DESK_TOP, 2, P, 3), { tone: "lo" }));
  if (state === "llega") out.push(capsule(basket.x + basket.w / 2, basket.y + basket.d / 2, DESK_TOP + 2, acento.ambar));
  // Terminal: la sesión que trabaja.
  const mon = { x: cx + 2, y: -6, w: 20, d: 12, r: 1.2 };
  out.push(S(k.slabOf({ x: cx + 9, y: -2, w: 6, d: 5, r: 1 }, DESK_TOP, 4, P, 2), { tone: "mid" }));
  out.push(S(k.slabOf(mon, DESK_TOP + 4, 16, P, 3, 0.5), { tone: "mid" }));
  const screen = { x: mon.x + 2, y: mon.y + mon.d, w: mon.w - 4, d: 0.8, r: 0.4 };
  const lit = state === "trabaja";
  out.push(S(k.slabOf(screen, DESK_TOP + 7, 10, P, 2), lit ? { tone: "hi", lit: true } : { tone: "lo", crease: "none" }));
  if (lit) {
    for (const [i, z] of [DESK_TOP + 14.5, DESK_TOP + 12, DESK_TOP + 9.5].entries()) {
      out.push(L(k.segment([screen.x + 2, screen.y + 0.8, z], [screen.x + (i === 2 ? 8 : 13), screen.y + 0.8, z], P), { tone: "lo", free: true }));
    }
  }
  // Teclado.
  const kb = { x: cx - 2, y: 12, w: 22, d: 8, r: 1 };
  out.push(S(k.slabOf(kb, DESK_TOP, 1.6, P, 2, 0.3), { tone: "mid" }));
  out.push(k.faceTextSvg(k.topMatrix([cx + 6, 25], DESK_TOP, P, "x"), "Frente", { size: 4, tone: "hi", anchor: "middle" }));
  return out.join("");
}

// Entre dos escritorios hay un caño con la válvula cerrada: dos sesiones atadas en los dos sentidos
// se contestarían hasta agotar los créditos.
function valve() {
  const out = [];
  const [a, b] = [DESKS[1].x + 15, DESKS[2].x + 15];
  const mid = (a + b) / 2;
  const [front, y, z] = [27.5, 42, 14];
  for (const route of [
    [[a, front, z], [a, y, z], [mid - 4, y, z]],
    [[mid + 4, y, z], [b, y, z], [b, front, z]],
  ]) {
    for (const piece of tubePieces(fillet(route, 5, 10), 1.8, P, { maxLength: 12 })) out.push(tubeSvg(piece, { tone: "mid" }));
  }
  out.push(S(k.slabOf({ x: mid - 4, y: y - 4, w: 8, d: 8, r: 1.5 }, z - 4, 8, P, 3, 0.4), { tone: "mid" }));
  out.push(S(k.cylinder(mid, y, 1, z + 4, 4, P, 12), { tone: "mid" }));
  out.push(S(k.cylinder(mid, y, 6, z + 8, 1.6, P, 32), { tone: "hi", className: acento.rojo }));
  out.push(L([0, 1].map((i) => k.lineOnTop([mid - Math.cos((i * Math.PI) / 2) * 5.6, y - Math.sin((i * Math.PI) / 2) * 5.6], [mid + Math.cos((i * Math.PI) / 2) * 5.6, y + Math.sin((i * Math.PI) / 2) * 5.6], z + 9.6, P)).join(""), { tone: "mid" }));
  return out.join("");
}

function tubes() {
  const items = [];
  DESKS.forEach(({ x: cx }, i) => {
    const port = PORTS[i];
    const rec = receiverOf(cx);
    const down = [rec.x + rec.w / 2, rec.y + rec.d / 2];
    const route = fillet([[port.x, RUN_Y, STATION_H + 7], [port.x, RUN_Y, port.z], [down[0], RUN_Y, port.z], [down[0], down[1], port.z], [down[0], down[1], DESK_TOP + 10]], 9, 12);
    for (const piece of tubePieces(route, TUBE_R, P, { maxLength: 14 })) items.push({ key: depth(piece.mid), svg: tubeSvg(piece, { tone: "mid" }) });
  });
  return items;
}

const items = [
  { key: depth([STATION.x + STATION.w / 2, STATION.y + STATION.d / 2, 0]), svg: station() },
  ...DESKS.map((d) => ({ key: depth([d.x, 8, 0]), svg: desk(d) })),
].sort((a, b) => a.key - b.key);
const body = [`<path class="iso-halo" d="${k.haloOf(FLOOR, 0, 7, P)}"/>`, ...items.map((item) => item.svg), ...tubes().sort((a, b) => a.key - b.key).map((item) => item.svg), valve()];

const label =
  "Delegar trabajo en Lienzo dibujado como un correo neumático. La estación de la sesión coordinadora despacha cápsulas por tres tubos a tres escritorios con su terminal. " +
  "En el primero acaba de llegar un encargo, en el segundo la sesión trabaja y el tercero ya terminó: su informe volvió solo a la bandeja de la estación. " +
  "Entre dos escritorios corre un caño con la válvula cerrada, porque dos sesiones atadas en los dos sentidos se contestarían sin fin.";

export function build() {
  return write("delegar", {
    width: WIDTH,
    height: HEIGHT,
    label,
    body,
    card: {
      fig: "Fig 3",
      title: "Delegar trabajo",
      hint: "Ámbar sale, verde vuelve",
      readout: "3 encargos repartidos · 1 informe de vuelta",
      keys: [
        { mark: "raised", label: "Cápsula ámbar: un encargo con «avisarme cuando termine»; verde: el informe que volvió solo" },
        { mark: "lit", label: "Pantalla encendida: la sesión que está trabajando" },
        { mark: "red", label: "Válvula cerrada: no se atan dos sesiones en los dos sentidos" },
      ],
      caption:
        "La coordinadora reparte encargos a varias terminales con «avisarme cuando termine»; cada una trabaja en lo suyo y su informe vuelve solo. " +
        "La coordinadora verifica, commitea y reparte la ronda siguiente. Es manual a propósito.",
    },
  });
}
