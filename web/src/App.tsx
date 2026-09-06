import { useCallback, useEffect, useRef, useState } from "react";
import { api, type AuthInfo } from "./api";
import { Board, type Agent } from "./components/Board";
import { shortName } from "./components/Card";
import { Enroll } from "./components/Enroll";
import { Forward } from "./components/Forward";
import { Header } from "./components/Header";
import { Login } from "./components/Login";
import { Panel } from "./components/Panel";
import { Setup, TotpQr } from "./components/Setup";
import { Toasts, useToasts } from "./components/Toasts";
import { UrlQr } from "./components/UrlQr";
import { useLienzoData } from "./hooks/useLienzoData";
import { useLocalFlag } from "./hooks/useLocalFlag";
import { useNotifications } from "./hooks/useNotifications";
import type { Config, State } from "./types";

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
  // dialogo de conectar (por arrastre o desde el boton del panel): flotante, sin abrir nada mas
  const [connect, setConnect] = useState<{ from: string; to: string } | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [showThinking, setShowThinking] = useState(false);
  const [filter, setFilter] = useState<State>("corriendo");
  // flechas visibles u ocultas, recordado por navegador
  const [showArrows, toggleArrows] = useLocalFlag("lienzo.arrows", true);
  // "Detalles tecnicos": PID/hooks/id en las tarjetas, contadores en cero del digest, nombre del
  // .jsonl en el panel. Sirven para depurar, no para usar: apagados por defecto
  const [details, toggleDetails] = useLocalFlag("lienzo.details", false);
  const { toasts, toast } = useToasts();
  const selectedRef = useRef<string | null>(null);
  selectedRef.current = selected;
  // una sesion que desaparece del tablero cierra su panel y el dialogo de conectar que la tenia
  const onRemoved = useCallback((sid: string) => {
    if (selectedRef.current === sid) setSelected(null);
    setConnect((c) => (c && (c.from === sid || c.to === sid) ? null : c));
  }, []);
  const { sessions, pending, links, rules, connected, polling, transcriptTick } = useLienzoData({ refreshAuth, selectedRef, onRemoved });
  // notificaciones del navegador cuando una sesion pide permiso; el click abre su panel
  const { notify, toggleNotify } = useNotifications({ sessions, pending, onOpen: setSelected, toast });

  // auto_continue vive en ~/.lienzo/config.json (lo lee el server): GET/PUT /config. null mientras
  // carga o si el server que corre no tiene la ruta todavia
  const [config, setConfig] = useState<Config | null>(null);
  const loadConfig = useCallback(() => api.get<Config>("/config").then(setConfig).catch(() => setConfig(null)), []);
  useEffect(() => {
    loadConfig();
  }, [loadConfig]);
  const toggleAutoContinue = useCallback(async () => {
    if (!config) {
      toast("El server que corre no tiene /config todavía: reiniciá el server", true);
      return;
    }
    try {
      const c = await api.put<Config>("/config", { auto_continue: !config.auto_continue });
      setConfig(c);
      toast(c.auto_continue ? "Ante un límite de uso con hora, se programa \"Continuar\" solo" : "Continuar automático apagado");
    } catch (e) {
      toast(`No se pudo cambiar: ${(e as Error).message}`, true);
    }
  }, [config, toast]);

  // filtro visual del header: texto + agentes. "/" enfoca la caja, Esc la limpia.
  const [query, setQuery] = useState("");
  const [agents, setAgents] = useState<Record<Agent, boolean>>({ claude: true, codex: true });
  const searchRef = useRef<HTMLInputElement>(null);
  const [showHelp, setShowHelp] = useState(false);
  // el panel va pegado a la derecha, debajo del header: su alto sale de aca (--hh)
  useEffect(() => {
    const h = document.querySelector("header");
    if (!h) return;
    const set = () => document.documentElement.style.setProperty("--hh", `${Math.ceil(h.getBoundingClientRect().height)}px`);
    set();
    const ro = new ResizeObserver(set);
    ro.observe(h);
    return () => ro.disconnect();
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const typing = !!t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
      if (e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();
        searchRef.current?.focus();
        searchRef.current?.select();
      } else if (e.key === "?" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();
        setShowHelp((v) => !v);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  // Escape cierra lo que este abierto: menu del header (lo cierra Header), ayuda, dialogo de
  // conexion, o panel
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (document.querySelector("header .dropdown")) return;
      if (showHelp) setShowHelp(false);
      else if (connect) setConnect(null);
      else if (selectedRef.current) setSelected(null);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [connect, showHelp]);

  // click fuera del panel (y fuera de una tarjeta o del header) lo cierra
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      const t = e.target as HTMLElement;
      if (!selectedRef.current) return;
      if (t.closest(".panel") || t.closest(".card") || t.closest(".toasts") || t.closest(".gate") || t.closest("header")) return;
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

  // estables: Board los usa como dependencias de listeners de document
  const deleteLink = useCallback((id: string) => api.del(`/links/${id}`).catch((e) => toast((e as Error).message, true)), [toast]);
  const deleteRule = useCallback((id: string) => api.del(`/rules/${id}`).catch((e) => toast((e as Error).message, true)), [toast]);
  const connectCards = useCallback((from: string, to: string) => setConnect({ from, to }), []);

  const sel = selected ? sessions[selected] : null;
  // sesiones a las que se les puede escribir: destinos de Conectar y coordinadora del SendBox
  const writable = Object.values(sessions).filter((s) => s.alive && s.pid);

  const flags = [
    { label: "Avisos", icon: "🔔", on: notify, toggle: toggleNotify, title: "aviso del navegador (aunque la pestaña esté atrás) cuando una sesión pide permiso o te hace una pregunta" },
    { label: "Flechas", icon: "↪", on: showArrows, toggle: toggleArrows, title: "dibujar las conexiones entre tarjetas: envíos hechos, reglas pendientes y canal nativo" },
    { label: "Pensamiento", icon: "💭", on: showThinking, toggle: () => setShowThinking((v) => !v), title: "en la pestaña Conversación, mostrar también lo que el agente razona antes de contestar (los bloques de pensamiento). Apagado se ve solo lo que dijo e hizo" },
    { label: "Detalles técnicos", icon: "🛠", on: details, toggle: toggleDetails, title: "para depurar: PID, hooks e id de sesión en las tarjetas, contadores en cero del digest, nombre del .jsonl en el panel" },
    {
      label: "Continuar solo tras límite de uso",
      icon: "⏰",
      on: !!config?.auto_continue,
      toggle: toggleAutoContinue,
      title: config
        ? "cuando una sesión avisa que llegó al límite de uso con hora de vuelta, programar \"Continuar\" un minuto después (auto_continue en ~/.lienzo/config.json)"
        : "el server que corre no tiene /config: reiniciá el server",
    },
  ];

  return (
    <div className={`${showThinking ? "showthink" : ""} ${details ? "details" : ""} ${sel ? "panel-open" : ""}`}>
      <Header
        authInfo={authInfo}
        connected={connected}
        polling={polling}
        query={query}
        onQuery={setQuery}
        agents={agents}
        onAgents={setAgents}
        searchRef={searchRef}
        onSetup={onSetup}
        onShowQr={() => setShowQr(true)}
        onShowTotp={() => setShowTotp(true)}
        onHelp={() => setShowHelp(true)}
        onRescan={rescan}
        onLogout={() => api.post("/logout", {}).then(refreshAuth).catch((e) => toast((e as Error).message, true))}
        flags={flags}
      />
      {showHelp && (
        <div className="gate" onMouseDown={(e) => e.target === e.currentTarget && setShowHelp(false)}>
          <div className="gate-box help" role="dialog" aria-label="atajos">
            <h1>Atajos</h1>
            <dl>
              <dt><kbd>Esc</kbd></dt>
              <dd>cierra el panel, el diálogo de conectar o esta ayuda; en la búsqueda, la limpia</dd>
              <dt><kbd>Tab</kbd></dt>
              <dd>en la caja de envío, acepta la sugerencia gris leída de la terminal</dd>
              <dt><kbd>/</kbd></dt>
              <dd>enfoca la búsqueda (repo, título, último pedido)</dd>
              <dt><kbd>?</kbd></dt>
              <dd>muestra u oculta esta ayuda</dd>
              <dt><kbd>Enter</kbd></dt>
              <dd>sobre una tarjeta enfocada, abre su panel</dd>
              <dt>arrastrar</dt>
              <dd>una tarjeta sobre otra abre el diálogo de conectar con ese destino</dd>
              <dt>click</dt>
              <dd>en el título de una columna la colapsa a una tira; en la tira, la expande</dd>
            </dl>
            <div className="row">
              <span className="sp" />
              <button onClick={() => setShowHelp(false)}>Cerrar</button>
            </div>
          </div>
        </div>
      )}
      {showQr && authInfo.remote_url && <UrlQr url={authInfo.remote_url} mode={authInfo.mode} onClose={() => setShowQr(false)} />}
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
        rules={rules}
        onDeleteLink={deleteLink}
        onDeleteRule={deleteRule}
        onConnect={connectCards}
        toast={toast}
        showArrows={showArrows}
        query={query}
        agents={agents}
      />
      {connect && sessions[connect.from] && (
        <div className="gate" onMouseDown={(e) => e.target === e.currentTarget && setConnect(null)}>
          <div className="gate-box wide connect">
            <h1>
              {/* soltada sobre si misma: una sola sesion con el bucle; si no, "repo · titulo → repo · titulo"
                  (shortName: dos sesiones del mismo repo no se distinguen por repo solo) */}
              {connect.to === connect.from && <span className="dim" title="programar un mensaje para esta misma sesión">↻</span>}
              <span className={`badge ${sessions[connect.from].agent}`}>{sessions[connect.from].agent}</span>
              {shortName(sessions[connect.from])}
              {connect.to && connect.to !== connect.from && sessions[connect.to] && (
                <>
                  <span className="dim">→</span>
                  <span className={`badge ${sessions[connect.to].agent}`}>{sessions[connect.to].agent}</span>
                  {shortName(sessions[connect.to])}
                </>
              )}
            </h1>
            <Forward
              from={sessions[connect.from]}
              others={writable.filter((s) => s.session_id !== connect.from)}
              initialTarget={connect.to || undefined}
              toast={toast}
              onDone={() => setConnect(null)}
            />
          </div>
        </div>
      )}
      {/* pegado a la derecha, sin fondo que tape: el tablero sigue recibiendo clicks a su izquierda */}
      {sel && (
        <Panel
          key={sel.session_id}
          session={sel}
          others={writable.filter((s) => s.session_id !== sel.session_id)}
          onConnect={() => setConnect({ from: sel.session_id, to: "" })}
          transcriptTick={transcriptTick}
          onClose={() => setSelected(null)}
          toast={toast}
          details={details}
        />
      )}
      <Toasts toasts={toasts} />
    </div>
  );
}
