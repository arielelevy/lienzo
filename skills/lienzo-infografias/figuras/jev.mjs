// Fig 6 del lienzo: Consultar Jev como una franqueadora de correo con colador.
import { acento, floorSvg, k, write } from "../kit.mjs";

const WIDTH = 640;
const HEIGHT = 440;

// Mundo: x en el sentido del correo (entra por la izquierda, sale por la derecha), y hacia el frente, z arriba.
const FLOOR = { x: -140, y: -64, w: 270, d: 130, r: 6 };
const BODY = { x: -38, y: -30, w: 72, d: 52, r: 3 };
const BODY_H = 34;
const RIGHT = BODY.x + BODY.w;
const FRONT = BODY.y + BODY.d;
const GRATE_X = -60;
const GRATE = [-26, 18]; // de dónde a dónde corre la reja en y
const SLOT_Y = [-13, 7]; // el hueco por donde pasa la muestra (ningún barrote entre -13 y 7)
const PAPER_Z = 12;

const P = k.fitProjection(
  [...k.boxCorners(FLOOR, -4, 0), [GRATE_X, GRATE[0], 40], [RIGHT + 40, 0, 20]],
  WIDTH,
  HEIGHT,
  { pad: 26, azimuth: 40, elevation: 30 },
);

const at = (p) => k.iso(p, P);
const S = (paths, style) => k.solidSvg(paths, style);
const L = (d, style) => k.lineSvg(d, style);
const D = (points, style) => k.dotsSvg(points, style);
const depth = (p) => k.depthOf(p, P);

// Un papel acostado con su pestaña de color.
function paper(x, y, z, clase, w = 24, tab = x + w - 6) {
  const out = [];
  out.push(S(k.slabOf({ x, y, w, d: 18, r: 0.6 }, z, 0.9, P, 1), { tone: "hi", crease: "none" }));
  out.push(S(k.slabOf({ x: tab, y: y + 18, w: 5, d: 2.4, r: 0.5 }, z, 0.9, P, 1), { tone: "hi", crease: "none", className: clase }));
  return out.join("");
}

// Lo que no sale: prompts, argumentos, resultados de herramientas y credenciales de la sesión, detrás de la reja.
function stack() {
  const out = [];
  const tray = { x: -122, y: -22, w: 50, d: 36, r: 2 };
  out.push(S(k.slabOf(tray, 0, 3, P, 3, 0.4), { tone: "lo" }));
  out.push(S(k.slabOf({ x: tray.x, y: tray.y, w: 2, d: tray.d, r: 0.4 }, 3, 10, P, 1), { tone: "mid" }));
  for (let i = 0; i < 5; i++) out.push(paper(tray.x + 8 + (i % 2) * 2, tray.y + 6 - (i % 2), 3 + i * 1.5, acento.rojo));
  return out.join("");
}

// El colador: una reja de barrotes con un solo hueco, a la altura de la muestra visible.
function grate() {
  const out = [];
  out.push(S(k.slabOf({ x: GRATE_X - 3, y: GRATE[0] - 3, w: 6, d: GRATE[1] - GRATE[0] + 6, r: 1 }, 0, 3, P, 2, 0.4), { tone: "mid" }));
  const bars = [];
  for (let y = GRATE[0]; y <= GRATE[1]; y += 4) if (y < SLOT_Y[0] || y > SLOT_Y[1]) bars.push(y);
  for (const y of bars) out.push(S(k.cylinder(GRATE_X, y, 0.9, 3, 33, P, 12), { tone: "mid" }));
  // Travesaño de arriba.
  out.push(S(k.slabOf({ x: GRATE_X - 2, y: GRATE[0] - 2, w: 4, d: GRATE[1] - GRATE[0] + 4, r: 0.8 }, 36, 3, P, 2, 0.4), { tone: "mid" }));
  return out.join("");
}

// La muestra visible, pasando por el hueco hacia la franqueadora.
function sample() {
  return paper(GRATE_X - 12, SLOT_Y[0] + 1, PAPER_Z, acento.verde, 32, GRATE_X - 10); // y de -12 a 6, dentro del hueco; la pestaña, del lado que se ve
}

function machine() {
  const out = [];
  out.push(S(k.slabOf(BODY, 0, BODY_H, P, 3, 0.8), { tone: "mid", inner: L(k.sideSeam(BODY, 8, P, 3), { tone: "faint" }) }));
  out.push(S(k.slabOf(k.insetPlan(BODY, -1.5), BODY_H, 3, P, 3, 0.8), { tone: "mid" }));
  const top = BODY_H + 3;
  // Visor del franqueo: antes de enviar se reserva el máximo de la cotización.
  const win = { x: BODY.x + 8, y: BODY.y + 8, w: 38, d: 16, r: 1.2 };
  out.push(S(k.slabOf(win, top, 1.2, P, 2), { tone: "lo" }));
  out.push(k.faceTextSvg(k.topMatrix([win.x + win.w / 2, win.y + win.d / 2 + 2.4], top + 1.2, P, "x"), "máx. cotizado", { size: 4.2, tone: "hi", anchor: "middle" }));
  // Botones de cifras.
  for (let i = 0; i < 3; i++) out.push(S(k.slabOf({ x: BODY.x + 52, y: BODY.y + 8 + i * 6, w: 10, d: 4, r: 1 }, top, 1.6, P, 2), { tone: "hi" }));
  // Ranura de salida en la cara derecha.
  out.push(S(k.slabOf({ x: RIGHT, y: -16, w: 1.2, d: 30, r: 0.4 }, PAPER_Z - 2, 4, P, 1), { tone: "lo", crease: "none" }));
  // Llave de autorización en el frente: una consulta, girada.
  const key = { x: BODY.x + 14, y: FRONT, w: 10, d: 2, r: 1 };
  out.push(S(k.slabOf(key, 14, 10, P, 2, 0.3), { tone: "lo" }));
  out.push(S(k.slabOf({ x: key.x + 3.5, y: FRONT + 2, w: 3, d: 6, r: 0.6 }, 17.5, 3, P, 2), { tone: "hi", className: acento.verde }));
  out.push(S(k.slabOf({ x: key.x + 2, y: FRONT + 8, w: 6, d: 2.4, r: 0.8 }, 16.5, 5, P, 2), { tone: "hi", className: acento.verde }));
  // Placa de la casa: un solo proveedor, con ZDR y sin recolección, sin reintentos.
  out.push(S(k.slabOf({ x: BODY.x + 36, y: FRONT, w: 26, d: 0.8, r: 0.3 }, 14, 8, P, 2), { tone: "lo", crease: "none" }));
  out.push(k.faceTextSvg(k.sideMatrix([BODY.x + 49, FRONT + 0.8], 19.5, P, "left"), "ZDR · sin reintentos", { size: 2.5, tone: "mid", anchor: "middle" }));
  return out.join("");
}

// El sobre que sale, con el sello ámbar de la reserva.
function envelope() {
  const out = [];
  const env = { x: RIGHT - 4, y: -14, w: 40, d: 26, r: 0 };
  const z = PAPER_Z - 0.6;
  out.push(S(k.slabOf(env, z, 1.2, P, 1), { tone: "hi" }));
  out.push(L(k.onTop([[env.x + env.w, env.y], [env.x + env.w - 13, env.y + env.d / 2], [env.x + env.w, env.y + env.d]], z + 1.2, P), { tone: "lo" }));
  out.push(S(k.slabOf({ x: env.x + 8, y: env.y + env.d - 10, w: 8, d: 7, r: 0.6 }, z + 1.2, 0.6, P, 2), { tone: "hi", crease: "none", className: acento.ambar }));
  return out.join("");
}

// El libro de cuentas: reservas y costos informados, renglón por renglón.
function ledger() {
  const out = [];
  const book = { x: 44, y: -54, w: 54, d: 30, r: 1 };
  out.push(S(k.slabOf(book, 0, 3, P, 2, 0.4), { tone: "mid" }));
  const half = { ...book, w: book.w / 2 - 1 };
  for (const page of [{ ...half, x: book.x + 1, y: book.y + 1, d: book.d - 2 }, { ...half, x: book.x + book.w / 2, y: book.y + 1, d: book.d - 2 }]) {
    out.push(S(k.slabOf(page, 3, 1, P, 1), { tone: "hi" }));
    for (let i = 0; i < 5; i++) {
      const y = page.y + 5 + i * 4.6;
      out.push(L(k.lineOnTop([page.x, y], [page.x + page.w, y], 4, P), { tone: "faint" }));
    }
  }
  // La última reserva, marcada en ámbar.
  out.push(S(k.slabOf({ x: book.x + book.w / 2 + 3, y: book.y + 20, w: 18, d: 2.6, r: 0.4 }, 4, 0.4, P, 1), { tone: "hi", crease: "none", className: acento.ambar }));
  // Lapicera.
  out.push(S(k.slabOf({ x: book.x + 6, y: book.y + book.d + 3, w: 30, d: 2.6, r: 1.2 }, 0, 2.6, P, 3), { tone: "mid" }));
  return out.join("");
}

const items = [
  { key: depth([-97, -4, 0]), svg: stack() },
  { key: depth([71, -39, 0]), svg: ledger() },
  { key: depth([GRATE_X, 0, 0]), svg: grate() },
  { key: depth([GRATE_X, 0, 0]) + 0.01, svg: sample() },
  { key: depth([BODY.x + BODY.w / 2, BODY.y + BODY.d / 2, 0]), svg: machine() },
  { key: depth([RIGHT + 16, 0, 0]), svg: envelope() },
].sort((a, b) => a.key - b.key);

const label =
  "Consultar Jev en Lienzo dibujado como una franqueadora de correo con colador. A la izquierda, una pila de papeles con pestaña roja (prompts, argumentos, resultados de herramientas y credenciales de la sesión) queda detrás de una reja. " +
  "Por el único hueco pasa la muestra visible de métricas y referencias, con pestaña verde. La franqueadora tiene la llave de autorización girada para una consulta manual, un visor que reserva el máximo cotizado y la placa «ZDR · sin reintentos». " +
  "Por la derecha sale el sobre con su sello ámbar, y al fondo el libro de cuentas guarda la reserva.";

export function build() {
  return write("jev", {
    width: WIDTH,
    height: HEIGHT,
    label,
    body: [floorSvg(FLOOR, P), ...items.map((item) => item.svg)],
    card: {
      fig: "Fig 6",
      title: "Consultar Jev",
      hint: "Sólo pasa la muestra visible",
      readout: "1 consulta manual autorizada · máximo reservado",
      keys: [
        { mark: "red", label: "Pestaña roja: prompts, argumentos, resultados de herramientas y credenciales de la sesión; no pasan la reja (la clave de OpenRouter sólo autoriza el pedido)" },
        { mark: "green", label: "Pestaña y llave verdes: la muestra visible y la consulta paga que autorizó la persona" },
        { mark: "raised", label: "Sello y renglón ámbar: se reserva el máximo cotizado (hasta USD 0,002688); el libro guarda reservas y costos informados" },
      ],
      caption:
        "A mano, Consultar Jev envía solamente la muestra visible de métricas y referencias tras autorizar una consulta paga, a un único proveedor con ZDR, sin reintentos. " +
        "El piloto, si está habilitado, consulta solo dentro de su ventana y su tope de intentos. Un cargo sin cota o un proveedor sin máximo comprobable bloquean la próxima. Jev propone; no instala, aprueba ni ejecuta.",
    },
  });
}
