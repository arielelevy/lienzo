// Fig 2 del lienzo: los plugins locales como tarjetas en las ranuras de una placa.
import { acento, k, write } from "../kit.mjs";

const WIDTH = 640;
const HEIGHT = 440;

// Mundo: x a lo ancho de la placa, y a lo largo de las ranuras (los soportes hacia +y), z arriba.
const TRAY = { x: -142, y: -82, w: 262, d: 150, r: 6 };
const TRAY_Z = -16;
const BOARD = { x: -134, y: -74, w: 246, d: 134, r: 4 };
const BOARD_H = 3;
const CPU = { x: 74, y: -68, w: 34, d: 34, r: 2 };
const SLOT_TOP = 7;
const SLOT_Y = [-48, 40];
const CARD_TOP = 56;
const LIFT = 36;
const SLOTS = [
  { x: -62, state: "on" },
  { x: -22, state: "on" },
  { x: 18, state: "fail" },
  { x: 58, state: "lift" },
];

const P = k.fitProjection(
  [...k.boxCorners(TRAY, TRAY_Z - 4, 0), [58, 46, CARD_TOP + LIFT + 6], [-62, 46, CARD_TOP + 8]],
  WIDTH,
  HEIGHT,
  { pad: 26, azimuth: 38, elevation: 30 },
);

const at = (p) => k.iso(p, P);
const S = (paths, style) => k.solidSvg(paths, style);
const L = (d, style) => k.lineSvg(d, style);
const D = (points, style) => k.dotsSvg(points, style);
const depth = (p) => k.depthOf(p, P);

function base() {
  const out = [`<path class="iso-halo" d="${k.haloOf(TRAY, TRAY_Z - 4, 4, P)}"/>`];
  for (const [x, y] of k.corners(TRAY, 12).sort((a, b) => depth([...a, 0]) - depth([...b, 0]))) {
    out.push(S(k.cylinder(x, y, 5.5, TRAY_Z - 4, 4, P, 24), { tone: "lo" }));
  }
  out.push(S(k.slabOf(TRAY, TRAY_Z, 4, P, 8, 0.8), { tone: "mid" }));
  // Separadores bajo la placa, en sus cuatro esquinas.
  for (const [x, y] of k.corners(BOARD, 8).sort((a, b) => depth([...a, 0]) - depth([...b, 0]))) {
    out.push(S(k.cylinder(x, y, 3, TRAY_Z + 4, -BOARD_H - TRAY_Z - 4, P, 18), { tone: "mid" }));
  }
  out.push(S(k.slabOf(BOARD, -BOARD_H, BOARD_H, P, 6, 0.5), { tone: "mid" }));
  const holes = k.corners(BOARD, 8);
  out.push(L(holes.map(([x, y]) => k.ring(x, y, 2.4, 0, P, 16)).join(""), { tone: "lo" }));
  out.push(D(holes.map(([x, y]) => at([x, y, 0])), { size: 0.5 }));
  return out.join("");
}

function traces() {
  // Una pista por ranura, del fondo de la ranura al server: la ruta /ext/<nombre>.
  const out = [];
  SLOTS.forEach(({ x }, i) => {
    const y = -52 - 3 * (SLOTS.length - 1 - i);
    out.push(L(k.onTop([[x, SLOT_Y[0]], [x, y], [CPU.x, y]], 0, P), { tone: "lo" }));
    out.push(D([at([x, SLOT_Y[0], 0]), at([CPU.x, y, 0])], { size: 0.45, tone: "mid" }));
  });
  return out.join("");
}

function server() {
  const out = [];
  out.push(S(k.slabOf(CPU, 0, 3, P, 3, 0.4), { tone: "lo" }));
  const sink = k.insetPlan(CPU, 2);
  out.push(S(k.slabOf(sink, 3, 13, P, 3, 0.6), { tone: "mid" }));
  for (let x = sink.x + 4; x < sink.x + sink.w - 2; x += 4) {
    out.push(L(k.lineOnTop([x, sink.y], [x, sink.y + sink.d], 16, P), { tone: "faint" }));
  }
  out.push(k.faceTextSvg(k.sideMatrix([CPU.x + CPU.w / 2, CPU.y + CPU.d], 11, P, "left"), "server", { size: 4.4, tone: "mid", anchor: "middle" }));
  return out.join("");
}

function slot(x) {
  const plan = { x: x - 3.5, y: SLOT_Y[0], w: 7, d: SLOT_Y[1] - SLOT_Y[0], r: 1 };
  const out = [S(k.slabOf(plan, 0, SLOT_TOP, P, 3, 0.4), { tone: "lo" })];
  out.push(L(k.planOutline(k.insetPlan(plan, 2.2), SLOT_TOP, P, 2), { tone: "faint" }));
  // Traba del extremo del soporte.
  out.push(S(k.slabOf({ x: x - 4, y: SLOT_Y[1] - 1, w: 8, d: 4, r: 1 }, 0, SLOT_TOP + 2, P, 2), { tone: "mid" }));
  return out.join("");
}

function card(x, state) {
  const dz = state === "lift" ? LIFT : 0;
  const out = [];
  const z0 = SLOT_TOP + dz - 3;
  const pcb = { x: x - 0.8, y: SLOT_Y[0] + 2, w: 1.6, d: SLOT_Y[1] - SLOT_Y[0] - 4, r: 0.3 };
  out.push(S(k.slabOf(pcb, z0, CARD_TOP - z0 + dz, P, 2), { tone: "mid" }));
  if (state === "lift") {
    // Peine de contactos: lo que entra en la ranura.
    for (let y = pcb.y + 4; y < pcb.y + pcb.d - 6; y += 3.2) {
      out.push(S(k.slabOf({ x: x + 0.8, y, w: 0.3, d: 1.8, r: 0 }, z0, 4, P, 1), { tone: "hi", crease: "none", className: acento.ambar }));
    }
  }
  // Dos chips en la cara visible: el del fondo es el módulo del server, el de adelante la vista.
  const back = { x: x + 0.8, y: pcb.y + 8, w: 2, d: 22, r: 0.6 };
  const front = { x: x + 0.8, y: pcb.y + 42, w: 2, d: 26, r: 0.6 };
  out.push(S(k.slabOf(back, z0 + 14, 16, P, 2, 0.3), { tone: "lo" }));
  out.push(D([4, 9, 14, 18].map((dy) => at([back.x + 2, back.y + dy, z0 + 30])), { size: 0.35 }));
  out.push(S(k.slabOf(front, z0 + 12, 22, P, 2, 0.3), { tone: "hi", crease: "lo" }));
  out.push(D([4, 10, 16, 22].map((dy) => at([front.x + 2, front.y + dy, z0 + 34])), { size: 0.35 }));
  // Soporte de chapa en la punta, con su pestaña atornillada y el LED de estado.
  const yb = pcb.y + pcb.d;
  out.push(S(k.slabOf({ x: x - 6, y: yb, w: 12, d: 1.4, r: 0.3 }, SLOT_TOP + dz - 4, CARD_TOP - SLOT_TOP + 10, P, 2), { tone: "mid" }));
  const tabZ = CARD_TOP + dz + 6;
  out.push(S(k.slabOf({ x: x - 6, y: yb, w: 12, d: 7, r: 0.6 }, tabZ, 1.6, P, 2), { tone: "mid" }));
  out.push(L(k.ring(x, yb + 4.5, 1.4, tabZ + 1.6, P, 14), { tone: "lo" }), D([at([x, yb + 4.5, tabZ + 1.6])], { size: 0.45 }));
  out.push(S(k.slabOf({ x: x - 3, y: yb + 1.4, w: 6, d: 1, r: 0.4 }, SLOT_TOP + dz + 10, 10, P, 2), { tone: "lo", crease: "none" }));
  const led = { x: x - 2, y: yb + 1.4, w: 4, d: 1.6, r: 0.8 };
  const style = { tone: "hi", className: state === "on" ? acento.verde : state === "fail" ? acento.rojo : undefined };
  out.push(S(k.slabOf(led, CARD_TOP + dz - 8, 4, P, 3), style));
  return out.join("");
}

const parts = [base(), traces(), server()];
for (const { x } of SLOTS) parts.push(slot(x));
for (const { x, state } of SLOTS) parts.push(card(x, state));

const label =
  "Los plugins de Lienzo dibujados como tarjetas de expansión en una placa. Cada ranura se conecta por una pista con el server. " +
  "Dos tarjetas están cargadas y tienen el LED encendido, una no cargó y tiene el LED apagado, y una cuarta está en el aire sobre su ranura vacía. " +
  "Una tarjeta puede llevar un módulo del server, una vista del tablero o los dos.";

export function build() {
  return write("plugins", {
    width: WIDTH,
    height: HEIGHT,
    label,
    body: parts,
    card: {
      fig: "Fig 2",
      title: "Los plugins",
      hint: "Cada tarjeta es un plugin local",
      readout: "2 cargados · 1 no cargó · el server sigue",
      keys: [
        { mark: "lit", label: "LED encendido: módulo cargado; si define get o post, responde en /ext/<nombre>" },
        { mark: "raised", label: "Chip de atrás: lienzo/extensiones/<nombre>.py · chip de adelante: web/src/extensiones/<nombre>.tsx; cada uno es opcional" },
        { mark: "dim", label: "LED apagado: el módulo no cargó; queda en el log y no frena al server" },
      ],
      caption:
        "Los plugins del lienzo son tarjetas que se enchufan en el server de una PC. Cada uno puede traer un módulo del server, una vista del tablero o los dos; " +
        "el server carga los módulos al arrancar y las vistas entran en el build. Las carpetas extensiones/ no van a Git: sin ninguna tarjeta, el server y el tablero andan igual.",
    },
  });
}
