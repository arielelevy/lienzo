import { useEffect, useLayoutEffect, useState } from "react";
import { ago } from "../api";
import type { Link } from "../types";

interface Props {
  links: Link[];
  boardRef: React.RefObject<HTMLDivElement | null>;
  deps: unknown[];
  onDelete: (id: string) => void;
}

interface Seg {
  link: Link;
  d: string;
  x: number;
  y: number;
}

/** Flechas entre tarjetas por cada reenvio A -> B. Se dibujan en un SVG que cubre el tablero;
 *  las posiciones salen del DOM (data-sid en cada tarjeta) y se recalculan al cambiar sesiones,
 *  vinculos o tamano de ventana. En pantalla angosta no hay flechas (una sola columna). */
export function Arrows({ links, boardRef, deps, onDelete }: Props) {
  const [segs, setSegs] = useState<Seg[]>([]);
  const [size, setSize] = useState({ w: 0, h: 0 });

  const compute = () => {
    const board = boardRef.current;
    if (!board || window.innerWidth <= 900) {
      setSegs([]);
      return;
    }
    const b = board.getBoundingClientRect();
    setSize({ w: board.scrollWidth, h: board.scrollHeight });
    const out: Seg[] = [];
    for (const l of links) {
      const a = board.querySelector<HTMLElement>(`[data-sid="${l.from}"]`);
      const c = board.querySelector<HTMLElement>(`[data-sid="${l.to}"]`);
      if (!a || !c) continue;
      const ra = a.getBoundingClientRect();
      const rc = c.getBoundingClientRect();
      const leftToRight = ra.left + ra.width / 2 <= rc.left + rc.width / 2;
      const x1 = (leftToRight ? ra.right : ra.left) - b.left;
      const y1 = ra.top + ra.height / 2 - b.top;
      const x2 = (leftToRight ? rc.left : rc.right) - b.left;
      const y2 = rc.top + rc.height / 2 - b.top;
      const sameCol = Math.abs(x1 - x2) < 40;
      let d: string;
      if (sameCol) {
        // misma columna: arco por la derecha
        const x = Math.max(x1, x2) + 40;
        d = `M ${ra.right - b.left} ${y1} C ${x} ${y1}, ${x} ${y2}, ${rc.right - b.left} ${y2}`;
      } else {
        const dx = Math.max(60, Math.abs(x2 - x1) / 2);
        d = `M ${x1} ${y1} C ${x1 + (leftToRight ? dx : -dx)} ${y1}, ${x2 - (leftToRight ? dx : -dx)} ${y2}, ${x2} ${y2}`;
      }
      out.push({ link: l, d, x: (x1 + x2) / 2, y: (y1 + y2) / 2 });
    }
    setSegs(out);
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useLayoutEffect(compute, [links, ...deps]);
  useEffect(() => {
    const on = () => compute();
    window.addEventListener("resize", on);
    const id = setInterval(on, 2000); // las tarjetas cambian de alto con el texto
    return () => {
      window.removeEventListener("resize", on);
      clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [links]);

  if (!segs.length) return null;
  return (
    <svg className="arrows" width={size.w} height={size.h} style={{ width: size.w, height: size.h }}>
      <defs>
        <marker id="arrowhead" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto">
          <path d="M0,0 L10,4 L0,8 z" fill="var(--acc)" />
        </marker>
      </defs>
      {segs.map((s) => (
        <g key={s.link.id} className="arrow">
          <path d={s.d} className="line" markerEnd="url(#arrowhead)" />
          <g onClick={() => confirm(`Quitar la flecha?\n\n${s.link.text}`) && onDelete(s.link.id)}>
            <title>{`reenvío hace ${ago(s.link.ts)}\n${s.link.text}\n(click para quitar la flecha)`}</title>
            <circle cx={s.x} cy={s.y} r="9" className="dot" />
            <text x={s.x} y={s.y + 3.5} textAnchor="middle" className="lbl">↪</text>
          </g>
        </g>
      ))}
    </svg>
  );
}
