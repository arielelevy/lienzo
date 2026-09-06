import { useCallback, useEffect, useRef, useState } from "react";
import { api, detail, type AuthInfo } from "./api";
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
import type { Config, Link, Pending, Rule, ServerEvent, Session, State } from "./types";

/** El tablero dibuja flechas entre sesiones: lo que mando el usuario desde el SendBox (from null,
 *  kind "user") no tiene origen y queda solo en la pestana Conexiones del panel. */
const boardLinks = (ls: Link[]): Link[] => ls.filter((l) => !!l.from);

/** Flag on/off recordado por navegador (localStorage); `def` cuando no hay storage. */
function useStoredFlag(key: string, def: boolean): [boolean, () => void] {
  const [on, setOn] = useState(() => {
    try {
      const v = localStorage.getItem(key);
      return v === null ? def : v === "1";
    } catch {
      return def;
    }
  });
  const toggle = useCallback(() => {
    setOn((v) => {
      try {
        localStorage.setItem(key, v ? "0" : "1");
      } catch {
        /* sin storage, no importa */
      }
      return !v;
    });
  }, [key]);
  return [on, toggle];
}

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
  const [rules, setRules] = useState<Rule[]>([]);
  // dialogo de conectar (por arrastre o desde el boton del panel): flotante, sin abrir nada mas
  const [connect, setConnect] = useState<{ from: string; to: string } | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [showThinking, setShowThinking] = useState(false);
  const [filter, setFilter] = useState<State>("corriendo");
  const [transcriptTick, setTranscriptTick] = useState(0);
  // flechas visibles u ocultas, recordado por navegador
  const [showArrows, toggleArrows] = useStoredFlag("lienzo.arrows", true);
  // "Detalles tecnicos": PID/hooks/id en las tarjetas, contadores en cero del digest, nombre del
  // .jsonl en el panel. Sirven para depurar, no para usar: apagados por defecto
  const [details, toggleDetails] = useStoredFlag("lienzo.details", false);
  const { toasts, toast } = useToasts();
  const selectedRef = useRef<string | null>(null);
  selectedRef.current = selected;

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

  // notificaciones del navegador: pedidos de permiso nuevos (pending) y tarjetas que pasan a
  // "te necesita" por permiso. Se detectan por transicion contra el estado anterior; el primer
  // snapshot solo inicializa, para no disparar una rafaga al abrir la pestana.
  const [notify, setNotify] = useState(() => {
    try {
      return localStorage.getItem("lienzo.notify") === "1" && typeof Notification !== "undefined" && Notification.permission === "granted";
    } catch {
      return false;
    }
  });
  const toggleNotify = useCallback(async () => {
    if (typeof Notification === "undefined") {
      toast("Este navegador no tiene notificaciones", true);
      return;
    }
    if (notify) {
      setNotify(false);
      try {
        localStorage.setItem("lienzo.notify", "0");
      } catch {
        /* sin storage, no importa */
      }
      return;
    }
    const perm = Notification.permission === "granted" ? "granted" : await Notification.requestPermission();
    if (perm !== "granted") {
      toast("El navegador no dio permiso para notificar", true);
      return;
    }
    setNotify(true);
    try {
      localStorage.setItem("lienzo.notify", "1");
    } catch {
      /* sin storage, no importa */
    }
    toast("Notificaciones activadas");
  }, [notify, toast]);
  const notifyRef = useRef(notify);
  notifyRef.current = notify;
  const seenPendingRef = useRef<Set<string> | null>(null);
  const permNeedRef = useRef<Set<string> | null>(null);
  // recien despues del primer render con datos se empieza a comparar: lo que ya estaba al abrir
  // la pestana no es novedad
  const armedRef = useRef(false);
  const hasData = Object.keys(sessions).length > 0 || Object.keys(pending).length > 0;
  const fire = useCallback((sid: string, title: string, body: string) => {
    if (!notifyRef.current || typeof Notification === "undefined" || Notification.permission !== "granted") return;
    try {
      const n = new Notification(title, { body, tag: `lienzo-${sid}` });
      n.onclick = () => {
        window.focus();
        setSelected(sid);
        n.close();
      };
    } catch {
      /* sin notificaciones (contexto inseguro, etc.) */
    }
  }, []);
  useEffect(() => {
    const ids = new Set(Object.keys(pending));
    const prev = seenPendingRef.current;
    seenPendingRef.current = ids;
    if (!prev || !armedRef.current) return;
    for (const p of Object.values(pending)) {
      if (prev.has(p.request_id)) continue;
      const s = sessions[p.session_id];
      const who = s?.repo ?? p.agent;
      fire(p.session_id, `${who} pide permiso: ${p.tool_name}`, detail(p.tool_input).slice(0, 200));
    }
  }, [pending, sessions, fire]);
  useEffect(() => {
    const now = new Set<string>();
    for (const s of Object.values(sessions)) if (s.state === "te_necesita" && s.needs?.kind === "permission") now.add(s.session_id);
    const prev = permNeedRef.current;
    permNeedRef.current = now;
    const armed = armedRef.current;
    if (hasData) armedRef.current = true; // este render ya tiene datos: el proximo compara
    if (!prev || !armed) return;
    for (const sid of now) {
      if (prev.has(sid)) continue;
      const s = sessions[sid];
      if (!s || s.pending_id) continue; // el pending ya avisa con mas detalle
      fire(sid, `${s.repo} pide permiso: ${s.needs?.tool ?? ""}`.trim(), (s.needs?.detail ?? "").slice(0, 200));
    }
  }, [sessions, hasData, fire]);

  const lastMsgRef = useRef(0);
  const [polling, setPolling] = useState(false);
  useEffect(() => {
    // carga inicial directa, y sondeo cada 4 s mientras el stream no entregue nada (un proxy
    // que retiene el SSE no deja el tablero vacio)
    const load = () =>
      Promise.all([api.get<Session[]>("/sessions"), api.get<Pending[]>("/pending"), api.get<Link[]>("/links"), api.get<Rule[]>("/rules")])
        .then(([ss, ps, ls, rs]) => {
          setSessions(Object.fromEntries(ss.map((s) => [s.session_id, s])));
          setPending(Object.fromEntries(ps.map((p) => [p.request_id, p])));
          setLinks(boardLinks(ls));
          setRules(rs);
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
        if (m.links) setLinks(boardLinks(m.links));
        if (m.rules) setRules(m.rules);
        setTranscriptTick((t) => t + 1);
      } else if (m.type === "links") {
        setLinks(boardLinks(m.links));
      } else if (m.type === "rules") {
        setRules(m.rules);
      } else if (m.type === "session") {
        setSessions((prev) => ({ ...prev, [m.session.session_id]: m.session }));
      } else if (m.type === "removed") {
        setSessions((prev) => {
          const next = { ...prev };
          delete next[m.session_id];
          return next;
        });
        if (selectedRef.current === m.session_id) setSelected(null);
        setConnect((c) => (c && (c.from === m.session_id || c.to === m.session_id) ? null : c));
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
    { label: "Avisos", icon: "🔔", on: notify, toggle: toggleNotify, title: "notificación del navegador cuando una sesión pide permiso" },
    { label: "Flechas", icon: "↪", on: showArrows, toggle: toggleArrows, title: "flechas entre tarjetas" },
    { label: "Pensamiento", icon: "💭", on: showThinking, toggle: () => setShowThinking((v) => !v), title: "mostrar el pensamiento del agente en la conversación" },
    { label: "Detalles técnicos", icon: "🛠", on: details, toggle: toggleDetails, title: "PID, hooks e id en las tarjetas; contadores en cero; nombre del .jsonl en el panel" },
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
