import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ago, api } from "../api";
import { hhmm, nextAt } from "../nl";
import { computeSegs, FRESH_MS, type Rect, type Seg } from "../arrows-geometry";
import { periodLabel } from "./Card";
import type { Link, Rule, Session } from "../types";

interface Props {
  links: Link[];
  rules: Rule[];
  /** para saber en que columna esta una sesion cuya tarjeta no se ve (columna colapsada) */
  sessions: Record<string, Session>;
  boardRef: React.RefObject<HTMLDivElement | null>;
  /** sube cuando cambian sesiones, filtro o seleccion: las tarjetas se movieron, hay que recalcular */
  version: number;
  /** tarjeta bajo el mouse: sus flechas se resaltan y el resto se atenua */
  hover: string | null;
  onDelete: (id: string) => void;
  onDeleteRule: (id: string) => void;
  toast?: (msg: string, err?: boolean) => void;
}

/** Editor de una conexion pendiente, anclado al glifo de su flecha. */
interface Edit {
  id: string;
  kind: Rule["kind"];
  x: number;
  y: number;
  text: string;
  time: string;
  /** on_stop: se repite hasta maxFires; at: es periodica (every_s) hasta maxFires */
  repeat: boolean;
  maxFires: number;
  /** at periodica: "repetir cada [everyN] [everyUnit]" */
  everyN: number;
  everyUnit: "min" | "h";
  /** at periodica: si el destino esta corriendo, saltear el disparo sin contarlo */
  skipBusy: boolean;
}

/** every_s en segundos → cantidad y unidad para el editor (horas enteras en h, el resto en min) */
function splitEvery(everyS: number | null | undefined): { everyN: number; everyUnit: "min" | "h" } {
  const s = everyS ?? 1800;
  if (s >= 3600 && s % 3600 === 0) return { everyN: s / 3600, everyUnit: "h" };
  return { everyN: Math.max(1, Math.round(s / 60)), everyUnit: "min" };
}

/** doble click en un envio ya hecho: no se edita, pero se ve que se mando y se puede reenviar */
interface View {
  ids: string[];
  from: string;
  to: string;
  native: boolean;
  x: number;
  y: number;
}

/** Flechas entre tarjetas. En el tablero quedan solo las conexiones pendientes (reglas on_stop y
 *  at, punteadas) y el canal nativo Claude<->Claude (doble). Un envio comun se muestra 60 s con
 *  un fade, para confirmar que salio, y despues se va: lo enviado vive en la pestana Conexiones.
 *  Las posiciones salen del DOM (data-sid) y se recalculan al cambiar sesiones, vinculos o tamano.
 *  Las curvas entre columnas viajan por el hueco entre los grupos de tarjetas vecinos; las de la
 *  misma columna hacen un arco corto por el costado con mas lugar. En pantalla angosta no hay flechas. */
export function Arrows({ links, rules, sessions, boardRef, version, hover, onDelete, onDeleteRule, toast }: Props) {
  const [segs, setSegs] = useState<Seg[]>([]);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [, setTick] = useState(0);
  // doble click en el glifo de una regla: editarla en el lugar. El click simple (quitar) espera
  // un poco para no confirmar dos veces antes de que llegue el doble click.
  const [edit, setEdit] = useState<Edit | null>(null);
  const [saving, setSaving] = useState(false);
  const clickTimer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(clickTimer.current), []);
  useEffect(() => {
    // la regla que se estaba editando desaparecio (la borro otro, o disparo): cerrar
    if (edit && !rules.some((r) => r.id === edit.id)) setEdit(null);
  }, [rules, edit]);
  const openEdit = (s: Seg) => {
    const r = rules.find((x) => x.id === s.ids[0]);
    if (!r) return;
    const periodic = r.kind === "at" && !!r.every_s;
    setEdit({
      id: r.id,
      kind: r.kind,
      x: s.x,
      y: s.y,
      text: r.text,
      time: r.at ? hhmm(new Date(r.at)) : "",
      repeat: r.kind === "at" ? periodic : r.repeat,
      maxFires: r.max_fires,
      ...splitEvery(r.every_s),
      skipBusy: r.skip_busy ?? true,
    });
  };
  const everySeconds = (e: Edit) => Math.max(60, e.everyN * (e.everyUnit === "h" ? 3600 : 60));
  const saveEdit = async () => {
    if (!edit) return;
    const body: Record<string, unknown> = { text: edit.text };
    if (edit.kind === "at") {
      const m = edit.time.trim().match(/^(\d{1,2}):(\d{2})$/);
      if (!m || Number(m[1]) > 23 || Number(m[2]) > 59) {
        toast?.("Hora inválida: usá HH:MM", true);
        return;
      }
      body.at = nextAt(Number(m[1]), Number(m[2])).toISOString(); // ya paso hoy: manana
      // periodica: every_s (null la vuelve de un disparo), tope de disparos y saltear si esta ocupada
      body.every_s = edit.repeat ? everySeconds(edit) : null;
      body.max_fires = edit.repeat ? edit.maxFires : 1;
      body.skip_busy = edit.skipBusy;
    } else {
      body.repeat = edit.repeat;
      body.max_fires = edit.maxFires;
    }
    setSaving(true);
    try {
      await api.put(`/rules/${edit.id}`, body);
      toast?.(
        edit.kind !== "at"
          ? "Conexión guardada"
          : edit.repeat
            ? `Desde las ${edit.time.trim()}, ${periodLabel(everySeconds(edit))}, hasta ${edit.maxFires} veces`
            : `Reprogramada a las ${edit.time.trim()}`,
      );
      setEdit(null);
    } catch (e) {
      toast?.(`No se pudo guardar: ${(e as Error).message}`, true);
    } finally {
      setSaving(false);
    }
  };

  // envio ya hecho (o canal nativo): ver los mensajes del par y, si el destino tiene consola,
  // mandar el ultimo de nuevo por POST /sessions/<to>/send
  const [view, setView] = useState<View | null>(null);
  const [resending, setResending] = useState(false);
  useEffect(() => {
    if (view && !view.ids.some((id) => links.some((l) => l.id === id))) setView(null); // se quito la flecha
  }, [links, view]);
  useEffect(() => {
    // la vista no tiene inputs con foco, asi que Esc se escucha en el documento mientras esta abierta
    if (!view) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setView(null);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [view]);
  const openView = (s: Seg) => {
    setEdit(null);
    setView({ ids: s.ids, from: s.from, to: s.to, native: s.kind === "native", x: s.x, y: s.y });
  };
  const viewLinks = view ? links.filter((l) => view.ids.includes(l.id)).sort((a, c) => c.ts.localeCompare(a.ts)) : [];
  const viewTarget = view ? sessions[view.to] : undefined;
  const canResend = !!viewTarget && viewTarget.alive && !viewTarget.orphan && !viewTarget.no_console && !viewTarget.pending_id;
  const nameOf = (sid: string) => {
    const o = sessions[sid];
    if (!o) return sid.slice(0, 8);
    return o.title ? `${o.repo} · ${o.title.slice(0, 24)}` : `${o.repo} · ${sid.slice(0, 8)}`;
  };
  const resend = async () => {
    if (!view || !viewLinks[0]) return;
    setResending(true);
    try {
      const r = await api.post<{ chars: number }>(`/sessions/${view.to}/send`, { text: viewLinks[0].text, attachments: [] });
      toast?.(`Reenviado a ${nameOf(view.to)} (${r.chars} caracteres)`);
      setView(null);
    } catch (e) {
      toast?.(`No se pudo reenviar: ${(e as Error).message}`, true);
    } finally {
      setResending(false);
    }
  };

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
    // sesion en una columna colapsada (por ejemplo la tarjeta paso a "Terminó"): la flecha llega a
    // la etiqueta vertical de esa tira en vez de perderse. Esos extremos van en `anchors`, aparte de
    // `rects`: la tira no es una tarjeta, no cuenta como columna ni dos veces como obstaculo
    const stripOf = (sid: string): Rect | undefined => {
      const st = sessions[sid]?.state;
      const el = st ? board.querySelector<HTMLElement>(`.col.${st}.collapsed .vlabel`) : null;
      if (!el) return undefined;
      const r = el.getBoundingClientRect();
      return { l: r.left - b.left, t: r.top - b.top, r: r.right - b.left, b: r.bottom - b.top };
    };
    const anchors = new Map(rects);
    for (const sid of new Set([...links.flatMap((l) => [l.from, l.to]), ...rules.flatMap((r) => [r.from, r.to])])) {
      if (sid && !anchors.has(sid)) {
        const r = stripOf(sid);
        if (r) anchors.set(sid, r);
      }
    }
    // columnas colapsadas: obstaculos laterales para el arco de misma columna (no son columnas)
    const strips = Array.from(board.querySelectorAll<HTMLElement>(".col.collapsed")).map((el) => {
      const r = el.getBoundingClientRect();
      return { l: r.left - b.left, r: r.right - b.left };
    });
    const out = computeSegs({
      rects,
      anchors,
      strips,
      boardWidth: board.scrollWidth,
      links,
      rules,
      fmt: { ago, hhmm: (iso) => hhmm(new Date(iso)) },
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
  // Recalcular cuando algo se movio sin que cambien props: una tarjeta que crece ("…más", chips,
  // botones rapidos), una columna que cambia de ancho, tarjetas que aparecen o cambian de columna.
  // El tablero solo no alcanza: con contenido mas bajo que su min-height no cambia de tamano.
  useEffect(() => {
    const board = boardRef.current;
    if (!board) return;
    let raf = 0;
    const schedule = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        computeRef.current();
      });
    };
    window.addEventListener("resize", schedule);
    const observed = new Set<Element>();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(schedule) : null;
    ro?.observe(board);
    const watch = () => {
      if (!ro) return;
      for (const el of observed) {
        if (!el.isConnected) {
          ro.unobserve(el);
          observed.delete(el);
        }
      }
      for (const el of board.querySelectorAll("[data-sid], .col")) {
        if (!observed.has(el)) {
          ro.observe(el);
          observed.add(el);
        }
      }
    };
    watch();
    const elOf = (n: Node) => (n instanceof Element ? n : n.parentElement);
    const mo =
      typeof MutationObserver !== "undefined"
        ? new MutationObserver((muts) => {
            if (muts.every((m) => elOf(m.target)?.closest(".arrows"))) return; // nuestro propio svg
            watch();
            schedule();
          })
        : null;
    mo?.observe(board, { childList: true, subtree: true });
    return () => {
      window.removeEventListener("resize", schedule);
      ro?.disconnect();
      mo?.disconnect();
      if (raf) cancelAnimationFrame(raf);
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
    <>
    {edit && (
      <div
        className="arrow-edit"
        style={{ left: edit.x, top: edit.y }}
        role="dialog"
        aria-label="editar conexión"
        onClick={(e) => e.stopPropagation()}
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          e.stopPropagation();
          if (e.key === "Escape") setEdit(null);
          else if (e.key === "Enter" && !(e.target instanceof HTMLTextAreaElement)) {
            e.preventDefault();
            saveEdit();
          }
        }}
      >
        <div className="hd">{edit.kind === "at" ? (edit.repeat ? "↻ periódica" : "⏰ programada") : "⏹ cuando termine"}</div>
        {edit.kind === "at" && (
          <label>
            {edit.repeat ? "primera vez (HH:MM)" : "hora (HH:MM)"}
            <input autoFocus value={edit.time} placeholder="HH:MM" onChange={(e) => setEdit({ ...edit, time: e.target.value })} />
          </label>
        )}
        <label>
          {edit.kind === "at" ? "texto que se escribe" : "plantilla ({repo}, {titulo}, {pedido}, {respuesta})"}
          <textarea rows={edit.kind === "at" ? 2 : 3} autoFocus={edit.kind !== "at"} value={edit.text} onChange={(e) => setEdit({ ...edit, text: e.target.value })} />
        </label>
        {edit.kind === "at" && (
          <>
            <label className="row">
              <input type="checkbox" checked={edit.repeat} onChange={(e) => setEdit({ ...edit, repeat: e.target.checked })} />
              repetir cada
              <input
                type="number"
                min={1}
                max={edit.everyUnit === "h" ? 168 : 1440}
                disabled={!edit.repeat}
                value={edit.everyN}
                onChange={(e) => setEdit({ ...edit, everyN: Math.max(1, Math.min(1440, Number(e.target.value) || 1)) })}
              />
              <select disabled={!edit.repeat} value={edit.everyUnit} onChange={(e) => setEdit({ ...edit, everyUnit: e.target.value as "min" | "h" })}>
                <option value="min">min</option>
                <option value="h">h</option>
              </select>
            </label>
            <label className="row indent">
              hasta
              <input type="number" min={1} max={50} disabled={!edit.repeat} value={edit.maxFires} onChange={(e) => setEdit({ ...edit, maxFires: Math.max(1, Math.min(50, Number(e.target.value) || 1)) })} />
              veces
            </label>
            <label className="row indent" title="si a esa hora el destino está corriendo, ese disparo se saltea y no cuenta">
              <input type="checkbox" disabled={!edit.repeat} checked={edit.skipBusy} onChange={(e) => setEdit({ ...edit, skipBusy: e.target.checked })} />
              sólo si está libre
            </label>
          </>
        )}
        {edit.kind === "on_stop" && (
          <label className="row">
            <input type="checkbox" checked={edit.repeat} onChange={(e) => setEdit({ ...edit, repeat: e.target.checked })} />
            repetir, hasta
            <input type="number" min={1} max={50} disabled={!edit.repeat} value={edit.maxFires} onChange={(e) => setEdit({ ...edit, maxFires: Math.max(1, Math.min(50, Number(e.target.value) || 1)) })} />
            veces
          </label>
        )}
        <div className="btns">
          <button type="button" onClick={() => setEdit(null)}>Cancelar</button>
          <button type="button" className="ok" disabled={saving} onClick={saveEdit}>Guardar</button>
        </div>
      </div>
    )}
    {view && (
      <div
        className="arrow-edit view"
        style={{ left: view.x, top: view.y }}
        role="dialog"
        aria-label="envío hecho"
        onClick={(e) => e.stopPropagation()}
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          e.stopPropagation();
          if (e.key === "Escape") setView(null);
        }}
      >
        <div className="hd">{view.native ? "⇄ canal nativo" : "↪ enviado"} · {nameOf(view.from)} → {nameOf(view.to)}</div>
        <div className="msgs">
          {viewLinks.slice(0, 5).map((l) => (
            <div key={l.id} className="msg" title={l.text}>
              <span className="dim">{hhmm(new Date(l.ts))}</span> {l.text}
            </div>
          ))}
          {viewLinks.length > 5 && <div className="dim small">… y {viewLinks.length - 5} más</div>}
        </div>
        <div className="dim small">
          {view.native
            ? "Lo que se dijeron por el canal nativo no se reenvía desde acá."
            : canResend
              ? "Un envío hecho no se edita; se puede mandar de nuevo el último tal cual."
              : "El destino no tiene consola donde escribir ahora."}
        </div>
        <div className="btns">
          <button type="button" onClick={() => setView(null)}>Cerrar</button>
          {!view.native && (
            <button type="button" className="ok" disabled={resending || !canResend} onClick={resend} title="escribe el último texto otra vez en la terminal destino">
              Mandar de nuevo
            </button>
          )}
        </div>
      </div>
    )}
    <svg className={`arrows ${hover ? "hovering" : ""}`} width={size.w} height={size.h} style={{ width: size.w, height: size.h }}>
      <defs>
        {/* puntas chicas (7x6): la linea es de 2 px y una punta de 10x8 se veia pesada */}
        <marker id="arrowhead" markerWidth="7" markerHeight="6" refX="6.5" refY="3" orient="auto">
          <path d="M0,0 L7,3 L0,6 z" fill="var(--acc)" />
        </marker>
        <marker id="arrowtail" markerWidth="7" markerHeight="6" refX="0.5" refY="3" orient="auto">
          <path d="M7,0 L0,3 L7,6 z" fill="var(--acc)" />
        </marker>
      </defs>
      {segs.map((s) => {
        const mine = hover !== null && (s.from === hover || s.to === hover);
        const many = s.ids.length > 1;
        return (
          <g
            key={s.ids[0]}
            className={`arrow ${s.old ? "old" : ""} ${mine ? "mine" : ""} ${s.fresh ? "fresh" : ""} ${s.dim ? "dim" : ""}`}
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
                window.clearTimeout(clickTimer.current);
                clickTimer.current = window.setTimeout(() => {
                  const q = s.kind === "rule" ? "Quitar la conexión?" : "Quitar la flecha?";
                  if (!confirm(q)) return;
                  for (const id of s.ids) (s.kind === "rule" ? onDeleteRule : onDelete)(id);
                }, 280);
              }}
              onDoubleClick={() => {
                window.clearTimeout(clickTimer.current);
                if (s.kind !== "rule") {
                  openView(s); // ver que se mando y, si hay donde, mandarlo de nuevo
                  return;
                }
                setView(null);
                openEdit(s);
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
    </>
  );
}
