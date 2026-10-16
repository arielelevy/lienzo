// Fig 4 del lienzo: la memoria por proyecto como un fichero de archivo.
import { acento, floorSvg, k, write } from "../kit.mjs";

const WIDTH = 640;
const HEIGHT = 440;

// Mundo: x a lo ancho del fichero, y hacia el frente (los cajones salen hacia +y), z arriba.
const FLOOR = { x: -130, y: -60, w: 250, d: 150, r: 6 };
const CAB = { x: -104, y: -40, w: 104, d: 64, r: 2 };
const CAB_H = 96;
const FRONT = CAB.y + CAB.d;
const COLS = [-78, -26];
const ROWS = [70, 42, 14]; // base de cada cajón
const DRAWER_H = 24;
const PULL = 52;
const OPEN = { col: 1, row: 1 };
const TRAY = { x: 30, y: -6, w: 62, d: 46, r: 3 };
const TRAY_H = 24;

const P = k.fitProjection(
  [...k.boxCorners(FLOOR, -4, 0), [CAB.x, CAB.y, CAB_H + 22], [COLS[1] + 24, FRONT + PULL + 4, ROWS[1] + DRAWER_H]],
  WIDTH,
  HEIGHT,
  { pad: 26, azimuth: 50, elevation: 30 },
);

const at = (p) => k.iso(p, P);
const S = (paths, style) => k.solidSvg(paths, style);
const L = (d, style) => k.lineSvg(d, style);
const D = (points, style) => k.dotsSvg(points, style);


// Una ficha parada (hasta 64 KB) con su sello «observado» arriba.
function card(x, y, z, h = 18) {
  const out = [];
  out.push(S(k.slabOf({ x: x - 9, y, w: 18, d: 0.8, r: 0.2 }, z, h, P, 1), { tone: "hi", crease: "none" }));
  out.push(S(k.slabOf({ x: x + 2, y, w: 5, d: 0.8, r: 0.2 }, z + h, 2.4, P, 1), { tone: "hi", crease: "none", className: acento.ambar }));
  return out.join("");
}

function cabinet() {
  const out = [];
  out.push(S(k.slabOf(CAB, 0, CAB_H, P, 3, 0.8), { tone: "mid" }));
  out.push(S(k.slabOf(k.insetPlan(CAB, -2), CAB_H, 4, P, 3, 0.8), { tone: "mid" }));
  // Ranura de entrada arriba: cada pedido, respuesta final, envío o disparo de regla entra solo.
  const slot = { x: -70, y: -14, w: 30, d: 8, r: 1.5 };
  out.push(S(k.slabOf(slot, CAB_H + 4, 3, P, 3, 0.4), { tone: "lo" }));
  out.push(card(slot.x + slot.w / 2, slot.y + 3.6, CAB_H + 7, 12));
  return out.join("");
}

function drawerFront(cx, z0, { open = false } = {}) {
  const out = [];
  const y = FRONT + (open ? PULL : 0);
  out.push(S(k.slabOf({ x: cx - 24, y, w: 48, d: 2.4, r: 0.8 }, z0 + 1, DRAWER_H - 2, P, 2, 0.4), { tone: "mid" }));
  // Portaetiqueta con la carpeta del proyecto y tirador.
  const label = { x: cx - 9, y: y + 2.4, w: 18, d: 0.8, r: 0.3 };
  out.push(S(k.slabOf(label, z0 + 13, 7, P, 2), { tone: "lo", crease: "none" }));
  out.push(L(k.segment([label.x + 3, label.y + 0.8, z0 + 17.5], [label.x + 15, label.y + 0.8, z0 + 17.5], P), { tone: "faint", free: true }));
  out.push(L(k.segment([label.x + 3, label.y + 0.8, z0 + 15.5], [label.x + 11, label.y + 0.8, z0 + 15.5], P), { tone: "faint", free: true }));
  out.push(S(k.slabOf({ x: cx - 6, y: y + 2.4, w: 12, d: 2, r: 0.8 }, z0 + 6, 2.4, P, 2), { tone: "hi" }));
  return out.join("");
}

// El cajón abierto: un proyecto, con sus fichas en fila.
function openDrawer(cx, z0) {
  const out = [];
  const y0 = FRONT - 6;
  const inner = { x: cx - 22, y: y0, w: 44, d: PULL + 6, r: 0.6 };
  out.push(S(k.slabOf(inner, z0 + 1, 1.6, P, 2), { tone: "lo" }));
  out.push(S(k.slabOf({ x: inner.x, y: y0, w: 1.6, d: inner.d, r: 0.3 }, z0 + 2.6, 14, P, 1), { tone: "mid" }));
  for (let y = y0 + 6; y < y0 + inner.d - 4; y += 5.2) out.push(card(cx, y, z0 + 2.6));
  // Varilla que pasa por las fichas, como en un fichero de verdad.
  out.push(L(k.segment([cx - 3, y0 + 2, z0 + 6], [cx - 3, y0 + inner.d - 2, z0 + 6], P), { tone: "lo" }));
  out.push(S(k.slabOf({ x: inner.x + inner.w - 1.6, y: y0, w: 1.6, d: inner.d, r: 0.3 }, z0 + 2.6, 14, P, 1), { tone: "mid" }));
  out.push(drawerFront(cx, z0, { open: true }));
  return out.join("");
}

// La bandeja de lo vigente: nada capturado pasa solo; decide la coordinadora o una persona.
function tray() {
  const out = [];
  out.push(S(k.slabOf(TRAY, 0, TRAY_H, P, 3, 0.6), { tone: "mid", inner: L(k.sideSeam(TRAY, 6, P, 3), { tone: "faint" }) }));
  out.push(S(k.slabOf(k.insetPlan(TRAY, -1.5), TRAY_H, 3, P, 3, 0.6), { tone: "mid" }));
  for (const x of [TRAY.x + 10, TRAY.x + TRAY.w - 10]) {
    out.push(S(k.cylinder(x, TRAY.y + 1, 1.8, TRAY_H + 0.5, 4, P, 14), { tone: "mid" }));
  }
  const front = TRAY.y + TRAY.d + 1.5;
  const lock = { x: TRAY.x + TRAY.w / 2 - 5, y: front, w: 10, d: 2, r: 1 };
  out.push(S(k.slabOf(lock, TRAY_H - 6, 9, P, 2, 0.3), { tone: "hi", className: acento.rojo }));
  out.push(D([at([lock.x + 5, front + 2, TRAY_H - 2])], { size: 0.9, tone: "hi" }));
  out.push(k.faceTextSvg(k.sideMatrix([TRAY.x + TRAY.w / 2, front], 11, P, "left"), "vigente", { size: 5, tone: "mid", anchor: "middle" }));
  return out.join("");
}

const fronts = [];
COLS.forEach((cx, c) =>
  ROWS.forEach((z0, r) => {
    if (c === OPEN.col && r === OPEN.row) return;
    fronts.push(drawerFront(cx, z0));
  }),
);
// El cajón abierto tapa al de abajo: va después de los demás frentes.
const body = [floorSvg(FLOOR, P), cabinet(), ...fronts, openDrawer(COLS[OPEN.col], ROWS[OPEN.row]), tray()];

const label =
  "La memoria por proyecto de Lienzo dibujada como un fichero de archivo. Cada cajón es un proyecto, con la carpeta en su etiqueta. " +
  "Por la ranura de arriba entra sola una ficha por cada pedido, respuesta final, envío entre sesiones o disparo de regla, con su sello de observado. " +
  "Un cajón abierto muestra las fichas en fila. Al lado, la bandeja de lo vigente tiene la tapa cerrada con llave: nada capturado pasa solo.";

export function build() {
  return write("memoria", {
    width: WIDTH,
    height: HEIGHT,
    label,
    body,
    card: {
      fig: "Fig 4",
      title: "Memoria por proyecto",
      hint: "Cada cajón es una carpeta",
      readout: "todo entra · nada pasa solo a vigente",
      keys: [
        { mark: "raised", label: "Ficha con sello ámbar: captura observada, hasta 64 KB con el hash del original" },
        { mark: "red", label: "Cerradura: lo vigente lo decide la coordinadora o una persona, nunca la captura" },
      ],
      caption:
        "Todo lo que pasa por el lienzo queda en la memoria sin registrar nada a mano. El proyecto es la carpeta: dos carpetas de una PC nunca comparten cajón, " +
        "y el remote sólo une la misma carpeta en dos PCs. Nada capturado pasa a vigente.",
    },
  });
}
