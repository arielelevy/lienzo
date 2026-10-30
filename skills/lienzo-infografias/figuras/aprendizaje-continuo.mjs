// Figure: fichero escalonado, banco de contraste y carril de devolución.
// Piezas: base y patas (5), 4 bandejas con placa de 9 (36), banco (14), retorno (9): 64.
// Los niveles y las tres salidas proceden del código; no son métricas de eficacia.
import { k, acento, write } from "../kit.mjs";

const width = 760, height = 450;
const base = { x: -170, y: -70, w: 340, d: 155, r: 5 };
const P = k.fitProjection(k.boxCorners(base, -12, 95), width, height,
  { pad: 35, azimuth: 55, elevation: 36 });
const plan = (x, y, w, d, r = 1) => ({ x, y, w, d, r });
const slab = (p, z, h, style = {}) => k.solidSvg(k.slabOf(p, z, h, P, 4, 0.6), { tone: "mid", ...style });

function bandeja(x, z, nombre) {
  const y = -52, out = [slab(plan(x, y, 42, 54, 2), 0, z + 3, { tone: "lo" })];
  for (const dx of [0, 39]) out.push(slab(plan(x + dx, y, 3, 54), z + 3, 9));
  out.push(slab(plan(x + 3, y, 36, 3), z + 3, 9));
  for (let i = 0; i < 3; i++) {
    const py = y + 8 + i * 12;
    out.push(slab(plan(x + 7, py, 28, 9), z + 3, 1, { tone: "hi" }));
    out.push(k.lineSvg(k.segment([x + 11, py + 4, z + 4], [x + 30, py + 4, z + 4], P), { tone: "lo", free: true }));
  }
  out.push(slab(plan(x + 15, y + 54, 12, 3), z - 1, 4,
    { className: nombre === "Creencias" ? acento.ambar : acento.verde }));
  out.push(slab(plan(x + 2, y + 54, 38, 0.8), z - 10, 8, { tone: "lo" }));
  out.push(k.faceTextSvg(k.sideMatrix([x + 21, y + 54.8], z - 8, P, "left"),
    nombre, { size: 4.8, tone: "hi", anchor: "middle" }));
  return out.join("");
}

function contraste() {
  const out = [], x = 82, y = -54;
  out.push(slab(plan(x, y, 72, 58, 3), 0, 6, { tone: "lo" }));
  // Prensa de comprobación: montantes, puente, émbolo cuadrado y matriz.
  for (const dx of [3, 61]) out.push(slab(plan(x + dx, y + 4, 8, 44), 6, 73));
  out.push(slab(plan(x + 31, y + 17, 10, 16), 47, 32, { tone: "hi" }));
  out.push(slab(plan(x + 17, y + 12, 38, 29), 42, 5, { tone: "hi" }));
  out.push(slab(plan(x + 17, y + 12, 38, 29), 6, 5, { tone: "hi", lit: true }));
  for (const dx of [22, 33, 44]) out.push(slab(plan(x + dx, y + 19, 6, 16), 11, 3));
  for (const [dx, color] of [[17, acento.verde], [33, acento.rojo], [49, acento.ambar]])
    out.push(slab(plan(x + dx, y + 49, 8, 6), 6, 3, { className: color }));
  out.push(slab(plan(x + 27, y + 58, 18, 4), 1, 4, { tone: "hi" }));
  // El puente tapa el extremo superior del émbolo que llega a su cara inferior.
  out.push(slab(plan(x + 3, y + 4, 66, 44), 79, 7));
  out.push(k.dotsSvg(k.corners(plan(x + 3, y + 4, 66, 44), 4).map(([a, b]) => k.iso([a, b, 86], P)), { size: 0.55 }));
  out.push(k.lineSvg(k.planOutline(plan(x + 15, y + 16, 42, 12), 86, P), { tone: "lo" }));
  out.push(k.faceTextSvg(k.topMatrix([x + 36, y + 24], 86, P, "x"), "Prolog",
    { size: 6, tone: "hi", anchor: "middle" }));
  return out.join("");
}

export function build() {
  const body = [`<path class="iso-halo" d="${k.haloOf(base, -12, 12, P)}"/>`];
  for (const [x, y] of k.corners(base, 12)) body.push(slab(plan(x - 4, y - 4, 8, 8), -12, 8, { tone: "lo" }));
  body.push(slab(base, -4, 4));
  const trays = [[-154, 16], [-98, 28], [-42, 40], [14, 52]];
  const nombres = ["1 Crudo", "2 Cómo", "3 Qué", "Creencias"];
  const stations = trays.map(([x, z], i) => ({ key: k.depthOf([x, -30, 0], P), svg: bandeja(x, z, nombres[i]) }));
  stations.push({ key: k.depthOf([118, -30, 0], P), svg: contraste() });
  body.push(...stations.sort((a, b) => a.key - b.key).map(s => s.svg));
  // Carril frontal que devuelve lo revisado a contexto, checklist y controles.
  body.push(slab(plan(-150, 30, 300, 36), 0, 3, { tone: "lo" }));
  for (const y of [30, 64]) body.push(slab(plan(-150, y, 300, 2), 3, 3));
  for (const [x, nombre] of [[-127, "Contexto"], [-27, "Checklist"], [73, "Controles"]]) {
    body.push(slab(plan(x, 38, 40, 18), 3, 2, { tone: "hi" }));
    body.push(slab(plan(x + 5, 43, 6, 8), 5, 1, { className: acento.verde }));
    body.push(k.faceTextSvg(k.topMatrix([x + 25, 49], 5, P, "x"), nombre,
      { size: 4, tone: "hi", anchor: "middle" }));
  }
  return write("aprendizaje-continuo", { width, height, body,
    label: "Fichero escalonado: nivel 1 crudo, nivel 2 cómo se hizo, nivel 3 qué se hizo, y creencias propuestas. La prensa representa Prolog: contraste, contraejemplos y deducción. El carril frontal devuelve aprendizajes revisados al contexto de sesión, checklist y controles.",
    card: { fig: "Fig 10", title: "Aprendizaje que vuelve al trabajo", hint: "Registrar · resumir · proponer · contrastar", readout: "La vigencia exige veredicto",
      keys: [{ mark: "raised", label: "Bandejas: crudo, proceso, resultados y creencias" },
        { mark: "lit", label: "Prensa Prolog: contraste, contraejemplos y deducción" },
        { mark: "flat", label: "Carril de retorno: contexto, checklist y controles" }],
      caption: "La escalera representa niveles de lectura, no una conversión obligatoria de toda captura. El resumidor produce nivel 3 en segundo plano; el investigador propone creencias. Prolog trabaja con hechos y reglas formalizadas, conserva pruebas y no otorga vigencia por sí solo." } });
}
