import { useEffect, useLayoutEffect, useState } from "react";
import { ago } from "../api";
import type { Link, Rule } from "../types";

interface Props {
  links: Link[];
  rules: Rule[];
  boardRef: React.RefObject<HTMLDivElement | null>;
  deps: unknown[];
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
 *  al cambiar sesiones, vinculos o tamano. En pantalla angosta no hay flechas. */
export function Arrows({ links, rules, boardRef, deps, onDelete, onDeleteRule }: Props) {
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
        const x = Math.max(x1, x2) + 40;
        return { d: `M ${ra.right - b.left} ${y1} C ${x} ${y1}, ${x} ${y2}, ${rc.right - b.left} ${y2}`, x: x - 10, y: (y1 + y2) / 2 };
      }
      const dx = Math.max(60, Math.abs(x2 - x1) / 2);
      return { d: `M ${x1} ${y1} C ${x1 + (leftToRight ? dx : -dx)} ${y1}, ${x2 - (leftToRight ? dx : -dx)} ${y2}, ${x2} ${y2}`, x: (x1 + x2) / 2, y: (y1 + y2) / 2 };
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
        const t = r.at ? new Date(r.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false }) : "?";
        out.push({ id: r.id, kind: "rule", ...p, glyph: "⏰", title: `a las ${t} → "${r.text}"\n(click para quitar la conexión)` });
      }
    }
    // solo re-renderizar si algo cambio: compute corre cada 2 s y en cada render del tablero
    setSegs((prev) => (JSON.stringify(prev) === JSON.stringify(out) ? prev : out));
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useLayoutEffect(compute, [links, rules, ...deps]);
  useEffect(() => {
    const on = () => compute();
    window.addEventListener("resize", on);
    const id = setInterval(on, 2000);
    return () => {
      window.removeEventListener("resize", on);
      clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [links, rules]);

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
