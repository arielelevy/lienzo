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
  /** links: el mas nuevo tiene mas de una hora; se dibuja apagado y sin punta */
  old: boolean;
}

const OLD_MS = 60 * 60 * 1000;
const cut = (t: string, n = 90) => (t.length > n ? `${t.slice(0, n).trimEnd()}…` : t);
type Pt = [number, number];

/** Flechas entre tarjetas: llenas por cada reenvio hecho (links, agrupados por par origen→destino),
 *  punteadas por cada conexion pendiente (rules). Las posiciones salen del DOM (data-sid) y se
 *  recalculan al cambiar sesiones, vinculos o tamano del tablero. En pantalla angosta no hay flechas. */
export function Arrows({ links, rules, boardRef, version, hover, onDelete, onDeleteRule }: Props) {
  const [segs, setSegs] = useState<Seg[]>([]);
  const [size, setSize] = useState({ w: 0, h: 0 });

  const compute = () => {
    const board = boardRef.current;
    if (!board || window.innerWidth <= 900) {
      setSegs([]);
      return;
    }
    const b = board.getBoundingClientRect();
    setSize((prev) => (prev.w === board.scrollWidth && prev.h === board.scrollHeight ? prev : { w: board.scrollWidth, h: board.scrollHeight }));
    // rects de todas las tarjetas, relativos al tablero: el circulo clickeable se apoya en el punto
    // de la curva mas lejano a cualquiera, para no robarle el click a una tarjeta
    const cards = Array.from(board.querySelectorAll<HTMLElement>("[data-sid]")).map((el) => {
      const r = el.getBoundingClientRect();
      return { l: r.left - b.left, t: r.top - b.top, r: r.right - b.left, b: r.bottom - b.top };
    });
    const clearance = (x: number, y: number) => {
      let best = Infinity;
      for (const c of cards) {
        const dx = Math.max(c.l - x, 0, x - c.r);
        const dy = Math.max(c.t - y, 0, y - c.b);
        // adentro de una tarjeta: negativo, tanto mas cuanto mas lejos del borde
        const d = dx || dy ? Math.hypot(dx, dy) : -Math.min(x - c.l, c.r - x, y - c.t, c.b - y);
        if (d < best) best = d;
      }
      return best;
    };
    const cubic = (p0: Pt, p1: Pt, p2: Pt, p3: Pt) => {
      const d = `M ${p0[0]} ${p0[1]} C ${p1[0]} ${p1[1]}, ${p2[0]} ${p2[1]}, ${p3[0]} ${p3[1]}`;
      let x = (p0[0] + p3[0]) / 2;
      let y = (p0[1] + p3[1]) / 2;
      let bestC = -Infinity;
      let bestT = 0.5;
      for (let t = 0.1; t <= 0.9001; t += 0.05) {
        const u = 1 - t;
        const px = u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0];
        const py = u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1];
        const c = clearance(px, py);
        // el centro de la curva desempata: mismo despeje, se prefiere el punto medio
        if (c > bestC + 0.5 || (Math.abs(c - bestC) <= 0.5 && Math.abs(t - 0.5) < Math.abs(bestT - 0.5))) {
          bestC = c;
          bestT = t;
          x = px;
          y = py;
        }
      }
      return { d, x, y };
    };
    const path = (from: string, to: string) => {
      const a = board.querySelector<HTMLElement>(`[data-sid="${from}"]`);
      const c = board.querySelector<HTMLElement>(`[data-sid="${to}"]`);
      if (!a || !c) return null;
      const ra = a.getBoundingClientRect();
      const rc = c.getBoundingClientRect();
      const y1 = ra.top + ra.height / 2 - b.top;
      const y2 = rc.top + rc.height / 2 - b.top;
      if (Math.abs(ra.left - rc.left) < 40) {
        // misma columna (mismo borde izquierdo): arco corto por la derecha de la columna, del borde
        // derecho del origen al borde derecho del destino
        const xr = Math.max(ra.right, rc.right) - b.left + 30;
        return cubic([ra.right - b.left, y1], [xr, y1], [xr, y2], [rc.right - b.left, y2]);
      }
      const leftToRight = ra.left < rc.left;
      const x1 = (leftToRight ? ra.right : ra.left) - b.left;
      const x2 = (leftToRight ? rc.left : rc.right) - b.left;
      const dx = Math.max(60, Math.abs(x2 - x1) / 2);
      return cubic([x1, y1], [x1 + (leftToRight ? dx : -dx), y1], [x2 - (leftToRight ? dx : -dx), y2], [x2, y2]);
    };

    const out: Seg[] = [];
    // un par origen→destino (y tipo) = una sola flecha, con contador y los textos en el tooltip
    const groups = new Map<string, Link[]>();
    for (const l of links) {
      const k = `${l.kind === "native" ? "n" : "s"}|${l.from}|${l.to}`;
      const g = groups.get(k);
      if (g) g.push(l);
      else groups.set(k, [l]);
    }
    for (const g of groups.values()) {
      g.sort((a, b) => b.ts.localeCompare(a.ts)); // mas nuevo primero
      const newest = g[0];
      const p = path(newest.from, newest.to);
      if (!p) continue;
      const native = newest.kind === "native";
      const old = Date.now() - new Date(newest.ts).getTime() > OLD_MS;
      const n = g.length;
      const head = native
        ? `canal nativo Claude↔Claude abierto hace ${ago(newest.ts)}`
        : n > 1
          ? `${n} reenvíos, el último hace ${ago(newest.ts)}`
          : `reenvío hace ${ago(newest.ts)}`;
      const texts = g.slice(0, 5).map((l) => `• ${hhmm(new Date(l.ts))} ${cut(l.text)}`);
      if (n > 5) texts.push(`… y ${n - 5} más`);
      out.push({
        ids: g.map((l) => l.id),
        kind: native ? "native" : "link",
        from: newest.from,
        to: newest.to,
        ...p,
        old,
        glyph: n > 1 ? `×${n}` : native ? "⇄" : "↪",
        title: `${head}\n${texts.join("\n")}\n(click para quitar ${n > 1 ? "las flechas" : "la flecha"})`,
      });
    }
    for (const r of rules) {
      if (!r.enabled || !r.from || r.from === r.to) continue;
      const p = path(r.from, r.to);
      if (!p) continue;
      if (r.kind === "on_stop") {
        out.push({ ids: [r.id], kind: "rule", from: r.from, to: r.to, ...p, old: false, glyph: "⏹", title: `cuando termine → manda su respuesta${r.repeat ? ` (${r.fired}/${r.max_fires})` : " (una vez)"}\n(click para quitar la conexión)` });
      } else {
        const t = r.at ? hhmm(new Date(r.at)) : "?";
        out.push({ ids: [r.id], kind: "rule", from: r.from, to: r.to, ...p, old: false, glyph: "⏰", title: `a las ${t} → "${r.text}"\n(click para quitar la conexión)` });
      }
    }
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

  if (!segs.length) return null;
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
          <g key={s.ids[0]} className={`arrow ${s.old ? "old" : ""} ${mine ? "mine" : ""}`}>
            {s.kind === "native" && <path d={s.d} className="line native-outer" />}
            <path
              d={s.d}
              className={`line ${s.kind}`}
              markerEnd={s.old ? undefined : "url(#arrowhead)"}
              markerStart={s.kind === "native" && !s.old ? "url(#arrowtail)" : undefined}
            />
            <g
              onClick={() => {
                const q = s.kind === "rule" ? "Quitar la conexión?" : many ? `Quitar las ${s.ids.length} flechas de este par?` : "Quitar la flecha?";
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
