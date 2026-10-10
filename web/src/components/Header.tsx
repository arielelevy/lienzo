import { useEffect, useRef, useState } from "react";
import type { AuthInfo } from "../api";
import { agentIds, type Agent } from "../agents";

interface Props {
  authInfo: AuthInfo;
  connected: boolean;
  polling: boolean;
  query: string;
  onQuery: (q: string) => void;
  agents: Record<Agent, boolean>;
  onAgents: (a: Record<Agent, boolean>) => void;
  /** el de App: useRef<HTMLInputElement>(null); con @types/react 18 el tipo va sin "| null" */
  searchRef: React.RefObject<HTMLInputElement>;
  onSetup: () => void;
  onShowQr: () => void;
  onShowTotp: () => void;
  onShowPairing: () => void;
  onHelp: () => void;
  onKnowledge?: () => void;
  onRescan: () => void;
  onLogout: () => void;
  /** el menu ⋯ se acaba de abrir (no en cada toggle): abrirlo es cambiar de contexto, asi que App
   *  cierra lo que haya abierto detras (panel, dialogo de conectar, ayuda) */
  onMenuOpen?: () => void;
  /** `vista`: interruptores de lo que se ve (flechas, detalles técnicos), juntos en un renglón del menú */
  flags: { label: string; icon: string; on: boolean; toggle: () => void; title: string; danger?: boolean; vista?: boolean }[];
  /** los chips de proyecto (ProjectStrip), que van despues de los de agente */
  projects?: React.ReactNode;
}

const Shield = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M12 2 4 5v6c0 5.2 3.4 9.6 8 11 4.6-1.4 8-5.8 8-11V5l-8-3z" fill="#2f7be8" />
    <rect x="8.5" y="11" width="7" height="5.5" rx="1" fill="#fff" />
    <path d="M10 11V9.6a2 2 0 0 1 4 0V11" stroke="#fff" strokeWidth="1.6" fill="none" />
  </svg>
);
const Phone = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
    <rect x="6" y="2" width="12" height="20" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
    <circle cx="12" cy="18.2" r="1" fill="currentColor" />
  </svg>
);

/** Header minimalista: marca y estado, buscador con chips por agente, acceso desde el celular
 *  (URL del tunel y QR de Authenticator, juntos) y un menu "⋯" con el resto. */
export function Header({ authInfo, connected, polling, query, onQuery, agents, onAgents, searchRef, onSetup, onShowQr, onShowTotp, onShowPairing, onHelp, onKnowledge, onRescan, onLogout, onMenuOpen, flags, projects }: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMenuOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);
  const closeAnd = (fn: () => void) => () => {
    setMenuOpen(false);
    fn();
  };
  // solo al pasar de cerrado a abierto: cerrar el menu no toca lo que haya detras
  const toggleMenu = () => {
    const open = !menuOpen;
    setMenuOpen(open);
    if (open) onMenuOpen?.();
  };
  const status = !connected ? "reconectando" : polling ? "sondeo cada 4 s" : "en vivo";

  return (
    <header>
      <h1>Lienzo</h1>
      <a className="chrome-link" href="/chrome" target="_blank" rel="noopener noreferrer" title="Abrir el navegador de otra PC en una pestaña nueva">Chrome remoto</a>
      <span className={`dot ${connected ? "on" : ""}`} title={status} aria-label={status} />
      <div className="search" role="search">
        <input
          ref={searchRef}
          type="search"
          value={query}
          placeholder="buscar  /"
          aria-label="filtrar tarjetas por agente, repo, rama, título o último pedido"
          onChange={(e) => onQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.stopPropagation();
              onQuery("");
              (e.target as HTMLInputElement).blur();
            }
          }}
        />
        {agentIds.map((a) => (
          <button
            key={a}
            className={`chip ${a} ${agents[a] ? "on" : ""}`}
            aria-pressed={agents[a]}
            title={agents[a] ? `ocultar sesiones de ${a}` : `mostrar sesiones de ${a}`}
            onClick={() => onAgents({ ...agents, [a]: !agents[a] })}
          >
            {a}
          </button>
        ))}
      </div>
      <span className="agent-project-separator" aria-hidden="true" />
      {projects}
      <span className="sp" />
      {authInfo.remote_url && authInfo.local && (
        <button className="icon lbl" title={`abrir en el celular: ${authInfo.remote_url.replace("https://", "")}`} aria-label="QR con la URL para el celular" onClick={onShowQr}>
          <Phone />
          <span className="txt">Celular</span>
        </button>
      )}
      {!authInfo.configured && authInfo.local && (
        <button className="icon lbl" onClick={onSetup} title="configurar el acceso desde el celular con Authenticator" aria-label="configurar acceso remoto">
          <Shield />
          <span className="txt">Acceso remoto</span>
        </button>
      )}
      {authInfo.configured && authInfo.local && (
        <button className="icon lbl auth" onClick={onShowTotp} title="QR de Microsoft Authenticator" aria-label="QR de Authenticator">
          <Shield />
          <span className="txt">Authenticator</span>
        </button>
      )}
      <div className="menu" ref={menuRef}>
        <button className="icon" title="más" aria-label="más opciones" aria-haspopup="menu" aria-expanded={menuOpen} onClick={toggleMenu}>
          ⋯
        </button>
        {menuOpen && (
          <div className="dropdown" role="menu">
            {/* primero lo que se abre (la memoria arriba de todo, que no quedaba a la vista), despues lo
                que se ve y al final la automatizacion. La descripcion va visible debajo del nombre: el
                title nativo tarda un segundo y nadie lo espera para saber que hace un interruptor */}
            {onKnowledge && <button role="menuitem" onClick={closeAnd(onKnowledge)}>
              <span className="row">🧠 Memoria</span>
              <span className="desc">lo aprendido y lo capturado por proyecto</span>
            </button>}
            <button role="menuitem" onClick={closeAnd(onShowPairing)}>
              <span className="row">🖥 Varias PCs</span>
              <span className="desc">emparejar con otra PC de la red local</span>
            </button>
            <button role="menuitem" onClick={closeAnd(() => window.open("/docs", "_blank", "noopener"))}>
              <span className="row">📖 Referencia</span>
              <span className="desc">README y diseño, con buscador (otra pestaña)</span>
            </button>
            <button role="menuitem" onClick={closeAnd(onHelp)}>
              <span className="row">? Atajos de teclado</span>
            </button>
            <button role="menuitem" onClick={closeAnd(onRescan)}>
              <span className="row">↻ Barrer procesos</span>
              <span className="desc">buscar sesiones ahora (si no, cada 30 s)</span>
            </button>
            <hr />
            {flags.some((f) => f.vista) && (
              <div className="vista" role="group" aria-label="Vista">
                <span className="vista-titulo">Vista</span>
                {flags.filter((f) => f.vista).map((f) => (
                  <button key={f.label} role="menuitemcheckbox" aria-checked={f.on} onClick={f.toggle} title={f.title}>
                    <span className="row">
                      {f.icon} {f.label} <span className={`state ${f.on ? "on" : ""}`}>{f.on ? "sí" : "no"}</span>
                    </span>
                  </button>
                ))}
              </div>
            )}
            {flags.filter((f) => !f.vista).map((f) => (
              <button key={f.label} role="menuitemcheckbox" aria-checked={f.on} onClick={f.toggle} className={f.danger ? "danger" : undefined}>
                <span className="row">
                  {/* "sí"/"no" y no "on"/"off": es lo único que quedaba en inglés en toda la app */}
                  {f.icon} {f.label} <span className={`state ${f.on ? "on" : ""}`}>{f.on ? "sí" : "no"}</span>
                </span>
                <span className="desc">{f.title}</span>
              </button>
            ))}
            {authInfo.configured && !authInfo.local && (
              <>
                <hr />
                <button role="menuitem" onClick={closeAnd(onLogout)}>
                  <span className="row">⏏ Salir</span>
                  <span className="desc">cerrar la sesión remota en este dispositivo</span>
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </header>
  );
}
