import { useEffect, useMemo, useRef, useState } from "react";
import { Arrows } from "./Arrows";
import { Card } from "./Card";
import type { Link, Pending, Rule, Session, State } from "../types";

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
  rules: Rule[];
  onDeleteLink: (id: string) => void;
  onDeleteRule: (id: string) => void;
  onConnect: (from: string, to: string) => void;
  /** boton del header: con muchas flechas conviene poder apagarlas */
  showArrows: boolean;
  /** filtro del header: texto libre (repo, titulo, ultimo pedido) y agentes visibles */
  query: string;
  agents: Record<Session["agent"], boolean>;
  /** toast global para las acciones de la tarjeta (copiar, botones rapidos, renombrar) */
  toast?: (msg: string, err?: boolean) => void;
}

export type Agent = Session["agent"];

const COLLAPSE_KEY = "lienzo.collapsed";
type Collapsed = Partial<Record<State, boolean>>;
function loadCollapsed(): Collapsed {
  try {
    const raw = localStorage.getItem(COLLAPSE_KEY);
    return raw ? (JSON.parse(raw) as Collapsed) : {};
  } catch {
    return {};
  }
}

const norm = (s: string) => s.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");

const canReceive = (s: Session | undefined) => !!s && s.alive && !!s.pid && !s.orphan && !s.no_console;

interface Drag {
  from: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  over: string | null;
}

export function Board({ sessions, pending, selected, filter, onFilter, onSelect, onDecide, onDrop, links, rules, onDeleteLink, onDeleteRule, onConnect, showArrows, query, agents, toast }: Props) {
  const boardRef = useRef<HTMLDivElement | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  // tarjeta bajo el mouse: Arrows resalta sus flechas y atenua las demas
  const [hover, setHover] = useState<string | null>(null);
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

  // una pasada por render: las sesiones que pasan el filtro del header, agrupadas por estado y
  // ordenadas por repo + inicio. El filtro es solo visual: el server no se entera.
  const byState = useMemo(() => {
    const q = norm(query.trim());
    const g: Record<State, Session[]> = { corriendo: [], te_necesita: [], termino: [], muerta: [] };
    for (const s of Object.values(sessions)) {
      if (!agents[s.agent]) continue;
      if (q && !norm(`${s.repo} ${s.title ?? ""} ${s.last_prompt ?? ""}`).includes(q)) continue;
      (g[s.state] ??= []).push(s);
    }
    for (const k of STATES.map(([k]) => k)) g[k].sort((a, b) => (a.repo + a.started).localeCompare(b.repo + b.started));
    return g;
  }, [sessions, query, agents]);

  // columnas colapsadas a la tira vertical. Sin eleccion guardada: "Terminó" arranca colapsada
  // (pedido del autor) y las vacias tambien; el click en la tira expande, el click en el titulo
  // colapsa, y la eleccion queda en localStorage.
  const [collapsed, setCollapsed] = useState<Collapsed>(loadCollapsed);
  const setCol = (k: State, v: boolean) => {
    setCollapsed((prev) => {
      const next = { ...prev, [k]: v };
      try {
        localStorage.setItem(COLLAPSE_KEY, JSON.stringify(next));
      } catch {
        /* sin storage, no importa */
      }
      return next;
    });
  };
  const isCollapsed = (k: State, n: number) => collapsed[k] ?? (k === "termino" || n === 0);

  // aprovechar el ancho: con una sola columna abierta sus tarjetas van en dos subcolumnas; con dos
  // abiertas, la que tiene mas tarjetas (dos en ejecucion y una en "te necesita", por ejemplo)
  const wideCols = useMemo(() => {
    const open = STATES.map(([k]) => k).filter((k) => !isCollapsed(k, byState[k].length));
    const out = new Set<State>();
    if (open.length === 1) out.add(open[0]);
    else if (open.length === 2) {
      const [a, b] = open;
      const na = byState[a].length, nb = byState[b].length;
      if (na >= 2 || nb >= 2) out.add(na >= nb ? a : b);
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [collapsed, byState]);

  // las flechas se recalculan cuando algo pudo mover una tarjeta
  const versionRef = useRef(0);
  const arrowsVersion = useMemo(() => ++versionRef.current, [sessions, filter, selected, collapsed, query, agents]);

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
      const cand = el && el.dataset.sid !== drag.from ? el.dataset.sid ?? null : null;
      const over = cand && canReceive(sessions[cand]) ? cand : null;
      setDrag((d) => (d ? { ...d, x2: e.clientX - b.left, y2: e.clientY - b.top, over } : d));
    };
    const up = (e: MouseEvent) => {
      const el = document.elementFromPoint(e.clientX, e.clientY)?.closest<HTMLElement>("[data-sid]");
      const to = el?.dataset.sid;
      setDrag(null);
      // soltar sobre una muerta, huerfana o sin consola no conecta: no habria a donde escribir
      if (to && to !== drag.from && canReceive(sessions[to])) onConnect(drag.from, to);
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDrag(null); // soltar en cualquier lado o Esc cancela
    };
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
      document.removeEventListener("keydown", key);
    };
  }, [drag?.from, onConnect]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <div className="filters">
        {STATES.map(([k, label]) => (
          <button key={k} className={filter === k ? "on" : ""} onClick={() => onFilter(k)}>
            {label} {byState[k].length}
          </button>
        ))}
      </div>
      <div
        className={`board ${drag ? "dragging" : ""}`}
        ref={boardRef}
        onMouseOver={(e) => {
          const sid = (e.target as HTMLElement).closest<HTMLElement>("[data-sid]")?.dataset.sid ?? null;
          setHover((h) => (h === sid ? h : sid));
        }}
        onMouseLeave={() => setHover(null)}
      >
        {showArrows && <Arrows links={links} rules={rules} sessions={sessions} boardRef={boardRef} version={arrowsVersion} hover={hover} onDelete={onDeleteLink} onDeleteRule={onDeleteRule} toast={toast} />}
        {drag && (
          <>
            <svg className="arrows draglink">
              <line x1={drag.x1} y1={drag.y1} x2={drag.x2} y2={drag.y2} />
            </svg>
            <div className="draghint">
              {drag.over ? `Soltá para conectar con ${sessions[drag.over]?.repo ?? ""}` : "Soltá sobre otra tarjeta para conectar · Esc cancela"}
            </div>
          </>
        )}
        {STATES.map(([k, label]) => {
          const list = byState[k];
          const col = isCollapsed(k, list.length);
          const wide = wideCols.has(k);
          return (
            <div key={k} className={`col ${k} ${col ? "collapsed" : ""} ${wide ? "wide" : ""} ${filter === k ? "show" : ""}`} style={wide ? { flexGrow: 2 } : undefined}>
              {col ? (
                <>
                  <div
                    className="vlabel"
                    role="button"
                    tabIndex={0}
                    title={`${label}: ${list.length} · click para expandir`}
                    onClick={() => setCol(k, false)}
                    onKeyDown={(e) => e.key === "Enter" && setCol(k, false)}
                  >
                    <span>{label}</span>
                    <span className="n">{list.length}</span>
                  </div>
                  <div className="empty">{list.length ? `${list.length} ocultas` : "nada acá"}</div>
                </>
              ) : (
                <>
                  <h2 title="click para colapsar la columna" onClick={() => setCol(k, true)}>
                    <span>{label}</span>
                    <span className="n">{list.length}</span>
                  </h2>
                  {list.length === 0 && <div className="empty">nada acá</div>}
                  <div className="cards">
                  {(wide ? [0, 1] : [null]).map((half) => {
                    // columna ancha: dos subcolumnas independientes (no una grilla por filas), asi
                    // cada tarjeta se apoya en la de arriba con el mismo aire aunque la de al lado
                    // sea mas alta; el orden se reparte alternado para conservar el de la lista
                    const items = half === null ? list : list.filter((_, j) => j % 2 === half);
                    const nodes = items.map((s) => (
                    <div key={s.session_id} className={drag?.over === s.session_id ? "droptarget" : ""}>
                      <Card
                        session={s}
                        pending={s.pending_id ? pending[s.pending_id] : undefined}
                        rules={rules.filter((r) => r.enabled && (r.to === s.session_id || r.from === s.session_id))}
                        links={links.filter((l) => l.to === s.session_id)}
                        sessions={sessions}
                        onDeleteRule={onDeleteRule}
                        toast={toast}
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
                        onPress={
                          canReceive(s)
                            ? (e) => {
                                pressRef.current = { sid: s.session_id, x: e.clientX, y: e.clientY };
                              }
                            : undefined
                        }
                      />
                    </div>
                    ));
                    return half === null ? nodes : <div key={half} className="subcol">{nodes}</div>;
                  })}
                  </div>
                </>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}
