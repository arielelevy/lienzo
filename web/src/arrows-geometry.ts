import type { Link, Rule } from "./types";

/** Geometria de las flechas del tablero, sin DOM ni React: funciones puras sobre rectangulos ya
 *  medidos. El componente Arrows lee los rects del DOM, llama a `computeSegs` y dibuja. Misma
 *  entrada, misma salida: todo lo que depende del reloj (hace cuanto, hora local) entra por `fmt`. */

export interface Rect {
  l: number;
  t: number;
  r: number;
  b: number;
}
export type Pt = [number, number];
/** grupo de tarjetas con el mismo borde izquierdo (una columna ancha con dos subcolumnas son dos) */
export interface Col {
  l: number;
  r: number;
}
/** franja horizontal que ocupa una columna colapsada: obstaculo, no columna */
export type Strip = Col;

/** Area util de una columna del tablero, medida en el DOM: sus bordes, el techo (borde inferior del
 *  encabezado, porque una flecha por encima tapa el titulo) y el piso. Si el tablero reservo el
 *  carril de las flechas, `lane` es la y del medio de ese carril. */
export interface Band {
  l: number;
  r: number;
  /** techo: borde inferior del encabezado de la columna. Nada de la flecha va por encima */
  t: number;
  /** piso: borde inferior de la columna */
  b: number;
  /** y del medio del carril reservado entre el encabezado y la primera tarjeta, si lo hay */
  lane?: number;
}

/** Donde pueden vivir los tramos y los glifos: las columnas medidas y las tiras colapsadas.
 *  **Sin columnas medidas (`bands` vacio) la geometria no restringe nada**, que es como se comporto
 *  hasta que el tablero supo decir donde termina el encabezado de cada columna. */
export interface Zone {
  bands: Band[];
  strips: Strip[];
}
export const FREE_ZONE: Zone = { bands: [], strips: [] };

export interface Seg {
  /** ids de todos los links agrupados (o el id de la regla) */
  ids: string[];
  kind: "link" | "rule" | "native";
  from: string;
  to: string;
  d: string;
  x: number;
  y: number;
  /** una linea, para el tooltip del glifo */
  title: string;
  /** que es esta flecha y que hace, en una o dos frases; se muestra mientras esta seleccionada y
   *  siempre termina diciendo que hace el doble click (es lo que enseña el gesto) */
  desc: string;
  glyph: string;
  /** canal nativo con mas de una hora: se dibuja apagado y sin punta */
  old: boolean;
  /** reservado: instante (ms) de un envio recien hecho. Hoy nunca se setea (la ultima flecha del par
   *  se ve siempre) y el componente no lo usa */
  fresh?: number;
  /** no hubo camino limpio (cruza una tercera tarjeta, o no entra en el area util): se dibuja
   *  igual, con opacidad baja */
  dim?: boolean;
  /** y del carril por el que corre (antes de repartir pistas). El tablero reserva el alto del
   *  carril mas cargado y solo si hay al menos una flecha que lo use */
  lane?: number;
  /** rectangulos de las dos puntas: seleccionada, la flecha las resalta para que se vea de quien
   *  a quien es */
  ends: [Rect, Rect];
}

/** Lo que hay que dibujar, antes de saber por donde pasa. */
export type Item = Omit<Seg, "d" | "x" | "y" | "dim" | "lane" | "ends">;

/** textos que dependen del reloj o de la zona horaria: los inyecta el componente */
export interface Formatters {
  /** "57 min", "2 h": hace cuanto fue un instante ISO */
  ago: (iso: string) => string;
  /** "20:53": hora local de un instante ISO */
  hhmm: (iso: string) => string;
  /** "lienzo · Encargo R1": como se llama una sesion */
  name: (sid: string) => string;
  /** "a las 22:19", "el vie 11/9 a las 22:19": una hora que puede no ser hoy */
  when: (iso: string) => string;
}

export interface GeometryInput {
  /** tarjetas visibles, por session id, relativas al tablero */
  rects: Map<string, Rect>;
  /** extremos posibles de una flecha: las tarjetas mas las tiras colapsadas de sesiones sin tarjeta */
  anchors: Map<string, Rect>;
  /** columnas colapsadas (obstaculos laterales) */
  strips: Strip[];
  /** ancho total del tablero (scrollWidth): pared derecha */
  boardWidth: number;
  /** area util de cada columna (abierta o colapsada). Vacio o ausente: sin restriccion */
  bands?: Band[];
  links: Link[];
  rules: Rule[];
  fmt: Formatters;
}

/** medio canal por defecto, si no se puede medir el hueco entre columnas abiertas */
export const HALF_GAP = 20; // la mitad del canal entre columnas (28 px) mas un poco de aire
/** separacion vertical entre flechas que salen o entran por el mismo lado de una tarjeta */
export const SLOT = 14;
/** dos tarjetas con bordes izquierdos a menos de esto son de la misma columna */
export const COL_TOL = 40;
/** radio de exclusion de un glifo ya puesto, para que dos flechas del mismo canal no se pisen */
const GLYPH_R = 22;
/** alto de un carril de flechas: la corrida horizontal va al medio y queda la mitad de aire a cada
 *  lado. Vale igual arriba, entre dos filas y abajo: es una sola regla (ver `freeLanes`). */
export const LANE_H = 28;
/** aire minimo a cada lado de la corrida. Una franja mas fina que el doble de esto se usa igual,
 *  pero pierde contra cualquier carril de verdad: es lo que evita que la linea roce una tarjeta */
export const LANE_CLEAR = 8;
/** separacion entre dos pistas del mismo carril: como las lineas de un mapa de subte */
export const TRACK_GAP = 7;
/** alto maximo que se le pide al tablero para un carril: con muchas flechas es mejor que se
 *  encimen un poco a que la columna quede con un hueco enorme arriba */
export const LANE_MAX = 60;

/** Alto que necesita un carril que lleva `n` flechas: el aire minimo a cada lado mas una pista por
 *  flecha. Es lo que el tablero reserva en el CSS de la columna (ver `data-lanes`). */
export const laneHeight = (n: number) => Math.min(LANE_MAX, 2 * LANE_CLEAR + n * TRACK_GAP);
/** aire por encima de la primera fila (o debajo de la ultima) cuando no hay columnas medidas */
export const TOP_MARGIN = LANE_H / 2;
/** radio de las esquinas redondeadas del camino ortogonal */
const CORNER = 8;
/** a cuanto del borde se saca un glifo que cayo adentro de una tarjeta */
const EJECT = 6;

export const cut = (t: string, n = 90) => (t.length > n ? `${t.slice(0, n).trimEnd()}…` : t);
export const midY = (r: Rect) => (r.t + r.b) / 2;
const midX = (r: Rect) => (r.l + r.r) / 2;
export const sameRect = (a: Rect, b: Rect) => a === b || (a.l === b.l && a.t === b.t && a.r === b.r && a.b === b.b);
/** el punto cae estrictamente adentro del rectangulo (eps de tolerancia en el borde) */
const contains = (c: Rect, x: number, y: number, eps = 0.5) => x > c.l + eps && x < c.r - eps && y > c.t + eps && y < c.b - eps;

/** agrega v a la lista de k, creandola si no existe */
function pushTo<K, V>(m: Map<K, V[]>, k: K, v: V): void {
  const arr = m.get(k);
  if (arr) arr.push(v);
  else m.set(k, [v]);
}

/** n posiciones alrededor de `center`, a SLOT una de otra, sin pasar de `size - pad` en total: asi
 *  varias flechas que comparten un borde no se pisan ni desbordan una tarjeta chica */
function spread(n: number, center: number, size: number, pad: number): number[] {
  const span = Math.min((n - 1) * SLOT, Math.max(0, size - pad));
  const step = n > 1 ? span / (n - 1) : 0;
  return Array.from({ length: n }, (_, i) => center - span / 2 + i * step);
}

/** Periodo de una regla "at" periodica, en palabras: "cada 5 min", "cada 30 min", "cada hora",
 *  "cada 2 h", "cada día". Vive aca (y no en Card) para que el modulo siga sin React: Card la
 *  reexporta y Panel/Arrows la toman de ahi. */
export function periodLabel(everyS: number | null | undefined): string {
  const s = Math.max(60, Math.round(everyS ?? 0));
  if (s % 86400 === 0) return s === 86400 ? "cada día" : `cada ${s / 86400} días`;
  if (s % 3600 === 0) return s === 3600 ? "cada hora" : `cada ${s / 3600} h`;
  if (s % 60 === 0) return `cada ${s / 60} min`;
  return `cada ${s} s`;
}

/** "(1/5, próx. 09:30)" o "(1/5)": disparos hechos sobre el tope y, si la hay, la proxima hora */
export function periodicCount(fired: number, maxFires: number, next: string | null): string {
  return next ? `(${fired}/${maxFires}, próx. ${next})` : `(${fired}/${maxFires})`;
}

/** "columnas" para las flechas = grupos de tarjetas con el mismo borde izquierdo, de izquierda a
 *  derecha. El canal de una curva es el hueco entre el grupo de salida y el vecino. */
export function groupColumns(cards: Rect[]): Col[] {
  const cols: Col[] = [];
  for (const c of [...cards].sort((a, d) => a.l - d.l)) {
    const last = cols[cols.length - 1];
    if (last && Math.abs(c.l - last.l) < COL_TOL) {
      last.r = Math.max(last.r, c.r);
    } else {
      cols.push({ l: c.l, r: c.r });
    }
  }
  return cols;
}

/** indice de la columna de un rect, -1 si no cae en ninguna (una tira colapsada, por ejemplo) */
export const colOf = (cols: Col[], rc: Rect) => cols.findIndex((c) => Math.abs(rc.l - c.l) < COL_TOL);

/** x del medio del canal a la derecha (dir 1) o a la izquierda (dir -1) de la columna i */
export function channelX(cols: Col[], i: number, dir: 1 | -1, fallback: number): number {
  const a = cols[i];
  const n = cols[i + dir];
  if (!a || !n) return fallback;
  return dir === 1 ? (a.r + n.l) / 2 : (n.r + a.l) / 2;
}

/** espacio libre a un costado de la columna i hasta lo primero que haya: otra columna, una tira
 *  colapsada o el borde del tablero */
export function freeAt(cols: Col[], strips: Strip[], boardWidth: number, i: number, dir: 1 | -1): number {
  const a = cols[i];
  if (!a) return 0;
  const walls = [...cols.filter((_, j) => j !== i), ...strips];
  if (dir === 1) {
    let x = boardWidth;
    for (const w of walls) if (w.l >= a.r - 1 && w.l < x) x = w.l;
    return x - a.r;
  }
  let x = 0;
  for (const w of walls) if (w.r <= a.l + 1 && w.r > x) x = w.r;
  return a.l - x;
}

/** cuanto lugar hay hacia `dir` desde la subcolumna `a` sin salirse de las columnas del tablero.
 *  Sin columnas medidas, todo el que diga `freeAt`. */
function outerRoom(bands: Band[], a: Col, dir: 1 | -1): number {
  if (!bands.length) return Infinity;
  return dir === 1 ? Math.max(...bands.map((b) => b.r)) - a.r : a.l - Math.min(...bands.map((b) => b.l));
}

/** arco entre dos tarjetas de la misma columna: por el costado con mas lugar (el canal vecino si
 *  lo hay, si no el aire que quede dentro de la columna); nunca por encima de una tarjeta ni fuera
 *  de las columnas. La panza se recorta al lugar real: sin eso, una columna pegada al borde
 *  izquierdo mandaba el arco (y su glifo) al padding del tablero, fuera de toda columna. */
export function sideArc(cols: Col[], strips: Strip[], boardWidth: number, i: number, bands: Band[] = []): { side: "l" | "r"; x: number } {
  const a = cols[i];
  const fr = Math.min(freeAt(cols, strips, boardWidth, i, 1), outerRoom(bands, a, 1));
  const fl = Math.min(freeAt(cols, strips, boardWidth, i, -1), outerRoom(bands, a, -1));
  const side: "l" | "r" = fl > fr ? "l" : "r";
  const room = side === "r" ? fr : fl;
  const bulge = Math.min(HALF_GAP, Math.max(20, room / 2), Math.max(0, room - 2));
  return { side, x: side === "r" ? a.r + bulge : a.l - bulge };
}

/** distancia al borde de la tarjeta mas cercana; negativa si el punto cae adentro de una */
export function clearance(cards: Rect[], x: number, y: number): number {
  let best = Infinity;
  for (const c of cards) {
    const dx = Math.max(c.l - x, 0, x - c.r);
    const dy = Math.max(c.t - y, 0, y - c.b);
    const d = dx || dy ? Math.hypot(dx, dy) : -Math.min(x - c.l, c.r - x, y - c.t, c.b - y);
    if (d < best) best = d;
  }
  return best;
}

/** el punto cae estrictamente adentro de alguna tarjeta (medio pixel de tolerancia en el borde) */
export const inside = (cards: Rect[], x: number, y: number, eps = 0.5) => cards.some((c) => contains(c, x, y, eps));

/** Glifo que cayo adentro de una tarjeta: se corre al hueco mas cercano, o sea al borde mas proximo
 *  de esa tarjeta mas EJECT px hacia afuera. Si ahi tambien hay tarjeta (filas pegadas), prueba
 *  los otros bordes en orden de cercania; si ninguno esta libre, se queda en el mas cercano. */
export function ejectGlyph(cards: Rect[], x: number, y: number): Pt {
  const c = cards.find((r) => contains(r, x, y));
  if (!c) return [x, y];
  const opts: { d: number; p: Pt }[] = (
    [
      { d: y - c.t, p: [x, c.t - EJECT] },
      { d: c.b - y, p: [x, c.b + EJECT] },
      { d: x - c.l, p: [c.l - EJECT, y] },
      { d: c.r - x, p: [c.r + EJECT, y] },
    ] as { d: number; p: Pt }[]
  ).sort((a, b) => a.d - b.d);
  return opts.find((o) => !inside(cards, o.p[0], o.p[1]))?.p ?? opts[0].p;
}

/** Franja vertical permitida en la x dada: [techo, piso]. Sin columnas medidas, todo. Dentro de una
 *  columna, de su encabezado a su piso; en el canal entre dos, manda la mas restrictiva de las dos.
 *  Fuera de las columnas (el padding del tablero) no entra nada: la franja sale vacia. */
export function slotAt(bands: Band[], x: number): [number, number] {
  if (!bands.length) return [-Infinity, Infinity];
  const hit = bands.filter((bd) => x >= bd.l && x <= bd.r);
  if (hit.length) return [Math.max(...hit.map((bd) => bd.t)), Math.min(...hit.map((bd) => bd.b))];
  let left: Band | undefined;
  let right: Band | undefined;
  for (const bd of bands) {
    if (bd.r < x && (!left || bd.r > left.r)) left = bd;
    if (bd.l > x && (!right || bd.l < right.l)) right = bd;
  }
  if (!left || !right) return [Infinity, -Infinity]; // afuera de todas: el padding del tablero
  return [Math.max(left.t, right.t), Math.min(left.b, right.b)];
}

/** el punto puede alojar un tramo de flecha: dentro de las columnas y debajo de los encabezados */
export function allowed(bands: Band[], x: number, y: number): boolean {
  const [t, b] = slotAt(bands, x);
  return y >= t && y <= b;
}

/** ademas de `allowed`, el glifo no puede caer sobre una tira colapsada: taparia su etiqueta */
export function glyphOk(zone: Zone, x: number, y: number): boolean {
  if (!zone.bands.length) return true;
  return allowed(zone.bands, x, y) && !zone.strips.some((s) => x > s.l && x < s.r);
}

/** El tramo horizontal de xa a xc a la altura y esta permitido en todo su recorrido. `slotAt` es
 *  constante entre borde y borde de columna, asi que alcanza con mirar los bordes y un punto entre
 *  cada dos (el medio del canal). */
export function runAllowed(bands: Band[], xa: number, xc: number, y: number): boolean {
  if (!bands.length) return true;
  const x1 = Math.min(xa, xc);
  const x2 = Math.max(xa, xc);
  const xs = [x1, x2];
  for (const bd of bands) for (const x of [bd.l, bd.r]) if (x > x1 && x < x2) xs.push(x);
  xs.sort((a, b) => a - b);
  for (let i = 0; i < xs.length; i++) {
    if (!allowed(bands, xs[i], y)) return false;
    if (i + 1 < xs.length && !allowed(bands, (xs[i] + xs[i + 1]) / 2, y)) return false;
  }
  return true;
}

/** Ultimo recurso para un glifo que quedo fuera de las columnas, por encima de un encabezado o sobre
 *  una tira colapsada: se corre al punto permitido mas cercano, adentro de alguna columna. */
export function clampGlyph(zone: Zone, x: number, y: number): Pt {
  if (glyphOk(zone, x, y)) return [x, y];
  let best: Pt = [x, y];
  let bestD = Infinity;
  for (const bd of zone.bands) {
    // una banda que coincide con una tira colapsada no sirve de refugio
    if (zone.strips.some((st) => bd.l >= st.l - 1 && bd.r <= st.r + 1)) continue;
    const p: Pt = [Math.min(Math.max(x, bd.l + EJECT), bd.r - EJECT), Math.min(Math.max(y, bd.t + EJECT), bd.b - EJECT)];
    const d = Math.hypot(p[0] - x, p[1] - y);
    if (d < bestD) {
      bestD = d;
      best = p;
    }
  }
  return best;
}

/** Carriles de una columna: las franjas horizontales sin tarjetas por donde puede correr una
 *  flecha, con la corrida (y el glifo) en el medio de la franja. Una sola regla para las tres
 *  posiciones que pide el tablero: arriba (entre el techo de la columna y la primera fila), en el
 *  medio (entre dos filas) y abajo (entre la ultima fila y el piso). Las franjas se calculan sobre
 *  todas las tarjetas juntas, asi una y libre lo es en todo el ancho del tablero; que el carril
 *  sirva para un recorrido concreto lo decide despues `segHits`. El carril se apoya en la fila de
 *  tarjetas (medio carril de aire) y se centra cuando la franja no da para tanto; `room` es el alto
 *  de la franja, que el ruteo usa para preferir un carril de verdad antes que un resquicio. Sin
 *  columnas medidas, el techo y el piso son medio carril por fuera de la primera y la ultima fila,
 *  que es como se ruteaba antes de que existieran los carriles. */
export function freeLanes(bands: Band[], cards: Rect[]): Lane[] {
  if (!cards.length) return [];
  const iv = cards.map((c) => [c.t, c.b] as [number, number]).sort((a, b) => a[0] - b[0]);
  const rows: [number, number][] = [[iv[0][0], iv[0][1]]];
  for (const [t, b] of iv.slice(1)) {
    const last = rows[rows.length - 1];
    if (t <= last[1]) last[1] = Math.max(last[1], b); // se superponen: es la misma fila
    else rows.push([t, b]);
  }
  const first = rows[0][0];
  const last = rows[rows.length - 1][1];
  const ceil = bands.length ? Math.max(...bands.map((bd) => bd.t)) : first - LANE_H;
  const floor = bands.length ? Math.min(...bands.map((bd) => bd.b)) : last + LANE_H;
  const ys: Lane[] = [];
  const add = (t: number, b: number, stick: "up" | "down" | "mid") => {
    const room = b - t;
    if (room <= 0) return;
    const y = room <= LANE_H || stick === "mid" ? (t + b) / 2 : stick === "up" ? t + LANE_H / 2 : b - LANE_H / 2;
    ys.push({ y, room, t, b });
  };
  add(ceil, first, "down"); // arriba: se apoya en la primera fila
  for (let i = 1; i < rows.length; i++) add(rows[i - 1][1], rows[i][0], "mid"); // entre dos filas
  add(last, floor, "up"); // abajo: se apoya en la ultima fila
  return ys;
}

/** punto de la cubica en t */
export function cubicAt(p0: Pt, p1: Pt, p2: Pt, p3: Pt, t: number): Pt {
  const u = 1 - t;
  return [
    u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
    u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1],
  ];
}

/** la cubica, muestreada en `n` puntos interiores, pasa por dentro de alguna de `others` */
export function cubicHits(others: Rect[], p0: Pt, p1: Pt, p2: Pt, p3: Pt, n = 20): boolean {
  for (let i = 1; i < n; i++) {
    const [px, py] = cubicAt(p0, p1, p2, p3, i / n);
    if (inside(others, px, py)) return true;
  }
  return false;
}

/** Cubica de p0 a p3 con controles p1 y p2, mas el punto donde va el circulo clickeable: el punto
 *  de la curva mas lejano a cualquier tarjeta (o sea, en el canal), para no robarle el click a una
 *  tarjeta; el centro desempata. Los circulos ya puestos (`taken`) cuentan como obstaculo, asi dos
 *  flechas que comparten canal no se pisan el glifo; el punto elegido se agrega a `taken`. Un punto
 *  adentro de una tarjeta (o fuera del area util de las columnas) pierde siempre contra uno afuera,
 *  por lejos que este de otros glifos; y si la curva entera va por adentro, el glifo se saca al
 *  hueco mas cercano (`ejectGlyph`) y, si hace falta, a la columna mas cercana (`clampGlyph`). */
export function cubic(cards: Rect[], taken: Pt[], p0: Pt, p1: Pt, p2: Pt, p3: Pt, zone: Zone = FREE_ZONE): { d: string; x: number; y: number } {
  const d = `M ${p0[0]} ${p0[1]} C ${p1[0]} ${p1[1]}, ${p2[0]} ${p2[1]}, ${p3[0]} ${p3[1]}`;
  let x = (p0[0] + p3[0]) / 2;
  let y = (p0[1] + p3[1]) / 2;
  let bestC = -Infinity;
  let bestT = 0.5;
  for (let t = 0.05; t <= 0.9501; t += 0.025) {
    const [px, py] = cubicAt(p0, p1, p2, p3, t);
    const clear = clearance(cards, px, py);
    let c = clear;
    for (const q of taken) c = Math.min(c, Math.hypot(px - q[0], py - q[1]) - GLYPH_R);
    if (clear < 0) c -= 10_000; // adentro de una tarjeta: solo si no hay otra cosa
    if (!glyphOk(zone, px, py)) c -= 20_000; // fuera del area util: peor todavia
    if (c > bestC + 0.5 || (Math.abs(c - bestC) <= 0.5 && Math.abs(t - 0.5) < Math.abs(bestT - 0.5))) {
      bestC = c;
      bestT = t;
      x = px;
      y = py;
    }
  }
  [x, y] = clampGlyph(zone, ...ejectGlyph(cards, x, y));
  taken.push([x, y]);
  return { d, x, y };
}

/** un segmento ortogonal (vertical u horizontal) de a a b corta el interior del rectangulo */
export function segHits(c: Rect, a: Pt, b: Pt, eps = 0.5): boolean {
  const x1 = Math.min(a[0], b[0]);
  const x2 = Math.max(a[0], b[0]);
  const y1 = Math.min(a[1], b[1]);
  const y2 = Math.max(a[1], b[1]);
  return x2 > c.l + eps && x1 < c.r - eps && y2 > c.t + eps && y1 < c.b - eps;
}

/** Camino ortogonal de tres tramos con esquinas redondeadas: vertical desde (xa, ya) hasta y,
 *  horizontal hasta xc, vertical hasta (xc, yc). El ultimo tramo es vertical, asi la punta de
 *  flecha entra por el borde superior (o inferior) del destino. */
export function orthoPath(xa: number, ya: number, y: number, xc: number, yc: number): string {
  const sx = Math.sign(xc - xa);
  const r = Math.min(CORNER, Math.abs(xc - xa) / 2, Math.abs(ya - y), Math.abs(yc - y));
  if (r < 1) return `M ${xa} ${ya} L ${xa} ${y} L ${xc} ${y} L ${xc} ${yc}`;
  const s1 = Math.sign(y - ya); // -1 sube, 1 baja
  const s2 = Math.sign(yc - y);
  const up = y - s1 * r === ya ? "" : ` L ${xa} ${y - s1 * r}`; // sin tramo recto si la esquina arranca en el borde
  return `M ${xa} ${ya}${up} Q ${xa} ${y}, ${xa + sx * r} ${y} L ${xc - sx * r} ${y} Q ${xc} ${y}, ${xc} ${y + s2 * r} L ${xc} ${yc}`;
}

/** un carril: la y por donde corre la flecha, la franja libre que lo aloja y su alto */
export interface Lane {
  y: number;
  room: number;
  /** bordes de la franja libre: entre `t` y `b` no hay ninguna tarjeta */
  t: number;
  b: number;
}

/** Pistas de un carril: `n` corridas paralelas separadas TRACK_GAP, centradas en la y del carril y
 *  siempre dentro de la franja libre con LANE_CLEAR de aire a cada lado. Si no entran, se comprimen
 *  (cuatro flechas encimadas se leen mejor que una columna con un hueco enorme arriba). */
export function tracks(n: number, lane: Lane): number[] {
  const lo = lane.t + LANE_CLEAR;
  const hi = lane.b - LANE_CLEAR;
  if (n <= 1 || !(hi > lo)) return Array.from({ length: n }, () => lane.y);
  const span = Math.min((n - 1) * TRACK_GAP, hi - lo);
  const step = span / (n - 1);
  const first = Math.min(Math.max(lane.y - span / 2, lo), hi - span);
  return Array.from({ length: n }, (_, i) => first + i * step);
}

export interface Ortho {
  d: string;
  x: number;
  y: number;
  /** ningun tramo cruza una tercera tarjeta y todo el camino entra en el area util */
  clean: boolean;
  /** por que borde sale del origen y entra al destino */
  exit: "t" | "b";
  enter: "t" | "b";
  /** carril elegido: las flechas que comparten uno se reparten en pistas paralelas */
  lane: Lane;
}

/** Flecha "por arriba" entre dos tarjetas: sale por el borde superior (o inferior) del origen en
 *  xa, corre en horizontal por un hueco entre filas (o por el margen del tablero) y baja al borde
 *  del destino en xc. Se prueban todos los huecos: el carril reservado de cada columna, el medio de
 *  cada hueco entre filas y los margenes de arriba y abajo. Manda quedar dentro del area util (nada
 *  por encima de un encabezado ni fuera de las columnas); despues, no cruzar una tercera tarjeta; a
 *  igualdad, el mas corto. O sea que un hueco interior le gana a uno de afuera aunque el camino sea
 *  mas largo. Si ninguno cumple las dos, el mejor igual, con `clean: false` (se dibuja apagado). El
 *  glifo va al medio de la corrida horizontal, que por construccion esta en un hueco. */
export function topRoute(ra: Rect, rc: Rect, xa: number, xc: number, cards: Rect[], zone: Zone = FREE_ZONE): Ortho {
  const others = cards.filter((c) => !sameRect(c, ra) && !sameRect(c, rc));
  // los carriles se buscan entre las tarjetas que el tramo horizontal podria cruzar (las que caen
  // en su franja de x). Mirando todas, una tarjeta alta de otra columna tapa el hueco entre dos
  // filas y el ruteo se queda sin el carril del medio
  const x1 = Math.min(xa, xc);
  const x2 = Math.max(xa, xc);
  const blockers = cards.filter((c) => c.r > x1 && c.l < x2);
  const ys = freeLanes(zone.bands, blockers.length ? blockers : cards);
  const outside = (r: Rect, y: number) => y <= r.t + 0.5 || y >= r.b - 0.5;
  let best: (Ortho & { len: number; score: number }) | null = null;
  for (const lane of ys) {
    const { y, room } = lane;
    if (!outside(ra, y) || !outside(rc, y)) continue; // tiene que salir por un borde, no por el medio
    const exit: "t" | "b" = y < ra.t ? "t" : "b";
    const enter: "t" | "b" = y < rc.t ? "t" : "b";
    const ya = exit === "t" ? ra.t : ra.b;
    const yc = enter === "t" ? rc.t : rc.b;
    const segs: [Pt, Pt][] = [
      [[xa, ya], [xa, y]],
      [[xa, y], [xc, y]],
      [[xc, y], [xc, yc]],
    ];
    const free = !others.some((c) => segs.some(([a, b]) => segHits(c, a, b)));
    const fits = runAllowed(zone.bands, xa, xc, y);
    // entrar en el area util pesa mas que esquivar tarjetas, y esquivarlas mas que el aire de sobra;
    // a igualdad, el camino mas corto. Un resquicio de 10 px pierde contra un carril de verdad
    const score = (fits ? 4 : 0) + (free ? 2 : 0) + (room >= 2 * LANE_CLEAR ? 1 : 0);
    const len = Math.abs(ya - y) + Math.abs(xa - xc) + Math.abs(y - yc);
    if (!best || score > best.score || (score === best.score && len < best.len - 0.5)) {
      best = { d: orthoPath(xa, ya, y, xc, yc), x: (xa + xc) / 2, y, clean: score >= 6, exit, enter, lane, len, score };
    }
  }
  const b = best!; // siempre hay al menos los dos margenes
  const [gx, gy] = clampGlyph(zone, ...ejectGlyph(cards, b.x, b.y));
  return { d: b.d, x: gx, y: gy, clean: b.clean, exit: b.exit, enter: b.enter, lane: b.lane };
}

/** 1) que hay que dibujar: canal nativo y ultimo envio por par (sin limite de tiempo; los
 *  anteriores del mismo par van al contador), mas las reglas activas con los dos extremos visibles.
 *  Orden: grupos de links en orden de primera aparicion, despues las reglas en su orden. */
/** primera letra en mayuscula, para arrancar una frase con "cada 2 h" o "el vie 11/9 a las 22:19" */
const cap = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);

export function buildItems(links: Link[], rules: Rule[], anchors: Map<string, Rect>, fmt: Formatters): Item[] {
  const items: Item[] = [];
  const groups = new Map<string, Link[]>();
  for (const l of links) {
    const native = l.kind === "native";
    const k = `${native ? "n" : "s"}|${l.from}|${l.to}`;
    const g = groups.get(k);
    if (g) g.push(l);
    else groups.set(k, [l]);
  }
  for (const g of groups.values()) {
    g.sort((a, c) => c.ts.localeCompare(a.ts)); // mas nuevo primero
    const newest = g[0];
    if (!anchors.has(newest.from) || !anchors.has(newest.to)) continue;
    const native = newest.kind === "native";
    const n = g.length;
    const a = fmt.name(newest.from);
    const b = fmt.name(newest.to);
    const when = fmt.ago(newest.ts);
    const head = native
      ? `canal nativo entre ${a} y ${b}, abierto hace ${when}`
      : n > 1
        ? `${n} envíos de ${a} a ${b}, el último hace ${when}`
        : `envío de ${a} a ${b}, hace ${when}`;
    const desc = native
      ? `${a} y ${b} tienen abierto el canal nativo desde hace ${when}. Doble click para ver lo que se dijeron.`
      : n > 1
        ? `${a} le mandó ${n} mensajes a ${b}. El último, hace ${when}. Doble click para verlos o mandar de nuevo.`
        : `${a} le mandó un mensaje a ${b} hace ${when}. Doble click para verlo o mandarlo de nuevo.`;
    items.push({
      ids: g.map((l) => l.id),
      kind: native ? "native" : "link",
      from: newest.from,
      to: newest.to,
      old: false, // sin limite de tiempo: la ultima flecha del par se ve igual siempre
      fresh: undefined,
      glyph: n > 1 ? `×${n}` : native ? "⇄" : "↪",
      title: `${head} · click para seleccionarla`,
      desc,
    });
  }
  for (const r of rules) {
    if (!r.enabled || !r.from || r.from === r.to || !anchors.has(r.from) || !anchors.has(r.to)) continue;
    const a = fmt.name(r.from);
    const b = fmt.name(r.to);
    const base = { ids: [r.id], kind: "rule" as const, from: r.from, to: r.to, old: false };
    const tail = " Doble click para editarla.";
    if (r.kind === "on_stop") {
      const count = r.repeat ? ` Van ${r.fired} de ${r.max_fires}.` : " Una sola vez.";
      items.push({
        ...base,
        glyph: "⏹",
        title: `cuando ${a} termine → su respuesta a ${b}${r.repeat ? ` (${r.fired}/${r.max_fires})` : ""} · click para seleccionarla`,
        desc: `Cada vez que ${a} cierre un turno, su respuesta se manda a ${b}.${count}${tail}`,
      });
    } else if (r.every_s) {
      // periodica: glifo ↻, y el titulo dice el periodo, cuantas veces fue y cuando es la proxima
      const next = r.at ? ` La próxima, ${fmt.when(r.at)}.` : "";
      const skip = r.skip_busy === false ? "" : " Se saltea si está trabajando.";
      items.push({
        ...base,
        glyph: "↻",
        title: `${periodLabel(r.every_s)} → «${r.text}» a ${b} ${periodicCount(r.fired, r.max_fires, r.at ? fmt.hhmm(r.at) : null)} · click para seleccionarla`,
        desc: `${cap(periodLabel(r.every_s))} se le escribe «${r.text}» a ${b}. Van ${r.fired} de ${r.max_fires}.${next}${skip} La programó ${a}.${tail}`,
      });
    } else {
      items.push({
        ...base,
        glyph: "⏰",
        title: `${r.at ? fmt.when(r.at) : "sin hora"} → «${r.text}» a ${b} · click para seleccionarla`,
        desc: `${r.at ? cap(fmt.when(r.at)) : "Sin hora fijada,"} se le escribe «${r.text}» a ${b}. La programó ${a}.${tail}`,
      });
    }
  }
  return items;
}

/** por que lado sale y entra un item, y si va por un arco de misma columna */
export interface Sides {
  exit: "l" | "r";
  enter: "l" | "r";
  same: boolean;
  arcX: number;
}

/** 2) por donde sale y entra cada item. Las que comparten lado de una tarjeta se apilan en
 *  vertical ordenadas por la altura del otro extremo, asi no se cruzan entre si. Devuelve, por
 *  item, los lados y la y de cada extremo. Todo item debe tener sus dos extremos en `anchors`. */
export function layoutEnds(items: Item[], anchors: Map<string, Rect>, cols: Col[], strips: Strip[], boardWidth: number, bands: Band[] = []): { sideOf: Sides[]; endY: { from: number; to: number }[] } {
  interface End {
    item: number;
    end: "from" | "to";
    otherY: number;
    y: number;
  }
  const slots = new Map<string, End[]>(); // `${sid}|${lado}` -> extremos que usan ese lado
  const sideOf: Sides[] = [];
  items.forEach((it, i) => {
    const ra = anchors.get(it.from)!;
    const rc = anchors.get(it.to)!;
    const ci = colOf(cols, ra);
    const same = ci >= 0 && ci === colOf(cols, rc); // misma columna: mismo grupo de borde izquierdo
    const ltr = ra.l < rc.l;
    const arc = same ? sideArc(cols, strips, boardWidth, ci, bands) : null;
    const exit: "l" | "r" = arc ? arc.side : ltr ? "r" : "l";
    const enter: "l" | "r" = arc ? arc.side : ltr ? "l" : "r";
    sideOf[i] = { exit, enter, same, arcX: arc?.x ?? 0 };
    pushTo(slots, `${it.from}|${exit}`, { item: i, end: "from", otherY: midY(rc), y: midY(ra) });
    pushTo(slots, `${it.to}|${enter}`, { item: i, end: "to", otherY: midY(ra), y: midY(rc) });
  });
  const endY: { from: number; to: number }[] = items.map(() => ({ from: 0, to: 0 }));
  for (const [k, ends] of slots) {
    const r = anchors.get(k.split("|")[0])!;
    ends.sort((a, c) => a.otherY - c.otherY);
    const ys = spread(ends.length, midY(r), r.b - r.t, 20); // no desbordar tarjetas bajas
    ends.forEach((e, i) => {
      endY[e.item][e.end] = ys[i];
    });
  }
  return { sideOf, endY };
}

/** 3) las curvas: misma columna, arco corto por el costado con mas lugar; columnas distintas, S
 *  que sale y entra por el canal entre columnas abiertas vecinas (si las columnas son vecinas los
 *  canales coinciden y la S vive entera en el hueco). */
/** Sobre la corrida horizontal de un camino por arriba (de xa a xc en y), el punto mas lejano de
 *  los glifos ya puestos; el centro desempata. Asi dos flechas que comparten un hueco no se pisan. */
export function spreadOnRun(taken: Pt[], xa: number, xc: number, y: number): Pt {
  let best: Pt = [(xa + xc) / 2, y];
  let bestD = -Infinity;
  // del centro hacia afuera: a igual distancia gana el mas central (el primero que se ve)
  for (const i of [5, 4, 6, 3, 7, 2, 8, 1, 9]) {
    const x = xa + ((xc - xa) * i) / 10;
    let d = Infinity;
    for (const q of taken) d = Math.min(d, Math.hypot(x - q[0], y - q[1]));
    if (d >= GLYPH_R * 2 && i === 5) return [x, y]; // el centro esta libre: listo
    if (d > bestD + 0.5) {
      bestD = d;
      best = [x, y];
    }
  }
  return best;
}

/** 3) las curvas. Por defecto: misma columna, arco corto por el costado con mas lugar; columnas
 *  distintas, S que sale y entra por el canal entre columnas abiertas vecinas (si son vecinas los
 *  canales coinciden y la S vive entera en el hueco). Si esa curva, muestreada, pasa por dentro de
 *  una tercera tarjeta (columnas no vecinas: la S atraviesa la del medio), el item va "por arriba":
 *  sale por el borde superior del origen, corre por un hueco entre filas o por el margen del tablero
 *  y baja al borde superior del destino (`topRoute`). Varias flechas que salen o entran por el mismo
 *  borde se reparten en x, ordenadas por el x del otro extremo, para no cruzarse. */
export function routeItems(items: Item[], anchors: Map<string, Rect>, cards: Rect[], cols: Col[], strips: Strip[], boardWidth: number, zone: Zone = FREE_ZONE): Seg[] {
  const { sideOf, endY } = layoutEnds(items, anchors, cols, strips, boardWidth, zone.bands);
  const taken: Pt[] = [];
  const out: (Seg | null)[] = items.map(() => null);

  // 1) curva por defecto de cada item, y si cruza una tercera tarjeta
  const plans = items.map((it, i) => {
    const ra = anchors.get(it.from)!;
    const rc = anchors.get(it.to)!;
    const others = cards.filter((c) => !sameRect(c, ra) && !sameRect(c, rc));
    const { exit, enter, same, arcX } = sideOf[i];
    const y1 = endY[i].from;
    const y2 = endY[i].to;
    let pts: [Pt, Pt, Pt, Pt];
    if (same) {
      // del borde de ese lado del origen al mismo borde del destino
      const xa = exit === "r" ? ra.r : ra.l;
      const xc = exit === "r" ? rc.r : rc.l;
      pts = [[xa, y1], [arcX, y1], [arcX, y2], [xc, y2]];
    } else {
      const x1 = exit === "r" ? ra.r : ra.l;
      const x2 = enter === "l" ? rc.l : rc.r;
      const dir: 1 | -1 = exit === "r" ? 1 : -1;
      const half = Math.min(HALF_GAP, Math.abs(x2 - x1) / 2);
      const c1 = channelX(cols, colOf(cols, ra), dir, x1 + dir * half);
      const c2 = channelX(cols, colOf(cols, rc), dir === 1 ? -1 : 1, x2 - dir * half);
      pts = [[x1, y1], [c1, y1], [c2, y2], [x2, y2]];
    }
    return { ra, rc, pts, top: cubicHits(others, ...pts) };
  });

  // 2) los que no cruzan, como siempre
  plans.forEach((p, i) => {
    if (!p.top) out[i] = { ...items[i], ends: [p.ra, p.rc], ...cubic(cards, taken, ...p.pts, zone) };
  });

  // 3) los que cruzan van por arriba. Primer pase con el centro de cada tarjeta, para saber por que
  //    borde sale y entra cada uno; despues se reparten en x los que comparten borde; ultimo pase
  const topIdx = plans.map((p, i) => (p.top ? i : -1)).filter((i) => i >= 0);
  if (topIdx.length) {
    interface End {
      item: number;
      end: "from" | "to";
      otherX: number;
    }
    const slots = new Map<string, End[]>();
    for (const i of topIdx) {
      const { ra, rc } = plans[i];
      const o = topRoute(ra, rc, midX(ra), midX(rc), cards, zone);
      pushTo(slots, `${items[i].from}|${o.exit}`, { item: i, end: "from", otherX: midX(rc) });
      pushTo(slots, `${items[i].to}|${o.enter}`, { item: i, end: "to", otherX: midX(ra) });
    }
    const xOf = new Map<string, number>();
    for (const [k, ends] of slots) {
      const r = anchors.get(k.split("|")[0])!;
      ends.sort((a, c) => a.otherX - c.otherX);
      const xs = spread(ends.length, midX(r), r.r - r.l, 40);
      ends.forEach((e, k2) => xOf.set(`${e.item}|${e.end}`, xs[k2]));
    }
    interface Routed {
      i: number;
      ra: Rect;
      rc: Rect;
      xa: number;
      xc: number;
      o: Ortho;
    }
    const routed: Routed[] = topIdx.map((i) => {
      const { ra, rc } = plans[i];
      const xa = xOf.get(`${i}|from`) ?? midX(ra);
      const xc = xOf.get(`${i}|to`) ?? midX(rc);
      return { i, ra, rc, xa, xc, o: topRoute(ra, rc, xa, xc, cards, zone) };
    });
    // las que eligieron el mismo carril se reparten en pistas paralelas: sin esto, cuatro flechas
    // quedan dibujadas en la misma y y se ven como una sola barra gruesa. El orden es estable (por
    // el x de donde salen, y a igual x por id) para que no salten de pista al redibujar por SSE
    const byLane = new Map<number, Routed[]>();
    for (const r of routed) pushTo(byLane, r.o.lane.y, r);
    const trackY = new Map<number, number>();
    for (const group of byLane.values()) {
      group.sort((a, b) => a.xa - b.xa || items[a.i].ids[0].localeCompare(items[b.i].ids[0]));
      // la franja util del grupo es la interseccion de las de cada flecha: dos que eligieron la
      // misma y pueden tener franjas distintas (cada una mira las tarjetas que cruzaria), y una
      // pista puesta segun la mas ancha se le acerca demasiado a una tarjeta de la otra
      const t = Math.max(...group.map((g) => g.o.lane.t));
      const b = Math.min(...group.map((g) => g.o.lane.b));
      const ys = tracks(group.length, { ...group[0].o.lane, t, b, room: b - t });
      group.forEach((g, k) => trackY.set(g.i, ys[k]));
    }
    for (const { i, ra, rc, xa, xc, o } of routed) {
      const y = trackY.get(i)!;
      const ya = o.exit === "t" ? ra.t : ra.b;
      const yc = o.enter === "t" ? rc.t : rc.b;
      let [gx, gy] = spreadOnRun(taken, xa, xc, y);
      [gx, gy] = clampGlyph(zone, ...ejectGlyph(cards, gx, gy));
      taken.push([gx, gy]);
      out[i] = { ...items[i], ends: [ra, rc], d: orthoPath(xa, ya, y, xc, yc), x: gx, y: gy, lane: o.lane.y, ...(o.clean ? {} : { dim: true }) };
    }
  }
  return out as Seg[];
}

/** Todo junto: de rects medidos, links y reglas a los segmentos listos para dibujar. */
export function computeSegs(input: GeometryInput): Seg[] {
  const cards = Array.from(input.rects.values());
  const cols = groupColumns(cards);
  const items = buildItems(input.links, input.rules, input.anchors, input.fmt);
  const zone: Zone = { bands: input.bands ?? [], strips: input.strips };
  return routeItems(items, input.anchors, cards, cols, input.strips, input.boardWidth, zone);
}
