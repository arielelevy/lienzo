import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Digest } from "./Digest";
import { SendBox } from "./SendBox";
import { TurnView } from "./Turn";
import type { DigestResponse, Session, Turn, TurnsResponse } from "../types";

interface Props {
  session: Session;
  onConnect: () => void;
  transcriptTick: number;
  onClose: () => void;
  toast: (msg: string, err?: boolean) => void;
}

export function Panel({ session: s, onConnect, transcriptTick, onClose, toast }: Props) {
  const [tab, setTab] = useState<"digest" | "chat" | "screen">("digest");
  type Screen = { ok: boolean; lines?: string[]; cols?: number; error?: string };
  const [screen, setScreen] = useState<Screen | null>(null);
  // devuelve el resultado en vez de setearlo: el efecto decide si todavia aplica (cancelled)
  const fetchScreen = (): Promise<Screen> =>
    api.get<Screen>(`/sessions/${s.session_id}/screen`).catch((e) => ({ ok: false, error: (e as Error).message }));
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
          {s.cwd} · PID {s.pid ?? "?"} · {s.state} · {s.transcript_path ? s.transcript_path.split(/[\\/]/).pop() : "sin transcripción"}
        </div>
      </div>
      <div className="body" ref={bodyRef}>
        {tab === "screen" ? (
          <>
            <div className="row" style={{ marginBottom: 8 }}>
              <span className="small dim">Buffer de la consola ({screen?.cols ?? "?"} columnas). No es la salida en vivo: es lo que hay pintado ahora.</span>
              <span className="sp" />
              <button onClick={() => fetchScreen().then(setScreen)}>↻ Refrescar</button>
            </div>
            {screen?.ok ? <pre className="screen">{(screen.lines ?? []).join("\n")}</pre> : <div className="empty">{screen?.error || "leyendo…"}</div>}
          </>
        ) : tab === "digest" ? (
          digest && digest.turns.length ? (
            digest.turns.map((t) => <Digest key={t.id} turn={t} />)
          ) : (
            <div className="empty">{note || "sin turnos"}</div>
          )
        ) : (
          <>
            {hasMore && <button onClick={loadMore}>cargar anteriores</button>}
            {turns.length ? turns.map((t) => <TurnView key={t.id} turn={t} />) : <div className="empty">{note || "sin turnos"}</div>}
          </>
        )}
      </div>
      <SendBox session={s} toast={toast} />
    </div>
  );
}
