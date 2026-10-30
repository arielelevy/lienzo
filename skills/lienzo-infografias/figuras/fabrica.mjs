// Figure: mesa de reparto. Las fichas viajan por dos carriles: encargo e informe.
// Piezas: base y patas (5), carriles con bordes y topes (10), estaciones (52), fichas (6): 73.
// Una estación coordina; las otras tres son frentes ilustrativos, no un límite.
import { k, acento, write } from "../kit.mjs";

const width = 760, height = 450;
const base = { x: -170, y: -75, w: 340, d: 150, r: 5 };
const P = k.fitProjection(k.boxCorners(base, -12, 82), width, height,
  { pad: 35, azimuth: 55, elevation: 36 });
const slab = (p, z, h, style = {}) => k.solidSvg(k.slabOf(p, z, h, P, 4, 0.6), { tone: "mid", ...style });
const plan = (x, y, w, d, r = 1) => ({ x, y, w, d, r });

function placa(x, y, z, w, texto) {
  return k.lineSvg(k.planOutline(plan(x, y, w, 10), z, P), { tone: "lo" }) +
    k.faceTextSvg(k.topMatrix([x + w / 2, y + 7], z, P, "x"), texto,
      { size: 4.8, tone: "hi", anchor: "middle" });
}

function ficha(x, y, z, color) {
  const p = plan(x, y, 18, 12);
  return slab(p, z, 1.2, { tone: "hi" }) +
    slab(plan(x, y, 3, 12), z + 1.2, 0.5, { className: color }) +
    [3, 6, 9].map(dy => k.lineSvg(k.segment([x + 5, y + dy, z + 1.2],
      [x + 15, y + dy, z + 1.2], P), { tone: "lo", free: true })).join("");
}

function estacion(x, coordina) {
  const y = -58, out = [];
  // Bancada y marco exterior: el meta-harness rodea el instrumento del agente.
  out.push(slab(plan(x, y, 64, 62, 3), 0, 5, { tone: "lo" }));
  out.push(slab(plan(x + 3, y + 3, 58, 5), 5, 65));
  for (const dx of [3, 56]) out.push(slab(plan(x + dx, y + 8, 5, 45), 5, 65));
  out.push(slab(plan(x + 3, y + 8, 58, 45), 70, 5));
  out.push(slab(plan(x + 14, y + 15, 36, 25, 2), 5, 36, { tone: "hi" }));
  out.push(slab(plan(x + 18, y + 40, 28, 1), 17, 20, { tone: "lo" }));
  out.push(slab(plan(x + 20, y + 41, 24, 0.6), 20, 14, { tone: "hi", lit: coordina }));
  // Pupitre, dos teclas, luz de estado y cajón de la ronda.
  out.push(slab(plan(x + 14, y + 42, 36, 12), 5, 8));
  for (const dx of [19, 32]) out.push(slab(plan(x + dx, y + 45, 9, 6), 13, 2, { tone: "hi" }));
  out.push(slab(plan(x + 45, y + 54, 5, 4), 5, 2, { className: coordina ? acento.ambar : acento.verde }));
  out.push(slab(plan(x + 18, y + 58, 28, 3), 1, 8, { tone: "hi" }));
  if (coordina) out.push(k.faceTextSvg(k.sideMatrix([x + 32, y + 61], 3, P, "left"),
    "Rondas", { size: 4, tone: "hi", anchor: "middle" }));
  out.push(k.dotsSvg(k.corners(plan(x + 3, y + 8, 58, 45), 3).map(([a, b]) => k.iso([a, b, 75], P)), { size: 0.55 }));
  out.push(placa(x + 8, y + 14, 75, 48, coordina ? "Coordinadora" : "Frente"));
  if (coordina) out.push(placa(x + 8, y + 31, 75, 48, "Meta-harness"));
  return out.join("");
}

export function build() {
  const body = [`<path class="iso-halo" d="${k.haloOf(base, -12, 12, P)}"/>`];
  for (const [x, y] of k.corners(base, 12)) body.push(slab(plan(x - 4, y - 4, 8, 8), -12, 8, { tone: "lo" }));
  body.push(slab(base, -4, 4));
  // Dos carriles de correo sobre la mesa. Cada uno tiene sus bordes y topes.
  for (const y of [18, 49]) {
    body.push(slab(plan(-150, y, 300, 22), 0, 3, { tone: "lo" }));
    for (const dy of [0, 20]) body.push(slab(plan(-150, y + dy, 300, 2), 3, 3));
    for (const x of [-150, 147]) body.push(slab(plan(x, y + 2, 3, 18), 3, 3));
  }
  const xs = [-153, -73, 7, 87].sort((a, b) => k.depthOf([a, -30, 0], P) - k.depthOf([b, -30, 0], P));
  for (const x of xs) body.push(estacion(x, x === -153));
  body.push(ficha(-125, 23, 3, acento.ambar), ficha(35, 23, 3, acento.ambar), ficha(-45, 54, 3, acento.verde));
  body.push(placa(-85, 24, 3, 55, "Encargos"), placa(55, 55, 3, 55, "Informes"));
  return write("fabrica", { width, height, body,
    label: "Mesa de una fábrica de software: la coordinadora y tres frentes ilustrativos trabajan en estaciones rodeadas por el meta-harness. Dos carriles llevan encargos e informes; el cajón conserva la ronda.",
    card: { fig: "Fig 9", title: "La fábrica de software", hint: "Encargos de ida · informes de vuelta", readout: "La coordinadora verifica el árbol",
      keys: [{ mark: "lit", label: "Puesto iluminado: coordinadora y veredictos" },
        { mark: "raised", label: "Marcos: meta-harness; instrumentos interiores: agentes" },
        { mark: "flat", label: "Fichas ámbar: encargos; verdes: informes; cajones: rondas" }],
      caption: "La coordinadora reparte frentes, recibe informes y verifica el software antes de decidir la ronda siguiente. El marco de cada estación representa lanzamiento, hooks, permisos y controles. Las estaciones son ilustrativas: no representan un máximo de sesiones." } });
}
