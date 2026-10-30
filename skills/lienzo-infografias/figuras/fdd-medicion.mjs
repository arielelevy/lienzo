// Medición del piloto de FDD (2026-10-26): retomar una feature con y sin el mapa del dominio.
// Datos de .temp/coordinacion/2026-10-26/ftd-fdd-ia.md: dos sesiones Codex nuevas, mismas 5 preguntas.
import { acento, k, write } from "../kit.mjs";

const WIDTH = 640;
const HEIGHT = 460;

// Lo medido: tokens de entrada (y cuántos sin caché), comandos para explorar y aciertos.
const CON = { tokens: 161510, nuevos: 24934, comandos: 4, aciertos: 5 };
const SIN = { tokens: 281865, nuevos: 56073, comandos: 8, aciertos: 5 };
const ALTO_MAX = 150; // la pila de «sin mapa»; la otra, en proporción exacta
const alto = (t) => (t / SIN.tokens) * ALTO_MAX;

// Mundo: x a lo ancho, y hacia el frente, z arriba. Una pila de hojas por condición.
const FLOOR = { x: -120, y: -50, w: 230, d: 150, r: 6 };
const PILAS = [
  { m: CON, x: -96, nombre: "con mapa" },
  { m: SIN, x: 6, nombre: "sin mapa" },
];
const PILA = { y: -30, w: 70, d: 50 };
const HOJA = 6; // alto de cada hoja de la pila

const P = k.fitProjection(
  [...k.boxCorners(FLOOR, -4, 0), [PILAS[1].x, PILA.y, ALTO_MAX + 10], [PILAS[1].x + PILA.w, PILA.y + PILA.d, ALTO_MAX]],
  WIDTH,
  HEIGHT,
  { pad: 24, azimuth: 50, elevation: 30 },
);

const at = (p) => k.iso(p, P);
const S = (paths, style) => k.solidSvg(paths, style);
const L = (d, style) => k.lineSvg(d, style);
const D = (points, style) => k.dotsSvg(points, style);
const frente = PILA.y + PILA.d;

// Una pila de hojas: lo leído de caché en tono medio, lo nuevo arriba en ámbar.
function pila({ m, x, nombre }) {
  const out = [];
  const plan = { x, y: PILA.y, w: PILA.w, d: PILA.d, r: 1.5 };
  const total = alto(m.tokens);
  const cache = total - alto(m.nuevos);
  const hojas = [];
  for (let z = HOJA; z < cache; z += HOJA) hojas.push(z);
  out.push(S(k.slabOf(plan, 0, cache, P, 2, 0.4), { tone: "mid", inner: hojas.map((z) => L(k.segment([x, frente, z], [x + PILA.w, frente, z], P), { tone: "faint", free: true })).join("") }));
  out.push(S(k.slabOf(plan, cache, total - cache, P, 2, 0.4), { tone: "hi", className: acento.ambar }));
  // Rótulo al frente y número de tokens arriba.
  out.push(k.faceTextSvg(k.sideMatrix([x + PILA.w / 2, frente], 14, P, "left"), nombre, { size: 7, tone: "hi", anchor: "middle" }));
  out.push(k.faceTextSvg(k.sideMatrix([x + PILA.w / 2, frente], cache - 6, P, "left"), m.tokens.toLocaleString("es-AR"), { size: 6, tone: "mid", anchor: "middle" }));
  return out.join("");
}

// Los comandos que corrió para orientarse: una clavija por comando, delante de su pila.
function comandos({ m, x }) {
  const out = [];
  const paso = PILA.w / 8;
  for (let i = 0; i < m.comandos; i++) {
    out.push(S(k.cylinder(x + paso / 2 + i * paso, frente + 14, 2.6, 0, 7, P, 14), { tone: "hi" }));
  }
  return out.join("");
}

// Los aciertos: cinco lámparas verdes en una regleta, las dos completas.
function aciertos({ m, x }) {
  const out = [];
  const regleta = { x: x + 6, y: frente + 26, w: PILA.w - 12, d: 10, r: 1 };
  out.push(S(k.slabOf(regleta, 0, 3, P, 2, 0.3), { tone: "lo" }));
  const paso = regleta.w / 5;
  for (let i = 0; i < m.aciertos; i++) {
    out.push(S(k.cylinder(regleta.x + paso / 2 + i * paso, regleta.y + 5, 2.2, 3, 2, P, 14), { tone: "hi", className: acento.verde }));
  }
  return out.join("");
}

// El mapa del dominio: una hoja plana con entidades unidas, delante de «con mapa», que la leyó primero.
function mapa() {
  const out = [];
  const hoja = { x: -92, y: frente + 42, w: 62, d: 30, r: 0.8 };
  const z = 1.4;
  out.push(S(k.slabOf(hoja, 0, z, P, 1), { tone: "hi", crease: "none" }));
  const nodos = [
    [hoja.x + 10, hoja.y + 8],
    [hoja.x + 30, hoja.y + 20],
    [hoja.x + 50, hoja.y + 9],
    [hoja.x + 16, hoja.y + 17],
  ];
  for (const [a, b] of [[0, 1], [1, 2], [1, 3]]) {
    out.push(L(k.segment([...nodos[a], z], [...nodos[b], z], P), { tone: "lo", free: true }));
  }
  for (const [x, y] of nodos) out.push(S(k.slabOf({ x: x - 3, y: y - 2, w: 6, d: 4, r: 0.6 }, z, 1.6, P, 1), { tone: "mid" }));
  out.push(k.faceTextSvg(k.topMatrix([hoja.x + 4, hoja.y + hoja.d - 3], z, P), "docs/dominio.md", { size: 4.4, tone: "mid" }));
  return out.join("");
}

// De atrás hacia adelante: la pila «sin mapa» queda más lejos, así que va antes que «con mapa».
const [con, sin] = PILAS;
const body = [`<path class="iso-halo" d="${k.haloOf(FLOOR, 0, 7, P)}"/>`, pila(sin), pila(con), comandos(sin), aciertos(sin), comandos(con), aciertos(con), mapa()];

const label =
  "Medición del piloto de FDD. Dos pilas de hojas muestran los tokens de entrada que leyó una sesión nueva para retomar la misma feature: " +
  `con el mapa del dominio, ${CON.tokens.toLocaleString("es-AR")}; sin el mapa, ${SIN.tokens.toLocaleString("es-AR")}. La parte ámbar de arriba son los tokens nuevos, ` +
  `sin caché: ${CON.nuevos.toLocaleString("es-AR")} contra ${SIN.nuevos.toLocaleString("es-AR")}. Delante, una clavija por comando de exploración (${CON.comandos} contra ${SIN.comandos}) ` +
  "y cinco lámparas verdes por pila: las dos acertaron las cinco preguntas. Al frente, la hoja del mapa del dominio, docs/dominio.md, que leyó la de la izquierda.";

export function build() {
  return write("fdd-medicion", {
    width: WIDTH,
    height: HEIGHT,
    label,
    body,
    card: {
      fig: "Piloto",
      title: "Retomar una feature, con y sin mapa",
      hint: "La altura es lo que leyó",
      readout: "43 % menos tokens · 5/5 en las dos",
      keys: [
        { mark: "raised", label: "Ámbar: tokens nuevos, sin caché" },
        { mark: "green", label: "Lámpara verde: respuesta correcta" },
      ],
      caption: "Dos sesiones Codex nuevas, mismo modelo, mismas cinco preguntas. Una muestra por condición: es un primer indicio.",
    },
  });
}
