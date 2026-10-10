import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, isMissingRoute, pendingApi, rulesApi, sessionsApi, type AuthInfo } from "./api";
import { Board, colOf, norm, passesFilters } from "./components/Board";
import { ConsultasBar } from "./components/Consulta";
import { RemoteBrowser } from "./components/RemoteBrowser";
import { allAgents } from "./agents";
import { canWrite, hasConsole, shortName, toggled } from "./names";
import { Enroll } from "./components/Enroll";
import { Forward } from "./components/Forward";
import { Header } from "./components/Header";
import { Login } from "./components/Login";
import { Knowledge } from "./components/Knowledge";
import { Pairing } from "./components/Pairing";
import { Panel } from "./components/Panel";
import { pcOf, PcStrip, usePcFilter, usePeers } from "./components/PcStrip";
import { ProjectStrip, expandSelected, repoGroups, useProjectFilter } from "./components/ProjectStrip";
import { SelectionBar } from "./components/SelectionBar";
import { Setup, TotpQr } from "./components/Setup";
import { Toasts, useToasts } from "./components/Toasts";
import { UrlQr } from "./components/UrlQr";
import { useLienzoData } from "./hooks/useLienzoData";
import { useLocalFlag } from "./hooks/useLocalFlag";
import { useNotifications } from "./hooks/useNotifications";
import type { Config, ConfigPut, Session, State } from "./types";

/** sin /auth todavia: cada cuanto se reintenta y desde cuantas fallas seguidas se dice el motivo */
const AUTH_RETRY_MS = 4000;
const AUTH_FAILS_SHOWN = 3;

export default function App() {
  const [authInfo, setAuthInfo] = useState<AuthInfo | null>(null);
  // fallas seguidas de /auth y la ultima: sin authInfo la pantalla es "conectando…", y antes un
  // /auth que fallaba al abrir (server reiniciandose, sin red) la dejaba asi para siempre, sin
  // reintentar ni decir por que
  const [authFail, setAuthFail] = useState<{ n: number; msg: string } | null>(null);
  const refreshAuth = useCallback(
    () =>
      api
        .get<AuthInfo>("/auth")
        .then((a) => {
          setAuthInfo(a);
          setAuthFail(null);
        })
        .catch((e) => setAuthFail((f) => ({ n: (f?.n ?? 0) + 1, msg: (e as Error).message }))),
    [],
  );
  useEffect(() => {
    refreshAuth();
  }, [refreshAuth]);
  // mientras no hay authInfo se reintenta solo; con authInfo el reloj de 20 s del tablero lo refresca
  useEffect(() => {
    if (authInfo) return;
    const id = window.setInterval(refreshAuth, AUTH_RETRY_MS);
    return () => window.clearInterval(id);
  }, [authInfo, refreshAuth]);

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
  if (!authInfo) {
    // las primeras fallas son lo normal de un server que se esta reiniciando: el motivo aparece
    // recien despues de varias, para no asustar en cada arranque
    return (
      <div className="empty">
        conectando…
        {authFail && authFail.n >= AUTH_FAILS_SHOWN && (
          <div className="small dim" role="alert" style={{ marginTop: 6 }}>
            El server no contesta ({authFail.msg}). Se reintenta cada {AUTH_RETRY_MS / 1000} s; si sigue así, fijate que esté corriendo.
          </div>
        )}
      </div>
    );
  }
  if (authInfo.configured && !authInfo.authenticated) return <Login onDone={refreshAuth} mode={authInfo.mode} initialPassphrase={prefill} />;
  if (window.location.pathname.replace(/\/+$/, "") === "/chrome") return <RemoteBrowser />;
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
  const { selected: selectedGroups, coordOnly, selectRepo, toggleRepo, showAll: showAllRepos, toggleCoord } = useProjectFilter(projectGroups);
  // un chip junta el mismo proyecto de varias PCs: el filtro de tarjetas recibe todos sus miembros
  const selectedRepos = useMemo(() => expandSelected(selectedGroups, projectGroups), [selectedGroups, projectGroups]);

  // seleccion multiple de tarjetas (Ctrl + click): los session_id marcados, en el orden en que se
  // marcaron. Se calcula sobre lo que existe: una sesion que desaparece sale sola de la seleccion
  const [marked, setMarked] = useState<Set<string>>(() => new Set());
  const markedLive = useMemo(() => new Set([...marked].filter((sid) => sessions[sid])), [marked, sessions]);
  const toggleMark = useCallback((sid: string) => setMarked((cur) => toggled(cur, sid)), []);
  const clearMarked = useCallback(() => setMarked((cur) => (cur.size ? new Set() : cur)), []);

  // auto_continue y auto_retry viven en ~/.lienzo/config.json (lo lee el server): GET/PUT /config.
  // null mientras carga o si el server que corre no tiene la ruta todavia.
  // Se refresca con el reloj de 20 s de abajo y no solo al abrir: auto_aprobar se propaga a todas
  // las PCs, asi que lo puede prender o apagar otra pestaña u otra PC, y la barra negra de peligro
  // tiene que seguir a lo que el server tiene de verdad (plan 0.3). Un error pasajero (server
  // reiniciandose, red) conserva el ultimo valor: volver a null escondia la barra con auto-aprobar
  // prendido. Solo el 404 de la ruta lo deja en null.
  const [config, setConfig] = useState<Config | null>(null);
  // cada PUT suma uno: un GET que salio antes de un PUT y vuelve despues trae el valor viejo y no
  // tiene que pisar lo que el PUT devolvio
  const configSeq = useRef(0);
  const loadConfig = useCallback(() => {
    const seq = configSeq.current;
    return api
      .get<Config>("/config")
      .then((c) => seq === configSeq.current && setConfig(c))
      .catch((e) => isMissingRoute(e) && setConfig(null));
  }, []);
  useEffect(() => {
    loadConfig();
  }, [loadConfig]);
  const toggleConfig = useCallback(
    async (key: keyof Config, on: string, off: string) => {
      if (!config) {
        toast("El server que corre no tiene /config todavía: reiniciá el server", true);
        return;
      }
      // el PUT manda el valor deseado y la pantalla muestra lo que el server devuelve, no lo deseado
      const deseado = !config[key];
      configSeq.current++;
      try {
        const { peers: porPc, ...c } = await api.put<ConfigPut>("/config", { [key]: deseado });
        setConfig(c);
        toast(c[key] ? on : off);
        // auto_aprobar se reenvia a cada PC emparejada; el server dice cual no lo tomo. Un server
        // anterior no manda `peers`: sin el campo no hay nada que avisar
        const fallaron = Object.entries(porPc ?? {}).filter(([, r]) => r !== "ok");
        if (fallaron.length) {
          const nombre = (id: string) => peers.find((p) => p.pc_id === id)?.name ?? id;
          toast(`${fallaron.map(([id, r]) => `${nombre(id)} no lo tomó (${r})`).join("; ")}: sigue como estaba ahí`, true);
        }
      } catch (e) {
        toast(`No se pudo cambiar: ${(e as Error).message}`, true);
      }
    },
    [config, toast, peers],
  );
  const toggleAutoContinue = useCallback(
    () => toggleConfig("auto_continue", 'Ante un límite de uso con hora, se programa "Continuar" solo', "Continuar automático apagado"),
    [toggleConfig],
  );
  const toggleAutoAprobar = useCallback(() => {
    if (!config?.auto_aprobar && !window.confirm("PELIGRO: cada permiso que pida cualquier agente (Claude, Codex, Pi, coda) en cualquier PC se aprueba solo, sin que nadie lo mire. ¿Prenderlo?")) return;
    void toggleConfig("auto_aprobar", "AUTO-APROBAR TODO prendido: nadie revisa los permisos", "Auto-aprobar apagado");
  }, [config, toggleConfig]);
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
      .filter((s) => hasConsole(s) && passesFilters(s, filtros, q) && colOf(s) !== "muerta" && !peerDown(s) && !markedLive.has(s.session_id))
      .map((s) => s.session_id);
  }, [sessions, query, agents, pcFilter, localPcId, selectedRepos, coordOnly, peerDown, markedLive]);
  const markVisible = useCallback(() => setMarked((cur) => new Set([...cur, ...visibleToMark])), [visibleToMark]);
  const [showHelp, setShowHelp] = useState(false);
  const [showKnowledge, setShowKnowledge] = useState(false);
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
      if (showKnowledge) {
        setShowKnowledge(false);
        if (!all) return;
      }
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
    [connect, showHelp, showKnowledge],
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

  // re-render periodico para los "hace X min", refresco del estado de acceso (URL del tunel) y de
  // la config (auto_aprobar puede cambiar desde otra PC)
  const [, setClock] = useState(0);
  useEffect(() => {
    const id = setInterval(() => {
      setClock((c) => c + 1);
      refreshAuth();
      loadConfig();
    }, 20000);
    return () => clearInterval(id);
  }, [refreshAuth, loadConfig]);

  const decide = useCallback(
    async (requestId: string, decision: "allow" | "deny") => {
      try {
        await pendingApi.decide(requestId, decision);
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
        await pendingApi.answer(requestId, answers);
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
        await sessionsApi.remove(sid);
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
  const deleteRule = useCallback((id: string) => rulesApi.remove(id).catch((e) => toast((e as Error).message, true)), [toast]);
  const connectCards = useCallback((from: string, to: string) => setConnect({ from, to }), []);

  const sel = selected ? sessions[selected] : null;
  // sesiones a las que se les puede escribir: destinos de Conectar y coordinadora del SendBox. Sin
  // consola sigue descartando `canWrite`; sumamos la PC caida, que no es "sin consola" pero tampoco
  // tiene a quien escribirle (notas-D.md, ronda 3)
  const writable = Object.values(sessions).filter((s) => canWrite(s) && !peerDown(s));

  const flags = [
    // grupo «mostrar»: lo que se ve en el tablero; «auto»: lo que el lienzo hace solo. `desc` es la linea
    // corta visible en el menu; `title`, el detalle entero en el tooltip
    { grupo: "mostrar", label: "Avisos del navegador", on: notify, toggle: toggleNotify, title: "aviso del navegador (aunque la pestaña esté atrás) cuando una sesión pide permiso o te hace una pregunta" },
    { grupo: "mostrar", label: "Flechas", on: showArrows, toggle: toggleArrows, title: "dibujar las conexiones entre tarjetas: envíos hechos, reglas pendientes y canal nativo" },
    { grupo: "mostrar", label: "Detalles técnicos", on: details, toggle: toggleDetails, title: "para depurar: PID, hooks e id de sesión en las tarjetas, contadores en cero del digest, nombre del .jsonl en el panel" },
    {
      grupo: "auto",
      label: "Reintentar tras un error de API",
      desc: "manda «Continuar» una vez, a los 10 s",
      on: !!config?.auto_retry,
      toggle: toggleAutoRetry,
      title: config
        ? "cuando un turno muere con \"API Error: The response stopped arriving\" (o parecido), mandar \"Continuar\" diez segundos después, una sola vez por error (auto_retry en ~/.lienzo/config.json)"
        : "el server que corre no tiene /config: reiniciá el server",
    },
    {
      grupo: "auto",
      label: "Auto-aprobar TODO",
      desc: "aprueba cada permiso sin mirarlo, en todas las PCs",
      on: !!config?.auto_aprobar,
      toggle: toggleAutoAprobar,
      danger: true,
      title: config
        ? "aprueba solo, sin mirarlo, cada permiso que pida cualquier agente en cualquier PC emparejada (las preguntas con opciones no). Cada aprobación queda en el log como AUTO-APROBADO"
        : "el server que corre no tiene /config: reiniciá el server",
    },
    {
      grupo: "auto",
      label: "Continuar tras el límite de uso",
      desc: "a la hora que avisa el agente",
      on: !!config?.auto_continue,
      toggle: toggleAutoContinue,
      title: config
        ? "cuando una sesión avisa que llegó al límite de uso con hora de vuelta, programar \"Continuar\" un minuto después (auto_continue en ~/.lienzo/config.json)"
        : "el server que corre no tiene /config: reiniciá el server",
    },
  ] as const;

  return (
    <div className={`${details ? "details" : ""} ${sel ? "panel-open" : ""}`}>
      {config?.auto_aprobar && (
        <div className="auto-aprobar-aviso" role="alert">
          ☠ AUTO-APROBAR TODO prendido: cada permiso se aprueba solo, sin mirarlo
          <button onClick={toggleAutoAprobar}>Apagar</button>
        </div>
      )}
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
        onKnowledge={() => { closeOverlays(true); setShowKnowledge(true); }}
        onRescan={rescan}
        projects={
          <ProjectStrip
            groups={projectGroups}
            selected={selectedGroups}
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
      {showKnowledge && <Knowledge onClose={() => setShowKnowledge(false)} />}
      {showQr && authInfo.remote_url && <UrlQr url={authInfo.remote_url} mode={authInfo.mode} onClose={() => setShowQr(false)} />}
      {showTotp && <TotpQr onClose={() => setShowTotp(false)} />}
      {showPairing && <Pairing peers={peers} toast={toast} onClose={() => setShowPairing(false)} />}
      <PcStrip peers={peers} sessions={sessions} filter={pcFilter} onSelect={selectPc} onToggle={togglePc} onAll={showAllPcs} />
      <ConsultasBar />
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
        escBlocked={showHelp || showKnowledge || !!connect}
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
