import { useCallback, useEffect, useRef, useState } from "react";
import { api, type AuthInfo } from "./api";
import { Board } from "./components/Board";
import { Enroll } from "./components/Enroll";
import { Login } from "./components/Login";
import { Panel } from "./components/Panel";
import { Setup, TotpQr } from "./components/Setup";
import { Toasts, useToasts } from "./components/Toasts";
import { UrlQr } from "./components/UrlQr";
import type { Link, Pending, ServerEvent, Session, State } from "./types";

export default function App() {
  const [authInfo, setAuthInfo] = useState<AuthInfo | null>(null);
  const refreshAuth = useCallback(() => api.get<AuthInfo>("/auth").then(setAuthInfo).catch(() => null), []);
  useEffect(() => {
    refreshAuth();
  }, [refreshAuth]);

  // el alta vive aca arriba: mientras esta abierta no la tapa ni el login ni un corte del SSE
  const [showSetup, setShowSetup] = useState(false);
  // celular: la URL del QR unico trae #enroll=<token>
  const [enrollToken, setEnrollToken] = useState<string | null>(() => {
    const m = window.location.hash.match(/enroll=([A-Za-z0-9_-]+)/);
    return m ? m[1] : null;
  });
  const [prefill, setPrefill] = useState("");
  if (enrollToken) {
    return (
      <Enroll
        token={enrollToken}
        onReady={(p) => {
          setPrefill(p);
          setEnrollToken(null);
          history.replaceState(null, "", window.location.pathname);
          refreshAuth();
        }}
      />
    );
  }
  if (showSetup) {
    return (
      <Setup
        onClose={(configured) => {
          setShowSetup(false);
          if (configured) refreshAuth();
        }}
      />
    );
  }
  if (!authInfo) return <div className="empty">conectando…</div>;
  if (authInfo.configured && !authInfo.authenticated) return <Login onDone={refreshAuth} mode={authInfo.mode} initialPassphrase={prefill} />;
  return <Dashboard authInfo={authInfo} refreshAuth={refreshAuth} onSetup={() => setShowSetup(true)} />;
}

function Dashboard({ authInfo, refreshAuth, onSetup }: { authInfo: AuthInfo; refreshAuth: () => void; onSetup: () => void }) {
  const [showQr, setShowQr] = useState(false);
  const [showTotp, setShowTotp] = useState(false);
  const [sessions, setSessions] = useState<Record<string, Session>>({});
  const [pending, setPending] = useState<Record<string, Pending>>({});
  const [links, setLinks] = useState<Link[]>([]);
  const [forwardTo, setForwardTo] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [showThinking, setShowThinking] = useState(false);
  const [filter, setFilter] = useState<State>("corriendo");
  const [transcriptTick, setTranscriptTick] = useState(0);
  const { toasts, toast } = useToasts();
  const selectedRef = useRef<string | null>(null);
  selectedRef.current = selected;

  const lastMsgRef = useRef(0);
  const [polling, setPolling] = useState(false);
  useEffect(() => {
    // carga inicial directa, y sondeo cada 4 s mientras el stream no entregue nada (un proxy
    // que retiene el SSE no deja el tablero vacio)
    const load = () =>
      Promise.all([api.get<Session[]>("/sessions"), api.get<Pending[]>("/pending"), api.get<Link[]>("/links")])
        .then(([ss, ps, ls]) => {
          setSessions(Object.fromEntries(ss.map((s) => [s.session_id, s])));
          setPending(Object.fromEntries(ps.map((p) => [p.request_id, p])));
          setLinks(ls);
          if (selectedRef.current) setTranscriptTick((t) => t + 1);
        })
        .catch(() => null);
    load();
    const poll = setInterval(() => {
      if (Date.now() - lastMsgRef.current > 20000) {
        setPolling(true);
        load();
      } else {
        setPolling(false);
      }
    }, 4000);
    const es = new EventSource("/events");
    es.onopen = () => {
      setConnected(true);
      refreshAuth(); // la URL del tunel puede haber aparecido o cambiado con un reinicio
    };
    es.onerror = () => {
      setConnected(false);
      refreshAuth(); // si la cookie vencio, /auth lo dice y aparece el login
    };
    es.onmessage = (ev) => {
      lastMsgRef.current = Date.now();
      const m = JSON.parse(ev.data) as ServerEvent;
      if (m.type === "snapshot") {
        setSessions(Object.fromEntries(m.sessions.map((s) => [s.session_id, s])));
        setPending(Object.fromEntries(m.pending.map((p) => [p.request_id, p])));
        if (m.links) setLinks(m.links);
        setTranscriptTick((t) => t + 1);
      } else if (m.type === "links") {
        setLinks(m.links);
      } else if (m.type === "session") {
        setSessions((prev) => ({ ...prev, [m.session.session_id]: m.session }));
      } else if (m.type === "removed") {
        setSessions((prev) => {
          const next = { ...prev };
          delete next[m.session_id];
          return next;
        });
        if (selectedRef.current === m.session_id) setSelected(null);
      } else if (m.type === "pending") {
        setPending(Object.fromEntries(m.pending.map((p) => [p.request_id, p])));
      } else if (m.type === "transcript") {
        if (selectedRef.current === m.session_id) setTranscriptTick((t) => t + 1);
      }
    };
    return () => {
      es.close();
      clearInterval(poll);
    };
  }, [refreshAuth]);

  // click fuera del panel (y fuera de una tarjeta) lo cierra
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      const t = e.target as HTMLElement;
      if (!selectedRef.current) return;
      if (t.closest(".panel") || t.closest(".card") || t.closest(".toasts")) return;
      setSelected(null);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  // re-render periodico para los "hace X min" y refresco del estado de acceso (URL del tunel)
  const [, setClock] = useState(0);
  useEffect(() => {
    const id = setInterval(() => {
      setClock((c) => c + 1);
      refreshAuth();
    }, 20000);
    return () => clearInterval(id);
  }, [refreshAuth]);

  const decide = useCallback(
    async (requestId: string, decision: "allow" | "deny") => {
      try {
        await api.post(`/pending/${requestId}`, { decision });
        toast(decision === "allow" ? "Permitido" : "Denegado");
      } catch (e) {
        toast(`No se pudo: ${(e as Error).message}`, true);
      }
    },
    [toast],
  );

  const drop = useCallback(
    async (sid: string) => {
      if (!confirm("Quitar la tarjeta? No toca la sesión.")) return;
      try {
        await api.del(`/sessions/${sid}`);
      } catch (e) {
        toast((e as Error).message, true);
      }
    },
    [toast],
  );

  const rescan = useCallback(async () => {
    try {
      await api.post("/rescan", {});
      toast("Barriendo procesos…");
    } catch (e) {
      toast((e as Error).message, true);
    }
  }, [toast]);

  const sel = selected ? sessions[selected] : null;

  return (
    <div className={showThinking ? "showthink" : ""}>
      <header>
        <h1>Lienzo</h1>
        <span>
          <span className={`dot ${connected ? "on" : ""}`} /> {!connected ? "reconectando" : polling ? "sondeo 4 s" : "en vivo"}
        </span>
        <span className="sp" />
        {authInfo.remote_url && authInfo.local && (
          <button className="url" title="QR para abrir en el celular" onClick={() => setShowQr(true)}>
            📱 <span className="txt">{authInfo.remote_url.replace("https://", "")}</span>
          </button>
        )}
        <label className="dim small think" title="mostrar el pensamiento del agente en la conversación">
          <input type="checkbox" checked={showThinking} onChange={(e) => setShowThinking(e.target.checked)} /> 💭<span className="txt"> pensamiento</span>
        </label>
        <button onClick={rescan} title="barrer procesos de VS Code">↻<span className="txt"> Rescan</span></button>
        {!authInfo.configured && authInfo.local && (
          <button onClick={onSetup} title="acceso desde el celular con Authenticator">📱<span className="txt"> Acceso remoto</span></button>
        )}
        {authInfo.configured && authInfo.local && (
          <button onClick={() => setShowTotp(true)} title="volver a ver el QR de Authenticator">🔑<span className="txt"> QR Authenticator</span></button>
        )}
        {authInfo.configured && !authInfo.local && (
          <button onClick={() => api.post("/logout", {}).then(refreshAuth)} title="cerrar sesión en este dispositivo">Salir</button>
        )}
      </header>
      {showQr && authInfo.remote_url && <UrlQr url={authInfo.remote_url} onClose={() => setShowQr(false)} />}
      {showTotp && <TotpQr onClose={() => setShowTotp(false)} />}
      <Board
        sessions={sessions}
        pending={pending}
        selected={selected}
        filter={filter}
        onFilter={setFilter}
        onSelect={setSelected}
        onDecide={decide}
        onDrop={drop}
        links={links}
        onDeleteLink={(id) => api.del(`/links/${id}`).catch((e) => toast((e as Error).message, true))}
        onConnect={(from, to) => {
          setSelected(from);
          setForwardTo(to);
        }}
      />
      {sel && (
        <Panel
          key={sel.session_id}
          session={sel}
          others={Object.values(sessions).filter((s) => s.session_id !== sel.session_id && s.alive && s.pid)}
          forwardTo={forwardTo}
          onForwardHandled={() => setForwardTo(null)}
          transcriptTick={transcriptTick}
          onClose={() => setSelected(null)}
          toast={toast}
        />
      )}
      <Toasts toasts={toasts} />
    </div>
  );
}
