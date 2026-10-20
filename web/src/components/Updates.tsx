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

// sólo las fases de una actualización en curso: sin novedades no hay ventana ni etiqueta
const PHASE: Record<string, string> = {
  preparing: "Preparando actualización…", building: "Compilando la interfaz…",
  applying: "Aplicando actualización…", restarting: "Reconectando…",
};

export function Updates({ peers, onClose, initialPc = "", target }: { peers: Peer[]; onClose: () => void; initialPc?: string; target?: string }) {
  const { data, error } = useUpdateStatus(initialPc, true, 0, 1000);
  const [failure, setFailure] = useState(target ? "" : "No hay una versión pendiente para actualizar.");
  const [accepted, setAccepted] = useState(false);
  const started = useRef(false);
  // el estado leído antes de aceptar puede traer el error de un intento anterior: sólo cuenta uno nuevo
  const latest = useRef(data);
  const [stale, setStale] = useState<UpdateStatus>();
  useEffect(() => { latest.current = data; }, [data]);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { dialog.current?.showModal(); }, []);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    if (!target) return;
    void api.get<UpdateStatus>(`/updates${initialPc ? `?pc=${encodeURIComponent(initialPc)}` : ""}`).then(current => {
      if (current.target === target && (current.busy || current.running === target)) return;
      return api.post("/updates/apply", { pc: initialPc || undefined, target });
    }).then(() => { setStale(latest.current); setAccepted(true); })
      .catch(problem => setFailure(updateError(problem)));
  }, [initialPc, target]);
  const fresh = accepted && data !== stale ? data : undefined;
  const done = !!fresh && fresh.running === target && !fresh.busy && !fresh.error;
  const pcName = peers.find(peer => peer.pc_id === initialPc)?.name ?? "Esta PC";
  const failed = failure || fresh?.error;
  return createPortal(<dialog ref={dialog} className="updates-dialog" aria-label="Actualizaciones" onCancel={onClose}>
    <div className="updates-heading"><h2>Actualizando {pcName}</h2><button onClick={onClose} aria-label="Cerrar actualizaciones">✕</button></div>
    <p role="status">{failed ? "No se pudo actualizar" : done ? "Actualización aplicada" : error && accepted ? "Reconectando…" : fresh && Object.hasOwn(PHASE, fresh.phase) ? PHASE[fresh.phase] : "Iniciando actualización…"}</p>
    {!done && !failed && <progress aria-label="Progreso de actualización" />}
    {failed && <p role="alert">{failed}</p>}
    {error && !accepted && !failure && <p role="alert">{error}</p>}
    {done && <p>Las terminales siguen abiertas.</p>}
    <button onClick={onClose}>Cerrar</button>
  </dialog>, document.body);
}
