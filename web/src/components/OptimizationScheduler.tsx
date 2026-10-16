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
  const budget = status?.budget;
  return <section className="mejoras-scheduler" aria-label="Aprendizaje en segundo plano">
    <div className="mejoras-seccion-cabecera">
      <div>
        <div className="mejoras-titulo"><h3>Aprendizaje en segundo plano</h3>{status && <span className={`chip estado ${status.enabled ? "ok" : "pausa"}`}>{status.enabled ? "habilitado" : "pausado"}</span>}</div>
        <p className="small dim">{status?.pilot_enabled ? "Piloto Jev de métricas con llamadas pagas acotadas; requiere quietud y recursos. Sin agentes nuevos." : "Análisis local en quietud. Piloto Jev sin habilitar; sin llamadas pagas."}</p>
      </div>
      {status && <button disabled={busy} onClick={() => void command({ action: "configure", enabled: !status.enabled })}>{status.enabled ? "Pausar aprendizaje" : "Habilitar aprendizaje"}</button>}
    </div>
    {error && <p role="alert">{error}</p>}
    {!status && !error && <p>Leyendo…</p>}
    {status && <>
      <div className="mejoras-estado">
        <span className="small dim">Ahora</span>
        <p className="mejoras-razon">{status.reason}</p>
        {status.automatic_scope && <p className="small dim">{status.automatic_scope}. Las hipótesis requieren veredicto humano.</p>}
      </div>
      {budget && <>
        <div className="mejoras-presupuesto" aria-label="Presupuesto">
          <div className="kpi"><span className="small dim">Presupuesto total</span> <strong>USD {budget.limit_usd ?? "en otra PC"}</strong></div>
          <div className="kpi"><span className="small dim">Confirmado</span><strong>USD {budget.spent_usd ?? "desconocido"}</strong></div>
          <div className="kpi"><span className="small dim">Reservado</span><strong>USD {budget.reserved_usd ?? "desconocido"}</strong></div>
          <div className={`kpi${budget.blocked ? " bloqueado" : ""}`}><span className="small dim">Disponible</span><strong>USD {budget.available_usd}</strong></div>
        </div>
        {budget.blocked && <p className="mejoras-aviso">{budget.reason || "Cargos previos sin conciliar; pagos bloqueados."}</p>}
        {!!budget.unknown_charges && <p className="small">Histórico de costo real desconocido: {budget.unknown_charges} cargo(s). Su cota permanece reservada; no se imputa cero.</p>}
        {budget.pilot && <div className="mejoras-piloto">
          <p className="small">Piloto {budget.pilot.within_window ? "habilitado" : "vencido"} · vence {new Date(budget.pilot.deadline * 1000).toLocaleString("es-AR")} · intentos {budget.pilot.attempts}/{budget.pilot.maximum_calls} · cooldown {budget.pilot.cooldown_seconds / 60} min.</p>
          <p className="small">{status.paid_enabled ? "Apto ahora; precio y muestra se revalidan antes de enviar." : "Sin envío automático ahora: revisar quietud, pausa, precio, cooldown, topes y presupuesto."} Confianza del modelo no mide acierto; perfil existente desconocido sin evidencia de lanzamiento.</p>
        </div>}
      </>}
      <div className="mejoras-acciones">
        <label>Proyecto para analizar<select value={project} onChange={e => setProject(e.target.value)}><option value="">Elegí un proyecto</option>{status.projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        <div className="mejoras-botones">
          <button disabled={busy || !project} onClick={() => void command({ action: "enqueue", project })}>Encolar análisis local</button>
          <button disabled={busy || !project} onClick={() => void command({ action: "enqueue_off_on", project })}>Comparar RTK cuando esté libre</button>
        </div>
      </div>
      <h4>Trabajos <span className="small dim">{status.jobs.length ? `${status.jobs.length} en la lista` : "ninguno en cola"}</span></h4>
      {status.jobs.length > 0 && <ul className="mejoras-trabajos" aria-label="Trabajos">
        {status.jobs.map(job => <li key={job.id} data-estado={job.state}>
          <div className="mejoras-trabajo-cabecera"><strong>{job.project} · {job.state}</strong><span className="chip">{job.automatic ? "automático" : "solicitado"}</span><span className="chip">{job.results.length} hipótesis</span></div>
          <p className="small">{job.reason || `${job.cursor} fuentes revisadas`}</p>
          {job.results.length > 0 && <p className="small dim">Las hipótesis requieren veredicto humano.</p>}
          {job.source_ids?.length ? <details><summary>Fuentes analizadas</summary><pre>{job.source_ids.join("\n")}</pre><small>Versión: {job.source_version}</small></details> : null}
          {job.results.length > 0 && <details><summary>Referencias en memoria</summary><pre>{job.results.join("\n")}</pre></details>}
        </li>)}
      </ul>}
    </>}
  </section>;
}
