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
export interface Strip {
  l: number;
  r: number;
}

export interface Seg {
  /** ids de todos los links agrupados (o el id de la regla) */
  ids: string[];
  kind: "link" | "rule" | "native";
  from: string;
  to: string;
  d: string;
  x: number;
  y: number;
  title: string;
  glyph: string;
  /** canal nativo con mas de una hora: se dibuja apagado y sin punta */
  old: boolean;
  /** envio recien hecho: instante (ms) del envio; se muestra FRESH_MS y se desvanece */
  fresh?: number;
}

/** Lo que hay que dibujar, antes de saber por donde pasa. */
export type Item = Omit<Seg, "d" | "x" | "y">;

/** textos que dependen del reloj o de la zona horaria: los inyecta el componente */
export interface Formatters {
  /** "57 min", "2 h": hace cuanto fue un instante ISO */
  ago: (iso: string) => string;
  /** "20:53": hora local de un instante ISO */
  hhmm: (iso: string) => string;
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
  links: Link[];
  rules: Rule[];
  fmt: Formatters;
}

/** un envio ya hecho se muestra este tiempo, como confirmacion visual, y despues desaparece */
export const FRESH_MS = 60_000;
/** medio canal por defecto, si no se puede medir el hueco entre columnas abiertas */
export const HALF_GAP = 20; // la mitad del canal entre columnas (28 px) mas un poco de aire
/** separacion vertical entre flechas que salen o entran por el mismo lado de una tarjeta */
export const SLOT = 14;
/** dos tarjetas con bordes izquierdos a menos de esto son de la misma columna */
export const COL_TOL = 40;
/** radio de exclusion de un glifo ya puesto, para que dos flechas del mismo canal no se pisen */
const GLYPH_R = 22;

export const cut = (t: string, n = 90) => (t.length > n ? `${t.slice(0, n).trimEnd()}…` : t);
export const midY = (r: Rect) => (r.t + r.b) / 2;

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

/** arco entre dos tarjetas de la misma columna: por el costado con mas lugar (el canal vecino si
 *  lo hay, si no el margen del tablero); nunca por encima de una tarjeta */
export function sideArc(cols: Col[], strips: Strip[], boardWidth: number, i: number): { side: "l" | "r"; x: number } {
  const a = cols[i];
  const fr = freeAt(cols, strips, boardWidth, i, 1);
  const fl = freeAt(cols, strips, boardWidth, i, -1);
  const side: "l" | "r" = fl > fr ? "l" : "r";
  const bulge = Math.min(HALF_GAP, Math.max(20, (side === "r" ? fr : fl) / 2));
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

/** Cubica de p0 a p3 con controles p1 y p2, mas el punto donde va el circulo clickeable: el punto
 *  de la curva mas lejano a cualquier tarjeta (o sea, en el canal), para no robarle el click a una
 *  tarjeta; el centro desempata. Los circulos ya puestos (`taken`) cuentan como obstaculo, asi dos
 *  flechas que comparten canal no se pisan el glifo; el punto elegido se agrega a `taken`. */
export function cubic(cards: Rect[], taken: Pt[], p0: Pt, p1: Pt, p2: Pt, p3: Pt): { d: string; x: number; y: number } {
  const d = `M ${p0[0]} ${p0[1]} C ${p1[0]} ${p1[1]}, ${p2[0]} ${p2[1]}, ${p3[0]} ${p3[1]}`;
  let x = (p0[0] + p3[0]) / 2;
  let y = (p0[1] + p3[1]) / 2;
  let bestC = -Infinity;
  let bestT = 0.5;
  for (let t = 0.05; t <= 0.9501; t += 0.025) {
    const u = 1 - t;
    const px = u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0];
    const py = u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1];
    let c = clearance(cards, px, py);
    for (const q of taken) c = Math.min(c, Math.hypot(px - q[0], py - q[1]) - GLYPH_R);
    if (c > bestC + 0.5 || (Math.abs(c - bestC) <= 0.5 && Math.abs(t - 0.5) < Math.abs(bestT - 0.5))) {
      bestC = c;
      bestT = t;
      x = px;
      y = py;
    }
  }
  taken.push([x, y]);
  return { d, x, y };
}

/** 1) que hay que dibujar: canal nativo y ultimo envio por par (sin limite de tiempo; los
 *  anteriores del mismo par van al contador), mas las reglas activas con los dos extremos visibles.
 *  Orden: grupos de links en orden de primera aparicion, despues las reglas en su orden. */
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
    const head = native
      ? `canal nativo Claude↔Claude abierto hace ${fmt.ago(newest.ts)}`
      : n > 1
        ? `último envío hace ${fmt.ago(newest.ts)} (${n} en total)`
        : `enviado hace ${fmt.ago(newest.ts)}`;
    const texts = g.slice(0, 5).map((l) => `• ${fmt.hhmm(l.ts)} ${cut(l.text)}`);
    if (n > 5) texts.push(`… y ${n - 5} más`);
    items.push({
      ids: g.map((l) => l.id),
      kind: native ? "native" : "link",
      from: newest.from,
      to: newest.to,
      old: false, // sin limite de tiempo: la ultima flecha del par se ve igual siempre
      fresh: undefined,
      glyph: n > 1 ? `×${n}` : native ? "⇄" : "↪",
      title: `${head}\n${texts.join("\n")}\n(click para quitar la flecha)`,
    });
  }
  for (const r of rules) {
    if (!r.enabled || !r.from || r.from === r.to || !anchors.has(r.from) || !anchors.has(r.to)) continue;
    if (r.kind === "on_stop") {
      items.push({ ids: [r.id], kind: "rule", from: r.from, to: r.to, old: false, glyph: "⏹", title: `cuando termine → manda su respuesta${r.repeat ? ` (${r.fired}/${r.max_fires})` : " (una vez)"}\n(click quita · doble click edita)` });
    } else {
      const t = r.at ? fmt.hhmm(r.at) : "?";
      items.push({ ids: [r.id], kind: "rule", from: r.from, to: r.to, old: false, glyph: "⏰", title: `a las ${t} → "${r.text}"\n(click quita · doble click edita)` });
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
export function layoutEnds(items: Item[], anchors: Map<string, Rect>, cols: Col[], strips: Strip[], boardWidth: number): { sideOf: Sides[]; endY: { from: number; to: number }[] } {
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
    const arc = same ? sideArc(cols, strips, boardWidth, ci) : null;
    const exit: "l" | "r" = arc ? arc.side : ltr ? "r" : "l";
    const enter: "l" | "r" = arc ? arc.side : ltr ? "l" : "r";
    sideOf[i] = { exit, enter, same, arcX: arc?.x ?? 0 };
    const push = (k: string, e: End) => {
      const arr = slots.get(k);
      if (arr) arr.push(e);
      else slots.set(k, [e]);
    };
    push(`${it.from}|${exit}`, { item: i, end: "from", otherY: midY(rc), y: midY(ra) });
    push(`${it.to}|${enter}`, { item: i, end: "to", otherY: midY(ra), y: midY(rc) });
  });
  const endY: { from: number; to: number }[] = items.map(() => ({ from: 0, to: 0 }));
  for (const [k, ends] of slots) {
    const r = anchors.get(k.split("|")[0])!;
    ends.sort((a, c) => a.otherY - c.otherY);
    const n = ends.length;
    const span = Math.min((n - 1) * SLOT, Math.max(0, r.b - r.t - 20)); // no desbordar tarjetas bajas
    const step = n > 1 ? span / (n - 1) : 0;
    ends.forEach((e, i) => {
      endY[e.item][e.end] = midY(r) - span / 2 + i * step;
    });
  }
  return { sideOf, endY };
}

/** 3) las curvas: misma columna, arco corto por el costado con mas lugar; columnas distintas, S
 *  que sale y entra por el canal entre columnas abiertas vecinas (si las columnas son vecinas los
 *  canales coinciden y la S vive entera en el hueco). */
export function routeItems(items: Item[], anchors: Map<string, Rect>, cards: Rect[], cols: Col[], strips: Strip[], boardWidth: number): Seg[] {
  const { sideOf, endY } = layoutEnds(items, anchors, cols, strips, boardWidth);
  const taken: Pt[] = [];
  const out: Seg[] = [];
  items.forEach((it, i) => {
    const ra = anchors.get(it.from)!;
    const rc = anchors.get(it.to)!;
    const { exit, enter, same, arcX } = sideOf[i];
    const y1 = endY[i].from;
    const y2 = endY[i].to;
    let p: { d: string; x: number; y: number };
    if (same) {
      // del borde de ese lado del origen al mismo borde del destino
      const xa = exit === "r" ? ra.r : ra.l;
      const xc = exit === "r" ? rc.r : rc.l;
      p = cubic(cards, taken, [xa, y1], [arcX, y1], [arcX, y2], [xc, y2]);
    } else {
      const x1 = exit === "r" ? ra.r : ra.l;
      const x2 = enter === "l" ? rc.l : rc.r;
      const dir: 1 | -1 = exit === "r" ? 1 : -1;
      const half = Math.min(HALF_GAP, Math.abs(x2 - x1) / 2);
      const c1 = channelX(cols, colOf(cols, ra), dir, x1 + dir * half);
      const c2 = channelX(cols, colOf(cols, rc), dir === 1 ? -1 : 1, x2 - dir * half);
      p = cubic(cards, taken, [x1, y1], [c1, y1], [c2, y2], [x2, y2]);
    }
    out.push({ ...it, ...p });
  });
  return out;
}

/** Todo junto: de rects medidos, links y reglas a los segmentos listos para dibujar. */
export function computeSegs(input: GeometryInput): Seg[] {
  const cards = Array.from(input.rects.values());
  const cols = groupColumns(cards);
  const items = buildItems(input.links, input.rules, input.anchors, input.fmt);
  return routeItems(items, input.anchors, cards, cols, input.strips, input.boardWidth);
}
