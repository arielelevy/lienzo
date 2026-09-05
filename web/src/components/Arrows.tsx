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
  onDelete: (id: string) => void;
  onDeleteRule: (id: string) => void;
}

interface Seg {
  id: string;
  kind: "link" | "rule" | "native";
  d: string;
  x: number;
  y: number;
  title: string;
  glyph: string;
}

/** Flechas entre tarjetas: llenas por cada reenvio hecho (links), punteadas por cada conexion
 *  pendiente (rules "cuando termine"). Las posiciones salen del DOM (data-sid) y se recalculan
 *  al cambiar sesiones, vinculos o tamano del tablero. En pantalla angosta no hay flechas. */
export function Arrows({ links, rules, boardRef, version, onDelete, onDeleteRule }: Props) {
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
    const cubic = (p0: [number, number], p1: [number, number], p2: [number, number], p3: [number, number]) => {
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
    const out: Seg[] = [];
    const path = (from: string, to: string) => {
      const a = board.querySelector<HTMLElement>(`[data-sid="${from}"]`);
      const c = board.querySelector<HTMLElement>(`[data-sid="${to}"]`);
      if (!a || !c) return null;
      const ra = a.getBoundingClientRect();
      const rc = c.getBoundingClientRect();
      const leftToRight = ra.left + ra.width / 2 <= rc.left + rc.width / 2;
      const x1 = (leftToRight ? ra.right : ra.left) - b.left;
      const y1 = ra.top + ra.height / 2 - b.top;
      const x2 = (leftToRight ? rc.left : rc.right) - b.left;
      const y2 = rc.top + rc.height / 2 - b.top;
      if (Math.abs(x1 - x2) < 40) {
        // misma columna: la curva sale por la derecha de las dos y vuelve
        const x = Math.max(x1, x2) + 40;
        return cubic([ra.right - b.left, y1], [x, y1], [x, y2], [rc.right - b.left, y2]);
      }
      const dx = Math.max(60, Math.abs(x2 - x1) / 2);
      return cubic([x1, y1], [x1 + (leftToRight ? dx : -dx), y1], [x2 - (leftToRight ? dx : -dx), y2], [x2, y2]);
    };
    for (const l of links) {
      const p = path(l.from, l.to);
      if (!p) continue;
      if (l.kind === "native") {
        out.push({ id: l.id, kind: "native", ...p, glyph: "⇄", title: `canal nativo Claude↔Claude abierto hace ${ago(l.ts)}\n${l.text}\n(click para quitar la flecha)` });
      } else {
        out.push({ id: l.id, kind: "link", ...p, glyph: "↪", title: `reenvío hace ${ago(l.ts)}\n${l.text}\n(click para quitar la flecha)` });
      }
    }
    for (const r of rules) {
      if (!r.enabled || !r.from || r.from === r.to) continue;
      const p = path(r.from, r.to);
      if (!p) continue;
      if (r.kind === "on_stop") {
        out.push({ id: r.id, kind: "rule", ...p, glyph: "⏹", title: `cuando termine → manda su respuesta${r.repeat ? ` (${r.fired}/${r.max_fires})` : " (una vez)"}\n(click para quitar la conexión)` });
      } else {
        const t = r.at ? hhmm(new Date(r.at)) : "?";
        out.push({ id: r.id, kind: "rule", ...p, glyph: "⏰", title: `a las ${t} → "${r.text}"\n(click para quitar la conexión)` });
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
    <svg className="arrows" width={size.w} height={size.h} style={{ width: size.w, height: size.h }}>
      <defs>
        <marker id="arrowhead" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto">
          <path d="M0,0 L10,4 L0,8 z" fill="var(--acc)" />
        </marker>
        <marker id="arrowtail" markerWidth="10" markerHeight="8" refX="1" refY="4" orient="auto">
          <path d="M10,0 L0,4 L10,8 z" fill="var(--acc)" />
        </marker>
      </defs>
      {segs.map((s) => (
        <g key={s.id} className="arrow">
          {s.kind === "native" && <path d={s.d} className="line native-outer" />}
          <path d={s.d} className={`line ${s.kind}`} markerEnd="url(#arrowhead)" markerStart={s.kind === "native" ? "url(#arrowtail)" : undefined} />
          <g
            onClick={() => {
              if (!confirm(s.kind === "rule" ? "Quitar la conexión?" : "Quitar la flecha?")) return;
              (s.kind === "rule" ? onDeleteRule : onDelete)(s.id);
            }}
          >
            <title>{s.title}</title>
            <circle cx={s.x} cy={s.y} r="9" className="dot" />
            <text x={s.x} y={s.y + 3.5} textAnchor="middle" className="lbl">{s.glyph}</text>
          </g>
        </g>
      ))}
    </svg>
  );
}
