import { ago } from "../api";
import type { Peer, PeerHealth } from "../types";

/** El logo de Chrome, en el subíndice del badge (`--chrome`) y en la tarjeta de la extensión. */
export function ChromeLogo({ size }: { size: number }) {
  return (
    <svg viewBox="0 0 16 16" width={size} height={size} aria-hidden="true">
      <path d="M8 8L1.07 4A8 8 0 0 1 14.93 4Z" fill="#db4437" />
      <path d="M8 8L14.93 4A8 8 0 0 1 8 16Z" fill="#f4b400" />
      <path d="M8 8L8 16A8 8 0 0 1 1.07 4Z" fill="#0f9d58" />
      <circle cx="8" cy="8" r="3.7" fill="#fff" />
      <circle cx="8" cy="8" r="2.8" fill="#4285f4" />
    </svg>
  );
}

export type ChromeConexion = NonNullable<PeerHealth["chrome_conexiones"]>[number] & { peer: Peer };

/** Las extensiones de Claude y Codex conectadas ahora en Chrome, de las PCs vivas que pasan el
 *  filtro de PC (chrome_claude.conexiones en la salud de cada PC). */
export function chromeConexiones(peers: Peer[], pcFilter: Set<string>): ChromeConexion[] {
  return peers
    .filter((p) => p.alive !== false && (pcFilter.size === 0 || pcFilter.has(p.pc_id)))
    .flatMap((p) => (p.health?.chrome_conexiones ?? []).map((c) => ({ ...c, peer: p })));
}

const VIA: Record<ChromeConexion["host"], string> = {
  desktop: "vía Claude Desktop",
  code: "vía Claude Code",
  codex: "vía Codex",
};

/** Una extensión conectada: sólo presencia. El chat vive en la nube y en la extensión, y el
 *  lienzo no lo lee; por eso la tarjeta no abre panel ni tiene acciones. */
export function ChromeCard({ c, pcColor }: { c: ChromeConexion; pcColor?: string }) {
  const nombre = c.agent === "codex" ? "Codex" : "Claude";
  return (
    <div
      className={`card chromeext ${pcColor ? "haspc" : ""}`}
      style={pcColor ? ({ "--pc-color": pcColor } as React.CSSProperties) : undefined}
      role="group"
      aria-label={`${nombre} en Chrome en ${c.peer.name}: conectada ${VIA[c.host]}`}
    >
      <div className="top">
        <span className={`badge ${c.agent}`}>
          {c.agent}
          <sub className="badge-chrome" role="img" aria-label="en Chrome">
            <ChromeLogo size={11} />
          </sub>
        </span>
        <span className="repo">{c.peer.name}</span>
        <span className="right" title={c.desde ?? undefined}>{c.desde ? ago(c.desde) : ""}</span>
      </div>
      <div className="title">{nombre} en Chrome</div>
      <div className="down small dim">Extensión conectada {VIA[c.host]}</div>
      <div className="meta">
        <span>PID {c.pids.join(", ")}</span>
      </div>
    </div>
  );
}
