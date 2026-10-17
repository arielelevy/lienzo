import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { OptimizationScheduler } from "./OptimizationScheduler";

/** Una integración del catálogo (lienzo/tools/): usa un repo o servicio externo. */
interface ToolInfo {
  id: string; nombre: string; tipo: "mejora" | "evaluacion" | "pruebas" | "trabajo" | "documentacion"; origen: string; descripcion: string;
  version: string | null; costo: "gratis" | "pago"; modos: string[]; preferencia: "brief" | "rtk" | null; instalar: string | null;
  estado: { disponible: boolean; detalle?: string; version_instalada?: string | null };
  formato?: "tool" | "skill" | "plugin-claude";
  compatible_con?: string[];
  limitaciones?: string[];
}
type Permiso = "lectura" | "escritura" | "ejecucion" | "red" | "efectos_externos";
interface PluginHealth { ok: boolean; detalle: string; conectado: boolean | null; ts: number }
/** Ficha de plugins.resumen(). Los campos opcionales faltan en un backend anterior al manifiesto. */
interface LocalPlugin {
  id: string; nombre: string; origen: string; cargado: boolean; capacidades: string[]; detalle: string;
  version?: string | null; descripcion?: string | null; url?: string | null;
  manifiesto?: "valido" | "ausente" | "invalido";
  estado?: "cargado" | "declarado" | "sin-configurar" | "deshabilitado" | "incompatible" | "error";
  puntos?: string[]; ciclo_de_vida?: string[];
  permisos?: Record<Permiso, string[]> | null;
  configuracion?: { completa: boolean; faltan: string[]; errores: string[] } | null;
  relaciones?: { tools: string[]; sistemas: string[] };
  errores?: string[]; advertencias?: string[];
  salud?: PluginHealth | null;
}
interface Settings {
  preferences: { brief: boolean; rtk: boolean };
  tools: ToolInfo[];
  plugins?: LocalPlugin[];
  scope: string;
}
const TIPO: Record<ToolInfo["tipo"], string> = { mejora: "mejora", evaluacion: "evaluación", pruebas: "pruebas", trabajo: "trabajo", documentacion: "documentación" };
const PERMISO: Record<Permiso, string> = { lectura: "lectura", escritura: "escritura", ejecucion: "ejecución", red: "red", efectos_externos: "efectos externos" };
const ESTADO_PLUGIN: Record<NonNullable<LocalPlugin["estado"]>, [string, string]> = {
  cargado: ["cargado", ""], declarado: ["declarado", ""], "sin-configurar": ["sin configurar", " pausa"],
  deshabilitado: ["deshabilitado", " pausa"], incompatible: ["incompatible", " falta"], error: ["con error", " falta"],
};
const CAPACIDAD: Record<string, string> = { integracion: "integración", "forma-de-trabajo": "forma de trabajo", tools: "tools", documentacion: "documentación", evaluacion: "evaluación" };
const PUNTO: Record<string, string> = { get: "lectura HTTP", post: "acciones HTTP", runners_externos: "procesos externos", vista: "vista", iniciar: "inicio", salud: "salud", detener: "parada" };
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
  const actualizar = () => { setError(""); setSettings(null); setReport(null); setJudgment(null); setCostAllowed(false); setReload(x => x + 1); };
  if (!sid) return <div className="mejoras-vista-cuerpo">
    <section className="agent-improvements mejoras-catalogo" aria-label="Mejoras de agentes">
      <div className="mejoras-seccion-cabecera">
        <div>
          <h3>Integraciones</h3>
          <p className="small dim">{settings ? `${settings.scope}. Las sesiones abiertas siguen como están.` : "Las preferencias valen para los próximos lanzamientos de esta PC."}</p>
        </div>
        <button disabled={busy} onClick={actualizar}>Actualizar</button>
      </div>
      {error && <p role="alert">{error}</p>}
      {!error && !settings && <p>Leyendo…</p>}
      {settings && <>
        <ul className="tools-catalogo" aria-label="Catálogo de tools">
          {settings.tools.map(t => <li key={t.id} className={`tool-card${t.preferencia ? " con-preferencia" : ""}${t.preferencia && settings.preferences[t.preferencia] ? " prendida" : ""}`}>
            <div className="tool-card-cabecera">
              {t.preferencia
                ? <label className="tool-switch"><input type="checkbox" role="switch" className="oculto-visual" aria-describedby={`estado-${t.id}`} checked={settings.preferences[t.preferencia]} disabled={busy} onChange={e => void save(t.preferencia as "brief" | "rtk", e.target.checked)} /><span className={`switch${settings.preferences[t.preferencia] ? " on" : ""}`} aria-hidden="true" /><strong>{t.nombre}</strong></label>
                : <strong>{t.nombre}</strong>}
              <span id={`estado-${t.id}`} className={`chip estado ${t.estado.disponible ? "ok" : "falta"}`}>{t.estado.disponible ? "disponible" : "no disponible"}</span>
            </div>
            <div className="tool-chips">
              <span className="chip">{TIPO[t.tipo]}</span>
              {t.formato === "plugin-claude" && <span className="chip">plugin de Claude Code</span>}
              {t.formato === "skill" && <span className="chip">skill</span>}
              {!!t.compatible_con?.length && <span className="chip">{t.compatible_con.join(", ")}</span>}
              <span className={`chip${t.costo === "pago" ? " paga" : ""}`}>{t.costo === "pago" ? "paga" : "gratis"}</span>
              {!t.modos.includes("general") && <span className="chip">solo modo {t.modos.join(", ")}</span>}
              {t.preferencia && <span className="chip">al lanzar</span>}
            </div>
            <p className="small">{t.descripcion}</p>
            {!!t.limitaciones?.length && <ul aria-label={`Límites de ${t.nombre}`} className="small">{t.limitaciones.map(limit => <li key={limit}>{limit}</li>)}</ul>}
            <p className="small dim tool-origen">{enlace(t.origen)}{t.version ? ` · ${t.version}` : ""}{t.estado.version_instalada ? ` · instalada ${t.estado.version_instalada}` : ""}{t.estado.detalle ? ` · ${t.estado.detalle}` : ""}</p>
            {!t.estado.disponible && t.instalar && <p className="small tool-instalar">Instalar: <code>{t.instalar}</code></p>}
          </li>)}
        </ul>
        {!!settings.plugins?.length && <section aria-label="Plugins locales de Lienzo">
          <h4>Plugins locales de Lienzo</h4>
          <p className="small dim">Integraciones y formas de trabajo. Pueden funcionar sin aportar tools.</p>
          <ul className="tools-catalogo">{settings.plugins.map(plugin => <PluginCard key={plugin.id} plugin={plugin} />)}</ul>
        </section>}
        <p className="small dim">RTK en WSL se verifica al lanzar. Jev se consulta desde «Mejoras» de una sesión.</p>
      </>}
    </section>
    <OptimizationScheduler />
  </div>;
  return <section className="agent-improvements" aria-label="Mejoras de agentes">
    <button disabled={busy} onClick={actualizar}>Actualizar</button>
    {error && <p role="alert">{error}</p>}
    {!error && !report && <p>Leyendo…</p>}
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

/** Ficha de un plugin local. La salud se consulta solo a pedido: cargado no es conectado ni sano. */
function PluginCard({ plugin }: { plugin: LocalPlugin }) {
  const [checked, setChecked] = useState<PluginHealth | null>(null);
  // la más nueva entre la que trajo el inventario (un «Actualizar») y la pedida desde esta ficha
  const health = [plugin.salud, checked].reduce<PluginHealth | null>((a, b) => (b && (!a || b.ts >= a.ts) ? b : a), null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  const [label, tone] = (plugin.estado && ESTADO_PLUGIN[plugin.estado]) || [plugin.estado ?? (plugin.cargado ? "cargado" : "no cargado"), ""];
  const mechanisms = [...(plugin.puntos ?? []), ...(plugin.ciclo_de_vida ?? [])].map(p => PUNTO[p] ?? p);
  const permits = plugin.permisos ? (Object.keys(PERMISO) as Permiso[]).filter(k => plugin.permisos![k]?.length) : [];
  const check = async () => {
    setChecking(true); setError("");
    try { setChecked((await api.get<{ salud: PluginHealth }>(`/ext/${encodeURIComponent(plugin.id)}/_salud`)).salud); }
    catch (e) { setError((e as Error).message); }
    finally { setChecking(false); }
  };
  return <li className="tool-card" aria-label={`Plugin ${plugin.nombre}`}>
    <div className="tool-card-cabecera"><strong>{plugin.nombre}</strong><span className={`chip estado${tone}`}>{label}</span></div>
    <div className="tool-chips">
      {plugin.capacidades.map(c => <span key={c} className="chip">{CAPACIDAD[c] ?? c}</span>)}
      {plugin.manifiesto === "ausente" && <span className="chip">sin manifiesto</span>}
      {plugin.manifiesto === "invalido" && <span className="chip estado falta">manifiesto inválido</span>}
      {health && <span className={`chip estado ${!health.ok ? "falta" : health.conectado === false ? "pausa" : "ok"}`}>{!health.ok ? "comprobación fallida" : health.conectado === false ? "sin conexión" : health.conectado ? "conectado" : "sano"}</span>}
    </div>
    {plugin.descripcion && <p className="small">{plugin.descripcion}</p>}
    <p className="small">{plugin.detalle}</p>
    {!!plugin.errores?.length && <ul aria-label={`Errores de ${plugin.nombre}`} className="small">{plugin.errores.map(e => <li key={e}>{e}</li>)}</ul>}
    {plugin.configuracion && !plugin.configuracion.completa && <p className="small">Configuración: {[...plugin.configuracion.faltan.map(f => `falta ${f}`), ...plugin.configuracion.errores].join("; ")}</p>}
    {plugin.permisos === null && <p className="small dim">Permisos no declarados.</p>}
    {plugin.permisos && <p className="small dim">{permits.length
      ? <>Permisos declarados, no aplicados por Lienzo: {permits.map(k => `${PERMISO[k]} (${plugin.permisos![k].join(", ")})`).join("; ")}</>
      : "No declara permisos ni efectos externos."}</p>}
    {!!plugin.advertencias?.length && <p className="small dim">{plugin.advertencias.join(" · ")}</p>}
    <p className="small dim">Origen: {plugin.url ? enlace(plugin.url) : plugin.origen}{plugin.version ? ` · ${plugin.version}` : ""}{mechanisms.length ? ` · ${mechanisms.join(", ")}` : ""}</p>
    {health && <p className="small">Salud: {health.detalle || (health.ok ? "sin detalle" : "sin motivo")}</p>}
    {plugin.cargado && plugin.ciclo_de_vida?.includes("salud") && <button disabled={checking} onClick={() => void check()}>{checking ? "Comprobando…" : "Comprobar salud"}</button>}
    {error && <p role="alert">{error}</p>}
  </li>;
}
