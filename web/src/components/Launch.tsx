import { useRef, useState } from "react";
import { api } from "../api";
import { AGENTS, agentIds, type Agent } from "../agents";
import type { Peer, Session } from "../types";

export function Launch({ peers, sessions, onClose, toast }: {
  peers: Peer[]; sessions: Session[]; onClose: () => void; toast?: (text: string, error?: boolean) => void;
}) {
  const [pc, setPc] = useState(peers.find(p => p.local)?.pc_id ?? "");
  const [cwd, setCwd] = useState("");
  const [project, setProject] = useState(() => {
    const local = peers.find(p => p.local)?.pc_id;
    const first = sessions.find(s => s.alive && !s.stopped_by && s.cwd && (!s.pc || s.pc === local));
    return first ? first.repo_key || first.repo || first.cwd! : "";
  });
  const [agent, setAgent] = useState<Agent>("codex");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const sending = useRef(false);
  const localPc = peers.find(p => p.local)?.pc_id ?? "";
  const active = sessions.filter(s => s.alive && !s.stopped_by && s.cwd);
  const projectKey = (s: Session) => s.repo_key || s.repo || s.cwd!;
  const projects = [...new Map(active.map(s => [projectKey(s), s.repo || s.cwd!] as const))];
  const source = active.find(s => projectKey(s) === project && (s.pc || localPc) === pc);
  const directory = project ? source?.cwd ?? "" : cwd.trim();
  const unavailable = !!pc && !peers.some(p => p.pc_id === pc && p.alive);
  const launch = async () => {
    if (sending.current || !directory || unavailable) return;
    sending.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await api.post<{ ok: boolean; error?: string }>("/sessions/launch", {
        cwd: directory, title: project ? source?.repo || "" : "", agent, ...(pc ? { pc } : {}),
      });
      if (!result.ok) throw new Error(result.error || "No se pudo lanzar la CLI");
      toast?.("CLI lanzada");
      onClose();
    } catch (e) { setError((e as Error).message); }
    finally { sending.current = false; setBusy(false); }
  };
  return <dialog ref={element => { if (element && !element.open) element.showModal(); }}
    className="gate-box launch-box" aria-label="Lanzar CLI" onKeyDown={e => e.stopPropagation()}
    onCancel={e => { e.preventDefault(); if (!busy) onClose(); }}>
    <form onSubmit={e => { e.preventDefault(); void launch(); }}>
      <div className="launch-heading"><h2>Lanzar CLI</h2><button type="button" className="icon" aria-label="Cerrar lanzamiento" disabled={busy} onClick={onClose}>×</button></div>
      <label>Proyecto<select autoFocus aria-label="Proyecto" disabled={busy} value={project} onChange={e => {
        const next = e.target.value;
        setProject(next); setError("");
        if (next && !active.some(s => projectKey(s) === next && (s.pc || localPc) === pc)) {
          const first = active.find(s => projectKey(s) === next && peers.some(p => p.pc_id === (s.pc || localPc) && p.alive));
          if (first) setPc(first.pc || localPc);
        }
      }}>
        <option value="">{projects.length ? "Otra carpeta…" : "Nueva carpeta"}</option>
        {projects.map(([key, name]) => <option key={key} value={key}>{name}</option>)}
      </select></label>
      <label>PC<select aria-label="PC" disabled={busy} value={pc} onChange={e => setPc(e.target.value)}>
        {!peers.length && <option value="">Esta PC</option>}
        {peers.map(p => <option key={p.pc_id} value={p.pc_id} disabled={!p.alive || (!!project && !active.some(s => projectKey(s) === project && (s.pc || localPc) === p.pc_id))}>{p.name}</option>)}
      </select></label>
      <label>Agente<select aria-label="Agente" disabled={busy} value={agent} onChange={e => setAgent(e.target.value as Agent)}>
        {agentIds.map(id => <option key={id} value={id}>{AGENTS[id].label}</option>)}
      </select></label>
      {!project && <label>Carpeta<input aria-label="Carpeta" required disabled={busy} value={cwd} onChange={e => setCwd(e.target.value)} /></label>}
      {error && <p role="alert">{error}</p>}
      {unavailable && <p role="alert">La PC elegida no está disponible.</p>}
      <div className="launch-actions"><button type="button" disabled={busy} onClick={onClose}>Cancelar</button>
        <button className="primary" disabled={busy || !directory || unavailable}>{busy ? "Lanzando…" : "Lanzar"}</button></div>
    </form>
  </dialog>;
}
