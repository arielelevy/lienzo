// Los pasos de FDD (skill fdd, 2026-10-26): una ficha avanza por cuatro hitos sobre la constitución,
// con el mapa del dominio al lado. El último hito, integrado, lo marca una persona: lleva cerradura.
import { acento, k, write } from "../kit.mjs";

const WIDTH = 680;
const HEIGHT = 440;

// Mundo: x a lo largo del recorrido, y hacia el frente, z arriba.
const BASE = { x: -150, y: -60, w: 300, d: 130, r: 6 };
const BASE_H = 14; // la constitución: todo apoya sobre ella
const HITOS = ["diseñado", "implementado", "verificado", "integrado"];
const PASO = 62;
const X0 = -112;
const EST = { y: -6, w: 40, d: 40 };
const EST_H = 10;
const ACTUAL = 2; // la ficha está en «verificado»: falta que una persona la integre

const P = k.fitProjection(
  [...k.boxCorners(BASE, 0, BASE_H), [X0, EST.y, BASE_H + EST_H + 50], [X0 + 3 * PASO + EST.w, EST.y + EST.d, BASE_H + EST_H + 30]],
  WIDTH,
  HEIGHT,
  { pad: 26, azimuth: 50, elevation: 30 },
);

const at = (p) => k.iso(p, P);
const S = (paths, style) => k.solidSvg(paths, style);
const L = (d, style) => k.lineSvg(d, style);
const D = (points, style) => k.dotsSvg(points, style);
const Z = BASE_H;

function constitucion() {
  const out = [];
  out.push(`<path class="iso-halo" d="${k.haloOf(BASE, 0, BASE_H, P)}"/>`);
  out.push(S(k.slabOf(BASE, 0, BASE_H, P, 8, 0.8), { tone: "mid" }));
  out.push(L(k.planOutline(k.insetPlan(BASE, 5), Z, P), { tone: "faint" }));
  out.push(D(k.corners(BASE, 9).map(([x, y]) => at([x, y, Z])), { size: 0.5 }));
  out.push(k.faceTextSvg(k.sideMatrix([BASE.x + 14, BASE.y + BASE.d], BASE_H - 4, P, "left"), "constitución: AGENTS.md, decisiones, contratos", { size: 5, tone: "mid" }));
  return out.join("");
}

// El riel que une las estaciones, por donde avanza la ficha.
function riel() {
  const y = EST.y + EST.d / 2;
  return L(k.segment([X0 + EST.w / 2, y, Z + 1], [X0 + 3 * PASO + EST.w / 2, y, Z + 1], P), { tone: "lo", dashed: true });
}

function estacion(i) {
  const out = [];
  const x = X0 + i * PASO;
  const plan = { x, y: EST.y, w: EST.w, d: EST.d, r: 2 };
  out.push(S(k.slabOf(plan, Z, EST_H, P, 3, 0.6), { tone: "mid" }));
  out.push(k.faceTextSvg(k.sideMatrix([x + EST.w / 2, EST.y + EST.d], Z + EST_H - 3.5, P, "left"), HITOS[i], { size: 4.6, tone: "hi", anchor: "middle" }));
  const top = Z + EST_H;
  if (i < 3) {
    // Lámpara: verde si el hito ya pasó con evidencia, apagada si falta.
    const hecho = i <= ACTUAL;
    out.push(S(k.cylinder(x + EST.w - 7, EST.y + 7, 2.4, top, 3, P, 16), { tone: hecho ? "hi" : "lo", className: hecho ? acento.verde : undefined }));
  } else {
    // Integrado: cerradura roja con su llave al lado. Lo marca una persona, nunca el agente.
    const lock = { x: x + EST.w / 2 - 6, y: EST.y + EST.d / 2 - 4, w: 12, d: 8, r: 1.4 };
    out.push(S(k.slabOf(lock, top, 9, P, 2, 0.4), { tone: "hi", className: acento.rojo }));
    out.push(S(k.cylinder(lock.x + 6, lock.y + 4, 3.4, top + 9, 3, P, 16), { tone: "mid" }));
    out.push(S(k.slabOf({ x: x + 5, y: EST.y + EST.d - 10, w: 12, d: 3, r: 0.8 }, top, 1.6, P, 2), { tone: "hi", className: acento.ambar }));
  }
  return out.join("");
}

// La ficha: una tarjeta parada con renglones (objetivo, alcance, criterios, evidencia, próximo paso).
function ficha() {
  const out = [];
  const x = X0 + ACTUAL * PASO + EST.w / 2 - 13;
  const y = EST.y + EST.d / 2 - 1;
  const z = Z + EST_H;
  const h = 34;
  out.push(S(k.slabOf({ x, y, w: 26, d: 2, r: 0.4 }, z, h, P, 1), { tone: "hi" }));
  for (let r = 0; r < 5; r++) {
    const zz = z + h - 7 - r * 5.6;
    out.push(L(k.segment([x + 4, y + 2, zz], [x + (r % 2 ? 16 : 22), y + 2, zz], P), { tone: "faint", free: true }));
  }
  out.push(S(k.slabOf({ x: x + 18, y: y + 2, w: 5, d: 0.6, r: 0.2 }, z + h - 6, 3, P, 1), { tone: "hi", className: acento.verde }));
  return out.join("");
}

// El mapa del dominio, al costado del inicio: lo que se lee antes de abrir una ficha.
function mapa() {
  const out = [];
  const hoja = { x: X0 - 6, y: BASE.y + 8, w: 70, d: 30, r: 0.8 };
  const z = Z + 1.2;
  out.push(S(k.slabOf(hoja, Z, 1.2, P, 1), { tone: "hi", crease: "none" }));
  const nodos = [
    [hoja.x + 10, hoja.y + 8],
    [hoja.x + 30, hoja.y + 18],
    [hoja.x + 54, hoja.y + 9],
    [hoja.x + 18, hoja.y + 16],
  ];
  for (const [a, b] of [[0, 1], [1, 2], [1, 3]]) out.push(L(k.segment([...nodos[a], z], [...nodos[b], z], P), { tone: "lo", free: true }));
  for (const [x, y] of nodos) out.push(S(k.slabOf({ x: x - 3, y: y - 2, w: 6, d: 4, r: 0.6 }, z, 1.6, P, 1), { tone: "mid" }));
  out.push(k.faceTextSvg(k.topMatrix([hoja.x + 4, hoja.y + hoja.d - 3], z, P), "mapa del dominio", { size: 4.4, tone: "mid" }));
  return out.join("");
}

// El mapa queda detrás de las estaciones: va antes que ellas.
const body = [constitucion(), mapa(), riel(), ...[0, 1, 2, 3].map(estacion), ficha()];

const label =
  "Los pasos de FDD para agentes. Sobre una base que es la constitución del proyecto (AGENTS.md, decisiones y contratos), " +
  "una ficha por feature avanza por cuatro estaciones: diseñado, implementado, verificado e integrado. Las tres primeras tienen una " +
  "lámpara que se prende verde sólo con evidencia observada. La última tiene una cerradura roja con su llave al lado: integrado lo " +
  "marca una persona, nunca el agente. Detrás del inicio, la hoja del mapa del dominio, que se lee antes de abrir la ficha.";

export function build() {
  return write("fdd-pasos", {
    width: WIDTH,
    height: HEIGHT,
    label,
    body,
    card: {
      fig: "FDD",
      title: "Una ficha, cuatro hitos",
      hint: "Todo apoya en la constitución",
      readout: "diseñado → implementado → verificado → integrado",
      keys: [
        { mark: "green", label: "Hito con evidencia observada" },
        { mark: "red", label: "Integrado: lo marca una persona" },
      ],
      caption: "Un cambio puntual y claro no abre ficha: se hace y se verifica directo.",
    },
  });
}
