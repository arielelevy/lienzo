import { useEffect, useMemo, useRef, useState } from "react";
import { Arrows } from "./Arrows";
import { Card, shortName } from "./Card";
import type { Link, Pending, Rule, Session, State } from "../types";

/** Columnas del tablero. "Trabajo" junta corriendo y termino (el estado se ve como icono en la
 *  tarjeta); "Te necesita" y "Muerta" siguen aparte porque piden accion. El tipo State es del
 *  server y no cambia: el mapeo estado -> columna vive aca. */
export type ColKey = "trabajo" | "te_necesita" | "muerta";
export const COLS: [ColKey, string][] = [
  ["trabajo", "Trabajo"],
  ["te_necesita", "Te necesita"],
  ["muerta", "Muerta"],
];
export const colOfState = (st: State): ColKey => (st === "corriendo" || st === "termino" ? "trabajo" : st);
/** Columna de una sesion. Una huerfana (proceso vivo pero sin terminal donde escribirle) o una con
 *  el proceso muerto va a "Muerta" aunque su estado diga otra cosa: no se le puede pedir nada. */
export const colOf = (s: Session): ColKey => (s.orphan || s.alive === false ? "muerta" : colOfState(s.state));
/** estado del filtro (State, lo maneja App) que representa a cada columna */
const FILTER_STATE: Record<ColKey, State> = { trabajo: "corriendo", te_necesita: "te_necesita", muerta: "muerta" };

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

/** Columnas que el usuario colapso a mano teniendo tarjetas: por columna, los ids que tenia en ese
 *  momento. Se respeta mientras la columna solo contenga esas tarjetas; una nueva la abre y borra la
 *  entrada. (El formato viejo, booleanos, se ignora.) */
const COLLAPSE_KEY = "lienzo.collapsed";
type Manual = Partial<Record<ColKey, string[]>>;
function loadManual(): Manual {
  try {
    const raw = localStorage.getItem(COLLAPSE_KEY);
    const j = raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
    const out: Manual = {};
    for (const [k] of COLS) if (Array.isArray(j[k])) out[k] = (j[k] as unknown[]).filter((x): x is string => typeof x === "string");
    return out;
  } catch {
    return {};
  }
}
const EMPTY_COLLAPSE_MS = 10_000;

/** Subcolumnas de tarjetas disponibles en total: 4 en pantalla ancha, 2 por debajo de ~1100 px
 *  (en movil el CSS fuerza 1). */
function useLaneBudget(): number {
  const mq = () => (typeof window !== "undefined" && window.matchMedia("(min-width: 1100px)").matches ? 4 : 2);
  const [budget, setBudget] = useState<number>(mq);
  useEffect(() => {
    const m = window.matchMedia("(min-width: 1100px)");
    const on = () => setBudget(m.matches ? 4 : 2);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  return budget;
}

/** Reparte `budget` subcolumnas entre las columnas abiertas segun cuantas tarjetas tienen: una
 *  abierta se lleva todas; dos, mitad y mitad (3 y 1 si una tiene muchas mas); tres, 2 para la
 *  que mas tiene y 1 para las otras. Ninguna recibe mas subcolumnas que tarjetas. */
export function splitLanes(open: { key: ColKey; n: number }[], budget: number): Record<ColKey, number> {
  const out = { trabajo: 1, te_necesita: 1, muerta: 1 } as Record<ColKey, number>;
  if (!open.length) return out;
  const sorted = [...open].sort((a, b) => b.n - a.n);
  if (open.length === 1) out[open[0].key] = budget;
  else if (open.length === 2) {
    const [a, b] = sorted;
    if (budget >= 4 && a.n >= 3 * Math.max(b.n, 1)) {
      out[a.key] = 3;
      out[b.key] = 1;
    } else {
      out[a.key] = budget / 2;
      out[b.key] = budget / 2;
    }
  } else {
    out[sorted[0].key] = budget >= 4 ? 2 : 1;
  }
  for (const o of open) out[o.key] = Math.max(1, Math.min(out[o.key], o.n));
  return out;
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
  // El arrastre va por Pointer Events, asi funciona igual con mouse y con el dedo. Presion sobre el
  // cuerpo de una tarjeta (solo mouse: con el dedo el cuerpo scrollea): es arrastre si se mueve mas
  // de 8 px, si no es click. Desde el agarre ⇢ arrastra de una, con cualquier puntero (.grip lleva
  // touch-action: none para que el scroll no se lo lleve).
  const pressRef = useRef<{ sid: string; x: number; y: number } | null>(null);
  const draggedRef = useRef(false);

  useEffect(() => {
    const move = (e: PointerEvent) => {
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
      // el click (si lo hay) llega despues del pointerup, y la tarjeta lo demora 280 ms para
      // distinguirlo del doble click: la marca tiene que sobrevivir a esa demora
      setTimeout(() => {
        draggedRef.current = false;
      }, 400);
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
    document.addEventListener("pointercancel", up);
    return () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      document.removeEventListener("pointercancel", up);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    const t = e.target as HTMLElement;
    const sid = t.closest<HTMLElement>("[data-sid]")?.dataset.sid;
    // una muerta, huerfana o sin consola no arrastra: no habria a donde escribir ni que programarle
    if (!sid || !canReceive(sessions[sid])) return;
    if (t.closest(".grip")) {
      draggedRef.current = true;
      startDragAt(sid, e.clientX, e.clientY);
      return;
    }
    if (e.pointerType !== "mouse" || t.closest("button, a, input, textarea, .x, code")) return;
    pressRef.current = { sid, x: e.clientX, y: e.clientY };
  };

  // una pasada por render: las sesiones que pasan el filtro del header, agrupadas por columna.
  // En "Trabajo" van primero las que corren (por repo + inicio) y despues las terminadas, la mas
  // reciente arriba. El filtro es solo visual: el server no se entera.
  const byState = useMemo(() => {
    const q = norm(query.trim());
    const g: Record<ColKey, Session[]> = { trabajo: [], te_necesita: [], muerta: [] };
    for (const s of Object.values(sessions)) {
      if (!agents[s.agent]) continue;
      if (q && !norm(`${s.repo} ${s.title ?? ""} ${s.last_prompt ?? ""}`).includes(q)) continue;
      g[colOf(s)].push(s);
    }
    const done = (s: Session) => (s.state === "termino" ? 1 : 0);
    for (const k of COLS.map(([k]) => k)) {
      g[k].sort((a, b) => {
        if (done(a) !== done(b)) return done(a) - done(b);
        if (done(a)) return b.state_since.localeCompare(a.state_since);
        return (a.repo + a.started).localeCompare(b.repo + b.started);
      });
    }
    return g;
  }, [sessions, query, agents]);

  // columnas colapsadas a la tira vertical. Regla: abierta si tiene tarjetas, colapsada si no, las
  // tres por igual. Encima de eso, dos excepciones:
  //  - `manual` (localStorage lienzo.collapsed): el usuario colapso a mano una columna con tarjetas.
  //    Se guarda con los ids que tenia y se respeta mientras solo contenga esas; una tarjeta nueva la
  //    vuelve a abrir y borra la eleccion.
  //  - `openEmpty` (solo en memoria): una columna vacia que esta abierta (el usuario la abrio, o se
  //    vacio estando abierta) se cierra sola a los 10 s.
  // Mientras el filtro del header (texto o agentes) matchea tarjetas de una columna colapsada, esa
  // columna se muestra abierta sin tocar nada de lo anterior.
  const [manual, setManual] = useState<Manual>(loadManual);
  const [openEmpty, setOpenEmpty] = useState<Partial<Record<ColKey, boolean>>>({});
  const emptyTimers = useRef<Partial<Record<ColKey, number>>>({});
  const filtering = query.trim() !== "" || Object.values(agents).some((v) => !v);
  const saveManual = (next: Manual) => {
    setManual(next);
    try {
      localStorage.setItem(COLLAPSE_KEY, JSON.stringify(next));
    } catch {
      /* sin storage, no importa */
    }
  };
  const stopEmptyTimer = (k: ColKey) => {
    window.clearTimeout(emptyTimers.current[k]);
    emptyTimers.current[k] = undefined;
  };
  // columna vacia abierta: 10 s y se cierra sola
  const holdOpenEmpty = (k: ColKey) => {
    stopEmptyTimer(k);
    setOpenEmpty((o) => ({ ...o, [k]: true }));
    emptyTimers.current[k] = window.setTimeout(() => {
      emptyTimers.current[k] = undefined;
      setOpenEmpty((o) => ({ ...o, [k]: false }));
    }, EMPTY_COLLAPSE_MS);
  };
  const setCol = (k: ColKey, collapse: boolean) => {
    const ids = byState[k].map((s) => s.session_id);
    if (collapse) {
      stopEmptyTimer(k);
      setOpenEmpty((o) => ({ ...o, [k]: false }));
      if (ids.length) saveManual({ ...manual, [k]: ids });
    } else if (ids.length) {
      const { [k]: _drop, ...rest } = manual;
      saveManual(rest);
    } else {
      holdOpenEmpty(k);
    }
  };
  // con cada cambio de tarjetas: una nueva en una columna colapsada a mano la abre (y borra la
  // eleccion); una columna abierta que se vacia arranca sus 10 s; una que recibe tarjetas deja de
  // depender del timer
  const prevCount = useRef<Record<ColKey, number>>(Object.fromEntries(COLS.map(([k]) => [k, byState[k].length])) as Record<ColKey, number>);
  useEffect(() => {
    let next = manual;
    let changed = false;
    for (const [k] of COLS) {
      const ids = byState[k].map((s) => s.session_id);
      const kept = next[k];
      if (kept && ids.some((id) => !kept.includes(id))) {
        const { [k]: _drop, ...rest } = next;
        next = rest;
        changed = true;
      }
      const n = ids.length;
      if (n === 0 && prevCount.current[k] > 0) holdOpenEmpty(k);
      if (n > 0 && emptyTimers.current[k] !== undefined) stopEmptyTimer(k);
      prevCount.current[k] = n;
    }
    if (changed) saveManual(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [byState]);
  useEffect(() => () => Object.values(emptyTimers.current).forEach((t) => window.clearTimeout(t)), []);

  const isCollapsed = (k: ColKey, n: number) => {
    if (filtering && n > 0) return false;
    if (n === 0) return !openEmpty[k];
    return !!manual[k];
  };

  // aprovechar el ancho: hasta 4 subcolumnas de tarjetas en total (2 en pantallas angostas),
  // repartidas entre las columnas abiertas. Cada columna crece en proporcion a sus subcolumnas,
  // asi todas las tarjetas del tablero quedan del mismo ancho
  const laneBudget = useLaneBudget();
  const lanes = useMemo(() => {
    const open = COLS.map(([k]) => k)
      .filter((k) => !isCollapsed(k, byState[k].length))
      .map((k) => ({ key: k, n: byState[k].length }));
    return splitLanes(open, laneBudget);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [manual, openEmpty, byState, filtering, laneBudget]);

  // las flechas se recalculan cuando algo pudo mover una tarjeta
  const versionRef = useRef(0);
  const arrowsVersion = useMemo(() => ++versionRef.current, [sessions, filter, selected, manual, openEmpty, query, agents, laneBudget]);

  // arrastre de una tarjeta a otra: linea provisoria que sigue al mouse, al soltar sobre otra
  // tarjeta se abre el reenvio con ese destino
  const startDragAt = (sid: string, cx: number, cy: number) => {
    const board = boardRef.current;
    if (!board) return;
    const b = board.getBoundingClientRect();
    // la linea sale del agarre ⇢ (fila de arriba de la tarjeta); sin agarre, del mouse
    const card = board.querySelector<HTMLElement>(`[data-sid="${sid}"]`);
    const r = card?.querySelector<HTMLElement>(".grip")?.getBoundingClientRect();
    const x1 = r ? (r.left + r.right) / 2 - b.left : cx - b.left;
    const y1 = r ? (r.top + r.bottom) / 2 - b.top : cy - b.top;
    setDrag({ from: sid, x1, y1, x2: cx - b.left, y2: cy - b.top, over: null });
  };
  useEffect(() => {
    if (!drag) return;
    const move = (e: PointerEvent) => {
      const board = boardRef.current;
      if (!board) return;
      const b = board.getBoundingClientRect();
      const el = document.elementFromPoint(e.clientX, e.clientY)?.closest<HTMLElement>("[data-sid]");
      // la propia tarjeta tambien es destino: la flecha que vuelve al mismo bloque es un bucle,
      // "programale un mensaje a esta misma sesion" (a una hora o cada tanto)
      const cand = el?.dataset.sid ?? null;
      const over = cand && canReceive(sessions[cand]) ? cand : null;
      setDrag((d) => (d ? { ...d, x2: e.clientX - b.left, y2: e.clientY - b.top, over } : d));
    };
    const up = (e: PointerEvent) => {
      const el = document.elementFromPoint(e.clientX, e.clientY)?.closest<HTMLElement>("[data-sid]");
      const to = el?.dataset.sid;
      setDrag(null);
      // soltar sobre una muerta, huerfana o sin consola no conecta: no habria a donde escribir.
      // Sobre si misma (solo si el arrastre ya arranco: un click sin mover nunca llega aca) abre el
      // dialogo con from === to, que Forward toma como "programar para esta sesion"
      if (to && canReceive(sessions[to])) onConnect(drag.from, to);
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDrag(null); // soltar en cualquier lado o Esc cancela
    };
    const cancel = () => setDrag(null); // el navegador se quedo el puntero (scroll, gesto del sistema)
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
    document.addEventListener("pointercancel", cancel);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      document.removeEventListener("pointercancel", cancel);
      document.removeEventListener("keydown", key);
    };
  }, [drag?.from, onConnect]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <div className="filters">
        {COLS.map(([k, label]) => (
          <button key={k} className={colOfState(filter) === k ? "on" : ""} onClick={() => onFilter(FILTER_STATE[k])}>
            {label} {byState[k].length}
          </button>
        ))}
      </div>
      <div
        className={`board ${drag ? "dragging" : ""}`}
        ref={boardRef}
        onPointerDown={onPointerDown}
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
              {drag.over === drag.from
                ? "Soltá acá para programarle un mensaje a esta sesión (a una hora o cada tanto)"
                : drag.over
                  ? `Soltá para conectar con ${shortName(sessions[drag.over])}`
                  : "Soltá sobre otra tarjeta para conectar, o sobre la misma para programarle un mensaje · Esc cancela"}
            </div>
          </>
        )}
        {COLS.map(([k, label]) => {
          const list = byState[k];
          const col = isCollapsed(k, list.length);
          const wide = lanes[k] > 1;
          // la columna lleva ademas las clases de los estados que contiene: Arrows ubica la tira de
          // una columna colapsada por `.col.<estado>.collapsed`, con el estado de la sesion
          const stateClasses = k === "trabajo" ? "corriendo termino" : k;
          return (
            <div
              key={k}
              className={`col ${k} ${stateClasses} ${col ? "collapsed" : ""} ${wide ? "wide" : ""} ${colOfState(filter) === k ? "show" : ""}`}
              style={col ? undefined : ({ flexGrow: lanes[k], "--lanes": lanes[k] } as React.CSSProperties)}
            >
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
                  {/* columna ancha: subcolumnas por CSS (column-count: var(--lanes) en .col.wide .cards),
                      no por padres distintos: si una tarjeta cambiara de subcolumna React la remontaria
                      y perderia su estado (pedido expandido, input de renombrar, toast) */}
                  {list.map((s) => (
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
                        // el agarre y la presion sobre el cuerpo se manejan con Pointer Events en el
                        // tablero (onPointerDown); onGrip solo hace que la tarjeta dibuje el agarre
                        onGrip={() => undefined}
                      />
                    </div>
                  ))}
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
