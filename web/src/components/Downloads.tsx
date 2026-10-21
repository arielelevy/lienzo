import { useEffect, useId, useRef, useState } from "react";
import { api, ApiError } from "../api";
import type { Peer } from "../types";
import "../downloads.css";

type File = { id: string; name: string; size: number; modified_ns: number; exists: boolean };
type Preview = { plan: string; source: string; destination: string; files: File[] };
type Job = { id: string; state: string; bytes: number; total: number; error: string | null; files: { name: string; state: string; error?: string }[] };
const size = (bytes: number) => bytes < 1024 ? `${bytes} B` : bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;

export function Downloads({ peer, onClose }: { peer: Peer; onClose: () => void }) {
  const selectionId = useId();
  const [preview, setPreview] = useState<Preview | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");
  const [permission, setPermission] = useState(false);
  const [loading, setLoading] = useState(true);
  const [confirm, setConfirm] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const generation = useRef(0);
  const closeButton = useRef<HTMLButtonElement>(null);
  const load = async () => {
    const id = ++generation.current;
    setLoading(true); setError(""); setPermission(false); setConfirm(false);
    try {
      const data = await api.get<Preview>(`/downloads?pc=${encodeURIComponent(peer.pc_id)}`);
      if (id !== generation.current) return;
      setPreview(data); setSelected(new Set());
    } catch (e) {
      if (id !== generation.current) return;
      setError((e as Error).message);
      setPermission(e instanceof ApiError && Boolean(e.body.needs_permission || e.body.needs_local_permission));
    } finally { if (id === generation.current) setLoading(false); }
  };
  useEffect(() => {
    closeButton.current?.focus();
    const timer = setTimeout(() => void load(), 0);
    return () => { clearTimeout(timer); generation.current = -1; };
    // El componente se monta por pc_id; un cambio de PC invalida respuestas pendientes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [peer.pc_id]);
  useEffect(() => {
    if (!job || !["waiting", "copying"].includes(job.state)) return;
    let disposed = false;
    const timer = setInterval(() => {
      api.get<Job>(`/downloads/jobs/${job.id}`).then(data => { if (!disposed) setJob(data); })
        .catch(e => { if (!disposed) setError((e as Error).message); });
    }, 700);
    return () => { disposed = true; clearInterval(timer); };
  }, [job]);
  const enable = async () => {
    setLoading(true);
    try { await api.post("/downloads/enable", { pc: peer.pc_id }); await load(); }
    catch (e) { setError((e as Error).message); setLoading(false); }
  };
  const bring = async (replace: boolean, skip = false) => {
    if (!preview) return;
    const files = preview.files.filter(file => selected.has(file.id) && (!skip || !file.exists));
    if (!files.length) { setConfirm(false); return; }
    setLoading(true); setError("");
    try {
      const result = await api.post<{ id: string }>("/downloads", {
        plan: preview.plan, files: files.map(file => file.id), replace: replace ? files.filter(file => file.exists).map(file => file.id) : [],
      });
      setConfirm(false);
      setJob(await api.get<Job>(`/downloads/jobs/${result.id}`));
    } catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  };
  const existing = preview?.files.filter(file => selected.has(file.id) && file.exists) ?? [];
  const active = Boolean(job && ["waiting", "copying"].includes(job.state));
  return <div className="downloads-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="downloads-dialog" role="dialog" aria-modal="true" aria-labelledby="downloads-title" onKeyDown={event => {
      if (event.key === "Escape") onClose();
      if (event.key === "Tab") {
        const inputs = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled)'));
        const first = inputs[0], last = inputs[inputs.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    }}>
      <header><h2 id="downloads-title">Traer descargas de {peer.name}</h2><button ref={closeButton} onClick={onClose} aria-label="Cerrar descargas">×</button></header>
      {!job && <p>Los 30 archivos más recientes. Elegí cuáles guardar en esta PC.</p>}
      {preview && <p className="downloads-path">Origen: {preview.source}<br />Guardar en: {preview.destination}</p>}
      {error && <p role="alert" className="downloads-error">{error}</p>}
      {permission && <div><p>Podés habilitar sólo la carpeta Descargas de ambas PCs para transferir estos archivos.</p><button disabled={loading} onClick={() => void enable()}>Habilitar carpeta Descargas</button></div>}
      {loading && <p role="status">Consultando…</p>}
      {!job && preview && <>
        <table><thead><tr><th>Traer</th><th>Archivo</th><th>Fecha</th><th>Tamaño</th><th>En esta PC</th></tr></thead>
          <tbody>{preview.files.map(file => <tr key={file.id}>
            <td><input id={`${selectionId}-${file.id}`} type="checkbox" aria-label={`Traer ${file.name}`} disabled={loading || confirm} checked={selected.has(file.id)} onChange={event => setSelected(current => {
              const next = new Set(current); if (event.target.checked) next.add(file.id); else next.delete(file.id); return next;
            })} /></td>
            <td><label htmlFor={`${selectionId}-${file.id}`}>{file.name}</label></td><td>{new Date(file.modified_ns / 1e6).toLocaleString()}</td><td>{size(file.size)}</td><td>{file.exists ? "Ya existe" : "Nuevo"}</td>
          </tr>)}</tbody>
        </table>
        {!preview.files.length && <p>No hay descargas terminadas para traer.</p>}
        {confirm ? <div className="downloads-confirm" role="alertdialog" aria-label="Confirmar sobrescritura">
          <h3>Estos archivos ya existen en esta PC</h3><ul>{existing.map(file => <li key={file.id}>{file.name}</li>)}</ul>
          <p>¿Querés reemplazarlos por los de {peer.name}?</p>
          <div className="downloads-actions"><button disabled={loading} onClick={() => void bring(true)}>Sobrescribir y traer</button><button disabled={loading} onClick={() => void bring(false, true)}>Saltear existentes</button><button disabled={loading} onClick={() => setConfirm(false)}>Volver</button></div>
        </div> : <footer><button disabled={loading} onClick={() => void load()}>Actualizar lista</button><button disabled={loading || !selected.size} onClick={() => { if (existing.length) setConfirm(true); else void bring(false); }}>Traer seleccionados ({selected.size})</button></footer>}
      </>}
      {job && <div role="status">
        {job.state === "received" && <h3>✓ Transferencia finalizada</h3>}
        <p>{job.state === "received" ? "Archivos recibidos y verificados" : job.state === "error" ? "La transferencia tuvo errores" : "Trayendo archivos…"} · {size(job.bytes)} de {size(job.total)}</p>
        {active && <progress aria-label="Progreso de descarga" max={job.total || 1} value={job.bytes} />}
        <ul>{job.files.map(file => <li key={file.name}>{file.name}: {file.state === "received" ? "recibido" : file.error || "pendiente"}</li>)}</ul>
        {job.error && <p role="alert" className="downloads-error">{job.error}</p>}
        {!active && <footer><button onClick={() => { setJob(null); void load(); }}>Ver descargas otra vez</button><button onClick={onClose}>Cerrar</button></footer>}
        {active && <p>Podés cerrar esta ventana; la transferencia sigue en Lienzo.</p>}
      </div>}
    </section>
  </div>;
}
