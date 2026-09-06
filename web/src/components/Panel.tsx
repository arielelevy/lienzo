import { Component, useEffect, useRef, useState, type ErrorInfo, type ReactNode } from "react";
import { ago, api } from "../api";
import { hhmm } from "../nl";
import { Digest } from "./Digest";
import { SendBox } from "./SendBox";
import { TurnView } from "./Turn";
import type { ConnectionsResponse, DigestResponse, OtherSession, Session, Turn, TurnsResponse } from "../types";

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
    if (r.kind === "at") return r.at ? `a las ${hhmm(new Date(r.at))}` : "programada";
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
          const label = r.kind === "at"
            ? `⏰ "${cut(r.text, 60)}" ${outbound ? "→ " + other : r.from && r.from !== sid ? "desde " + other : "a esta sesión"}`
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
  const [digest, setDigest] = useState<DigestResponse | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);

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
        <span className="t">{s.title || s.repo}</span>
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
          ) : (
            <div className="empty">{note || "sin turnos"}</div>
          )
        ) : (
          <>
            {hasMore && <button onClick={loadMore}>cargar anteriores</button>}
            {turns.length ? turns.map((t) => <TurnView key={t.id} turn={t} />) : <div className="empty">{note || "sin turnos"}</div>}
          </>
        )}
        </ErrorBoundary>
      </div>
      <SendBox session={s} others={others} toast={toast} />
    </div>
  );
}
