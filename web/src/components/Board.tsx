import { useEffect, useRef, useState } from "react";
import { Arrows } from "./Arrows";
import { Card } from "./Card";
import type { Link, Pending, Session, State } from "../types";

export const STATES: [State, string][] = [
  ["corriendo", "Corriendo"],
  ["te_necesita", "Te necesita"],
  ["termino", "Terminó"],
  ["muerta", "Muerta"],
];

interface Props {
  sessions: Record<string, Session>;
  pending: Record<string, Pending>;
  selected: string | null;
  filter: State;
  onFilter: (s: State) => void;
  onSelect: (sid: string) => void;
  onDecide: (requestId: string, decision: "allow" | "deny") => void;
  onDrop: (sid: string) => void;
  links: Link[];
  onDeleteLink: (id: string) => void;
  onConnect: (from: string, to: string) => void;
}

interface Drag {
  from: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  over: string | null;
}

export function Board({ sessions, pending, selected, filter, onFilter, onSelect, onDecide, onDrop, links, onDeleteLink, onConnect }: Props) {
  const boardRef = useRef<HTMLDivElement | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  // mousedown sobre el cuerpo de una tarjeta: es arrastre si se mueve mas de 8 px, si no es click
  const pressRef = useRef<{ sid: string; x: number; y: number } | null>(null);
  const draggedRef = useRef(false);

  useEffect(() => {
    const move = (e: MouseEvent) => {
      const pr = pressRef.current;
      if (!pr) return;
      if (Math.hypot(e.clientX - pr.x, e.clientY - pr.y) > 8) {
        pressRef.current = null;
        draggedRef.current = true;
        startDragAt(pr.sid, e.clientX, e.clientY);
      }
    };
    const up = () => {
      pressRef.current = null;
      // el click (si lo hay) llega despues del mouseup; recien entonces se limpia la marca
      setTimeout(() => {
        draggedRef.current = false;
      }, 0);
    };
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
    return () => {
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const byState = (k: State) =>
    Object.values(sessions)
      .filter((s) => s.state === k)
      .sort((a, b) => (a.repo + a.started).localeCompare(b.repo + b.started));

  // arrastre de una tarjeta a otra: linea provisoria que sigue al mouse, al soltar sobre otra
  // tarjeta se abre el reenvio con ese destino
  const startDragAt = (sid: string, cx: number, cy: number) => {
    const board = boardRef.current;
    if (!board) return;
    const b = board.getBoundingClientRect();
    const card = board.querySelector<HTMLElement>(`[data-sid="${sid}"]`);
    const r = card?.getBoundingClientRect();
    const x1 = r ? r.right - b.left - 14 : cx - b.left;
    const y1 = r ? r.bottom - b.top - 14 : cy - b.top;
    setDrag({ from: sid, x1, y1, x2: cx - b.left, y2: cy - b.top, over: null });
  };
  const startDrag = (sid: string, e: React.MouseEvent) => {
    draggedRef.current = true;
    startDragAt(sid, e.clientX, e.clientY);
  };

  useEffect(() => {
    if (!drag) return;
    const move = (e: MouseEvent) => {
      const board = boardRef.current;
      if (!board) return;
      const b = board.getBoundingClientRect();
      const el = document.elementFromPoint(e.clientX, e.clientY)?.closest<HTMLElement>("[data-sid]");
      const over = el && el.dataset.sid !== drag.from ? el.dataset.sid ?? null : null;
      setDrag((d) => (d ? { ...d, x2: e.clientX - b.left, y2: e.clientY - b.top, over } : d));
    };
    const up = (e: MouseEvent) => {
      const el = document.elementFromPoint(e.clientX, e.clientY)?.closest<HTMLElement>("[data-sid]");
      const to = el?.dataset.sid;
      setDrag(null);
      if (to && to !== drag.from) onConnect(drag.from, to);
    };
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
    return () => {
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
    };
  }, [drag?.from, onConnect]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <div className="filters">
        {STATES.map(([k, label]) => (
          <button key={k} className={filter === k ? "on" : ""} onClick={() => onFilter(k)}>
            {label} {byState(k).length}
          </button>
        ))}
      </div>
      <div className={`board ${drag ? "dragging" : ""}`} ref={boardRef}>
        <Arrows links={links} boardRef={boardRef} deps={[sessions, filter, selected]} onDelete={onDeleteLink} />
        {drag && (
          <svg className="arrows draglink">
            <line x1={drag.x1} y1={drag.y1} x2={drag.x2} y2={drag.y2} />
          </svg>
        )}
        {STATES.map(([k, label]) => {
          const list = byState(k);
          const collapsed = list.length === 0;
          return (
            <div key={k} className={`col ${k} ${collapsed ? "collapsed" : ""} ${filter === k ? "show" : ""}`}>
              {collapsed ? (
                <>
                  <div className="vlabel">
                    <span>{label}</span>
                    <span className="n">0</span>
                  </div>
                  <div className="empty">nada acá</div>
                </>
              ) : (
                <>
                  <h2>
                    <span>{label}</span>
                    <span className="n">{list.length}</span>
                  </h2>
                  {list.map((s) => (
                    <div key={s.session_id} className={drag?.over === s.session_id ? "droptarget" : ""}>
                      <Card
                        session={s}
                        pending={s.pending_id ? pending[s.pending_id] : undefined}
                        selected={selected === s.session_id}
                        onSelect={() => {
                          // el click que cierra un arrastre no abre el panel
                          if (draggedRef.current) {
                            draggedRef.current = false;
                            return;
                          }
                          onSelect(s.session_id);
                        }}
                        onDecide={onDecide}
                        onDrop={() => onDrop(s.session_id)}
                        onGrip={(e) => startDrag(s.session_id, e)}
                        onPress={(e) => {
                          pressRef.current = { sid: s.session_id, x: e.clientX, y: e.clientY };
                        }}
                      />
                    </div>
                  ))}
                </>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}
