import { useEffect, useRef, useState } from "react";
import { api } from "../api";

interface Status {
  enabled: boolean; reason: string;
  automatic_scope?: string;
  pilot_enabled?: boolean; paid_enabled?: boolean;
  projects: { id: string; name: string }[];
  jobs: { id: string; project: string; state: string; cursor: number; reason?: string; results: string[]; automatic?: boolean; source_ids?: string[] | null; source_version?: string | null }[];
  budget?: { limit_usd?: string; spent_usd?: string; reserved_usd?: string; available_usd: string; unknown_charges?: number; unbounded_charges?: number; blocked: boolean; reason?: string; pilot?: { deadline: number; attempts: number; maximum_calls: number; cooldown_seconds: number; within_window: boolean } | null };
}

export function useOptimizationActivity(enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;
    let last = 0;
    let warned = false;
    const activity = () => {
      if (Date.now() - last < 5000) return;
      last = Date.now();
      void api.put("/agent-improvements/scheduler", { action: "activity" }).catch(e => {
        if (!warned) { console.warn("No se pudo avisar actividad al scheduler", e); warned = true; }
      });
    };
    const events = ["pointerdown", "pointermove", "keydown", "wheel"];
    for (const event of events) window.addEventListener(event, activity, { passive: true });
    activity();
    return () => { for (const event of events) window.removeEventListener(event, activity); };
  }, [enabled]);
}

export function OptimizationScheduler() {
  const [status, setStatus] = useState<Status | null>(null);
  const [project, setProject] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const guard = useRef({ epoch: 0, active: true, pending: false });
  useEffect(() => {
    const lifecycle = guard.current;
    lifecycle.active = true;
    const read = () => {
      if (lifecycle.pending) return;
      const epoch = ++lifecycle.epoch;
      void api.get<Status>("/agent-improvements/scheduler").then(data => {
        if (lifecycle.active && epoch === lifecycle.epoch) { setStatus(data); setError(""); }
      }).catch(e => { if (lifecycle.active && epoch === lifecycle.epoch) setError((e as Error).message); });
    };
    void read();
    const timer = window.setInterval(() => void read(), 5000);
    return () => { lifecycle.active = false; lifecycle.epoch++; window.clearInterval(timer); };
  }, []);
  const command = async (data: object) => {
    const lifecycle = guard.current;
    if (lifecycle.pending) return;
    lifecycle.pending = true;
    const epoch = ++lifecycle.epoch;
    setBusy(true); setError("");
    try { const result = await api.put<Status>("/agent-improvements/scheduler", data); if (lifecycle.active && epoch === lifecycle.epoch) setStatus(result); }
    catch (e) { if (lifecycle.active && epoch === lifecycle.epoch) setError((e as Error).message); }
    finally { lifecycle.pending = false; if (lifecycle.active && epoch === lifecycle.epoch) setBusy(false); }
  };
  return <section aria-label="Aprendizaje en segundo plano">
    <h3>Aprendizaje en segundo plano</h3>
    <p className="small dim">{status?.pilot_enabled ? "Piloto Jev de métricas con llamadas pagas acotadas; requiere quietud y recursos. Sin agentes nuevos." : "Análisis local en quietud. Piloto Jev sin habilitar; sin llamadas pagas."}</p>
    {error && <p role="alert">{error}</p>}
    {status && <>
      <p>{status.reason}</p>
      {status.automatic_scope && <p className="small dim">{status.automatic_scope}. Las hipótesis requieren veredicto humano.</p>}
      {status.budget && <p className="small">Presupuesto total USD {status.budget.limit_usd ?? "en otra PC"} · confirmado {status.budget.spent_usd ?? "desconocido"} · reservado {status.budget.reserved_usd ?? "desconocido"} · disponible {status.budget.available_usd}. {status.budget.blocked && (status.budget.reason || "Cargos previos sin conciliar; pagos bloqueados.")}</p>}
      {!!status.budget?.unknown_charges && <p className="small">Histórico de costo real desconocido: {status.budget.unknown_charges} cargo(s). Su cota permanece reservada; no se imputa cero.</p>}
      {status.budget?.pilot && <>
        <p className="small">Piloto {status.budget.pilot.within_window ? "habilitado" : "vencido"} · vence {new Date(status.budget.pilot.deadline * 1000).toLocaleString("es-AR")} · intentos {status.budget.pilot.attempts}/{status.budget.pilot.maximum_calls} · cooldown {status.budget.pilot.cooldown_seconds / 60} min.</p>
        <p className="small">{status.paid_enabled ? "Apto ahora; precio y muestra se revalidan antes de enviar." : "Sin envío automático ahora: revisar quietud, pausa, precio, cooldown, topes y presupuesto."} Confianza del modelo no mide acierto; perfil existente desconocido sin evidencia de lanzamiento.</p>
      </>}
      <button disabled={busy} onClick={() => void command({ action: "configure", enabled: !status.enabled })}>{status.enabled ? "Pausar aprendizaje" : "Habilitar aprendizaje"}</button>
      <label>Proyecto para analizar<select value={project} onChange={e => setProject(e.target.value)}><option value="">Elegí un proyecto</option>{status.projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
      <button disabled={busy || !project} onClick={() => void command({ action: "enqueue", project })}>Encolar análisis local</button>
      <button disabled={busy || !project} onClick={() => void command({ action: "enqueue_off_on", project })}>Comparar RTK cuando esté libre</button>
      {status.jobs.map(job => <article key={job.id}><strong>{job.project} · {job.state}</strong><p>{job.reason || `${job.cursor} fuentes revisadas`}</p><p className="small dim">{job.automatic ? "Análisis automático de evidencia nueva" : "Análisis solicitado"}. Hipótesis propuestas: {job.results.length}; requieren veredicto humano.</p>{job.source_ids?.length ? <details><summary>Fuentes analizadas</summary><pre>{job.source_ids.join("\n")}</pre><small>Versión: {job.source_version}</small></details> : null}{job.results.length > 0 && <details><summary>Referencias en memoria</summary><pre>{job.results.join("\n")}</pre></details>}</article>)}
    </>}
  </section>;
}
