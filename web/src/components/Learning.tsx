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
  /** null: el motor no respondió y la aplicable no tiene contraste. */
  sostenida?: Justification | null; cuestionada_por?: (Justification & { regla: string })[];
}
/** El motor lógico sobre el checklist: sostenido, con diferencias, sin respuesta o sin creencias. */
interface Motor { estado: string; error?: string; motor?: { name: string; version: string }; program_hash?: string; hechos?: number; diferencias?: unknown[] }
interface Checklist { total: number; items: Item[]; no_aplican_total: number; no_aplican: Item[]; motor?: Motor; cuestionadas_total: number; cuestionadas: Item[] }
interface Belief { id: string; texto: string; estado: string; datos: { accion?: string; contexto?: Record<string, string>; fuentes?: string[]; excepciones?: string } }
interface Evidence { id: string; texto: string }
interface Pattern { contexto: Record<string, string>; encargos: number; fuentes: string[]; controles_declarados: Record<string, number>; controles_evidencia: { ejecutados?: unknown[]; verificados?: unknown[] }[] }
interface Patterns { revisados: number; sin_clasificar: number; muestra_parcial: boolean; patrones: Pattern[] }
interface Data { checklist: Checklist; pending: Belief[]; evidence: Evidence[]; patterns: Patterns }
interface Reasoning { motor: string; snapshot: string; conclusiones: { id: string; status: string; chains: string[][] }[]; diferencias: { id: string; python: string; prolog: string }[] }
/** Prueba del contrato 3: un hecho dado, una regla con premisas, una negación o un recorte. */
type Proof = { by: "given" | "rule" | "truncated"; fact: { pred: string; args: unknown[] }; rule?: string; premises?: (Proof | { not: { pred: string; args: unknown[] } })[] };
interface Justification { prueba: Proof; fuentes: string[]; prueba_truncada: boolean }
interface Observation extends Justification { tipo: string; con: string[] }
interface CandidateContrast { observaciones: Observation[]; evidencia_independiente: "humana" | "no_verificada" | "ausente"; listo_para_revision: boolean | null; justificacion_listo: Justification | null }
interface NodeInfo { tipo: string; estado: string | null; clase: string | null; texto: string }
interface Contrast {
  autoridad: string; concluyente: boolean; reglas: string; motor: { name: string; version: string }; program_hash: string; snapshot: string;
  cobertura: { nodos: number; vinculos: number; candidatos: number };
  candidatos: Record<string, CandidateContrast>; nodos: Record<string, NodeInfo>;
  diferencias_python: { consulta: string; solo_prolog: string[][]; solo_python: string[][] }[];
}

export const CONTEXT = [
  ["tipo_trabajo", "Tipo de trabajo"], ["tecnologia", "Tecnología"], ["area", "Área"], ["fase", "Fase"],
  ["agente", "Agente"], ["modelo", "Modelo"], ["version_agente", "Versión del agente"], ["version_modelo", "Versión del modelo"],
] as const;
const STATES: Record<string, string> = {
  aplicable: "Aplica", sin_veredicto: "Sin veredicto", refutada: "Refutada", vencida: "Vencida",
  respaldo_retirado: "Respaldo retirado", respaldo_caido: "Respaldo caído",
  fuera_de_contexto: "Otro contexto", contexto_insuficiente: "Falta contexto", contexto_invalido: "Contexto inválido",
  cuestionada: "Cuestionada",
};
const MOTOR: Record<string, string> = {
  sostenido: "Cada aplicable está sostenida por el motor lógico, con su prueba.",
  con_diferencias: "El motor lógico y Python no coinciden en algo: lo que no coincide queda cuestionado.",
  no_disponible: "El motor lógico no respondió: las aplicables se muestran sin contraste.",
  respuesta_invalida: "La respuesta del motor lógico no fue válida: las aplicables se muestran sin contraste.",
  sin_creencias: "No hay creencias que contrastar.",
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
const OBSERVATIONS: Record<string, string> = {
  respaldo_caido: "Respaldo caído", regla_cuestionada: "Depende de una regla cuestionada", contradice: "Contradice una decisión vigente",
  reabre_rechazado: "Reabre un hallazgo rechazado", apoyo_retirado: "Apoyo retirado",
};
const EVIDENCE_STATE: Record<string, string> = {
  humana: "Evidencia de una persona", no_verificada: "Evidencia de procedencia no verificada", ausente: "Sin evidencia independiente",
};
const strings = (v: unknown) => Array.isArray(v) && v.every(x => typeof x === "string");
const justified = (j: unknown) => obj(j) && obj(j.prueba) && strings(j.fuentes) && typeof j.prueba_truncada === "boolean";
function parseContrast(v: unknown): Contrast {
  if (!obj(v) || typeof v.concluyente !== "boolean" || typeof v.program_hash !== "string" || typeof v.snapshot !== "string" || typeof v.reglas !== "string"
    || !obj(v.motor) || typeof v.motor.version !== "string" || !obj(v.cobertura) || !int(v.cobertura.candidatos)
    || !obj(v.candidatos) || !obj(v.nodos) || !Array.isArray(v.diferencias_python)) bad("El contraste");
  for (const c of Object.values(v.candidatos)) {
    if (!obj(c) || !Array.isArray(c.observaciones) || !(c.evidencia_independiente as string in EVIDENCE_STATE)
      || !(c.listo_para_revision === null || typeof c.listo_para_revision === "boolean")
      || !(c.justificacion_listo === null || justified(c.justificacion_listo))
      || c.observaciones.some(o => !obj(o) || typeof o.tipo !== "string" || !strings(o.con) || !justified(o))) bad("El contraste");
  }
  return v as unknown as Contrast;
}
function bad(what: string): never { throw new Error(what + " no tiene el formato esperado"); }
function items(v: unknown): Item[] {
  if (!Array.isArray(v) || v.some(x => !obj(x) || typeof x.creencia !== "string" || typeof x.accion !== "string" || typeof x.estado !== "string" || typeof x.motivo !== "string" || !obj(x.usos))) bad("El aprendizaje");
  return v as Item[];
}
function checklist(v: unknown): Checklist {
  if (!obj(v) || !int(v.total) || !int(v.no_aplican_total) || (v.motor !== undefined && (!obj(v.motor) || typeof v.motor.estado !== "string"))) bad("El aprendizaje");
  const sueltas = v.cuestionadas === undefined ? [] : items(v.cuestionadas);
  return { total: v.total as number, items: items(v.items), no_aplican_total: v.no_aplican_total as number, no_aplican: items(v.no_aplican),
    motor: v.motor as Motor | undefined, cuestionadas_total: int(v.cuestionadas_total) ? v.cuestionadas_total as number : sueltas.length, cuestionadas: sueltas };
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
/** El contexto con los nombres de los campos y en su orden, para leerlo de un vistazo. */
const ctxLabels = (c: Record<string, string>) => CONTEXT.filter(([key]) => c[key]?.trim()).map(([key, title]) => `${title}: ${c[key].trim()}`).join(" · ") || "sin completar";
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

/** El contexto sugerido por la API; algo inválido es «sin sugerencia», no un error que tape lo demás. */
function suggested(v: unknown): { contexto: Record<string, string>; fuente: string | null } {
  if (!obj(v) || !obj(v.contexto)) return { contexto: {}, fuente: null };
  const keys = new Set<string>(CONTEXT.map(([key]) => key));
  const contexto = Object.fromEntries(Object.entries(v.contexto).filter(([key, x]) => keys.has(key) && typeof x === "string" && x.trim())) as Record<string, string>;
  return { contexto, fuente: typeof v.fuente === "string" ? v.fuente : null };
}

/** Todas las creencias del proyecto de un vistazo, con su estado para lo que vas a hacer. El detalle
 *  (prueba, cadena, uso, veredicto) sigue en las secciones de abajo. */
function Overview({ checklist: c }: { checklist: Checklist }) {
  const all = [...c.items, ...c.cuestionadas, ...c.no_aplican];
  const label = (x: Item) => x.estado !== "aplicable" ? STATES[x.estado] ?? x.estado
    : x.sostenida ? "Aplica · sostenida por el motor" : x.sostenida === null ? "Aplica · sin contraste del motor" : "Aplica";
  const more = c.total > c.items.length || c.cuestionadas_total > c.cuestionadas.length || c.no_aplican_total > c.no_aplican.length;
  return <section className="knowledge-section" aria-label="Creencias del proyecto"><h3>Creencias del proyecto</h3>
    {all.length === 0
      ? <p className="knowledge-empty">Este proyecto todavía no tiene creencias. Nacen de los patrones de los encargos y del análisis de cómo se trabaja; una persona las valida con evidencia.</p>
      : <ul className="learning-overview">{all.map(x => <li key={x.creencia}><strong>{label(x)}</strong> · {x.accion || x.texto}</li>)}</ul>}
    {more && <p className="knowledge-notice">Hay más creencias que las listadas; abajo se ven por grupo.</p>}
  </section>;
}

const literal = (l: { pred: string; args: unknown[] }) => `${l.pred}(${l.args.map(a => String(a)).join(", ")})`;
/** La prueba como árbol: cada paso nombra la regla de Lienzo; cada hoja, un hecho del grafo. */
function ProofTree({ proof }: { proof: Proof | { not: { pred: string; args: unknown[] } } }) {
  if ("not" in proof) return <li>no {literal(proof.not)}</li>;
  if (proof.by === "truncated") return <li>{literal(proof.fact)} · <em>prueba recortada</em></li>;
  if (proof.by === "given") return <li>{literal(proof.fact)} · hecho del grafo</li>;
  return <li>{literal(proof.fact)} · regla {proof.rule}{!!proof.premises?.length && <ul>{proof.premises.map((p, i) => <ProofTree key={i} proof={p} />)}</ul>}</li>;
}
function Why({ label, j }: { label: string; j: Justification }) {
  return <details className="learning-evidence"><summary>{label}</summary>
    <ul className="knowledge-value">{<ProofTree proof={j.prueba} />}</ul>
    <p className="knowledge-note">Fuentes: {j.fuentes.join(", ") || "ninguna"}{j.prueba_truncada ? " · la prueba se recortó por profundidad" : ""}.</p>
  </details>;
}
function ContrastSection({ c }: { c: Contrast }) {
  const ids = Object.keys(c.candidatos);
  const name = (id: string) => `${c.nodos[id]?.texto || id} · ${id.slice(0, 8)}`;
  return <section className="knowledge-section" aria-label="Contraste de candidatos">
    <h3>Contraste de candidatos</h3>
    <p>{c.motor.name} {c.motor.version} · {c.cobertura.candidatos} candidatos · {c.diferencias_python.length} diferencias con Python.</p>
    <p className="knowledge-note">{c.autoridad}. Una propuesta sigue esperando el veredicto de una persona.</p>
    {!c.concluyente && <p role="alert" className="knowledge-error">Prolog y Python no coinciden: el contraste no es concluyente y no se marca nada como listo para revisar.</p>}
    {ids.length === 0 ? <p className="knowledge-empty">No hay candidatos que esperen veredicto en este proyecto.</p>
      : <ul className="learning-cards">{ids.map(id => {
        const x = c.candidatos[id];
        return <li key={id} className="learning-card">
          <p className="learning-action">{name(id)}</p>
          <p className="knowledge-note">{c.nodos[id]?.tipo} {c.nodos[id]?.estado}{c.nodos[id]?.clase ? ` · ${c.nodos[id]?.clase}` : ""} · {EVIDENCE_STATE[x.evidencia_independiente]}
            {" · "}{x.listo_para_revision === null ? "sin conclusión" : x.listo_para_revision ? "listo para revisar" : x.observaciones.length ? "con observaciones" : "falta evidencia de una persona"}</p>
          {x.observaciones.map((o, i) => <div key={i}>
            <strong>{OBSERVATIONS[o.tipo] ?? o.tipo}</strong>: {o.con.map(name).join(" · ")}
            <Why label="¿Por qué?" j={o} />
          </div>)}
          {x.justificacion_listo && <Why label="¿Por qué está listo para revisar?" j={x.justificacion_listo} />}
        </li>;
      })}</ul>}
    <details><summary>Huella y comparación</summary>
      <p className="knowledge-value">reglas {c.reglas} · {c.program_hash} · snapshot {c.snapshot} · {c.cobertura.nodos} nodos · {c.cobertura.vinculos} vínculos</p>
      {c.diferencias_python.map(d => <p key={d.consulta}>{d.consulta}: sólo Prolog {JSON.stringify(d.solo_prolog)} · sólo Python {JSON.stringify(d.solo_python)}</p>)}
    </details>
  </section>;
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

/** Al abrir, completa el contexto desde la sesión elegida (`session`) o el encargo en curso y lee solo:
 *  nadie tiene que saber qué escribir en seis campos para ver qué aprendió el proyecto (Ariel, 2026-10-22). */
export function Learning({ base, session }: { base: string; session?: string }) {
  const fieldId = useId();
  const [context, setContext] = useState<Record<string, string>>({});
  const [source, setSource] = useState<string | null>(null);
  const [contextOpen, setContextOpen] = useState(false);
  // la sugerencia del contexto en vuelo, y si la persona ya editó o consultó: entonces no se aplica
  const suggestion = useRef<AbortController>();
  const touched = useRef(false);
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
  const [contrast, setContrast] = useState<Contrast>();
  const [contrastError, setContrastError] = useState("");
  const [contrastBusy, setContrastBusy] = useState(false);
  const contrastRequest = useRef<AbortController>();
  const request = useRef<AbortController>();
  // el contexto vigente, no el de la pantalla donde se apretó: una recarga tras guardar usa lo que se ve
  const current = useRef(context);
  useEffect(() => { current.current = context; }, [context]);
  useEffect(() => () => { request.current?.abort(); prologRequest.current?.abort(); contrastRequest.current?.abort(); }, []);
  // otro proyecto: el contraste anterior y su respuesta tardía no son de este
  useEffect(() => () => { contrastRequest.current?.abort(); setContrast(undefined); setContrastError(""); setContrastBusy(false); }, [base]);
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
  /** Corta la consulta en curso: su respuesta tardía se descarta (como «Cancelar consulta» en las demás vistas). */
  const cancel = () => { request.current?.abort(); setLoading(false); setData(undefined); setError(""); setNotice(""); };
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
    request.current?.abort(); setLoading(false); setData(undefined); setNotice(""); setSource(null);
    touched.current = true; suggestion.current?.abort();  // lo que escribe la persona gana a una sugerencia tardía
    setContext(c => ({ ...c, [key]: value }));
  };
  // al abrir (y al cambiar de proyecto o de sesión): contexto sugerido y primera lectura, sin apretar nada
  useEffect(() => {
    const controller = new AbortController();
    suggestion.current = controller; touched.current = false;
    const query = session ? "?session_id=" + encodeURIComponent(session) : "";
    void api.get<unknown>(base + "/contexto-sugerido" + query, { signal: controller.signal })
      .then(suggested, () => ({ contexto: {}, fuente: null }))
      .then(s => {
        if (controller.signal.aborted || touched.current) return;
        current.current = s.contexto; setContext(s.contexto); setSource(s.fuente);
        setContextOpen(Object.keys(s.contexto).length === 0);
        void load();
      });
    return () => controller.abort();
    // load lee el contexto de `current`: la primera lectura depende sólo del proyecto y de la sesión
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base, session]);
  /** Contraste lógico de lo que espera veredicto: no depende del contexto, sólo lee y no escribe. */
  const contrastCandidates = async () => {
    contrastRequest.current?.abort();
    const controller = new AbortController(); contrastRequest.current = controller;
    setContrastBusy(true); setContrastError(""); setContrast(undefined);
    try {
      const response = await fetch(base + "/candidatos/contraste", { method: "POST", signal: controller.signal,
        headers: { "X-Lienzo": "1", "Content-Type": "application/json" }, body: "{}" });
      const result: unknown = await response.json();
      if (!response.ok) throw new Error(obj(result) && typeof result.error === "string" ? result.error : "El motor lógico no está disponible");
      const parsed = parseContrast(result);
      if (!controller.signal.aborted) setContrast(parsed);
    } catch (failure) { if (!controller.signal.aborted) setContrastError(failure instanceof Error ? failure.message : "No se pudo contrastar"); }
    finally { if (!controller.signal.aborted) setContrastBusy(false); }
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
    <form className="knowledge-query" onSubmit={e => { e.preventDefault(); touched.current = true; suggestion.current?.abort(); void load(); }}>
      <h2>Aprendizaje</h2>
      <p className="learning-lead">Qué aprendió este proyecto y qué aplica a lo que vas a hacer.</p>
      <p className="knowledge-note">Cada creencia la valida una persona con evidencia; el motor lógico confirma cuáles se sostienen. Leer no cambia nada.</p>
      <details className="knowledge-context" open={contextOpen} onToggle={e => setContextOpen(e.currentTarget.open)}>
        <summary>Lo que vas a hacer: {ctxLabels(context)}{source ? ` · completado desde ${source}` : ""}</summary>
        <p className="knowledge-note">Se completa solo desde la sesión elegida o el encargo en curso; cambialo si hace falta. Una creencia que exige un dato que falta sale como «Falta contexto».</p>
        {CONTEXT.map(([key, title]) => <div key={key}><label htmlFor={fieldId + "-" + key}>{title}</label><input id={fieldId + "-" + key} maxLength={100} value={context[key] ?? ""} onChange={e => edit(key, e.target.value)} /></div>)}
      </details>
      <label htmlFor={fieldId + "-name"}>Tu nombre (firma veredictos y uso)</label>
      <input id={fieldId + "-name"} maxLength={100} value={name} onChange={e => { setName(e.target.value); saveName(e.target.value); }} />
      <div className="knowledge-query-actions"><button className="primary" type="submit" disabled={loading}>{loading ? "Consultando…" : "Consultar aprendizaje"}</button>{loading && <button type="button" onClick={cancel}>Cancelar consulta</button>}<button type="button" disabled={reasonBusy || loading} onClick={() => void infer()}>{reasonBusy ? "Razonando…" : "Contrastar con Prolog"}</button><button type="button" disabled={contrastBusy} onClick={() => void contrastCandidates()}>{contrastBusy ? "Contrastando…" : "Contrastar candidatos"}</button></div>
    </form>
    <div className="knowledge-results" aria-busy={loading}>
      {loading && <p role="status">Leyendo el aprendizaje del proyecto…</p>}
      {error && <div role="alert" className="knowledge-error">{error}</div>}
      {notice && <p role="status" className="knowledge-notice">{notice}</p>}
      {reasonError && <p role="alert" className="knowledge-error">{reasonError}. No se ejecutó el razonamiento Prolog. Las creencias y el aprendizaje siguen disponibles.</p>}
      {reasoning && <section className="knowledge-section" aria-label="Razonamiento Prolog"><h3>Razonamiento Prolog</h3><p>{reasoning.motor} respondió · {reasoning.conclusiones.length} creencias analizadas · {reasoning.diferencias.length} diferencias con Python.</p><p className="knowledge-note">Consulta de sólo lectura sobre el mismo contexto y evidencia. No valida ni modifica creencias.</p>{reasoning.conclusiones.length === 0 && <p>No hay creencias registradas para contrastar.</p>}<ul>{reasoning.conclusiones.map(c => <li key={c.id}>{c.id}: {STATES[c.status] ?? c.status}{c.chains.map((path, i) => <div key={i}>{path.join(" → ")}</div>)}</li>)}</ul><details><summary>Snapshot y comparación</summary><p className="knowledge-value">{reasoning.snapshot}</p>{reasoning.diferencias.map(d => <p key={d.id}>{d.id}: Python {d.python} · Prolog {d.prolog}</p>)}</details></section>}
      {contrastError && <p role="alert" className="knowledge-error">{contrastError}. No se contrastaron los candidatos; nada cambió.</p>}
      {contrast && <ContrastSection c={contrast} />}
      {!loading && !error && !data && <p className="knowledge-empty">Cambiaste lo que vas a hacer: consultá para ver qué aplica.</p>}
      {data && <>
        <Overview checklist={data.checklist} />
        <section className="knowledge-section"><h3>Aplica a este contexto</h3>
          <p>{data.checklist.total} aplicables{data.checklist.total > data.checklist.items.length ? `; mostrando ${data.checklist.items.length}` : ""}.</p>
          {data.checklist.motor && <p className={data.checklist.motor.estado === "sostenido" || data.checklist.motor.estado === "sin_creencias" ? "knowledge-note" : "knowledge-notice"} role="status">
            {MOTOR[data.checklist.motor.estado] ?? data.checklist.motor.estado}{data.checklist.motor.motor ? ` ${data.checklist.motor.motor.name} ${data.checklist.motor.motor.version}` : ""}{data.checklist.motor.error ? ` (${data.checklist.motor.error})` : ""}</p>}
          {data.checklist.items.length === 0 ? <p className="knowledge-empty">Nada validado aplica a este contexto todavía. Abajo está por qué no aplica lo demás y qué espera veredicto.</p>
            : <ul className="learning-cards">{data.checklist.items.map(item => <li key={item.creencia} className="learning-card">
              <div className="knowledge-node-status"><strong>{STATES[item.estado]}</strong>{item.revisar && <strong className="learning-flag">Revisar: no aplicó varias veces</strong>}</div>
              <p className="learning-action">{item.accion}</p>
              <p className="knowledge-note">{item.motivo}. Usos: {item.usos.sirvio} sirvió · {item.usos.no_aplico} no aplicó · {item.usos.ya_sabido} ya se sabía.</p>
              {item.sostenida ? <Why label="Sostenida por el motor lógico: ver la prueba" j={item.sostenida} />
                : item.sostenida === null && <p className="knowledge-note">Sin contraste del motor lógico.</p>}
              <Chain item={item} />
              <div className="learning-uses" role="group" aria-label={"Uso de " + item.creencia}>
                {USES.map(([value, text]) => <button key={value} type="button" disabled={busy !== ""} onClick={() => void write(item.creencia + value, `/creencias/${item.creencia}/uso`, { resultado: value }, `Uso registrado: ${text}.`)}>{text}</button>)}
              </div>
            </li>)}</ul>}
        </section>
        {data.checklist.cuestionadas_total > 0 && <section className="knowledge-section"><h3>Cuestionadas</h3>
          <p className="knowledge-note">Aplicarían por contexto y veredicto, pero el motor lógico no las sostiene. Revisalas antes de seguirlas.</p>
          <ul className="learning-cards">{data.checklist.cuestionadas.map(item => <li key={item.creencia} className="learning-card">
            <div className="knowledge-node-status"><strong className="learning-flag">Cuestionada</strong></div>
            <p className="learning-action">{item.accion}</p>
            <p className="knowledge-note">{item.motivo}.</p>
            {item.cuestionada_por?.map(q => <Why key={q.regla} label={`Regla cuestionada ${q.regla.slice(0, 8)}: ver la prueba`} j={q} />)}
            <Chain item={item} />
          </li>)}</ul>
          {data.checklist.cuestionadas_total > data.checklist.cuestionadas.length && <p className="knowledge-notice">Se muestran {data.checklist.cuestionadas.length} de {data.checklist.cuestionadas_total}.</p>}
        </section>}
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
