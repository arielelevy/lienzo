import { useCallback, useEffect, useRef, useState } from "react";
import { api, detail, type AuthInfo } from "./api";
import { Board, type Agent } from "./components/Board";
import { Enroll } from "./components/Enroll";
import { Forward } from "./components/Forward";
import { Login } from "./components/Login";
import { Panel } from "./components/Panel";
import { Setup, TotpQr } from "./components/Setup";
import { Toasts, useToasts } from "./components/Toasts";
import { UrlQr } from "./components/UrlQr";
import type { Link, Pending, Rule, ServerEvent, Session, State } from "./types";

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
  const [showArrows, setShowArrows] = useState(() => {
    try {
      return localStorage.getItem("lienzo.arrows") !== "0";
    } catch {
      return true;
    }
  });
  const toggleArrows = useCallback(() => {
    setShowArrows((v) => {
      try {
        localStorage.setItem("lienzo.arrows", v ? "0" : "1");
      } catch {
        /* sin storage, no importa */
      }
      return !v;
    });
  }, []);
  const { toasts, toast } = useToasts();
  const selectedRef = useRef<string | null>(null);
  selectedRef.current = selected;

  // filtro visual del header: texto + agentes. "/" enfoca la caja, Esc la limpia.
  const [query, setQuery] = useState("");
  const [agents, setAgents] = useState<Record<Agent, boolean>>({ claude: true, codex: true });
  const searchRef = useRef<HTMLInputElement>(null);
  const [showHelp, setShowHelp] = useState(false);
  // menu "⋯" del header: click afuera lo cierra
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [menuOpen]);
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
          setLinks(ls);
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
        if (m.links) setLinks(m.links);
        if (m.rules) setRules(m.rules);
        setTranscriptTick((t) => t + 1);
      } else if (m.type === "links") {
        setLinks(m.links);
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

  // Escape cierra lo que este abierto: ayuda, dialogo de conexion, o panel
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (menuOpen) setMenuOpen(false);
      else if (showHelp) setShowHelp(false);
      else if (connect) setConnect(null);
      else if (selectedRef.current) setSelected(null);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [connect, showHelp, menuOpen]);

  // click fuera del panel (y fuera de una tarjeta) lo cierra
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      const t = e.target as HTMLElement;
      if (!selectedRef.current) return;
      if (t.closest(".panel") || t.closest(".card") || t.closest(".toasts") || t.closest(".gate")) return;
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

  return (
    <div className={showThinking ? "showthink" : ""}>
      <header>
        <h1>Lienzo</h1>
        <span className={`dot ${connected ? "on" : ""}`} title={!connected ? "reconectando" : polling ? "sondeo cada 4 s" : "en vivo"} aria-label={!connected ? "reconectando" : "conectado"} />
        <div className="search" role="search">
          <input
            ref={searchRef}
            type="search"
            value={query}
            placeholder="buscar  /"
            aria-label="filtrar tarjetas por repo, título o último pedido"
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                e.stopPropagation();
                setQuery("");
                (e.target as HTMLInputElement).blur();
              }
            }}
          />
          {(["claude", "codex"] as Agent[]).map((a) => (
            <button
              key={a}
              className={`chip ${a} ${agents[a] ? "on" : ""}`}
              aria-pressed={agents[a]}
              title={agents[a] ? `ocultar sesiones de ${a}` : `mostrar sesiones de ${a}`}
              onClick={() => setAgents((prev) => ({ ...prev, [a]: !prev[a] }))}
            >
              {a}
            </button>
          ))}
        </div>
        <span className="sp" />
        {/* acceso desde el celular: URL del tunel y QR de Authenticator, juntos */}
        {authInfo.remote_url && authInfo.local && (
          <button className="icon lbl" title={`abrir en el celular: ${authInfo.remote_url.replace("https://", "")}`} aria-label="QR con la URL para el celular" onClick={() => setShowQr(true)}>
            <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="2" width="12" height="20" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.8" /><circle cx="12" cy="18.2" r="1" fill="currentColor" /></svg><span className="txt">Celular</span>
          </button>
        )}
        {!authInfo.configured && authInfo.local && (
          <button className="icon lbl" onClick={onSetup} title="configurar el acceso desde el celular con Authenticator" aria-label="configurar acceso remoto">
            <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2 4 5v6c0 5.2 3.4 9.6 8 11 4.6-1.4 8-5.8 8-11V5l-8-3z" fill="#2f7be8" /><rect x="8.5" y="11" width="7" height="5.5" rx="1" fill="#fff" /><path d="M10 11V9.6a2 2 0 0 1 4 0V11" stroke="#fff" strokeWidth="1.6" fill="none" /></svg><span className="txt">Acceso remoto</span>
          </button>
        )}
        {authInfo.configured && authInfo.local && (
          <button className="icon lbl auth" onClick={() => setShowTotp(true)} title="QR de Microsoft Authenticator" aria-label="QR de Authenticator">
            <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2 4 5v6c0 5.2 3.4 9.6 8 11 4.6-1.4 8-5.8 8-11V5l-8-3z" fill="#2f7be8" /><rect x="8.5" y="11" width="7" height="5.5" rx="1" fill="#fff" /><path d="M10 11V9.6a2 2 0 0 1 4 0V11" stroke="#fff" strokeWidth="1.6" fill="none" /></svg><span className="txt">Authenticator</span>
          </button>
        )}
        <div className="menu" ref={menuRef}>
          <button className="icon" title="más" aria-label="más opciones" aria-haspopup="menu" aria-expanded={menuOpen} onClick={() => setMenuOpen((v) => !v)}>
            ⋯
          </button>
          {menuOpen && (
            <div className="dropdown" role="menu">
              <button role="menuitemcheckbox" aria-checked={notify} onClick={toggleNotify} title="notificación del navegador cuando una sesión pide permiso">
                🔔 Avisos <span className={`state ${notify ? "on" : ""}`}>{notify ? "on" : "off"}</span>
              </button>
              <button role="menuitemcheckbox" aria-checked={showArrows} onClick={toggleArrows} title="flechas entre tarjetas">
                ↪ Flechas <span className={`state ${showArrows ? "on" : ""}`}>{showArrows ? "on" : "off"}</span>
              </button>
              <button role="menuitemcheckbox" aria-checked={showThinking} onClick={() => setShowThinking((v) => !v)} title="mostrar el pensamiento del agente en la conversación">
                💭 Pensamiento <span className={`state ${showThinking ? "on" : ""}`}>{showThinking ? "on" : "off"}</span>
              </button>
              <hr />
              <button
                role="menuitem"
                onClick={() => {
                  setMenuOpen(false);
                  rescan();
                }}
                title="barrer procesos de VS Code"
              >
                ↻ Rescan
              </button>
              <button
                role="menuitem"
                onClick={() => {
                  setMenuOpen(false);
                  setShowHelp(true);
                }}
              >
                ? Atajos de teclado
              </button>
              {authInfo.configured && !authInfo.local && (
                <>
                  <hr />
                  <button
                    role="menuitem"
                    onClick={() => {
                      setMenuOpen(false);
                      api.post("/logout", {}).then(refreshAuth).catch((e) => toast((e as Error).message, true));
                    }}
                    title="cerrar sesión en este dispositivo"
                  >
                    ⏏ Salir
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      </header>
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
              <span className={`badge ${sessions[connect.from].agent}`}>{sessions[connect.from].agent}</span>
              {sessions[connect.from].title || sessions[connect.from].repo}
              {connect.to && sessions[connect.to] && (
                <>
                  <span className="dim">→</span>
                  <span className={`badge ${sessions[connect.to].agent}`}>{sessions[connect.to].agent}</span>
                  {sessions[connect.to].title || sessions[connect.to].repo}
                </>
              )}
            </h1>
            <Forward
              from={sessions[connect.from]}
              others={Object.values(sessions).filter((s) => s.session_id !== connect.from && s.alive && s.pid)}
              initialTarget={connect.to || undefined}
              toast={toast}
              onDone={() => setConnect(null)}
            />
          </div>
        </div>
      )}
      {sel && <div className="panel-backdrop" aria-hidden="true" />}
      {sel && (
        <Panel
          key={sel.session_id}
          session={sel}
          onConnect={() => setConnect({ from: sel.session_id, to: "" })}
          transcriptTick={transcriptTick}
          onClose={() => setSelected(null)}
          toast={toast}
        />
      )}
      <Toasts toasts={toasts} />
    </div>
  );
}
