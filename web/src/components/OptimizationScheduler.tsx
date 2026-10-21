import { useEffect, useRef, useState } from "react";
import { api } from "../api";

interface ResearchCase { case_key: string; area: string; priority?: number; origin?: string }
interface Job {
  id: string; project: string; state: string; cursor: number; reason?: string; results: string[]; automatic?: boolean; source_ids?: string[] | null; source_version?: string | null;
  kind?: string; case?: ResearchCase; attempts?: number; runs?: number[];
  last_run?: { code: number | null; seconds?: number; timed_out?: boolean; stopped?: string | null } | null;
  /** transiciones pedidas a mano (reencolar, descartar), con el motivo que tenía antes */
  history?: { at: number; from: string; to: string; reason?: string | null }[];
}
/** Última evaluación de la política del investigador (optimization_research_policy.evaluate). */
interface ResearchEvaluation {
  enabled: boolean; reasons: string[]; runs_today: number; project?: string; evaluated_at?: number;
  limits: { max_runs_per_day?: number; max_weekly_used_pct?: number; max_seconds?: number };
  adapter?: { name?: string; consumption_bound?: { weekly_used_pct?: number; weekly_max_used_pct?: number; basis?: string } | null };
  authorization?: { autorizado_por?: string; fecha?: string; vence?: string | null } | null;
}
interface Research { last_evaluation: ResearchEvaluation | null; scope?: string; note?: string | null; ceilings?: { max_starts_per_case?: number } }
interface Status {
  research?: Research;
  enabled: boolean; reason: string;
  automatic_scope?: string;
  pilot_enabled?: boolean; paid_enabled?: boolean;
  projects: { id: string; name: string }[];
  jobs: Job[];
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
  const [preview, setPreview] = useState<ResearchCase[] | null>(null);
  const check = async () => {
    setPreview(null);
    const lifecycle = guard.current;
    if (lifecycle.pending) return;
    lifecycle.pending = true;
    const epoch = ++lifecycle.epoch;
    setBusy(true); setError("");
    try {
      const result = await api.put<Status & { research_preview?: ResearchCase[] }>("/agent-improvements/scheduler", { action: "research_check", project });
      if (lifecycle.active && epoch === lifecycle.epoch) { setStatus(result); setPreview(result.research_preview ?? []); }
    } catch (e) { if (lifecycle.active && epoch === lifecycle.epoch) setError((e as Error).message); }
    finally { lifecycle.pending = false; if (lifecycle.active && epoch === lifecycle.epoch) setBusy(false); }
  };
  const evaluation = status?.research?.last_evaluation;
  const weekly = evaluation?.adapter?.consumption_bound?.weekly_used_pct;
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
      {status.research && <div className="mejoras-investigador" aria-label="Investigador Codex">
        <div className="mejoras-titulo"><h4>Investigador Codex</h4>{evaluation && <span className={`chip estado ${evaluation.enabled ? "ok" : "pausa"}`}>{evaluation.enabled ? "habilitado" : "bloqueado"}</span>}</div>
        <p className="small dim">Usa la suscripción de Codex, no el presupuesto en USD de Jev. {status.research.scope}</p>
        {!evaluation && <p className="small">{status.research.note || "Sin evaluar"}: «Revisar investigador» lee la cuota en vivo.</p>}
        {evaluation && <>
          <p className="small">
            {weekly != null ? `Uso semanal ${weekly} %` : "Uso semanal sin leer"}
            {evaluation.limits.max_weekly_used_pct != null ? ` · corre hasta ${evaluation.limits.max_weekly_used_pct} % usado` : ""}
            {` · ejecuciones hoy ${evaluation.runs_today}`}{evaluation.limits.max_runs_per_day != null ? `/${evaluation.limits.max_runs_per_day}` : ""}
            {evaluation.project ? ` · ${evaluation.project}` : ""}
          </p>
          {evaluation.authorization && <p className="small dim">Autorizó {evaluation.authorization.autorizado_por} el {evaluation.authorization.fecha}{evaluation.authorization.vence ? `, vence ${evaluation.authorization.vence}` : ""}.</p>}
          {!!evaluation.reasons.length && <ul aria-label="Motivos de bloqueo" className="small">{evaluation.reasons.map(r => <li key={r}>{r}</li>)}</ul>}
        </>}
        <div className="mejoras-botones">
          <button disabled={busy || !project} onClick={() => void check()}>Revisar investigador</button>
          <button disabled={busy || !project || !evaluation?.enabled} onClick={() => void command({ action: "enqueue_research", project })}>Encolar investigación</button>
        </div>
        {preview && <p className="small">{preview.length ? `Casos candidatos: ${preview.map(c => `${c.area} (${c.case_key})`).join(", ")}` : "Sin casos nuevos para investigar."}</p>}
      </div>}
      <h4>Trabajos <span className="small dim">{status.jobs.length ? `${status.jobs.length} en la lista` : "ninguno en cola"}</span></h4>
      {status.jobs.length > 0 && <ul className="mejoras-trabajos" aria-label="Trabajos">
        {status.jobs.map(job => <li key={job.id} data-estado={job.state}>
          <div className="mejoras-trabajo-cabecera"><strong>{job.project} · {job.state}</strong>{job.kind === "research" && <span className="chip">investigación</span>}<span className="chip">{job.automatic ? "automático" : "solicitado"}</span><span className="chip">{job.results.length} {job.kind === "research" ? "propuestas" : "hipótesis"}</span></div>
          {job.case && <p className="small">Caso {job.case.area} · {job.case.case_key}{job.attempts != null ? ` · intentos ${job.attempts}` : ""}{job.last_run ? ` · última corrida: código ${job.last_run.code ?? "—"}${job.last_run.timed_out ? ", plazo agotado" : ""}${job.last_run.stopped ? `, cortada: ${job.last_run.stopped}` : ""}` : ""}</p>}
          <p className="small">{job.reason || `${job.cursor} fuentes revisadas`}</p>
          {job.kind === "research" && ["queued", "running", "paused"].includes(job.state) && <button disabled={busy} onClick={() => void command({ action: "cancel_research", job: job.id })}>Cancelar investigación</button>}
          {job.kind === "research" && job.state === "review" && <ReviewActions job={job} busy={busy} maxStarts={status.research?.ceilings?.max_starts_per_case} command={command} />}
          {job.results.length > 0 && <p className="small dim">Las hipótesis requieren veredicto humano.</p>}
          {job.source_ids?.length ? <details><summary>Fuentes analizadas</summary><pre>{job.source_ids.join("\n")}</pre><small>Versión: {job.source_version}</small></details> : null}
          {job.results.length > 0 && <details><summary>Referencias en memoria</summary><pre>{job.results.join("\n")}</pre></details>}
        </li>)}
      </ul>}
    </>}
  </section>;
}

/** Un trabajo en revisión no sale solo: el usuario lo revisa y lo reencola (si le quedan inicios y
 *  la política lo habilita; conserva intentos y corridas) o lo descarta (queda en el historial). */
function ReviewActions({ job, busy, maxStarts, command }: {
  job: Job; busy: boolean; maxStarts?: number; command: (data: object) => Promise<void>;
}) {
  const exhausted = maxStarts != null && (job.attempts ?? 0) >= maxStarts;
  return <details className="mejoras-revision">
    <summary>Revisar</summary>
    <p className="small">Intentos {job.attempts ?? 0}{maxStarts != null ? ` de ${maxStarts}` : ""} · corridas {job.runs?.length ?? 0}{job.last_run?.stopped ? ` · último corte: ${job.last_run.stopped}` : ""}</p>
    {!!job.history?.length && <ul className="small" aria-label="Historial de revisión">
      {job.history.map(h => <li key={h.at}>{new Date(h.at * 1000).toLocaleString("es-AR")}: {h.from} → {h.to}{h.reason ? ` (${h.reason})` : ""}</li>)}
    </ul>}
    {exhausted && <p className="small">Intentos agotados: el caso no se puede reencolar. Podés descartarlo.</p>}
    <div className="mejoras-botones">
      <button disabled={busy || exhausted} onClick={() => void command({ action: "requeue_research", job: job.id })}>Reencolar investigación</button>
      <button disabled={busy} onClick={() => {
        if (window.confirm("¿Descartar esta investigación? Queda en el historial y el caso no vuelve solo.")) void command({ action: "dismiss_research", job: job.id });
      }}>Descartar</button>
    </div>
  </details>;
}
