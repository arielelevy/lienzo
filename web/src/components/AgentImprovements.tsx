import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { OptimizationScheduler } from "./OptimizationScheduler";

/** Una integración del catálogo (lienzo/tools/): usa un repo o servicio externo. */
interface ToolInfo {
  id: string; nombre: string; tipo: "mejora" | "evaluacion" | "pruebas" | "trabajo"; origen: string; descripcion: string;
  version: string | null; costo: "gratis" | "pago"; modos: string[]; preferencia: "brief" | "rtk" | null; instalar: string | null;
  estado: { disponible: boolean; detalle?: string };
}
interface Settings {
  preferences: { brief: boolean; rtk: boolean };
  tools: ToolInfo[];
  scope: string;
}
const TIPO: Record<ToolInfo["tipo"], string> = { mejora: "mejora", evaluacion: "evaluación", pruebas: "pruebas", trabajo: "trabajo" };
const enlace = (origen: string) => (origen.startsWith("https://") ? <a href={origen} target="_blank" rel="noreferrer">{origen.replace("https://", "")}</a> : <code>{origen}</code>);
interface Evaluation {
  session_id: string; snapshot: string; agent: string; model: string | null; version?: string | null;
  durations?: { turn: string; seconds: number }[];
  usage?: { turn: string; reported: Record<string, unknown> }[];
  usage_note?: string;
  quality: string; note: string | null; jev_available: boolean; jev_max_cost_usd: number;
  paid_block_reason?: string;
  evidence: { counts: { turns: number | null; closed: number | null; tools: number | null; errors: number | null; known_results: number | null; missing_results: number | null }; scope: string; unavailable?: boolean };
  suggestions: { tool: string; action: string; limit: string; evidence: { turn: string; tool: string } }[];
}
interface Judgment {
  session_id: string;
  decision: { choice: string; note: string; model: string; usage: { cost: number }; budget_exceeded: boolean };
}

/** Montado con key por sesión: ninguna respuesta tardía cruza de tarjeta. */
export function AgentImprovements({ sid }: { sid?: string }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [report, setReport] = useState<Evaluation | null>(null);
  const [judgment, setJudgment] = useState<Judgment | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [costAllowed, setCostAllowed] = useState(false);
  const [reload, setReload] = useState(0);
  const lifecycle = useRef({ generation: 0 });
  const pending = useRef(false);
  useEffect(() => {
    const guard = lifecycle.current;
    const token = ++guard.generation;
    const path = sid ? `/sessions/${sid}/improvements` : "/agent-improvements";
    api.get<Settings | Evaluation>(path).then(result => {
      if (token !== guard.generation) return;
      if (sid) setReport(result as Evaluation); else setSettings(result as Settings);
    }).catch(e => { if (token === guard.generation) setError((e as Error).message); });
    return () => { guard.generation++; };
  }, [sid, reload]);
  const save = async (name: "brief" | "rtk", enabled: boolean) => {
    if (pending.current) return;
    pending.current = true;
    const guard = lifecycle.current;
    const token = guard.generation;
    setBusy(true); setError("");
    try {
      const result = await api.put<Settings>("/agent-improvements", { [name]: enabled });
      if (token === guard.generation) setSettings(result);
    } catch (e) { if (token === guard.generation) setError((e as Error).message); }
    finally { pending.current = false; if (token === guard.generation) setBusy(false); }
  };
  const judge = async () => {
    if (!sid || !report || pending.current || !costAllowed) return;
    pending.current = true;
    const guard = lifecycle.current;
    const token = guard.generation;
    setBusy(true); setError("");
    try {
      const result = await api.post<Judgment>(`/sessions/${sid}/improvements/jev`, { snapshot: report.snapshot, allow_cost: true });
      if (token === guard.generation && result.session_id === sid) setJudgment(result);
    } catch (e) { if (token === guard.generation) setError((e as Error).message); }
    finally { pending.current = false; if (token === guard.generation) { setBusy(false); setCostAllowed(false); } }
  };
  return <section className="agent-improvements" aria-label="Mejoras de agentes">
    <button disabled={busy} onClick={() => { setError(""); setSettings(null); setReport(null); setJudgment(null); setCostAllowed(false); setReload(x => x + 1); }}>Actualizar</button>
    {error && <p role="alert">{error}</p>}
    {!error && !settings && !report && <p>Leyendo…</p>}
    {settings && <>
      <p className="small dim">{settings.scope}. Las sesiones abiertas siguen como están.</p>
      <ul className="tools-catalogo" aria-label="Catálogo de tools">
        {settings.tools.map(t => <li key={t.id}>
          {t.preferencia ? <label><input type="checkbox" checked={settings.preferences[t.preferencia]} disabled={busy} onChange={e => void save(t.preferencia as "brief" | "rtk", e.target.checked)} /> <strong>{t.nombre}</strong></label> : <strong>{t.nombre}</strong>}
          {" "}<span className="small dim">{TIPO[t.tipo]}{t.costo === "pago" ? " · paga" : ""}{t.modos.includes("general") ? "" : ` · solo modo ${t.modos.join(", ")}`}</span>
          <p className="small">{t.descripcion}</p>
          <p className="small dim">{enlace(t.origen)}{t.version ? ` · ${t.version}` : ""} · {t.estado.disponible ? "disponible" : "no disponible"}{t.estado.detalle ? ` (${t.estado.detalle})` : ""}{!t.estado.disponible && t.instalar ? ` · instalar: ${t.instalar}` : ""}</p>
        </li>)}
      </ul>
      <p className="small dim">Las mejoras se prenden acá; RTK en WSL se verifica al lanzar. Jev se consulta desde «Mejoras» de una sesión.</p>
      <OptimizationScheduler />
    </>}
    {report && <>
      <p className="small dim">{report.agent} · modelo {report.model ?? "desconocido"} · versión {report.version ?? "desconocida"}</p>
      <p>{report.note || `${report.evidence.counts.turns} turnos · ${report.evidence.counts.tools} herramientas`}</p>
      {!report.evidence.unavailable && <p className="small">{report.evidence.counts.errors} errores explícitos de {report.evidence.counts.known_results} resultados conocidos; {report.evidence.counts.missing_results} sin resultado.</p>}
      <p className="small dim">{report.evidence.scope}. Calidad: {report.quality}.</p>
      {(report.durations || report.usage) && <details><summary>Duraciones y consumo informado</summary><p className="small dim">{report.usage_note}</p><pre>{JSON.stringify({ durations: report.durations, usage: report.usage }, null, 2)}</pre></details>}
      {report.suggestions.map((s, i) => <article key={i}><strong>{s.tool}</strong><p>{s.action}</p><small>{s.limit} · turno {s.evidence.turn} · {s.evidence.tool}</small></article>)}
      {!report.suggestions.length && <p>No hay una sugerencia fundada en esta muestra.</p>}
      <details><summary>Muestra que recibirá Jev</summary><pre>{JSON.stringify(report.evidence, null, 2)}</pre></details>
      <label><input type="checkbox" checked={costAllowed} disabled={busy || !report.jev_available || !report.evidence.counts.tools} onChange={e => setCostAllowed(e.target.checked)} /> Autorizar una consulta paga (cota estimada USD {report.jev_max_cost_usd})</label>
      <button disabled={busy || !costAllowed || !report.jev_available} onClick={() => void judge()}>{busy ? "Consultando…" : "Consultar Jev"}</button>
      {!report.jev_available && <p className="small dim">{report.paid_block_reason || "Sin credencial Jev en la PC dueña de esta sesión."}</p>}
      {judgment && <article><strong>Jev sugiere: {judgment.decision.choice}</strong><p>{judgment.decision.note}</p><small>{judgment.decision.model} · USD {judgment.decision.usage.cost}</small>{judgment.decision.budget_exceeded && <p role="alert">El proveedor informó un costo superior a la cota; revisar antes de otra consulta.</p>}</article>}
    </>}
  </section>;
}
