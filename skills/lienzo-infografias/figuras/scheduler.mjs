// Fig 5 del lienzo: el scheduler de mejoras como una máquina con enclavamiento: sólo arranca libre.
import { acento, floorSvg, k, write } from "../kit.mjs";

const WIDTH = 640;
const HEIGHT = 440;

// Mundo: x a lo ancho, y hacia el frente (la bandeja de salida), z arriba.
const FLOOR = { x: -120, y: -66, w: 230, d: 140, r: 6 };
const BODY = { x: -60, y: -44, w: 96, d: 72, r: 3 };
const BODY_H = 58;
const SIDE = BODY.x + BODY.w; // cara derecha, donde va el panel de condiciones
const FRONT = BODY.y + BODY.d;
const HOPPER = { x: -44, y: -32, w: 46, d: 40, r: 2 };
const TRAY = { x: -48, y: FRONT, w: 46, d: 30, r: 2 };
const TRAY_Z = 16;

const P = k.fitProjection(
  [...k.boxCorners(FLOOR, -4, 0), [HOPPER.x, HOPPER.y, BODY_H + 30], [SIDE + 4, BODY.y, BODY_H + 4]],
  WIDTH,
  HEIGHT,
  { pad: 26, azimuth: 40, elevation: 30 },
);

const at = (p) => k.iso(p, P);
const S = (paths, style) => k.solidSvg(paths, style);
const L = (d, style) => k.lineSvg(d, style);
const D = (points, style) => k.dotsSvg(points, style);

// Un círculo sobre la cara derecha (normal +x), con centro (y, z).
const faceRing = (y, z, r, steps = 32) => k.sideRing([SIDE + 1.6, y, z], r, "x", P, steps);
const facePoint = (y, z) => [SIDE + 1.6, y, z];

function body() {
  const out = [];
  out.push(S(k.slabOf(BODY, 0, BODY_H, P, 3, 0.8), { tone: "mid", inner: L(k.sideSeam(BODY, 10, P, 3), { tone: "faint" }) }));
  out.push(S(k.slabOf(k.insetPlan(BODY, -2), BODY_H, 4, P, 3, 0.8), { tone: "mid" }));
  // Rejilla de ventilación en el frente.
  for (let i = 0; i < 5; i++) {
    const x = BODY.x + 58 + i * 6;
    out.push(S(k.slabOf({ x, y: FRONT, w: 3, d: 0.6, r: 0.3 }, 30, 18, P, 1), { tone: "lo", crease: "none" }));
  }
  return out.join("");
}

// La cola: cada trabajo toma los 30 incidentes más recientes de un proyecto; hasta 100 trabajos.
function hopper() {
  const out = [];
  const z0 = BODY_H + 4;
  out.push(S(k.slabOf(HOPPER, z0, 3, P, 3, 0.4), { tone: "lo" }));
  const walls = [
    { x: HOPPER.x, y: HOPPER.y, w: 2, d: HOPPER.d },
    { x: HOPPER.x, y: HOPPER.y, w: HOPPER.w, d: 2 },
  ];
  for (const w of walls) out.push(S(k.slabOf({ ...w, r: 0.4 }, z0 + 3, 9, P, 1), { tone: "mid" }));
  for (let i = 0; i < 10; i++) {
    const plan = { x: HOPPER.x + 5, y: HOPPER.y + 5, w: HOPPER.w - 12, d: HOPPER.d - 12, r: 0.6 };
    out.push(S(k.slabOf({ ...plan, x: plan.x + (i % 2) * 1.2 }, z0 + 3 + i * 1.6, 1.4, P, 1), { tone: "hi", crease: "none" }));
  }
  for (const w of [
    { x: HOPPER.x + HOPPER.w - 2, y: HOPPER.y, w: 2, d: HOPPER.d },
    { x: HOPPER.x, y: HOPPER.y + HOPPER.d - 2, w: HOPPER.w, d: 2 },
  ]) out.push(S(k.slabOf({ ...w, r: 0.4 }, z0 + 3, 9, P, 1), { tone: "mid" }));
  out.push(k.faceTextSvg(k.sideMatrix([HOPPER.x + HOPPER.w / 2, HOPPER.y + HOPPER.d], z0 + 9, P, "left"), "30 / proyecto", { size: 3.8, tone: "mid", anchor: "middle" }));
  return out.join("");
}

// Las salidas: hipótesis propuestas, con veredicto pendiente. No vuelven a la cola.
function tray() {
  const out = [];
  out.push(S(k.slabOf(TRAY, TRAY_Z, 2, P, 3, 0.4), { tone: "mid" }));
  out.push(S(k.slabOf({ x: TRAY.x, y: TRAY.y + TRAY.d - 2, w: TRAY.w, d: 2, r: 0.6 }, TRAY_Z + 2, 4, P, 2), { tone: "mid" }));
  for (let i = 0; i < 3; i++) {
    const card = { x: TRAY.x + 6 + i * 1.4, y: TRAY.y + 4 + i * 1.6, w: 30, d: 20, r: 0.6 };
    const z = TRAY_Z + 2 + i * 1.2;
    out.push(S(k.slabOf(card, z, 1, P, 1), { tone: "hi", crease: "none" }));
    if (i === 2) out.push(S(k.slabOf({ x: card.x + card.w - 9, y: card.y + 3, w: 6, d: 6, r: 0.8 }, z + 1, 0.6, P, 2), { tone: "hi", crease: "none", className: acento.ambar }));
  }
  return out.join("");
}

// El panel de condiciones: arranca sólo si todas están en verde.
function panel() {
  const out = [];
  const plate = { x: SIDE, y: BODY.y + 8, w: 1.6, d: BODY.d - 16, r: 0.4 };
  out.push(S(k.slabOf(plate, 8, BODY_H - 14, P, 2), { tone: "lo" }));
  out.push(D([facePoint(plate.y + 3, 11), facePoint(plate.y + plate.d - 3, 11), facePoint(plate.y + 3, BODY_H - 9), facePoint(plate.y + plate.d - 3, BODY_H - 9)].map(at), { size: 0.45 }));
  // 1. Reloj de inactividad: 180 s cumplidos, arco completo en verde.
  const [ty, tz, tr] = [BODY.y + 24, 34, 11];
  out.push(L(faceRing(ty, tz, tr), { tone: "mid" }));
  out.push(L(faceRing(ty, tz, tr - 2.6, 40), { tone: "hi", className: acento.verde }));
  for (let i = 0; i < 12; i++) {
    const a = (i / 12) * Math.PI * 2;
    out.push(L(k.segment(facePoint(ty + Math.sin(a) * (tr - 1), tz + Math.cos(a) * (tr - 1)), facePoint(ty + Math.sin(a) * (tr - 0.2), tz + Math.cos(a) * (tr - 0.2)), P), { tone: "lo", free: true }));
  }
  out.push(`<path class="iso-line" data-tone="hi" data-free="end" d="${k.segment(facePoint(ty, tz), facePoint(ty - 0.2, tz + tr - 3), P)}" style="stroke-width:1.1"/>`);
  out.push(D([at(facePoint(ty, tz))], { size: 1, tone: "hi" }));
  // 2. Recursos: CPU hasta 35 % (arriba) y memoria libre de 1,5 GB o más (abajo), con su LED.
  for (const [i, gz] of [42, 24].entries()) {
    const gy = BODY.y + 50;
    out.push(L(faceRing(gy, gz, 6), { tone: "mid" }));
    out.push(`<path class="iso-line" data-tone="hi" data-free="end" d="${k.segment(facePoint(gy, gz), facePoint(gy + 3.4, gz + 3.4 - i), P)}"/>`);
    out.push(D([at(facePoint(gy, gz))], { size: 0.8, tone: "hi" }));
    out.push(S(k.slabOf({ x: SIDE + 1.6, y: gy + 9, w: 1.4, d: 3.4, r: 0.6 }, gz - 1.7, 3.4, P, 2), { tone: "hi", className: acento.verde }));
  }
  // 3. Ningún agente ocupado ni permiso vigente: en verde.
  out.push(S(k.slabOf({ x: SIDE + 1.6, y: ty - 3, w: 1.4, d: 6, r: 1 }, 14, 4, P, 2), { tone: "hi", className: acento.verde }));
  // 4. La llave del usuario: el aprendizaje habilitado (no pausado).
  const [ky, kz] = [ty + 12, 15];
  out.push(L(faceRing(ky, kz, 3.2, 20), { tone: "mid" }));
  out.push(S(k.slabOf({ x: SIDE + 1.6, y: ky - 0.7, w: 1.6, d: 1.4, r: 0.4 }, kz - 0.4, 3.4, P, 1), { tone: "hi", className: acento.verde }));
  return out.join("");
}

// Luz de marcha arriba: todas las condiciones, cumplidas en dos muestras seguidas.
function beacon() {
  const out = [];
  const [x, y] = [BODY.x + BODY.w - 14, BODY.y + 14];
  out.push(S(k.cylinder(x, y, 5, BODY_H + 4, 2, P, 24), { tone: "mid" }));
  out.push(S(k.cylinder(x, y, 3.6, BODY_H + 6, 7, P, 24), { tone: "hi", className: acento.verde }));
  out.push(S(k.cylinder(x, y, 4, BODY_H + 13, 1.4, P, 24), { tone: "mid" }));
  return out.join("");
}

const body_ = [floorSvg(FLOOR, P), body(), panel(), hopper(), beacon(), tray()];

const label =
  "El scheduler de mejoras de Lienzo dibujado como una máquina con enclavamiento. Arriba, una tolva con los 30 incidentes más recientes de un proyecto; la cola admite hasta 100 trabajos. " +
  "En el costado, el panel de condiciones, todo en verde: el reloj marca los 180 segundos de inactividad, la CPU está en 35 % o menos, la memoria libre en 1,5 GB o más, no hay agentes ocupados ni permiso vigente y la llave del usuario está habilitada. " +
  "Con todo cumplido en dos muestras seguidas, la luz de marcha está en verde. Al frente, la bandeja con las hipótesis propuestas, con su veredicto pendiente.";

export function build() {
  return write("scheduler", {
    width: WIDTH,
    height: HEIGHT,
    label,
    body: body_,
    card: {
      fig: "Fig 5",
      title: "Mejoras cuando está libre",
      hint: "Arranca sólo con todo en verde",
      readout: "180 s libre · CPU y memoria aptas · 2 muestras seguidas",
      keys: [
        { mark: "green", label: "Todo en verde: 180 s sin actividad, CPU ≤ 35 %, memoria libre ≥ 1,5 GB, nadie ocupado ni permiso vigente y la llave habilitada, en dos muestras seguidas" },
        { mark: "raised", label: "Tolva: los 30 incidentes más recientes de cada proyecto; un cambio en ellos encola otro análisis; hasta 100 trabajos, cooldown de 120 s" },
        { mark: "flat", label: "Bandeja con sello ámbar: hipótesis propuestas, veredicto pendiente; no generan otra ronda" },
      ],
      caption:
        "El scheduler analiza los incidentes recientes de la memoria cuando hay 180 segundos de inactividad, dos muestras seguidas aptas y ningún agente ocupado ni permiso vigente. " +
        "Encola por proyecto y versión de fuentes; sus propias hipótesis no generan otra ronda.",
    },
  });
}
