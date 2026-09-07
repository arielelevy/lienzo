import { Component, useEffect, useRef, useState, type ErrorInfo, type ReactNode } from "react";
import { ago, api, detail } from "../api";
import { hhmm } from "../nl";
import { isFree, periodLabel, schedLabel, stalledReason } from "../names";
import { Digest } from "./Digest";
import { SendBox } from "./SendBox";
import { TurnView } from "./Turn";
import type { ConnectionRule, ConnectionsResponse, DigestResponse, OtherSession, Pending, Session, Turn, TurnsResponse } from "../types";

/** La otra punta de un vinculo o regla, en texto: el server la manda como objeto
 *  {session_id, name}; uno anterior la mandaba como string. Nunca renderizar `other` crudo. */
export function otherName(x: { other?: OtherSession | null }): string {
  return x.other?.name || "?";
}

/** Limite de error chico: un dato inesperado en una pestana muestra un aviso en vez de tirar
 *  la app entera. `resetKey` cambia con la pestana o la sesion y vuelve a intentar. */
class ErrorBoundary extends Component<{ resetKey: string; children: ReactNode }, { error: string | null }> {
  state = { error: null as string | null };
  static getDerivedStateFromError(e: unknown) {
    return { error: (e as Error)?.message || String(e) };
  }
  componentDidCatch(e: unknown, info: ErrorInfo) {
    console.error("panel:", e, info.componentStack);
  }
  componentDidUpdate(prev: { resetKey: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }
  render() {
    if (this.state.error) {
      return (
        <div className="empty" role="alert">
          no pude mostrar esto
          <div className="small dim" style={{ marginTop: 4, overflowWrap: "anywhere" }}>{this.state.error}</div>
          <button style={{ marginTop: 8 }} onClick={() => this.setState({ error: null })}>reintentar</button>
        </div>
      );
    }
    return this.props.children;
  }
}

interface Props {
  session: Session;
  /** las demas sesiones vivas con consola: el SendBox busca ahi a la coordinadora */
  others: Session[];
  onConnect: () => void;
  transcriptTick: number;
  onClose: () => void;
  toast: (msg: string, err?: boolean) => void;
  /** "Detalles tecnicos" del menu: PID y nombre del .jsonl en el encabezado, contadores en cero */
  details: boolean;
  /** rect de la tarjeta que abrio el panel: el panel se dibuja al lado, del lado mas libre */
  anchor?: { left: number; top: number; width: number; height: number } | null;
  /** permiso pendiente de esta sesion, si lo hay: se contesta desde aca tambien */
  pending?: Pending;
  onDecide: (requestId: string, decision: "allow" | "deny") => void;
}

const cut = (t: string, n = 160) => (t.length > n ? `${t.slice(0, n).trimEnd()}…` : t);

/** ancho de pantalla en el que el panel pasa a ocupar todo: el mismo numero que el
 *  `@media (max-width: 900px)` de styles.css. */
const MOBILE = 900;

/** El estado en palabras, con la misma palabra que la columna del tablero: `te_necesita` es el
 *  nombre interno de la API y no es para leer. (Viviria mejor en names.ts, al lado de COLS, pero
 *  ese archivo lo esta tocando otra sesion.) */
const ESTADO: Record<Session["state"], string> = {
  corriendo: "corriendo",
  termino: "terminó",
  te_necesita: "te necesita",
  muerta: "muerta",
};

/** La linea que va al lado del titulo: rama y estado. Tres decisiones de producto:
 *  - "HEAD" no es una rama, es lo que devuelve un repo en detached: no se muestra.
 *  - muerta o sin terminal mandan sobre lo que diga `state`, igual que la columna del tablero:
 *    a una huerfana no se le puede escribir aunque figure corriendo.
 *  - una que figura corriendo pero esta quieta (sin cupo, o sin actividad hace rato) lo dice en
 *    palabras y con el motivo medido; en la tarjeta eso es solo un punto apagado. */
function headLine(s: Session): string {
  const parts: string[] = [];
  if (s.branch && s.branch !== "HEAD") parts.push(s.branch);
  if (s.alive === false) parts.push(ESTADO.muerta);
  else if (s.orphan) parts.push("sin terminal");
  else {
    const quieta = stalledReason(s);
    parts.push(quieta ? `quieta · ${quieta}` : ESTADO[s.state] ?? s.state);
  }
  return parts.join(" · ");
}

/** Pestana "Conexiones": dos listas, lo que paso (links) y lo que sigue armado (rules). */
function Connections({ sid, conn }: { sid: string; conn: ConnectionsResponse | "old" | null }) {
  if (conn === null) return <div className="empty">leyendo…</div>;
  if (conn === "old") return <div className="empty">El server que corre no tiene esta ruta todavía: reiniciá el server.</div>;
  const links = [...conn.links].sort((a, b) => b.ts.localeCompare(a.ts));
  const rules = [...conn.rules].sort((a, b) => Number(b.enabled) - Number(a.enabled));
  const ruleState = (r: ConnectionsResponse["rules"][number]) => {
    if (!r.enabled) return "cumplida";
    if (r.kind === "at") {
      if (r.every_s) {
        // periodica: proxima hora, cuenta de disparos y si saltea al destino ocupado
        const next = r.at ? `próx. ${hhmm(new Date(r.at))}` : "programada";
        const busy = r.skip_busy === false ? "" : " · saltea si está ocupada";
        return `${next} · ${r.fired}/${r.max_fires}${busy}${r.last_fired ? ` · última hace ${ago(r.last_fired)}` : ""}`;
      }
      return r.at ? `a las ${hhmm(new Date(r.at))}` : "programada";
    }
    const n = r.max_fires > 1 ? ` ${r.fired}/${r.max_fires}` : r.fired ? " ya disparó" : "";
    return `esperando que termine${n}${r.last_fired ? ` · última hace ${ago(r.last_fired)}` : ""}`;
  };
  return (
    <div className="conns">
      <h3>Recibido de / Enviado a</h3>
      {links.length ? (
        links.map((l) => {
          const inbound = l.to === sid;
          // kind "user": lo escribio el usuario desde el lienzo; other viene como "vos (lienzo)"
          const dir = l.kind === "native" ? "⇄ canal con" : inbound ? "↙ recibido de" : "↗ enviado a";
          return (
            <div key={l.id} className={`conn ${inbound ? "in" : "out"}`} title={l.text}>
              <div className="hd">
                <span className="who">{dir} {otherName(l)}</span>
                <span className="dim small">hace {ago(l.ts)}{l.rule_id ? " · por regla" : ""}</span>
              </div>
              <div className="txt">{cut(l.text)}</div>
            </div>
          );
        })
      ) : (
        <div className="empty">nada mandado ni recibido</div>
      )}
      <h3>Conexiones activas</h3>
      {rules.length ? (
        rules.map((r) => {
          const outbound = r.from === sid;
          const other = otherName(r);
          const where = outbound ? "→ " + other : r.from && r.from !== sid ? "desde " + other : "a esta sesión";
          const label = r.kind === "at"
            ? r.every_s
              ? `↻ ${periodLabel(r.every_s)} "${cut(r.text, 60)}" ${where}`
              : `⏰ "${cut(r.text, 60)}" ${where}`
            : outbound
              ? `⏹ al terminar → ${other}`
              : `⏹ recibe de ${other} al terminar`;
          return (
            <div key={r.id} className={`conn rule ${r.enabled ? "" : "done"}`}>
              <div className="hd">
                <span className="who">{label}</span>
                <span className="dim small">{ruleState(r)}</span>
              </div>
            </div>
          );
        })
      ) : (
        <div className="empty">ninguna regla toca esta sesión</div>
      )}
    </div>
  );
}

export function Panel({ session: s, others, onConnect, transcriptTick, onClose, toast, details, anchor, pending, onDecide }: Props) {
  const [tab, setTab] = useState<"digest" | "chat" | "screen" | "conn">("digest");
  type Screen = { ok: boolean; lines?: string[]; cols?: number; error?: string };
  const [screen, setScreen] = useState<Screen | null>(null);
  // devuelve el resultado en vez de setearlo: el efecto decide si todavia aplica (cancelled)
  const fetchScreen = (): Promise<Screen> =>
    api.get<Screen>(`/sessions/${s.session_id}/screen`).catch((e) => ({ ok: false, error: (e as Error).message }));
  // conexiones de la sesion: alimentan la pestana Conexiones y la fila de programadas del
  // encabezado. Las reglas llegan por SSE al App pero el Panel no las recibe: se piden a
  // /connections al abrir, con cada transcriptTick, cada 30 s y despues de quitar una. null
  // mientras carga; "old" si el server no tiene la ruta (la fila no aparece).
  const [conn, setConn] = useState<ConnectionsResponse | "old" | null>(null);
  const [connTick, setConnTick] = useState(0);
  useEffect(() => setConn(null), [s.session_id]);
  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api
        .get<ConnectionsResponse>(`/sessions/${s.session_id}/connections`)
        .then((c) => !cancelled && setConn(c))
        .catch((e) => {
          if (cancelled) return;
          if ((e as Error).message === "404") setConn("old");
          else console.warn("connections:", e); // sin red o server caido: se reintenta en 30 s
        });
    load();
    const id = setInterval(load, 30_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [s.session_id, transcriptTick, connTick]);
  const sched = conn && conn !== "old" ? conn.rules.filter((r) => r.kind === "at" && r.enabled && r.to === s.session_id) : [];
  const dropSched = async (r: ConnectionRule) => {
    if (!confirm("Quitar esta programación?")) return;
    try {
      await api.del(`/rules/${r.id}`);
      toast("programación quitada");
    } catch (e) {
      toast(`No se pudo quitar: ${(e as Error).message}`, true);
    }
    setConnTick((t) => t + 1);
  };
  const [digest, setDigest] = useState<DigestResponse | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  // El ajuste del borde a la grilla de tarjetas se mide una vez por apertura y ancho de ventana:
  // si se recalculara en cada render, el panel cambiaria de ancho solo cada vez que el tablero se
  // mueve atras. El componente se remonta por sesion (key en App), asi que el ref muere con ella
  const snapRef = useRef<{ vw: number; left: number; width: number; out: { left: number; width: number } } | null>(null);
  // el tamano del panel se calcula al pintar: si la ventana cambia (girar el celular, abrir el
  // teclado, agrandar la ventana) hay que volver a pintar. visualViewport tambien avisa cuando
  // el teclado achica o desplaza lo visible sin tocar innerHeight (iOS)
  const [, redraw] = useState(0);
  useEffect(() => {
    const on = () => redraw((n) => n + 1);
    const vv = window.visualViewport;
    window.addEventListener("resize", on);
    window.addEventListener("scroll", on, { passive: true }); // en el celular el tope depende del header
    vv?.addEventListener("resize", on);
    vv?.addEventListener("scroll", on);
    return () => {
      window.removeEventListener("resize", on);
      window.removeEventListener("scroll", on);
      vv?.removeEventListener("resize", on);
      vv?.removeEventListener("scroll", on);
    };
  }, []);
  // sesion libre: viva, con consola y sin ningun pedido todavia. El estado vacio de Destacados y
  // Conversacion dice que hacer, y la caja de envio arranca con el foco ("Darle trabajo" de la tarjeta)
  const free = isFree(s);
  const freeEmpty = (
    <div className="empty free">
      Esta sesión todavía no recibió pedidos. Escribile abajo, o marcá "avisarme cuando termine" para que su informe te llegue solo.
    </div>
  );

  useEffect(() => {
    let cancelled = false;
    const body = bodyRef.current;
    const atBottom = !body || body.scrollHeight - body.scrollTop - body.clientHeight < 80;
    (async () => {
      try {
        if (tab === "screen") {
          const r = await fetchScreen();
          if (!cancelled) setScreen(r);
          return;
        }
        if (tab === "conn") return; // ya cargado por el efecto de conexiones
        if (tab === "digest") {
          const d = await api.get<DigestResponse>(`/sessions/${s.session_id}/digest?n=10`);
          if (!cancelled) {
            setDigest(d);
            setNote(d.note ?? null);
          }
        } else {
          const d = await api.get<TurnsResponse>(`/sessions/${s.session_id}/turns?n=10`);
          if (!cancelled) {
            setTurns(d.turns);
            setHasMore(d.has_more);
            setNote(d.note ?? null);
          }
        }
        if (atBottom && body) requestAnimationFrame(() => (body.scrollTop = body.scrollHeight));
      } catch (e) {
        if (!cancelled) setNote(`error: ${(e as Error).message}`);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [s.session_id, tab, transcriptTick]);

  const loadMore = async () => {
    const first = turns[0];
    if (!first) return;
    try {
      const d = await api.get<TurnsResponse>(`/sessions/${s.session_id}/turns?n=20&before=${first.id}`);
      setTurns((prev) => [...d.turns, ...prev]);
      setHasMore(d.has_more);
    } catch (e) {
      toast(`No pude cargar más: ${(e as Error).message}`, true);
    }
  };

  // el panel se abre sobre la tarjeta que lo abrio, no en un costado fijo: se ancla a su esquina
  // superior izquierda y se corre lo justo para entrar en la ventana. El ancho se calcula aca y
  // va en el style: el CSS ya no fija ninguno, asi el mismo numero manda el ancho pintado y el
  // clamp del left. Antes el @media del celular ponia width: 100vw contra un left calculado con
  // min(720, innerWidth - 24) y el panel se salia 12 px por la derecha (medido en 420x860).
  const box = ((): { left: number; top: number; width: number; height?: number } => {
    // clientWidth y no innerWidth: innerWidth cuenta la barra de scroll y el borde derecho del
    // panel quedaba debajo de ella
    const vv = window.visualViewport;
    const vw = document.documentElement.clientWidth || window.innerWidth;
    const vh = document.documentElement.clientHeight || window.innerHeight;
    if (vw <= MOBILE) {
      // celular: pantalla entera, pero abajo del header, que va por encima (z-index 40) y si no
      // tapaba el titulo y la ✕ del panel. El alto sale de visualViewport, que se achica con el
      // teclado abierto, para que la caja de envio quede siempre a la vista (con 84vh quedaba
      // debajo del teclado). El header dice sticky pero no se pega: con la pagina scrolleada su
      // borde inferior da negativo (medido: -53 en 420x430) y el panel se iba para arriba, asi
      // que si no esta arriba el panel toma la pantalla entera
      const top = Math.max(0, Math.round(document.querySelector("header")?.getBoundingClientRect().bottom ?? 0));
      return {
        left: Math.round(vv?.offsetLeft ?? 0),
        top: Math.round((vv?.offsetTop ?? 0) + top),
        width: Math.round(Math.min(vv?.width ?? vw, vw)),
        height: Math.max(200, Math.round(vv?.height ?? vh) - top),
      };
    }
    // Escritorio: al lado de la tarjeta, nunca encima, y del lado que tenga mas lugar. El ancho
    // sale de la ventana (46 %, entre 380 y 720) y no de un numero fijo: con 720 sobre un tablero
    // de 1152 el panel tapaba 8 de 10 tarjetas y quedaban 3,4 legibles en promedio; asi quedan 5,1
    // y la tarjeta que abrio el panel se ve siempre (antes, nunca). Medido abriendo el panel en
    // cada una de las 10 tarjetas. Achicarlo mas no gana ninguna tarjeta (la grilla de subcolumnas
    // manda), asi que se queda en el ancho comodo para leer.
    const width = Math.max(380, Math.min(720, Math.round(vw * 0.46), vw - 24));
    const h = Math.min(vh * 0.84, vh - 70);
    // El ancla se mide una sola vez al abrir, a proposito: si se remidiera, el panel saltaria
    // mientras el tablero se reacomoda detras. El costo es que, si la ventana se achica despues,
    // esas coordenadas son de la ventana vieja y el panel se iba entero para afuera: es `fixed`,
    // asi que no hay barra de scroll con la que alcanzarlo y el tablero quedaba difuminado sin
    // panel a la vista. Medido abriendolo a 2560 y achicando: se salia 89 px en 1440, 377 en 1152
    // y 569 en 960. Este clamp cierra las tres ramas de abajo, no una sola.
    const dentro = (b: { left: number; top: number; width: number }) => {
      const w = Math.min(b.width, vw - 24);
      return { ...b, width: w, left: Math.round(Math.min(Math.max(b.left, 12), Math.max(12, vw - w - 12))) };
    };
    const top = (t: number) => Math.round(Math.min(Math.max(t - 8, 52), Math.max(52, vh - h - 12)));
    if (!anchor) return dentro({ left: Math.round((vw - width) / 2), top: 56, width });
    const libreDer = vw - (anchor.left + anchor.width) - 24;
    const libreIzq = anchor.left - 24;
    const alLado = Math.max(libreDer, libreIzq);
    // El borde del panel no parte una tarjeta al medio: si cae adentro de una, se retrae hasta el
    // hueco anterior, siempre que el panel no baje de 380 px. Medido en 1440 sobre las 10 tarjetas:
    // pasa de tapar 5,7 a tapar 3,3, y de 4,3 a 6,7 tarjetas legibles, a cambio de 60-110 px de
    // ancho. En 1152 el borde ya caia en un hueco y no cambia nada.
    const alaGrilla = (left: number, w: number): { left: number; width: number } => {
      const c = snapRef.current;
      if (c && c.vw === vw && c.left === left && c.width === w) return c.out;
      const alto = { top: top(anchor.top), bottom: top(anchor.top) + h };
      const cruzan = Array.from(document.querySelectorAll(".card"))
        .map((el) => el.getBoundingClientRect())
        .filter((r) => r.top < alto.bottom && r.bottom > alto.top);
      let l = left;
      let ancho = w;
      const cortaDer = cruzan.filter((r) => r.left < l + ancho && l + ancho < r.right);
      if (cortaDer.length) {
        const borde = Math.min(...cortaDer.map((r) => r.left)) - 12;
        if (borde - l >= 380) ancho = borde - l;
      }
      const cortaIzq = cruzan.filter((r) => r.left < l && l < r.right);
      if (cortaIzq.length) {
        const borde = Math.max(...cortaIzq.map((r) => r.right)) + 12;
        if (l + ancho - borde >= 380) {
          ancho = l + ancho - borde;
          l = borde;
        }
      }
      const out = { left: Math.round(l), width: Math.round(ancho) };
      snapRef.current = { vw, left, width: w, out };
      return out;
    };
    if (alLado >= 380) {
      // entra al costado: se pega al borde de la tarjeta del lado mas libre y usa lo que haya
      const w = Math.min(width, alLado);
      const izquierda = libreDer >= libreIzq ? anchor.left + anchor.width + 12 : anchor.left - 12 - w;
      const ajustado = alaGrilla(izquierda, w);
      return dentro({ left: ajustado.left, top: top(anchor.top), width: ajustado.width });
    }
    // ventana angosta: no hay costado donde entre, vuelve a abrirse sobre la tarjeta
    return dentro({ left: anchor.left - 8, top: top(anchor.top), width });
  })();

  return (
    /* angosto: el encabezado usa las pestanas compactas, las mismas del celular, para no comerse
       filas cuando el panel se achica para dejar ver el tablero. El corte esta en 700 px porque
       abajo de eso las cuatro pestanas mas Conectar no entran en una fila con el tamano grande */
    <div className={`panel ${box.width < 700 ? "narrow" : ""}`} style={{ left: box.left, top: box.top, width: box.width, height: box.height, maxHeight: box.height }}>
      <div className="ph">
        <span className={`badge ${s.agent}`}>{s.agent}</span>
        {/* una linea sola: el titulo largo se corta con puntos suspensivos y va entero en el title,
            asi no empuja las pestanas tres renglones para abajo */}
        <span className="t">
          <span className="ttext" title={s.title || s.repo}>{s.title || s.repo}</span>
          {s.coordinator && (
            <span className="coord" title="coordinadora del repo: recibe los avisos 'cuando termine' y 'avisame'">
              ★<span className="lbl"> coordinadora</span>
            </span>
          )}
          {/* rama y estado al lado del nombre: es lo unico que servia de la fila de la ruta, que
              ya no esta. La ruta vuelve abajo solo con "Detalles tecnicos" */}
          {/* el texto entero en el title: cuando la fila viene justa, esta parte se recorta para
              que el nombre entre entero */}
          <span className="sub dim small" title={[headLine(s), s.cwd].filter(Boolean).join("\n")}>
            {headLine(s)}
          </span>
        </span>
        <div className="tabs">
          <button className={tab === "digest" ? "on" : ""} onClick={() => setTab("digest")}>Destacados</button>
          <button className={tab === "chat" ? "on" : ""} onClick={() => setTab("chat")}>Conversación</button>
          <button className={tab === "conn" ? "on" : ""} onClick={() => setTab("conn")} title="qué mandó, qué recibió y qué conexiones siguen activas">Conexiones</button>
          {s.agent === "claude" && !s.orphan && (
            <button className={tab === "screen" ? "on" : ""} onClick={() => setTab("screen")} title="texto visible de la terminal, leído del buffer">Pantalla</button>
          )}
        </div>
        {!s.orphan && s.alive && (
          <button onClick={onConnect} title="conectar con otra sesión: ahora, cuando termine, o a una hora">
            Conectar…
          </button>
        )}
        {/* en la esquina de arriba a la derecha, chica como la ✕ de una tarjeta: antes se llevaba
            una fila entera para un solo boton */}
        <button className="x" onClick={onClose} aria-label="cerrar panel" title="cerrar">✕</button>
        {/* la ruta absoluta no aporta (el repo ya esta en el titulo y en la tarjeta): la fila
            aparece solo con "Detalles tecnicos", que es donde vive lo de depurar */}
        {details && (
          <div className="pmeta dim small" title={`${s.cwd ?? ""}\n${s.transcript_path ?? "sin transcripción"}`}>
            {`${s.cwd} · PID ${s.pid ?? "?"} · ${s.state} · ${s.transcript_path ? s.transcript_path.split(/[\\/]/).pop() : "sin transcripción"}`}
          </div>
        )}
      </div>
      {/* El permiso tambien se contesta desde el panel. Con el panel abierto la tarjeta queda
          atras y difuminada (en el celular, tapada del todo), asi que el "contestalo arriba" de la
          caja de envio no llevaba a ningun lado. Es el mismo bloque `.needs` de la tarjeta: antes
          era un `.sched` (una fila de chips) al que seis estilos en linea le daban vuelta la
          maqueta. La hora va con hhmm, en 24 h como el resto de la app. */}
      {pending && (
        <div className="needs">
          <b>Pide permiso: {pending.tool_name}</b>
          <code>{detail(pending.tool_input)}</code>
          <div className="btns">
            <button className="allow" onClick={() => onDecide(pending.request_id, "allow")}>Permitir</button>
            <button className="deny" onClick={() => onDecide(pending.request_id, "deny")}>Denegar</button>
            <span className="dim small">vence {hhmm(new Date(pending.expires_at))}</span>
          </div>
        </div>
      )}
      {sched.length > 0 && (
        <div className="sched" title="mensajes programados hacia esta sesión">
          {sched.map((r) => {
            const { text, auto } = schedLabel(r);
            return (
              <div key={r.id} className="item">
                <span title={text}>
                  {text}
                  {auto && <span className="auto"> (auto)</span>}
                </span>
                <button type="button" className="del" title="quitar" aria-label="quitar programación" onClick={() => dropSched(r)}>
                  ✕
                </button>
              </div>
            );
          })}
        </div>
      )}
      <div className="body" ref={bodyRef}>
        <ErrorBoundary resetKey={`${s.session_id}:${tab}:${transcriptTick}`}>
        {tab === "screen" ? (
          <>
            <div className="row" style={{ marginBottom: 8 }}>
              <span className="small dim">Buffer de la consola ({screen?.cols ?? "?"} columnas). No es la salida en vivo: es lo que hay pintado ahora.</span>
              <span className="sp" />
              <button onClick={() => fetchScreen().then(setScreen)}>↻ Refrescar</button>
            </div>
            {screen?.ok ? <pre className="screen">{(screen.lines ?? []).join("\n")}</pre> : <div className="empty">{screen?.error || "leyendo…"}</div>}
          </>
        ) : tab === "conn" ? (
          <Connections sid={s.session_id} conn={conn} />
        ) : tab === "digest" ? (
          digest && digest.turns.length ? (
            // "0 herramientas · 0 lecturas" no dice nada: sin "Detalles tecnicos" se esconde (CSS)
            digest.turns.map((t) => (
              <div key={t.id} className={!t.tools && !t.reads && !t.subagents ? "nostats" : undefined}>
                <Digest turn={t} toast={toast} />
              </div>
            ))
          ) : free ? (
            freeEmpty
          ) : (
            <div className="empty">{note || "sin turnos"}</div>
          )
        ) : (
          <>
            {hasMore && <button onClick={loadMore}>cargar anteriores</button>}
            {turns.length ? turns.map((t) => <TurnView key={t.id} turn={t} />) : free ? freeEmpty : <div className="empty">{note || "sin turnos"}</div>}
          </>
        )}
        </ErrorBoundary>
      </div>
      <SendBox session={s} others={others} toast={toast} autoFocus={free} />
    </div>
  );
}
