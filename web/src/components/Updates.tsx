import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, ApiError } from "../api";
import type { Peer } from "../types";
import "./Updates.css";

export interface UpdateStatus {
  phase: string; available: boolean; busy: boolean; running: string; target?: string;
  head?: string; version?: string; checked_at: number | null; blocked?: string;
  error?: string; message?: string; changes: string[];
}

export function updateError(error: unknown) {
  return error instanceof ApiError && error.status === 404
    ? "Esta PC todavía no tiene el actualizador. Necesita una primera actualización desde su terminal."
    : error instanceof Error ? error.message : "No se pudo consultar la actualización";
}

/** El GET sólo lee caché: buscar Git ocurre en el servidor, nunca por cada render. */
export function useUpdateStatus(pc = "", enabled = true, revision = 0, intervalMs = 30000) {
  const [state, setState] = useState<{ pc: string; data?: UpdateStatus; error?: string }>({ pc });
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let busy = false;
    const read = async () => {
      if (busy) return;
      busy = true;
      try {
        const data = await api.get<UpdateStatus>(`/updates${pc ? `?pc=${encodeURIComponent(pc)}` : ""}`, { signal: controller.signal });
        if (!Array.isArray(data.changes) || typeof data.phase !== "string" || typeof data.available !== "boolean") throw new Error("El actualizador devolvió datos inválidos");
        if (!controller.signal.aborted) setState({ pc, data });
      } catch (error) {
        if (!controller.signal.aborted) setState(previous => ({ pc, data: previous.pc === pc ? previous.data : undefined, error: updateError(error) }));
      } finally { busy = false; }
    };
    void read();
    const timer = window.setInterval(() => void read(), intervalMs);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [pc, enabled, revision, intervalMs]);
  return state.pc === pc ? state : { pc };
}

const PHASE: Record<string, string> = {
  idle: "Sin consultar", checking: "Buscando novedades…", available: "Actualización disponible",
  current: "Al día", preparing: "Preparando actualización…", building: "Compilando la interfaz…",
  applying: "Aplicando actualización…", restarting: "Reconectando…", applied: "Actualización aplicada", error: "La actualización no pudo terminar",
};

export function Updates({ peers, onClose }: { peers: Peer[]; onClose: () => void }) {
  const [pc, setPc] = useState("");
  const [revision, setRevision] = useState(0);
  const [action, setAction] = useState<{ pc: string; error?: string; busy?: boolean }>({ pc: "" });
  const { data, error } = useUpdateStatus(pc, true, revision, 3000);
  const dialog = useRef<HTMLDialogElement>(null);
  const selected = useRef(pc);
  useEffect(() => { selected.current = pc; }, [pc]);
  useEffect(() => { dialog.current?.showModal(); }, []);
  const submit = async (kind: "check" | "apply") => {
    const targetPc = pc;
    setAction({ pc, busy: true });
    try {
      await api.post(`/updates/${kind}`, { pc: pc || undefined, target: kind === "apply" ? data?.target : undefined });
      if (selected.current === targetPc) setRevision(value => value + 1);
    } catch (failure) {
      if (selected.current === targetPc) setAction({ pc, error: updateError(failure) });
      return;
    }
    if (selected.current === targetPc) setAction({ pc });
  };
  const ownAction: { error?: string; busy?: boolean } = action.pc === pc ? action : {};
  const busy = data?.busy || ownAction.busy;
  return createPortal(<dialog ref={dialog} className="updates-dialog" aria-label="Actualizaciones" onCancel={onClose}>
    <div className="updates-heading"><h2>Actualizaciones</h2><button onClick={onClose} aria-label="Cerrar actualizaciones">✕</button></div>
    <label>PC <select aria-label="PC a actualizar" value={pc} onChange={event => setPc(event.target.value)}>
      <option value="">Esta PC</option>{peers.filter(peer => !peer.local).map(peer => <option key={peer.pc_id} value={peer.pc_id} disabled={!peer.alive}>{peer.name}{peer.alive ? "" : " · sin conexión"}</option>)}
    </select></label>
    <p role="status">{data ? PHASE[data.phase] ?? data.phase : "Consultando…"}</p>
    {data && <>
      <dl><dt>En ejecución</dt><dd>{data.running?.slice(0, 8)}</dd><dt>Disponible en Git</dt><dd>{data.version ? `v${data.version}` : "Sin consultar"} {data.target?.slice(0, 8)}</dd></dl>
      {data.checked_at && <p className="small dim">Consultado {new Date(data.checked_at * 1000).toLocaleString()}</p>}
      {data.message && <p>{data.message}</p>}
      {data.blocked && <p className="updates-notice">{data.blocked}</p>}
      <h3>Qué cambió</h3>{data.changes.length ? <ul>{data.changes.map(change => <li key={change}>{change}</li>)}</ul> : <p>No hay novedades registradas en esta consulta.</p>}
    </>}
    {(error || ownAction.error || data?.error) && <p role="alert">{ownAction.error || error || data?.error}</p>}
    <p className="small dim">Se prepara y compila antes de aplicar. Lienzo reconecta automáticamente; las terminales siguen abiertas.</p>
    <div className="updates-actions"><button disabled={busy} onClick={() => void submit("check")}>Buscar novedades</button><button className="primary" disabled={!data?.available || !!data.blocked || busy || !!error} onClick={() => void submit("apply")}>Actualizar {pc ? "PC elegida" : "esta PC"}</button></div>
  </dialog>, document.body);
}
