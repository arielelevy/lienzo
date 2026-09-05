import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Digest } from "./Digest";
import { Forward } from "./Forward";
import { SendBox } from "./SendBox";
import { TurnView } from "./Turn";
import type { DigestResponse, Session, Turn, TurnsResponse } from "../types";

interface Props {
  session: Session;
  others: Session[];
  forwardTo?: string | null;
  onForwardHandled?: () => void;
  transcriptTick: number;
  onClose: () => void;
  toast: (msg: string, err?: boolean) => void;
}

export function Panel({ session: s, others, forwardTo, onForwardHandled, transcriptTick, onClose, toast }: Props) {
  const [tab, setTab] = useState<"digest" | "chat" | "screen">("digest");
  const [forwarding, setForwarding] = useState(!!forwardTo);
  useEffect(() => {
    if (forwardTo) setForwarding(true);
  }, [forwardTo]);
  const [screen, setScreen] = useState<{ ok: boolean; lines?: string[]; cols?: number; error?: string } | null>(null);
  const loadScreen = () => api.get<{ ok: boolean; lines?: string[]; cols?: number; error?: string }>(`/sessions/${s.session_id}/screen`).then(setScreen).catch((e) => setScreen({ ok: false, error: (e as Error).message }));
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
          await loadScreen();
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
    const d = await api.get<TurnsResponse>(`/sessions/${s.session_id}/turns?n=20&before=${first.id}`);
    setTurns((prev) => [...d.turns, ...prev]);
    setHasMore(d.has_more);
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
        <button className={forwarding ? "on" : ""} onClick={() => setForwarding(!forwarding)} title="mandar la última respuesta a otra sesión">
          Reenviar a…
        </button>
        <button onClick={onClose}>✕</button>
        <div className="pmeta dim small">
          {s.cwd} · PID {s.pid ?? "?"} · {s.state} · {s.transcript_path || "sin transcripción"}
        </div>
      </div>
      {forwarding && (
        <Forward
          from={s}
          others={others}
          initialTarget={forwardTo ?? undefined}
          toast={toast}
          onDone={() => {
            setForwarding(false);
            onForwardHandled?.();
          }}
        />
      )}
      <div className="body" ref={bodyRef}>
        {tab === "screen" ? (
          <>
            <div className="row" style={{ marginBottom: 8 }}>
              <span className="small dim">Buffer de la consola ({screen?.cols ?? "?"} columnas). No es la salida en vivo: es lo que hay pintado ahora.</span>
              <span className="sp" />
              <button onClick={loadScreen}>↻ Refrescar</button>
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
