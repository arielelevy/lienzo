import { useEffect, useId, useRef, useState } from "react";
import { api, failMsg } from "../api";

/** Aprendizaje del proyecto en una vista: lo que aplica al contexto, por qué lo demás no aplica,
 *  lo que espera veredicto y los patrones. Leer no cambia nada; veredicto y uso son acciones
 *  explícitas de una persona con nombre, y después se vuelve a leer. */
type Usos = { sirvio: number; no_aplico: number; ya_sabido: number };
interface Item {
  creencia: string; texto: string; accion: string; estado: string; motivo: string;
  evidencia: string | null; excepciones: string; vigente_hasta: string | null;
  contexto: Record<string, string>; usos: Usos; revisar: boolean; cadenas?: { id: string; texto: string }[][];
}
interface Checklist { total: number; items: Item[]; no_aplican_total: number; no_aplican: Item[] }
interface Belief { id: string; texto: string; estado: string; datos: { accion?: string; contexto?: Record<string, string>; fuentes?: string[]; excepciones?: string } }
interface Evidence { id: string; texto: string }
interface Pattern { contexto: Record<string, string>; encargos: number; fuentes: string[]; controles_declarados: Record<string, number>; controles_evidencia: { ejecutados?: unknown[]; verificados?: unknown[] }[] }
interface Patterns { revisados: number; sin_clasificar: number; muestra_parcial: boolean; patrones: Pattern[] }
interface Data { checklist: Checklist; pending: Belief[]; evidence: Evidence[]; patterns: Patterns }
interface Reasoning { motor: string; snapshot: string; conclusiones: { id: string; status: string; chains: string[][] }[]; diferencias: { id: string; python: string; prolog: string }[] }

export const CONTEXT = [
  ["tipo_trabajo", "Tipo de trabajo"], ["tecnologia", "Tecnología"], ["area", "Área"], ["fase", "Fase"],
  ["agente", "Agente"], ["modelo", "Modelo"], ["version_agente", "Versión del agente"], ["version_modelo", "Versión del modelo"],
] as const;
const STATES: Record<string, string> = {
  aplicable: "Aplica", sin_veredicto: "Sin veredicto", refutada: "Refutada", vencida: "Vencida",
  respaldo_retirado: "Respaldo retirado", respaldo_caido: "Respaldo caído",
  fuera_de_contexto: "Otro contexto", contexto_insuficiente: "Falta contexto", contexto_invalido: "Contexto inválido",
};
const USES = [["sirvio", "Sirvió"], ["no_aplico", "No aplicó"], ["ya_sabido", "Ya lo sabía"]] as const;
const NAME_KEY = "lienzo.persona";

const obj = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const int = (v: unknown) => Number.isInteger(v) && Number(v) >= 0;
function parseReasoning(v: unknown): Reasoning {
  if (!obj(v) || typeof v.motor !== "string" || typeof v.snapshot !== "string" || !Array.isArray(v.conclusiones) || !Array.isArray(v.diferencias)) throw new Error("Respuesta Prolog inválida");
  for (const c of v.conclusiones) {
    if (!obj(c) || typeof c.id !== "string" || typeof c.status !== "string" || !Array.isArray(c.chains)
      || c.chains.some(path => !Array.isArray(path) || path.some(id => typeof id !== "string"))) throw new Error("Conclusión Prolog inválida");
  }
  if (v.diferencias.some(d => !obj(d) || typeof d.id !== "string" || typeof d.python !== "string" || typeof d.prolog !== "string")) throw new Error("Comparación Prolog inválida");
  return v as unknown as Reasoning;
}
function bad(what: string): never { throw new Error(what + " no tiene el formato esperado"); }
function items(v: unknown): Item[] {
  if (!Array.isArray(v) || v.some(x => !obj(x) || typeof x.creencia !== "string" || typeof x.accion !== "string" || typeof x.estado !== "string" || typeof x.motivo !== "string" || !obj(x.usos))) bad("El aprendizaje");
  return v as Item[];
}
function checklist(v: unknown): Checklist {
  if (!obj(v) || !int(v.total) || !int(v.no_aplican_total)) bad("El aprendizaje");
  return { total: v.total as number, items: items(v.items), no_aplican_total: v.no_aplican_total as number, no_aplican: items(v.no_aplican) };
}
function beliefs(v: unknown): Belief[] {
  if (!Array.isArray(v) || v.some(x => !obj(x) || typeof x.id !== "string" || typeof x.texto !== "string" || typeof x.estado !== "string" || !obj(x.datos))) bad("Las creencias");
  return (v as Belief[]).filter(b => b.estado === "propuesta");
}
function evidence(v: unknown): { total: number; nodos: Evidence[] } {
  if (!obj(v) || !int(v.total) || !Array.isArray(v.nodos) || v.nodos.some(x => !obj(x) || typeof x.id !== "string" || typeof x.texto !== "string")) bad("La evidencia");
  return { total: v.total as number, nodos: v.nodos as Evidence[] };
}
function patterns(v: unknown): Patterns {
  if (!obj(v) || !Array.isArray(v.patrones) || !int(v.revisados) || !int(v.sin_clasificar) || typeof v.muestra_parcial !== "boolean"
    || v.patrones.some(p => !obj(p) || !obj(p.contexto) || !int(p.encargos) || !Array.isArray(p.fuentes) || !Array.isArray(p.controles_evidencia))) bad("Los patrones");
  return v as unknown as Patterns;
}
function readName() { try { return localStorage.getItem(NAME_KEY) ?? ""; } catch { return ""; } }
function saveName(v: string) { try { localStorage.setItem(NAME_KEY, v); } catch { /* sin almacenamiento: se pide de nuevo */ } }
/** Fecha local (no UTC): a las 22 h en Argentina toISOString ya da el día siguiente. */
function inDays(days: number) {
  const d = new Date(); d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
const ctxText = (c: Record<string, string> | undefined) => c && Object.keys(c).length ? Object.entries(c).map(([k, v]) => `${k}: ${v}`).join(" · ") : "cualquier contexto";

function Chain({ item }: { item: Item }) {
  return <details className="learning-evidence"><summary>Ver evidencia · {item.creencia}</summary>
    <dl className="knowledge-fields">
      <div><dt>Creencia</dt><dd>{item.texto}</dd></div>
      <div><dt>Evidencia del veredicto</dt><dd>{item.evidencia ?? <span className="knowledge-muted">Sin veredicto</span>}</dd></div>
      <div><dt>Contexto exigido</dt><dd>{ctxText(item.contexto)}</dd></div>
      <div><dt>Vigente hasta</dt><dd>{item.vigente_hasta ?? <span className="knowledge-muted">Sin fecha</span>}</dd></div>
      {item.excepciones && <div><dt>Excepciones</dt><dd>{item.excepciones}</dd></div>}
      {item.cadenas?.map((c, i) => <div key={i}><dt>Cadena hasta la fuente caída</dt><dd>{[item.creencia, ...c.map(s => `${s.id} (${s.texto})`)].join(" → ")}</dd></div>)}
    </dl>
  </details>;
}

function Verdict({ belief, evidence: options, onSubmit, busy }: { belief: Belief; evidence: Evidence[]; busy: boolean; onSubmit: (body: Record<string, string>) => void }) {
  const id = useId();
  const [proof, setProof] = useState("");
  const [typed, setTyped] = useState("");
  const [result, setResult] = useState("validada");
  const [reason, setReason] = useState("");
  const [until, setUntil] = useState(inDays(90));
  const evidenceId = typed.trim() || proof;
  return <form className="learning-verdict" onSubmit={e => {
    e.preventDefault();
    const body: Record<string, string> = { evidencia: evidenceId, resultado: result, motivo: reason.trim() };
    if (result === "validada") body.vigente_hasta = new Date(until + "T23:59:59").toISOString();
    onSubmit(body);
  }}>
    <label htmlFor={id + "-ev"}>Evidencia que lo sostiene</label>
    <select id={id + "-ev"} value={proof} onChange={e => setProof(e.target.value)}>
      <option value="">Elegí una evidencia reciente</option>
      {options.map(o => <option key={o.id} value={o.id}>{o.texto.slice(0, 80)} · {o.id.slice(0, 8)}</option>)}
    </select>
    <label htmlFor={id + "-evid"}>O el ID de otra evidencia</label>
    <input id={id + "-evid"} maxLength={64} value={typed} onChange={e => setTyped(e.target.value)} />
    {options.length === 0 && <p className="knowledge-note">No hay evidencia registrada en el proyecto: sin evidencia no hay veredicto.</p>}
    <fieldset><legend>Veredicto</legend>
      <label><input type="radio" name={id + "-r"} checked={result === "validada"} onChange={() => setResult("validada")} /> Validar</label>
      <label><input type="radio" name={id + "-r"} checked={result === "refutada"} onChange={() => setResult("refutada")} /> Refutar</label>
    </fieldset>
    {result === "validada" && <><label htmlFor={id + "-until"}>Vigente hasta</label><input id={id + "-until"} type="date" required min={inDays(1)} value={until} onChange={e => setUntil(e.target.value)} /></>}
    <label htmlFor={id + "-why"}>Motivo</label>
    <textarea id={id + "-why"} required rows={2} maxLength={2000} value={reason} onChange={e => setReason(e.target.value)} />
    <button type="submit" disabled={busy || !evidenceId || !reason.trim()}>{busy ? "Guardando…" : "Guardar veredicto de " + belief.id.slice(0, 8)}</button>
  </form>;
}

export function Learning({ base }: { base: string }) {
  const fieldId = useId();
  const [context, setContext] = useState<Record<string, string>>({});
  const [name, setName] = useState(readName);
  const [data, setData] = useState<Data>();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState("");
  const [reasoning, setReasoning] = useState<Reasoning>();
  const [reasonError, setReasonError] = useState("");
  const [reasonBusy, setReasonBusy] = useState(false);
  const prologRequest = useRef<AbortController>();
  const request = useRef<AbortController>();
  // el contexto vigente, no el de la pantalla donde se apretó: una recarga tras guardar usa lo que se ve
  const current = useRef(context);
  useEffect(() => { current.current = context; }, [context]);
  useEffect(() => () => { request.current?.abort(); prologRequest.current?.abort(); }, []);
  const person = name.trim();

  /** Las 100 evidencias más nuevas (la API pagina de a 100 desde la más vieja), la última primero. */
  const recentEvidence = async (signal: AbortSignal) => {
    const { total } = evidence(await api.get<unknown>(base + "/nodos?tipo=evidencia&limite=1", { signal }));
    const page = await api.get<unknown>(`${base}/nodos?tipo=evidencia&limite=100&desde=${Math.max(0, total - 100)}`, { signal });
    return evidence(page).nodos.reverse();
  };
  const load = async () => {
    prologRequest.current?.abort(); setReasoning(undefined); setReasonError(""); setReasonBusy(false);
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    setLoading(true); setError("");
    const params = new URLSearchParams();
    for (const [key] of CONTEXT) if (current.current[key]?.trim()) params.set(key, current.current[key].trim());
    params.set("limite", "20");
    const opts = { signal: controller.signal };
    try {
      const [c, b, e, p] = await Promise.all([
        api.get<unknown>(base + "/checklist?" + params.toString(), opts).then(checklist),
        api.get<unknown>(base + "/creencias", opts).then(beliefs),
        recentEvidence(controller.signal),
        api.get<unknown>(base + "/patrones-desarrollo", opts).then(patterns),
      ]);
      if (!controller.signal.aborted) setData({ checklist: c, pending: b, evidence: e, patterns: p });
    } catch (err: unknown) {
      if (!controller.signal.aborted) { setData(undefined); setError(failMsg("leer el aprendizaje")(err)); }
    } finally { if (!controller.signal.aborted) setLoading(false); }
  };
  const write = async (key: string, path: string, body: Record<string, string>, done: string) => {
    if (!person) { setError("Escribí tu nombre: los veredictos y el uso quedan firmados por una persona."); return; }
    setBusy(key); setError(""); setNotice("");
    try {
      await api.post(base + path, { ...body, por: "persona:" + person });
      setNotice(done);
      await load();
    } catch (err: unknown) { setError(failMsg("guardar")(err)); } finally { setBusy(""); }
  };
  const edit = (key: string, value: string) => {
    prologRequest.current?.abort(); setReasoning(undefined); setReasonError(""); setReasonBusy(false);
    request.current?.abort(); setLoading(false); setData(undefined); setNotice("");
    setContext(c => ({ ...c, [key]: value }));
  };
  const infer = async () => {
    prologRequest.current?.abort();
    const controller = new AbortController(); prologRequest.current = controller;
    setReasonBusy(true); setReasonError(""); setReasoning(undefined);
    const contexto = Object.fromEntries(Object.entries(current.current).filter(([, value]) => value.trim()).map(([key, value]) => [key, value.trim()]));
    try {
      const response = await fetch(base + "/razonamiento", { method: "POST", signal: controller.signal,
        headers: { "X-Lienzo": "1", "Content-Type": "application/json" }, body: JSON.stringify({ contexto }) });
      const result: unknown = await response.json();
      if (!response.ok) throw new Error(obj(result) && typeof result.error === "string" ? result.error : "Prolog no está disponible");
      const parsed = parseReasoning(result);
      if (!controller.signal.aborted) setReasoning(parsed);
    } catch (failure) { if (!controller.signal.aborted) setReasonError(failure instanceof Error ? failure.message : "No se pudo consultar Prolog"); }
    finally { if (!controller.signal.aborted) setReasonBusy(false); }
  };

  return <div className="knowledge-workspace">
    <form className="knowledge-query" onSubmit={e => { e.preventDefault(); void load(); }}>
      <h2>Aprendizaje</h2>
      <p className="knowledge-note">Qué aprendió el proyecto, para qué trabajo sirve y en qué se apoya. Consultar no cambia nada.</p>
      <fieldset className="knowledge-context"><legend>Contexto de trabajo</legend>
        <p className="knowledge-note">Lo que no completes queda sin informar: una creencia que lo exige sale como «Falta contexto».</p>
        {CONTEXT.map(([key, title]) => <div key={key}><label htmlFor={fieldId + "-" + key}>{title}</label><input id={fieldId + "-" + key} maxLength={100} value={context[key] ?? ""} onChange={e => edit(key, e.target.value)} /></div>)}
      </fieldset>
      <label htmlFor={fieldId + "-name"}>Tu nombre (firma veredictos y uso)</label>
      <input id={fieldId + "-name"} maxLength={100} value={name} onChange={e => { setName(e.target.value); saveName(e.target.value); }} />
      <div className="knowledge-query-actions"><button className="primary" type="submit" disabled={loading}>{loading ? "Consultando…" : "Consultar aprendizaje"}</button><button type="button" disabled={reasonBusy || loading} onClick={() => void infer()}>{reasonBusy ? "Razonando…" : "Contrastar con Prolog"}</button></div>
    </form>
    <div className="knowledge-results" aria-busy={loading}>
      {loading && <p role="status">Leyendo el aprendizaje del proyecto…</p>}
      {error && <div role="alert" className="knowledge-error">{error}</div>}
      {notice && <p role="status" className="knowledge-notice">{notice}</p>}
      {reasonError && <p role="alert" className="knowledge-error">{reasonError}. No se ejecutó el razonamiento Prolog. Las creencias y el aprendizaje siguen disponibles.</p>}
      {reasoning && <section className="knowledge-section" aria-label="Razonamiento Prolog"><h3>Razonamiento Prolog</h3><p>{reasoning.motor} respondió · {reasoning.conclusiones.length} creencias analizadas · {reasoning.diferencias.length} diferencias con Python.</p><p className="knowledge-note">Consulta de sólo lectura sobre el mismo contexto y evidencia. No valida ni modifica creencias.</p>{reasoning.conclusiones.length === 0 && <p>No hay creencias registradas para contrastar.</p>}<ul>{reasoning.conclusiones.map(c => <li key={c.id}>{c.id}: {STATES[c.status] ?? c.status}{c.chains.map((path, i) => <div key={i}>{path.join(" → ")}</div>)}</li>)}</ul><details><summary>Snapshot y comparación</summary><p className="knowledge-value">{reasoning.snapshot}</p>{reasoning.diferencias.map(d => <p key={d.id}>{d.id}: Python {d.python} · Prolog {d.prolog}</p>)}</details></section>}
      {!loading && !error && !data && <p className="knowledge-empty">Completá el contexto del trabajo y consultá.</p>}
      {data && <>
        <section className="knowledge-section"><h3>Aplica a este contexto</h3>
          <p>{data.checklist.total} aplicables{data.checklist.total > data.checklist.items.length ? `; mostrando ${data.checklist.items.length}` : ""}.</p>
          {data.checklist.items.length === 0 ? <p className="knowledge-empty">Nada validado aplica a este contexto todavía. Abajo está por qué no aplica lo demás y qué espera veredicto.</p>
            : <ul className="learning-cards">{data.checklist.items.map(item => <li key={item.creencia} className="learning-card">
              <div className="knowledge-node-status"><strong>{STATES[item.estado]}</strong>{item.revisar && <strong className="learning-flag">Revisar: no aplicó varias veces</strong>}</div>
              <p className="learning-action">{item.accion}</p>
              <p className="knowledge-note">{item.motivo}. Usos: {item.usos.sirvio} sirvió · {item.usos.no_aplico} no aplicó · {item.usos.ya_sabido} ya se sabía.</p>
              <Chain item={item} />
              <div className="learning-uses" role="group" aria-label={"Uso de " + item.creencia}>
                {USES.map(([value, text]) => <button key={value} type="button" disabled={busy !== ""} onClick={() => void write(item.creencia + value, `/creencias/${item.creencia}/uso`, { resultado: value }, `Uso registrado: ${text}.`)}>{text}</button>)}
              </div>
            </li>)}</ul>}
        </section>
        <section className="knowledge-section"><h3>No aplica, y por qué</h3>
          {data.checklist.no_aplican.length === 0 ? <p className="knowledge-empty">No hay otras creencias en este proyecto.</p>
            : <ul className="learning-cards">{data.checklist.no_aplican.map(item => <li key={item.creencia} className="learning-card">
              <div className="knowledge-node-status"><strong>{STATES[item.estado] ?? item.estado}</strong>{item.revisar && <strong className="learning-flag">Revisar</strong>}</div>
              <p className="learning-action">{item.accion}</p>
              <p className="knowledge-note">{item.motivo}.</p>
              <Chain item={item} />
            </li>)}</ul>}
          {data.checklist.no_aplican_total > data.checklist.no_aplican.length && <p className="knowledge-notice">Se muestran {data.checklist.no_aplican.length} de {data.checklist.no_aplican_total}.</p>}
        </section>
        <section className="knowledge-section"><h3>Esperan veredicto</h3>
          <p className="knowledge-note">Una propuesta no se aplica hasta que una persona la valida con evidencia. Refutarla la saca del todo.</p>
          {data.pending.length === 0 ? <p className="knowledge-empty">No hay propuestas pendientes.</p>
            : <ul className="learning-cards">{data.pending.map(b => <li key={b.id} className="learning-card">
              <p className="learning-action">{b.datos.accion ?? b.texto}</p>
              <p className="knowledge-note">{b.texto} · Contexto: {ctxText(b.datos.contexto)} · Fuentes: {(b.datos.fuentes ?? []).join(", ") || "sin fuentes"}</p>
              <Verdict belief={b} evidence={data.evidence} busy={busy === b.id} onSubmit={body => void write(b.id, `/creencias/${b.id}/veredicto`, body, "Veredicto guardado.")} />
            </li>)}</ul>}
        </section>
        <section className="knowledge-section"><h3>Patrones de trabajo</h3>
          <p>{data.patterns.revisados} encargos revisados · {data.patterns.sin_clasificar} sin clasificar.</p>
          {data.patterns.muestra_parcial && <p className="knowledge-notice">Muestra parcial: se revisaron los 500 encargos más recientes.</p>}
          <p className="knowledge-note">Los controles declarados no acreditan ejecución: cuentan los que tienen evidencia.</p>
          {data.patterns.patrones.length === 0 ? <p className="knowledge-empty">Todavía no hay encargos clasificados.</p>
            : <ul className="learning-cards">{data.patterns.patrones.map(p => {
              const ran = p.controles_evidencia.reduce((n, c) => n + (c.ejecutados?.length ?? 0) + (c.verificados?.length ?? 0), 0);
              const declared = Object.values(p.controles_declarados).reduce((a, b) => a + b, 0);
              return <li key={JSON.stringify(p.contexto)} className="learning-card">
                <p className="learning-action">{ctxText(p.contexto)}</p>
                <p className="knowledge-note">{p.encargos} encargos · {declared} controles declarados · {ran} con evidencia de ejecución.</p>
                <details><summary>Encargos de este patrón</summary><p className="knowledge-value">{p.fuentes.join(", ")}</p></details>
              </li>;
            })}</ul>}
        </section>
      </>}
    </div>
  </div>;
}
