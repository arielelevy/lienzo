import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ago } from "../api";
import { hhmm } from "../nl";
import type { Link, Rule } from "../types";

interface Props {
  links: Link[];
  rules: Rule[];
  boardRef: React.RefObject<HTMLDivElement | null>;
  /** sube cuando cambian sesiones, filtro o seleccion: las tarjetas se movieron, hay que recalcular */
  version: number;
  /** tarjeta bajo el mouse: sus flechas se resaltan y el resto se atenua */
  hover: string | null;
  onDelete: (id: string) => void;
  onDeleteRule: (id: string) => void;
}

interface Seg {
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
type Item = Omit<Seg, "d" | "x" | "y">;

/** un envio ya hecho se muestra este tiempo, como confirmacion visual, y despues desaparece */
const FRESH_MS = 60_000;
/** medio canal por defecto, si no se puede medir el hueco entre columnas abiertas */
const HALF_GAP = 20; // la mitad del canal entre columnas (28 px) mas un poco de aire
/** separacion vertical entre flechas que salen o entran por el mismo lado de una tarjeta */
const SLOT = 14;
const cut = (t: string, n = 90) => (t.length > n ? `${t.slice(0, n).trimEnd()}…` : t);
type Pt = [number, number];
interface Rect {
  l: number;
  t: number;
  r: number;
  b: number;
}

/** Flechas entre tarjetas. En el tablero quedan solo las conexiones pendientes (reglas on_stop y
 *  at, punteadas) y el canal nativo Claude<->Claude (doble). Un envio comun se muestra 60 s con
 *  un fade, para confirmar que salio, y despues se va: lo enviado vive en la pestana Conexiones.
 *  Las posiciones salen del DOM (data-sid) y se recalculan al cambiar sesiones, vinculos o tamano.
 *  Las curvas entre columnas viajan por el hueco entre los grupos de tarjetas vecinos; las de la
 *  misma columna hacen un arco corto por el costado con mas lugar. En pantalla angosta no hay flechas. */
export function Arrows({ links, rules, boardRef, version, hover, onDelete, onDeleteRule }: Props) {
  const [segs, setSegs] = useState<Seg[]>([]);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [, setTick] = useState(0);

  const compute = () => {
    const board = boardRef.current;
    if (!board || window.innerWidth <= 900) {
      setSegs([]);
      return;
    }
    const b = board.getBoundingClientRect();
    setSize((prev) => (prev.w === board.scrollWidth && prev.h === board.scrollHeight ? prev : { w: board.scrollWidth, h: board.scrollHeight }));

    // rects de todas las tarjetas, relativos al tablero
    const rects = new Map<string, Rect>();
    for (const el of board.querySelectorAll<HTMLElement>("[data-sid]")) {
      const r = el.getBoundingClientRect();
      if (el.dataset.sid) rects.set(el.dataset.sid, { l: r.left - b.left, t: r.top - b.top, r: r.right - b.left, b: r.bottom - b.top });
    }
    const cards = Array.from(rects.values());
    // "columnas" para las flechas = grupos de tarjetas con el mismo borde izquierdo (una columna
    // ancha con dos subcolumnas cuenta como dos). El canal de una curva es el hueco entre el grupo
    // de salida y el vecino; las tiras colapsadas son obstaculos, no columnas.
    const cols: { l: number; r: number }[] = [];
    for (const c of [...cards].sort((a, d) => a.l - d.l)) {
      const last = cols[cols.length - 1];
      if (last && Math.abs(c.l - last.l) < 40) {
        last.r = Math.max(last.r, c.r);
      } else {
        cols.push({ l: c.l, r: c.r });
      }
    }
    const colOf = (rc: Rect) => cols.findIndex((c) => Math.abs(rc.l - c.l) < 40);
    // x del medio del canal a la derecha (dir 1) o a la izquierda (dir -1) de la columna i
    const channelX = (i: number, dir: 1 | -1, fallback: number) => {
      const a = cols[i];
      const n = cols[i + dir];
      if (!a || !n) return fallback;
      return dir === 1 ? (a.r + n.l) / 2 : (n.r + a.l) / 2;
    };
    // espacio libre a un costado de la columna i hasta lo primero que haya: otra columna, una tira
    // colapsada o el borde del tablero
    const strips = Array.from(board.querySelectorAll<HTMLElement>(".col.collapsed")).map((el) => {
      const r = el.getBoundingClientRect();
      return { l: r.left - b.left, r: r.right - b.left };
    });
    const freeAt = (i: number, dir: 1 | -1) => {
      const a = cols[i];
      if (!a) return 0;
      const walls = [...cols.filter((_, j) => j !== i), ...strips];
      if (dir === 1) {
        let x = board.scrollWidth;
        for (const w of walls) if (w.l >= a.r - 1 && w.l < x) x = w.l;
        return x - a.r;
      }
      let x = 0;
      for (const w of walls) if (w.r <= a.l + 1 && w.r > x) x = w.r;
      return a.l - x;
    };
    // arco entre dos tarjetas de la misma columna: por el costado con mas lugar (el canal vecino si
    // lo hay, si no el margen del tablero); nunca por encima de una tarjeta
    const sideArc = (i: number): { side: "l" | "r"; x: number } => {
      const a = cols[i];
      const fr = freeAt(i, 1);
      const fl = freeAt(i, -1);
      const side: "l" | "r" = fl > fr ? "l" : "r";
      const bulge = Math.min(HALF_GAP, Math.max(20, (side === "r" ? fr : fl) / 2));
      return { side, x: side === "r" ? a.r + bulge : a.l - bulge };
    };
    // distancia al borde de la tarjeta mas cercana; negativa si el punto cae adentro de una
    const clearance = (x: number, y: number) => {
      let best = Infinity;
      for (const c of cards) {
        const dx = Math.max(c.l - x, 0, x - c.r);
        const dy = Math.max(c.t - y, 0, y - c.b);
        const d = dx || dy ? Math.hypot(dx, dy) : -Math.min(x - c.l, c.r - x, y - c.t, c.b - y);
        if (d < best) best = d;
      }
      return best;
    };
    // el circulo clickeable va en el punto de la curva mas lejano a cualquier tarjeta (o sea, en el
    // canal), para no robarle el click a una tarjeta; el centro desempata
    const cubic = (p0: Pt, p1: Pt, p2: Pt, p3: Pt) => {
      const d = `M ${p0[0]} ${p0[1]} C ${p1[0]} ${p1[1]}, ${p2[0]} ${p2[1]}, ${p3[0]} ${p3[1]}`;
      let x = (p0[0] + p3[0]) / 2;
      let y = (p0[1] + p3[1]) / 2;
      let bestC = -Infinity;
      let bestT = 0.5;
      for (let t = 0.05; t <= 0.9501; t += 0.025) {
        const u = 1 - t;
        const px = u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0];
        const py = u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1];
        const c = clearance(px, py);
        if (c > bestC + 0.5 || (Math.abs(c - bestC) <= 0.5 && Math.abs(t - 0.5) < Math.abs(bestT - 0.5))) {
          bestC = c;
          bestT = t;
          x = px;
          y = py;
        }
      }
      return { d, x, y };
    };

    // 1) que hay que dibujar: canal nativo y ultimo envio por par, mas reglas
    const items: Item[] = [];
    const groups = new Map<string, Link[]>();
    for (const l of links) {
      // decision del autor: la flecha del ultimo mensaje entre cada par queda siempre (sin limite
      // de tiempo); los anteriores del mismo par se agrupan en el contador
      const native = l.kind === "native";
      const k = `${native ? "n" : "s"}|${l.from}|${l.to}`;
      const g = groups.get(k);
      if (g) g.push(l);
      else groups.set(k, [l]);
    }
    for (const g of groups.values()) {
      g.sort((a, c) => c.ts.localeCompare(a.ts)); // mas nuevo primero
      const newest = g[0];
      if (!rects.has(newest.from) || !rects.has(newest.to)) continue;
      const native = newest.kind === "native";
      const n = g.length;
      const head = native
        ? `canal nativo Claude↔Claude abierto hace ${ago(newest.ts)}`
        : n > 1
          ? `último envío hace ${ago(newest.ts)} (${n} en total)`
          : `enviado hace ${ago(newest.ts)}`;
      const texts = g.slice(0, 5).map((l) => `• ${hhmm(new Date(l.ts))} ${cut(l.text)}`);
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
      if (!r.enabled || !r.from || r.from === r.to || !rects.has(r.from) || !rects.has(r.to)) continue;
      if (r.kind === "on_stop") {
        items.push({ ids: [r.id], kind: "rule", from: r.from, to: r.to, old: false, glyph: "⏹", title: `cuando termine → manda su respuesta${r.repeat ? ` (${r.fired}/${r.max_fires})` : " (una vez)"}\n(click para quitar la conexión)` });
      } else {
        const t = r.at ? hhmm(new Date(r.at)) : "?";
        items.push({ ids: [r.id], kind: "rule", from: r.from, to: r.to, old: false, glyph: "⏰", title: `a las ${t} → "${r.text}"\n(click para quitar la conexión)` });
      }
    }

    // 2) por donde sale y entra cada una. Las que comparten lado de una tarjeta se apilan en
    //    vertical ordenadas por la altura del otro extremo, asi no se cruzan entre si.
    const midY = (r: Rect) => (r.t + r.b) / 2;
    interface End {
      item: number;
      end: "from" | "to";
      otherY: number;
      y: number;
    }
    const slots = new Map<string, End[]>(); // `${sid}|${lado}` -> extremos que usan ese lado
    const sideOf: { exit: "l" | "r"; enter: "l" | "r"; same: boolean; arcX: number }[] = [];
    items.forEach((it, i) => {
      const ra = rects.get(it.from)!;
      const rc = rects.get(it.to)!;
      const ci = colOf(ra);
      const same = ci >= 0 && ci === colOf(rc); // misma columna: mismo grupo de borde izquierdo
      const ltr = ra.l < rc.l;
      const arc = same ? sideArc(ci) : null;
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
      const r = rects.get(k.split("|")[0])!;
      ends.sort((a, c) => a.otherY - c.otherY);
      const n = ends.length;
      const span = Math.min((n - 1) * SLOT, Math.max(0, r.b - r.t - 20)); // no desbordar tarjetas bajas
      const step = n > 1 ? span / (n - 1) : 0;
      ends.forEach((e, i) => {
        endY[e.item][e.end] = midY(r) - span / 2 + i * step;
      });
    }

    // 3) las curvas
    const out: Seg[] = [];
    items.forEach((it, i) => {
      const ra = rects.get(it.from)!;
      const rc = rects.get(it.to)!;
      const { exit, enter, same, arcX } = sideOf[i];
      const y1 = endY[i].from;
      const y2 = endY[i].to;
      let p: { d: string; x: number; y: number };
      if (same) {
        // misma columna: arco corto por el costado con mas lugar, del borde de ese lado del origen
        // al mismo borde del destino
        const xa = exit === "r" ? ra.r : ra.l;
        const xc = exit === "r" ? rc.r : rc.l;
        p = cubic([xa, y1], [arcX, y1], [arcX, y2], [xc, y2]);
      } else {
        // columnas distintas: sale y entra por el canal entre columnas abiertas vecinas; los
        // controles quedan en el medio de cada canal (si las columnas son vecinas, coinciden y la
        // S vive entera en el hueco)
        const x1 = exit === "r" ? ra.r : ra.l;
        const x2 = enter === "l" ? rc.l : rc.r;
        const dir: 1 | -1 = exit === "r" ? 1 : -1;
        const half = Math.min(HALF_GAP, Math.abs(x2 - x1) / 2);
        const c1 = channelX(colOf(ra), dir, x1 + dir * half);
        const c2 = channelX(colOf(rc), dir === 1 ? -1 : 1, x2 - dir * half);
        p = cubic([x1, y1], [c1, y1], [c2, y2], [x2, y2]);
      }
      out.push({ ...it, ...p });
    });
    // solo re-renderizar si algo cambio: compute corre en cada render del tablero y en cada resize
    setSegs((prev) => (JSON.stringify(prev) === JSON.stringify(out) ? prev : out));
  };

  // el observer y el listener de resize se enganchan una sola vez; llaman siempre al compute mas
  // reciente (con los links/rules de este render) a traves del ref
  const computeRef = useRef(compute);
  computeRef.current = compute;

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useLayoutEffect(compute, [links, rules, version]);
  useEffect(() => {
    const on = () => computeRef.current();
    window.addEventListener("resize", on);
    const board = boardRef.current;
    const ro = board && typeof ResizeObserver !== "undefined" ? new ResizeObserver(on) : null;
    if (ro && board) ro.observe(board);
    return () => {
      window.removeEventListener("resize", on);
      ro?.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // mientras haya envios recientes en pantalla: re-render cada 400 ms para el fade, y recompute
  // cuando alguno cumple los 60 s (ahi desaparece)
  useEffect(() => {
    if (!segs.some((s) => s.fresh)) return;
    const id = setInterval(() => {
      const now = Date.now();
      if (segs.some((s) => s.fresh && now - s.fresh >= FRESH_MS)) computeRef.current();
      else setTick((t) => t + 1);
    }, 400);
    return () => clearInterval(id);
  }, [segs]);

  if (!segs.length) return null;
  const now = Date.now();
  // envio reciente: opaco 45 s, despues se desvanece hasta los 60 s
  const freshOpacity = (ts: number) => Math.max(0, Math.min(1, 1 - (now - ts - 45_000) / 15_000));
  return (
    <svg className={`arrows ${hover ? "hovering" : ""}`} width={size.w} height={size.h} style={{ width: size.w, height: size.h }}>
      <defs>
        <marker id="arrowhead" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto">
          <path d="M0,0 L10,4 L0,8 z" fill="var(--acc)" />
        </marker>
        <marker id="arrowtail" markerWidth="10" markerHeight="8" refX="1" refY="4" orient="auto">
          <path d="M10,0 L0,4 L10,8 z" fill="var(--acc)" />
        </marker>
      </defs>
      {segs.map((s) => {
        const mine = hover !== null && (s.from === hover || s.to === hover);
        const many = s.ids.length > 1;
        return (
          <g
            key={s.ids[0]}
            className={`arrow ${s.old ? "old" : ""} ${mine ? "mine" : ""} ${s.fresh ? "fresh" : ""}`}
            style={s.fresh ? { opacity: freshOpacity(s.fresh) } : undefined}
          >
            {s.kind === "native" && <path d={s.d} className="line native-outer" />}
            <path
              d={s.d}
              className={`line ${s.kind}`}
              markerEnd={s.old ? undefined : "url(#arrowhead)"}
              markerStart={s.kind === "native" && !s.old ? "url(#arrowtail)" : undefined}
            />
            <g
              onClick={() => {
                if (s.fresh) return; // el envio reciente se va solo
                const q = s.kind === "rule" ? "Quitar la conexión?" : "Quitar la flecha?";
                if (!confirm(q)) return;
                for (const id of s.ids) (s.kind === "rule" ? onDeleteRule : onDelete)(id);
              }}
            >
              <title>{s.title}</title>
              <circle cx={s.x} cy={s.y} r={many ? 11 : 9} className="dot" />
              <text x={s.x} y={s.y + 3.5} textAnchor="middle" className={`lbl ${many ? "count" : ""}`}>{s.glyph}</text>
            </g>
          </g>
        );
      })}
    </svg>
  );
}
