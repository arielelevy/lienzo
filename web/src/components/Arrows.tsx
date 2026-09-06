import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ago, api } from "../api";
import { everySeconds, hhmm, nextAt, splitEvery, type EveryUnit } from "../nl";
import { periodLabel, shortName, whenLabel } from "../names";
import { computeSegs, laneHeight, type Band, type Rect, type Seg } from "../arrows-geometry";
import type { Link, Rule, Session } from "../types";

interface Props {
  links: Link[];
  rules: Rule[];
  /** para saber en que columna esta una sesion cuya tarjeta no se ve (columna colapsada) */
  sessions: Record<string, Session>;
  boardRef: React.RefObject<HTMLDivElement | null>;
  /** sube cuando cambian sesiones, filtro o seleccion: las tarjetas se movieron, hay que recalcular */
  version: number;
  /** tarjeta seleccionada (antes: bajo el mouse): sus flechas se resaltan y el resto se atenua */
  hover: string | null;
  onDelete: (id: string) => void;
  onDeleteRule: (id: string) => void;
  toast?: (msg: string, err?: boolean) => void;
}

/** Alto del carril que el tablero tiene que reservar, en `data-lanes` y en la variable `--lane-h`
 *  que usa el CSS de la columna. Cero: no hay ninguna flecha que use carril y la columna se ve
 *  como siempre. La variable va en el style del nodo, que React no toca (el div del tablero no
 *  lleva prop `style`), asi sobrevive a los renders. */
function setLanes(board: HTMLDivElement, px: number): void {
  if (px > 0) {
    board.dataset.lanes = String(px);
    board.style.setProperty("--lane-h", `${px}px`);
  } else {
    board.removeAttribute("data-lanes");
    board.style.removeProperty("--lane-h");
  }
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
  everyUnit: EveryUnit;
  /** at periodica: si el destino esta corriendo, saltear el disparo sin contarlo */
  skipBusy: boolean;
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

/** Flechas entre tarjetas: las conexiones pendientes (reglas on_stop y at, punteadas), el canal
 *  nativo Claude<->Claude (doble) y el ultimo envio de cada par (los anteriores van al contador).
 *  Las posiciones salen del DOM (data-sid) y se recalculan al cambiar sesiones, vinculos o tamano.
 *  Las curvas entre columnas viajan por el hueco entre los grupos de tarjetas vecinos; las de la
 *  misma columna hacen un arco corto por el costado con mas lugar; la que cruzaria una tercera
 *  tarjeta corre en horizontal por un carril libre (arriba del todo, entre dos filas o abajo).
 *  En pantalla angosta no hay flechas.
 *
 *  Un click en el glifo **selecciona** la flecha: se resalta, se resaltan las dos tarjetas que une
 *  y aparece al lado una descripcion de que es y que hace. Recien el doble click abre para operar
 *  (el editor de una regla, la vista de un envio), y Quitar vive adentro de esos dos, con
 *  confirmacion. Antes el click borraba y el doble click era la unica puerta al editor. */
export function Arrows({ links, rules, sessions, boardRef, version, hover, onDelete, onDeleteRule, toast }: Props) {
  const [segs, setSegs] = useState<Seg[]>([]);
  const [size, setSize] = useState({ w: 0, h: 0 });
  // flecha seleccionada, por el id de su primer link o regla: mientras lo esta, se explica sola
  const [sel, setSel] = useState<string | null>(null);
  const selSeg = sel ? (segs.find((s) => s.ids[0] === sel) ?? null) : null;
  const [edit, setEdit] = useState<Edit | null>(null);
  const [saving, setSaving] = useState(false);
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
      body.every_s = edit.repeat ? everySeconds(edit.everyN, edit.everyUnit) : null;
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
            ? `Desde las ${edit.time.trim()}, ${periodLabel(everySeconds(edit.everyN, edit.everyUnit))}, hasta ${edit.maxFires} veces`
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
  const nameOf = (sid: string) => shortName(sessions[sid], sid.slice(0, 8));
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

  /** Quitar vive adentro del editor y de la vista, nunca suelto en el tablero: un click perdido no
   *  puede borrar una conexion. La confirmacion queda igual que siempre. */
  const removeSeg = (s: Seg) => {
    if (!confirm(s.kind === "rule" ? "Quitar la conexión?" : "Quitar la flecha?")) return;
    for (const id of s.ids) (s.kind === "rule" ? onDeleteRule : onDelete)(id);
    setEdit(null);
    setView(null);
    setSel(null);
  };

  // con una flecha seleccionada: Esc la suelta, Supr ofrece quitarla, un click en el vacio la suelta
  useEffect(() => {
    if (!sel) return;
    const typing = (t: EventTarget | null) =>
      t instanceof HTMLElement && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));
    const onKey = (e: KeyboardEvent) => {
      if (typing(e.target)) return;
      if (e.key === "Escape") setSel(null);
      else if (e.key === "Delete") {
        const s = segs.find((x) => x.ids[0] === sel);
        if (s) removeSeg(s);
      }
    };
    const onDown = () => setSel(null); // el click sobre el glifo vuelve a seleccionar despues
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sel, segs]);

  const compute = () => {
    const board = boardRef.current;
    if (!board || window.innerWidth <= 900) {
      if (board) setLanes(board, 0);
      setSegs([]);
      return;
    }
    const b = board.getBoundingClientRect();
    setSize((prev) => (prev.w === board.scrollWidth && prev.h === board.scrollHeight ? prev : { w: board.scrollWidth, h: board.scrollHeight }));
    const rel = (el: Element): Rect => {
      const r = el.getBoundingClientRect();
      return { l: r.left - b.left, t: r.top - b.top, r: r.right - b.left, b: r.bottom - b.top };
    };

    // rects de todas las tarjetas, relativos al tablero
    const rects = new Map<string, Rect>();
    for (const el of board.querySelectorAll<HTMLElement>("[data-sid]")) {
      if (el.dataset.sid) rects.set(el.dataset.sid, rel(el));
    }
    // area util de cada columna: de aca para abajo puede haber flechas. El techo es el borde
    // inferior del encabezado, porque una linea por encima le pasa por arriba al titulo
    const bands: Band[] = Array.from(board.querySelectorAll<HTMLElement>(".col")).map((col) => {
      const r = rel(col);
      const h2 = col.querySelector<HTMLElement>(":scope > h2");
      return { ...r, t: h2 ? rel(h2).b : r.t };
    });
    // sesion en una columna colapsada (por ejemplo la tarjeta paso a "Terminó"): la flecha llega a
    // la etiqueta vertical de esa tira en vez de perderse. Esos extremos van en `anchors`, aparte de
    // `rects`: la tira no es una tarjeta, no cuenta como columna ni dos veces como obstaculo
    const stripOf = (sid: string): Rect | undefined => {
      const st = sessions[sid]?.state;
      const el = st ? board.querySelector<HTMLElement>(`.col.${st}.collapsed .vlabel`) : null;
      return el ? rel(el) : undefined;
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
      const r = rel(el);
      return { l: r.l, r: r.r };
    });
    const out = computeSegs({
      rects,
      anchors,
      strips,
      bands,
      boardWidth: board.scrollWidth,
      links,
      rules,
      fmt: {
        ago,
        hhmm: (iso) => hhmm(new Date(iso)),
        name: (sid) => shortName(sessions[sid], sid.slice(0, 8)),
        when: (iso) => whenLabel(iso, true),
      },
    });
    // el carril de las flechas ocupa lugar solo si alguna lo usa: con las flechas apagadas, sin
    // flechas o en pantalla angosta la columna se ve igual que siempre. Se le pide al CSS el alto
    // que de verdad hace falta, el del carril mas cargado (una pista por flecha). El CSS de la
    // columna es de otro archivo; sin esa regla el ruteo usa el aire que ya haya y igual no cruza
    // el encabezado, pero las pistas quedan comprimidas
    const porCarril = new Map<number, number>();
    for (const s of out) if (s.lane !== undefined) porCarril.set(s.lane, (porCarril.get(s.lane) ?? 0) + 1);
    setLanes(board, porCarril.size ? Math.max(...[...porCarril.values()].map(laneHeight)) : 0);
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
      setLanes(board, 0);
      if (raf) cancelAnimationFrame(raf);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!segs.length) return null;
  // la descripcion va al lado del glifo, no en una franja fija: se lee junto a lo que explica. Se
  // corre para no salirse del tablero por ningun costado
  const descX = selSeg ? Math.max(180, Math.min(selSeg.x, Math.max(180, size.w - 180))) : 0;
  const kindOf = (s: Seg) => (s.kind === "rule" ? "conexión pendiente" : s.kind === "native" ? "canal nativo" : "envío hecho");
  return (
    <>
    {selSeg && !edit && !view && (
      <div
        className="arrow-edit desc"
        style={{ left: descX, top: selSeg.y, width: "auto", maxWidth: 340 }}
        role="status"
        aria-live="polite"
        onClick={(e) => e.stopPropagation()}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="hd">{kindOf(selSeg)}</div>
        <div>{selSeg.desc}</div>
      </div>
    )}
    {/* fondo atenuado y difuminado mientras el editor o la vista estan abiertos. Va como elemento
        propio y no como ::before del popover: el popover tiene transform, y un transform en el
        ancestro hace que position: fixed se resuelva contra el, no contra la ventana. */}
    {(edit || view) && <div className="arrow-backdrop" />}
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
          {(() => {
            const s = segs.find((x) => x.ids[0] === edit.id);
            return s ? (
              <button type="button" style={{ marginRight: "auto" }} title="borra esta conexión" onClick={() => removeSeg(s)}>
                Quitar
              </button>
            ) : null;
          })()}
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
          {(() => {
            const s = segs.find((x) => x.ids[0] === view.ids[0]);
            return s ? (
              <button type="button" style={{ marginRight: "auto" }} title="borra esta flecha del tablero" onClick={() => removeSeg(s)}>
                Quitar
              </button>
            ) : null;
          })()}
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
      {/* seleccionada: se marcan las dos tarjetas que une, para ver de quien a quien es */}
      {selSeg?.ends.map((r, i) => (
        <rect
          key={i}
          x={r.l + 1}
          y={r.t + 1}
          width={Math.max(0, r.r - r.l - 2)}
          height={Math.max(0, r.b - r.t - 2)}
          rx={10}
          fill="none"
          stroke="var(--acc)"
          strokeWidth={2}
          strokeDasharray="6 4"
          opacity={0.9}
        />
      ))}
      {segs.map((s) => {
        const mine = hover !== null && (s.from === hover || s.to === hover);
        const many = s.ids.length > 1;
        const on = sel !== null && s.ids[0] === sel;
        return (
          <g
            key={s.ids[0]}
            className={`arrow ${s.old ? "old" : ""} ${mine ? "mine" : ""} ${s.dim ? "dim" : ""}`}
            style={sel !== null ? { opacity: on ? 1 : 0.12 } : undefined}
          >
            {s.kind === "native" && <path d={s.d} className="line native-outer" />}
            <path
              d={s.d}
              className={`line ${s.kind}`}
              style={on ? { strokeWidth: 3, opacity: 1 } : undefined}
              markerEnd={s.old ? undefined : "url(#arrowhead)"}
              markerStart={s.kind === "native" && !s.old ? "url(#arrowtail)" : undefined}
            />
            <g
              onClick={() => {
                setSel(s.ids[0]); // seleccionar: no borra nada ni abre nada
                setEdit(null);
                setView(null);
              }}
              onDoubleClick={() => {
                setSel(s.ids[0]);
                if (s.kind !== "rule") {
                  openView(s); // ver que se mando y, si hay donde, mandarlo de nuevo
                  return;
                }
                setView(null);
                openEdit(s);
              }}
            >
              <title>{s.title}</title>
              {/* blanco de 32 px: el texto del glifo mide 13x14 y pedirle al mouse que caiga ahi
                  justo era pedirle demasiado */}
              <circle cx={s.x} cy={s.y} r={16} fill="transparent" style={{ pointerEvents: "all", cursor: "pointer" }} />
              <circle cx={s.x} cy={s.y} r={11} className="dot" style={on ? { strokeWidth: 2.5 } : undefined} />
              <text x={s.x} y={s.y + 3.5} textAnchor="middle" className={`lbl ${many ? "count" : ""}`}>{s.glyph}</text>
            </g>
          </g>
        );
      })}
    </svg>
    </>
  );
}
