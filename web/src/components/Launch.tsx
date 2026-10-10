import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { AGENTS, agentIds, type Agent } from "../agents";
import { opcionesProyecto } from "../recientes";
import type { Peer, Reciente, Session } from "../types";

export function Launch({ peers, sessions, onClose, toast }: {
  peers: Peer[]; sessions: Session[]; onClose: () => void; toast?: (text: string, error?: boolean) => void;
}) {
  const localPc = peers.find(p => p.local)?.pc_id ?? "";
  // null: sin elegir todavía. Se deriva de lo que llegó, así un GET /peers que contesta después de
  // abrir el diálogo igual deja esta PC y su primera carpeta elegidas
  const [pcElegida, setPc] = useState<string | null>(null);
  const pc = pcElegida ?? localPc;
  const [cwd, setCwd] = useState("");
  // lo que recuerda el server (GET /recientes): un server viejo sin la ruta deja la lista vacía
  const [recientes, setRecientes] = useState<Reciente[]>([]);
  useEffect(() => {
    let vivo = true;
    api.get<Reciente[]>("/recientes").then(r => { if (vivo && Array.isArray(r)) setRecientes(r); }).catch(() => {});
    return () => { vivo = false; };
  }, []);
  const grupos = useMemo(() => opcionesProyecto(pc, peers, sessions, recientes), [pc, peers, sessions, recientes]);
  const opciones = useMemo(() => [...grupos.carpetas, ...grupos.usadas, ...grupos.otras], [grupos]);
  // null: la primera carpeta de la PC elegida (la abierta ahora, si hay); "" es «Otra carpeta…»
  const [projectElegido, setProject] = useState<string | null>(null);
  const project = projectElegido ?? grupos.carpetas[0]?.key ?? "";
  const [agent, setAgent] = useState<Agent>("codex");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const sending = useRef(false);
  const elegida = opciones.find(o => o.key === project);
  const directory = elegida?.cwd ?? cwd.trim();
  const unavailable = !!pc && !peers.some(p => p.pc_id === pc && p.alive);
  // distros de WSL de la PC elegida. Por defecto se lanza como siempre (en Windows): la distro va solo
  // si se elige una (revisión 2026-10-10: con una sola distro se mandaba siempre y todo nacía en WSL)
  const distros = peers.find(p => p.pc_id === pc)?.health?.distros_wsl ?? [];
  // la distro elegida recuerda para qué PC fue: al cambiar de PC vuelve la default de esa PC,
  // sin effect (setState sincrónico en un effect encadena renders)
  const [distroElegida, setDistro] = useState<{ pc: string; d: string } | null>(null);
  const distro = distroElegida && distroElegida.pc === pc && distros.includes(distroElegida.d) ? distroElegida.d : "";
  const launch = async () => {
    if (sending.current || !directory || unavailable) return;
    sending.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await api.post<{ ok: boolean; error?: string }>("/sessions/launch", {
        cwd: directory, title: elegida?.title ?? "", agent, ...(pc ? { pc } : {}),
        ...(distro ? { distro } : {}),
      });
      if (!result.ok) throw new Error(result.error || "No se pudo lanzar la CLI");
      toast?.("CLI lanzada");
      onClose();
    } catch (e) { setError((e as Error).message); }
    finally { sending.current = false; setBusy(false); }
  };
  const opcion = (o: { key: string; label: string }) => <option key={o.key} value={o.key}>{o.label}</option>;
  return <dialog ref={element => { if (element && !element.open) element.showModal(); }}
    className="gate-box launch-box" aria-label="Lanzar CLI" onKeyDown={e => e.stopPropagation()}
    onCancel={e => { e.preventDefault(); if (!busy) onClose(); }}>
    <form onSubmit={e => { e.preventDefault(); void launch(); }}>
      <div className="launch-heading"><h2>Lanzar CLI</h2><button type="button" className="icon" aria-label="Cerrar lanzamiento" disabled={busy} onClick={onClose}>×</button></div>
      <label>Proyecto<select autoFocus aria-label="Proyecto" disabled={busy} value={elegida ? project : ""} onChange={e => {
        setProject(e.target.value); setCwd(""); setError("");
      }}>
        <option value="">{opciones.length ? "Otra carpeta…" : "Nueva carpeta"}</option>
        {grupos.carpetas.length > 0 && <optgroup label="Carpetas">{grupos.carpetas.map(opcion)}</optgroup>}
        {grupos.usadas.length > 0 && <optgroup className="launch-recientes" label="Usadas estos días">{grupos.usadas.map(opcion)}</optgroup>}
        {grupos.otras.length > 0 && <optgroup label="En otras PCs">{grupos.otras.map(opcion)}</optgroup>}
      </select></label>
      <label>PC<select aria-label="PC" disabled={busy} value={pc} onChange={e => {
        const next = e.target.value;
        // la misma carpeta por nombre si esa PC la tiene; si no, su primera
        const nombre = elegida?.title.toLowerCase();
        const g = opcionesProyecto(next, peers, sessions, recientes);
        const igual = [...g.carpetas, ...g.usadas].find(o => o.title.toLowerCase() === nombre);
        setPc(next); setProject(igual?.key ?? null); setCwd(""); setError("");
      }}>
        {!peers.length && <option value="">Esta PC</option>}
        {peers.map(p => <option key={p.pc_id} value={p.pc_id} disabled={!p.alive}>{p.name}</option>)}
      </select></label>
      <label>Agente<select aria-label="Agente" disabled={busy} value={agent} onChange={e => setAgent(e.target.value as Agent)}>
        {agentIds.map(id => <option key={id} value={id}>{AGENTS[id].label}</option>)}
      </select></label>
      {distros.length > 0 && <label>Dónde<select aria-label="Distro de WSL" disabled={busy} value={distro} onChange={e => setDistro({ pc, d: e.target.value })}>
        <option value="">Windows</option>
        {distros.map(d => <option key={d} value={d}>WSL · {d}</option>)}
      </select></label>}
      {!elegida?.cwd && <label>Carpeta{elegida && pc ? ` en ${peers.find(p => p.pc_id === pc)?.name || "la PC elegida"}` : ""}<input aria-label="Carpeta" required disabled={busy} value={cwd} onChange={e => setCwd(e.target.value)} /></label>}
      {error && <p role="alert">{error}</p>}
      {unavailable && <p role="alert">La PC elegida no está disponible.</p>}
      <div className="launch-actions"><button type="button" disabled={busy} onClick={onClose}>Cancelar</button>
        <button className="primary" disabled={busy || !directory || unavailable}>{busy ? "Lanzando…" : "Lanzar"}</button></div>
    </form>
  </dialog>;
}
