import { Component, useCallback, useEffect, useRef, useState, type ErrorInfo, type ReactNode } from "react";
import { ago, api } from "../api";
import { hhmm } from "../nl";
import { periodLabel } from "./Card";
import { Digest } from "./Digest";
import { SendBox } from "./SendBox";
import { TurnView } from "./Turn";
import type { ConnectionRule, ConnectionsResponse, DigestResponse, OtherSession, Session, Turn, TurnsResponse } from "../types";

/** "a las 22:19" si es hoy, "el jue 11/9 a las 22:19" si es otro dia */
export function whenLabel(iso: string, now = new Date()): string {
  const d = new Date(iso);
  const hm = hhmm(d);
  if (d.toDateString() === now.toDateString()) return `a las ${hm}`;
  const wd = d.toLocaleDateString("es-AR", { weekday: "short" }).replace(".", "");
  return `el ${wd} ${d.getDate()}/${d.getMonth() + 1} a las ${hm}`;
}

/** Fila fija del panel: una regla "at" habilitada hacia esta sesion, en una linea. `(auto)` cuando
 *  la creo el server por un limite de uso (el campo `auto` todavia no esta en el tipo). */
export function schedLabel(r: ConnectionRule, now = new Date()): { text: string; auto: boolean } {
  const auto = !!(r as { auto?: boolean }).auto;
  if (r.every_s) {
    const next = r.at ? ` · próx. ${whenLabel(r.at, now).replace(/^a las /, "").replace(/^el /, "")}` : "";
    return { text: `↻ ${r.text} ${periodLabel(r.every_s)}${next} (${r.fired}/${r.max_fires})`, auto };
  }
  return { text: `⏰ ${r.text} ${r.at ? whenLabel(r.at, now) : "sin hora"}`, auto };
}

/** La otra punta de un vinculo o regla, en texto: el server la manda como objeto
 *  {session_id, name}; uno anterior la mandaba como string. Nunca renderizar `other` crudo. */
export function otherName(x: { other?: OtherSession | null }): string {
  const o = x.other;
  if (o == null) return "?";
  if (typeof o === "string") return o;
  if (typeof o === "object" && typeof o.name === "string") return o.name;
  return "?";
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
          <div className="small dim" style={{ marginTop: 4, wordBreak: "break-all" }}>{this.state.error}</div>
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
}

const cut = (t: string, n = 160) => (t.length > n ? `${t.slice(0, n).trimEnd()}…` : t);

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

export function Panel({ session: s, others, onConnect, transcriptTick, onClose, toast, details }: Props) {
  const [tab, setTab] = useState<"digest" | "chat" | "screen" | "conn">("digest");
  type Screen = { ok: boolean; lines?: string[]; cols?: number; error?: string };
  const [screen, setScreen] = useState<Screen | null>(null);
  // devuelve el resultado en vez de setearlo: el efecto decide si todavia aplica (cancelled)
  const fetchScreen = (): Promise<Screen> =>
    api.get<Screen>(`/sessions/${s.session_id}/screen`).catch((e) => ({ ok: false, error: (e as Error).message }));
  // conexiones: null mientras carga; "old" si el server no tiene el endpoint todavia
  const [conn, setConn] = useState<ConnectionsResponse | "old" | null>(null);
  // lo programado hacia esta sesion (reglas "at" habilitadas), visible al abrir la tarjeta. Las
  // reglas llegan por SSE al App pero el Panel no las recibe: se piden a /connections al montar,
  // con cada transcriptTick y cada 30 s. Sin la ruta (server viejo) la fila no aparece.
  const [sched, setSched] = useState<ConnectionRule[]>([]);
  const loadSched = useCallback(async () => {
    try {
      const c = await api.get<ConnectionsResponse>(`/sessions/${s.session_id}/connections`);
      setSched(c.rules.filter((r) => r.kind === "at" && r.enabled && r.to === s.session_id));
    } catch {
      setSched([]);
    }
  }, [s.session_id]);
  useEffect(() => {
    loadSched();
    const id = setInterval(loadSched, 30_000);
    return () => clearInterval(id);
  }, [loadSched, transcriptTick]);
  const dropSched = async (r: ConnectionRule) => {
    if (!confirm("Quitar esta programación?")) return;
    try {
      await api.del(`/rules/${r.id}`);
      toast("programación quitada");
    } catch (e) {
      toast(`No se pudo quitar: ${(e as Error).message}`, true);
    }
    loadSched();
  };
  const [digest, setDigest] = useState<DigestResponse | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  // sesion libre: viva, con consola y sin ningun pedido todavia. El estado vacio de Destacados y
  // Conversacion dice que hacer, y la caja de envio arranca con el foco ("Darle trabajo" de la tarjeta)
  const free = !!s.alive && !s.orphan && !s.no_console && !(s.last_prompt || "").trim() && !(s.last_reply || "").trim();
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
        if (tab === "conn") {
          try {
            const c = await api.get<ConnectionsResponse>(`/sessions/${s.session_id}/connections`);
            if (!cancelled) setConn(c);
          } catch (e) {
            // 404 = server anterior a la ruta; cualquier otro error va a la nota
            if (!cancelled) {
              if ((e as Error).message === "404") setConn("old");
              else setNote(`error: ${(e as Error).message}`);
            }
          }
          return;
        }
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

  return (
    <div className="panel">
      <div className="ph">
        <span className={`badge ${s.agent}`}>{s.agent}</span>
        <span className="t">
          {s.title || s.repo}
          {s.coordinator && (
            <span className="coord" title="coordinadora del repo: recibe los avisos 'cuando termine' y 'avisame'">
              ★ coordinadora
            </span>
          )}
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
        <button onClick={onClose} aria-label="cerrar panel" title="cerrar">✕</button>
        <div className="pmeta dim small" title={`${s.cwd ?? ""}\n${s.transcript_path ?? "sin transcripción"}`}>
          {details
            ? `${s.cwd} · PID ${s.pid ?? "?"} · ${s.state} · ${s.transcript_path ? s.transcript_path.split(/[\\/]/).pop() : "sin transcripción"}`
            : `${s.cwd}${s.branch ? ` · ${s.branch}` : ""} · ${s.state}`}
        </div>
      </div>
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
