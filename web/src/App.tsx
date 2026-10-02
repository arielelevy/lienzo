import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type AuthInfo } from "./api";
import { Board, canReceive, colOf, norm, passesFilters } from "./components/Board";
import { allAgents } from "./agents";
import { canWrite, shortName, toggled } from "./names";
import { Enroll } from "./components/Enroll";
import { Forward } from "./components/Forward";
import { Header } from "./components/Header";
import { Login } from "./components/Login";
import { Pairing } from "./components/Pairing";
import { Panel } from "./components/Panel";
import { pcOf, PcStrip, usePcFilter, usePeers } from "./components/PcStrip";
import { ProjectStrip, repoGroups, useProjectFilter } from "./components/ProjectStrip";
import { SelectionBar } from "./components/SelectionBar";
import { Setup, TotpQr } from "./components/Setup";
import { Toasts, useToasts } from "./components/Toasts";
import { UrlQr } from "./components/UrlQr";
import { useLienzoData } from "./hooks/useLienzoData";
import { useLocalFlag } from "./hooks/useLocalFlag";
import { useNotifications } from "./hooks/useNotifications";
import type { Config, Session, State } from "./types";

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
  const [showPairing, setShowPairing] = useState(false);
  // dialogo de conectar (se abre arrastrando una tarjeta sobre otra): flotante, sin abrir nada mas
  const [connect, setConnect] = useState<{ from: string; to: string } | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [anchor, setAnchor] = useState<{ left: number; top: number; width: number; height: number } | null>(null);
  // Medir al abrir, no durante render: SSE no mueve un panel que ya esta abierto.
  const openPanel = useCallback((sid: string) => {
    const rect = document.querySelector(`.card[data-sid="${CSS.escape(sid)}"]`)?.getBoundingClientRect();
    setAnchor(rect ? { left: rect.left, top: rect.top, width: rect.width, height: rect.height } : null);
    setSelected(sid);
  }, []);
  const [filter, setFilter] = useState<State>("corriendo");
  // flechas visibles u ocultas, recordado por navegador
  const [showArrows, toggleArrows] = useLocalFlag("lienzo.arrows", true);
  // "Detalles tecnicos": PID/hooks/id en las tarjetas, contadores en cero del digest, nombre del
  // .jsonl en el panel. Sirven para depurar, no para usar: apagados por defecto
  const [details, toggleDetails] = useLocalFlag("lienzo.details", false);
  const { toasts, toast } = useToasts();
  const selectedRef = useRef<string | null>(null);
  useEffect(() => { selectedRef.current = selected; }, [selected]);
  // una sesion que desaparece del tablero cierra su panel y el dialogo de conectar que la tenia
  const onRemoved = useCallback((sid: string) => {
    setSelected((current) => current === sid ? null : current);
    setConnect((c) => (c && (c.from === sid || c.to === sid) ? null : c));
  }, []);
  const { sessions, pending, links, rules, connected, polling, transcriptTick } = useLienzoData({ refreshAuth, selectedRef, onRemoved });
  // notificaciones del navegador cuando una sesion pide permiso; el click abre su panel
  const { notify, toggleNotify } = useNotifications({ sessions, pending, onOpen: openPanel, toast });

  // tira de PCs (ronda multi-PC, §3.9 del plan): [] hasta que exista GET /peers, y entonces la
  // tira ni el filtro se dibujan (PcStrip lo decide solo con el arreglo vacío)
  const peers = usePeers();
  const { pcFilter, selectPc, togglePc, showAllPcs } = usePcFilter(peers);
  // sesion de una PC caida: ni el tablero (Board.tsx tiene su propio peerDownOf) ni el selector de
  // destino de Conectar/Pegar trabajo tienen a quien escribirle, aunque la sesion siga "viva" en el
  // espejo (mismo criterio que Board: peer.alive === false)
  const peersById = useMemo(() => new Map(peers.map((p) => [p.pc_id, p])), [peers]);
  const localPcId = useMemo(() => peers.find((p) => p.local)?.pc_id ?? null, [peers]);
  const peerDown = useCallback((s: Session) => peersById.get(pcOf(s, localPcId) ?? "")?.alive === false, [peersById, localPcId]);
  // tira de proyectos (pedido de Ariel, parte 3): un chip por repo con sesiones vivas, y ★ Coordinadoras
  const projectGroups = useMemo(() => repoGroups(Object.values(sessions)), [sessions]);
  const { selected: selectedRepos, coordOnly, selectRepo, toggleRepo, showAll: showAllRepos, toggleCoord } = useProjectFilter(projectGroups);

  // seleccion multiple de tarjetas (Ctrl + click): los session_id marcados, en el orden en que se
  // marcaron. Se calcula sobre lo que existe: una sesion que desaparece sale sola de la seleccion
  const [marked, setMarked] = useState<Set<string>>(() => new Set());
  const markedLive = useMemo(() => new Set([...marked].filter((sid) => sessions[sid])), [marked, sessions]);
  const toggleMark = useCallback((sid: string) => setMarked((cur) => toggled(cur, sid)), []);
  const clearMarked = useCallback(() => setMarked((cur) => (cur.size ? new Set() : cur)), []);

  // auto_continue y auto_retry viven en ~/.lienzo/config.json (lo lee el server): GET/PUT /config.
  // null mientras carga o si el server que corre no tiene la ruta todavia
  const [config, setConfig] = useState<Config | null>(null);
  const loadConfig = useCallback(() => api.get<Config>("/config").then(setConfig).catch(() => setConfig(null)), []);
  useEffect(() => {
    loadConfig();
  }, [loadConfig]);
  const toggleConfig = useCallback(
    async (key: keyof Config, on: string, off: string) => {
      if (!config) {
        toast("El server que corre no tiene /config todavía: reiniciá el server", true);
        return;
      }
      try {
        const c = await api.put<Config>("/config", { [key]: !config[key] });
        setConfig(c);
        toast(c[key] ? on : off);
      } catch (e) {
        toast(`No se pudo cambiar: ${(e as Error).message}`, true);
      }
    },
    [config, toast],
  );
  const toggleAutoContinue = useCallback(
    () => toggleConfig("auto_continue", 'Ante un límite de uso con hora, se programa "Continuar" solo', "Continuar automático apagado"),
    [toggleConfig],
  );
  const toggleAutoRetry = useCallback(
    () => toggleConfig("auto_retry", 'Ante un error de API, se reintenta solo (una vez por error)', "Reintento automático apagado"),
    [toggleConfig],
  );

  // filtro visual del header: texto + agentes. "/" enfoca la caja, Esc la limpia.
  const [query, setQuery] = useState("");
  const [agents, setAgents] = useState(allAgents);
  const searchRef = useRef<HTMLInputElement>(null);
  // lo que se ve ahora: pasa los filtros (header, PCs, proyectos) y se le puede escribir. Una de la
  // columna Muerta o de una PC caida no entra: no hay a quien mandarle nada
  const visibleToMark = useMemo(() => {
    if (markedLive.size === 0) return []; // la barra de seleccion solo existe con algo marcado
    const filtros = { query, agents, pcFilter, localPcId, selectedRepos, coordOnly };
    const q = norm(query.trim());
    return Object.values(sessions)
      .filter((s) => canReceive(s) && passesFilters(s, filtros, q) && colOf(s) !== "muerta" && !peerDown(s) && !markedLive.has(s.session_id))
      .map((s) => s.session_id);
  }, [sessions, query, agents, pcFilter, localPcId, selectedRepos, coordOnly, peerDown, markedLive]);
  const markVisible = useCallback(() => setMarked((cur) => new Set([...cur, ...visibleToMark])), [visibleToMark]);
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

  // Lo que hay abierto sobre el tablero, de adelante hacia atras: ayuda, dialogo de conectar,
  // panel. `all` cierra todo de una; sin `all` cierra un nivel, el de mas adelante.
  const closeOverlays = useCallback(
    (all = false) => {
      if (showHelp) {
        setShowHelp(false);
        if (!all) return;
      }
      if (connect) {
        setConnect(null);
        if (!all) return;
      }
      if (selectedRef.current) setSelected(null);
    },
    [connect, showHelp],
  );

  // Escape va de a un nivel; el menu del header lo cierra el propio Header y frena esta cascada
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (document.querySelector("header .dropdown")) return;
      closeOverlays();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [closeOverlays]);

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

  /** Contestar una pregunta con opciones: es el mismo pendiente que un permiso, pero la respuesta
   *  elegida viaja en `answers` y el hook la mete en el input de la herramienta. */
  const answer = useCallback(
    async (requestId: string, answers: Record<string, string>) => {
      try {
        await api.post(`/pending/${requestId}`, { decision: "allow", answers });
        toast(`Contestado: ${Object.values(answers).join(" · ")}`);
      } catch (e) {
        toast(`No se pudo contestar: ${(e as Error).message}`, true);
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
  // sesiones a las que se les puede escribir: destinos de Conectar y coordinadora del SendBox. Sin
  // consola sigue descartando `canWrite`; sumamos la PC caida, que no es "sin consola" pero tampoco
  // tiene a quien escribirle (notas-D.md, ronda 3)
  const writable = Object.values(sessions).filter((s) => canWrite(s) && !peerDown(s));

  const flags = [
    { label: "Avisos", icon: "🔔", on: notify, toggle: toggleNotify, title: "aviso del navegador (aunque la pestaña esté atrás) cuando una sesión pide permiso o te hace una pregunta" },
    { label: "Flechas", icon: "↪", on: showArrows, toggle: toggleArrows, title: "dibujar las conexiones entre tarjetas: envíos hechos, reglas pendientes y canal nativo" },
    { label: "Detalles técnicos", icon: "🛠", on: details, toggle: toggleDetails, title: "para depurar: PID, hooks e id de sesión en las tarjetas, contadores en cero del digest, nombre del .jsonl en el panel" },
    {
      label: "Reintentar solo tras un error de API",
      icon: "↻",
      on: !!config?.auto_retry,
      toggle: toggleAutoRetry,
      title: config
        ? "cuando un turno muere con \"API Error: The response stopped arriving\" (o parecido), mandar \"Continuar\" diez segundos después, una sola vez por error (auto_retry en ~/.lienzo/config.json)"
        : "el server que corre no tiene /config: reiniciá el server",
    },
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
    <div className={`${details ? "details" : ""} ${sel ? "panel-open" : ""}`}>
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
        // el header quedo por encima del modal: estos abren otro, asi que cierran lo de atras
        // primero y no se apilan dos fondos oscuros
        onShowQr={() => {
          closeOverlays(true);
          setShowQr(true);
        }}
        onShowTotp={() => {
          closeOverlays(true);
          setShowTotp(true);
        }}
        onShowPairing={() => {
          closeOverlays(true);
          setShowPairing(true);
        }}
        onHelp={() => setShowHelp(true)}
        onRescan={rescan}
        projects={
          <ProjectStrip
            groups={projectGroups}
            selected={selectedRepos}
            coordOnly={coordOnly}
            onSelectRepo={selectRepo}
            onToggleRepo={toggleRepo}
            onShowAll={showAllRepos}
            onToggleCoord={toggleCoord}
          />
        }
        onLogout={() => api.post("/logout", {}).then(refreshAuth).catch((e) => toast((e as Error).message, true))}
        // abrir el menu es cambiar de contexto: cierra todo lo que haya detras, no un nivel
        onMenuOpen={() => closeOverlays(true)}
        flags={flags}
      />
      {showHelp && (
        <div className="gate" onMouseDown={(e) => e.target === e.currentTarget && setShowHelp(false)}>
          <div className="gate-box help" role="dialog" aria-label="atajos">
            <h1>Atajos</h1>
            {/* primero los gestos del mouse, que son los que se olvidan, y despues las teclas */}
            <dl>
              <dt>click</dt>
              <dd>elige la tarjeta: la resalta con sus flechas y muestra sus conexiones en palabras</dd>
              <dt><kbd>Ctrl</kbd> + click</dt>
              <dd>suma o saca la tarjeta de una selección múltiple (también <kbd>Ctrl</kbd> + <kbd>Espacio</kbd> con la tarjeta enfocada); abajo aparece la barra para enviarles a todas, interrumpirlas o limpiar. En un chip de proyecto o de PC, suma o saca ese chip del filtro</dd>
              <dt>doble click</dt>
              <dd>abre el panel de la tarjeta</dd>
              <dt>arrastrar</dt>
              <dd>una tarjeta sobre otra abre el diálogo de conectar con ese destino; soltarla sobre sí misma, Programar</dd>
              <dt>✎</dt>
              <dd>renombra la tarjeta en el lugar (aparece al pasar el mouse, junto a la estrella)</dd>
              <dt>flecha</dt>
              <dd>un click la elige; doble click la opera: en un envío muestra lo que se mandó, en una regla la abre para editar</dd>
              <dt>columna</dt>
              <dd>click en su título la colapsa a una tira; en la tira, la expande</dd>
              <dt><kbd>Esc</kbd></dt>
              <dd>pela una capa por vez: el arrastre, esta ayuda, el diálogo de conectar, el panel, la selección múltiple, y al final la tarjeta elegida; en la búsqueda, la limpia</dd>
              <dt><kbd>Enter</kbd></dt>
              <dd>sobre una tarjeta enfocada, abre su panel</dd>
              <dt><kbd>Tab</kbd></dt>
              <dd>en la caja de envío, acepta la sugerencia gris leída de la terminal</dd>
              <dt><kbd>/</kbd></dt>
              <dd>enfoca la búsqueda (agente, repo, rama, título, último pedido)</dd>
              <dt><kbd>?</kbd></dt>
              <dd>muestra u oculta esta ayuda</dd>
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
      {showPairing && <Pairing peers={peers} toast={toast} onClose={() => setShowPairing(false)} />}
      <PcStrip peers={peers} sessions={sessions} filter={pcFilter} onSelect={selectPc} onToggle={togglePc} onAll={showAllPcs} />
      <Board
        sessions={sessions}
        pending={pending}
        selected={selected}
        filter={filter}
        onFilter={setFilter}
        onSelect={openPanel}
        onDecide={decide}
        onAnswer={answer}
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
        peers={peers}
        pcFilter={pcFilter}
        selectedRepos={selectedRepos}
        coordOnly={coordOnly}
        marked={markedLive}
        onMark={toggleMark}
        onClearMarked={clearMarked}
        escBlocked={showHelp || !!connect}
      />
      <SelectionBar sids={[...markedLive]} sessions={sessions} onClear={clearMarked} visibleToMark={visibleToMark} onMarkVisible={markVisible} />
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
      {/* se abre sobre la tarjeta que lo abrio, con el tablero atenuado y difuminado detras */}
      {sel && (
        <>
        <div className="panel-backdrop" />
        <Panel
          anchor={anchor}
          key={sel.session_id}
          session={sel}
          others={writable.filter((s) => s.session_id !== sel.session_id)}
          transcriptTick={transcriptTick}
          onClose={() => setSelected(null)}
          toast={toast}
          details={details}
          /* el permiso pendiente viaja al panel: con el panel abierto la tarjeta con los botones
             queda atras y difuminada, y en el celular tapada del todo */
          pending={sel.pending_id ? pending[sel.pending_id] : undefined}
          onDecide={decide}
          onAnswer={answer}
        />
        </>
      )}
      <Toasts toasts={toasts} />
    </div>
  );
}
