import { useEffect, useId, useRef, useState } from "react";
import { api, failMsg } from "../api";
import LearningReviewIA from "./LearningReviewIA";

/** Aprendizaje del proyecto en una vista: todas sus creencias con su estado y el veredicto en un clic, las de
 *  cómo se trabaja con Lienzo aparte, un filtro opcional por lo que vas a hacer y los patrones. Leer no
 *  cambia nada; veredicto y uso son acciones explícitas de una persona con nombre, y después se vuelve a leer. */
type Usos = { sirvio: number; no_aplico: number; ya_sabido: number };
interface Item {
  creencia: string; texto: string; accion: string; estado: string; motivo: string;
  evidencia: string | null; excepciones: string; vigente_hasta: string | null;
  contexto: Record<string, string>; usos: Usos; revisar: boolean; alcance?: string; cadenas?: { id: string; texto: string }[][];
  /** Lo que el motor dijo de la propuesta al guardarla (investigador): una observación con fecha, no el estado actual. */
  contraste?: { resultado: string; motivo?: string; observaciones?: string[]; fecha?: string };
  /** Reglas derivadas de la creencia que quedaron cuestionadas (vista del proyecto). */
  reglas_cuestionadas?: string[];
  /** El proyecto dueño: las de proceso de Lienzo viven en `lienzo` aunque se vean en otro. */
  proyecto?: string;
  /** null: el motor no respondió y la aplicable no tiene contraste. */
  sostenida?: Justification | null; cuestionada_por?: (Justification & { regla: string })[];
  /** Pendiente sin refutar: falta medir la eficacia de la acción o falta evidencia para decidir. */
  pendiente?: { falta: "eficacia" | "evidencia"; motivo?: string; fecha?: string };
  /** Una medición que se repite suma observaciones a la misma creencia en vez de crear otra. */
  observaciones?: number; ultima_observacion?: string | null;
}
/** El motor lógico sobre el checklist: sostenido, con diferencias, sin respuesta o sin creencias. */
interface Motor { estado: string; error?: string; motor?: { name: string; version: string }; program_hash?: string; hechos?: number; diferencias?: unknown[] }
interface Checklist { contexto: Record<string, string>; total: number; items: Item[]; no_aplican_total: number; no_aplican: Item[]; motor?: Motor; motor_proceso?: Motor; cuestionadas_total: number; cuestionadas: Item[] }
interface Belief { id: string; texto: string; estado: string; datos: { accion?: string; contexto?: Record<string, string>; fuentes?: string[]; excepciones?: string } }
interface Evidence { id: string; texto: string }
interface Pattern { contexto: Record<string, string>; encargos: number; fuentes: string[]; controles_declarados: Record<string, number>; controles_evidencia: { ejecutados?: unknown[]; verificados?: unknown[] }[] }
interface Patterns { revisados: number; sin_clasificar: number; muestra_parcial: boolean; patrones: Pattern[] }
interface ProjectBlock { total: number; items: Item[] }
/** La vista del proyecto sin contexto: sus creencias y las de proceso de Lienzo, que valen para todos. */
interface ProjectView { proyecto: ProjectBlock; lienzo: ProjectBlock }
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
  aplicable: "Aplica", vigente: "Vigente", sin_veredicto: "Espera tu veredicto", refutada: "Refutada", vencida: "Vencida",
  reemplazada: "Reemplazada", pendiente_validacion: "Falta medir si sirve", pendiente_evidencia: "Falta evidencia",
  pendiente_formalizacion: "Falta formalizar",
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
/** El contraste guardado de una propuesta, aparte del veredicto humano (revisión V-4). */
const CONTRASTE: Record<string, string> = {
  sostenida: "la sostuvo", contradice: "contradice una decisión vigente", cuestionada: "la cuestionó", sin_motor: "no se pudo contrastar",
};
function contrastText(c: NonNullable<Item["contraste"]>) {
  const day = c.fecha ? c.fecha.slice(0, 10) : "";
  if (c.resultado === "sin_motor") return `Motor lógico: no se pudo contrastar${c.motivo ? ": " + c.motivo : ""}${day ? ` (${day})` : ""}`;
  return `Motor lógico: ${CONTRASTE[c.resultado] ?? c.resultado}${day ? ` (contraste del ${day})` : ""}`;
}
const motorLine = (m: Motor) => `${MOTOR[m.estado] ?? m.estado}${m.motor ? ` ${m.motor.name} ${m.motor.version}` : ""}${m.error ? ` (${m.error})` : ""}`;
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
  const contexto = obj(v.contexto) ? Object.fromEntries(Object.entries(v.contexto).filter(([, x]) => typeof x === "string")) as Record<string, string> : {};
  return { contexto, total: v.total as number, items: items(v.items), no_aplican_total: v.no_aplican_total as number, no_aplican: items(v.no_aplican),
    motor: v.motor as Motor | undefined, motor_proceso: obj(v.motor_proceso) && typeof v.motor_proceso.estado === "string" ? v.motor_proceso as unknown as Motor : undefined, cuestionadas_total: int(v.cuestionadas_total) ? v.cuestionadas_total as number : sueltas.length, cuestionadas: sueltas };
}
function projectView(v: unknown): ProjectView {
  const block = (b: unknown): ProjectBlock => {
    if (!obj(b) || !int(b.total)) bad("El aprendizaje del proyecto");
    return { total: b.total as number, items: items(b.items) };
  };
  if (!obj(v)) bad("El aprendizaje del proyecto");
  return { proyecto: block(v.proyecto), lienzo: block(v.lienzo) };
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
const TITLES: Record<string, string> = Object.fromEntries(CONTEXT);
const ctxText = (c: Record<string, string> | undefined) => c && Object.keys(c).length ? Object.entries(c).map(([k, v]) => `${TITLES[k] ?? k}: ${v}`).join(" · ") : "cualquier contexto";

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

/** El contexto sugerido por la API (o propuesto por la IA), con de dónde salió cada dato; algo inválido es
 *  «sin sugerencia», no un error que tape lo demás. */
function suggested(v: unknown): { contexto: Record<string, string>; fuente: string | null; fuentes: Record<string, string> } {
  if (!obj(v) || !obj(v.contexto)) return { contexto: {}, fuente: null, fuentes: {} };
  const keys = new Set<string>(CONTEXT.map(([key]) => key));
  const contexto = Object.fromEntries(Object.entries(v.contexto).filter(([key, x]) => keys.has(key) && typeof x === "string" && x.trim())) as Record<string, string>;
  const fuentes = obj(v.fuentes) ? Object.fromEntries(Object.entries(v.fuentes).filter(([key, x]) => key in contexto && typeof x === "string")) as Record<string, string> : {};
  return { contexto, fuente: typeof v.fuente === "string" ? v.fuente : null, fuentes };
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

/** Una creencia con su estado y el veredicto en un clic (pedido de Ariel, 2026-10-22). Aceptar y rechazar
 *  quedan firmados por la persona, con la revisión como evidencia; corregir abre el texto para editarlo. */
function BeliefCard({ item, busy, lienzo, onReview, onScope, evidence: options }: {
  item: Item; busy: string; lienzo: boolean; evidence: Evidence[];
  onReview: (body: Record<string, string>, done: string) => void; onScope?: (alcance: string) => void;
}) {
  const id = useId();
  const [fixing, setFixing] = useState(false);
  const [action, setAction] = useState(item.accion);
  const [text, setText] = useState(item.texto);
  const [scope, setScope] = useState(item.alcance ?? "proyecto");
  const open = item.estado === "sin_veredicto" || item.estado === "pendiente_validacion" || item.estado === "pendiente_evidencia";
  const closed = item.estado === "refutada" || item.estado === "reemplazada";
  const mine = busy.startsWith(item.creencia);
  const note = [ctxText(item.contexto), lienzo ? (item.alcance === "proceso_lienzo" ? "proceso de Lienzo" : "de este proyecto") : ""].filter(Boolean).join(" · ");
  return <li className="learning-card">
    <div className="knowledge-node-status"><strong className={open ? "learning-flag" : undefined}>{STATES[item.estado] ?? item.estado}</strong>{item.revisar && <strong className="learning-flag">Revisar: no aplicó varias veces</strong>}</div>
    <p className="learning-action">{item.accion || item.texto}</p>
    {item.accion && item.texto !== item.accion && <p className="knowledge-note">{item.texto}</p>}
    <p className="knowledge-note">{item.motivo}. Contexto: {note}{item.vigente_hasta && item.estado !== "sin_veredicto" ? ` · vigente hasta ${item.vigente_hasta.slice(0, 10)}` : ""}.</p>
    {item.pendiente?.motivo && <p className="knowledge-note">Revisión: {item.pendiente.motivo}</p>}
    {item.observaciones && item.observaciones > 1 && <p className="knowledge-note">Medida {item.observaciones} veces{item.ultima_observacion ? `; la última: ${item.ultima_observacion}` : ""}.</p>}
    {item.contraste && <p className={item.contraste.resultado === "sostenida" ? "knowledge-note" : "knowledge-note learning-flag"}>{contrastText(item.contraste)}.</p>}
    {item.reglas_cuestionadas?.map(r => <p key={r} className="knowledge-note learning-flag">Cuestionada: la regla {r.slice(0, 8)} derivada de ella quedó cuestionada. Consultá el motor en el filtro para ver la prueba.</p>)}
    {!closed && !fixing && <div className="learning-uses" role="group" aria-label={"Veredicto de " + item.creencia}>
      <button type="button" className={open ? "primary" : undefined} disabled={busy !== ""} onClick={() => onReview({ accion: "aceptar" }, open ? "Aceptada: ya cuenta como vigente." : "Renovada por 90 días.")}>{open ? "Aceptar" : "Renovar"}</button>
      <button type="button" disabled={busy !== ""} onClick={() => onReview({ accion: "rechazar" }, "Rechazada: deja de aplicar.")}>Rechazar</button>
      <button type="button" disabled={busy !== ""} onClick={() => setFixing(true)}>Corregir</button>
      {onScope && <button type="button" disabled={busy !== ""} onClick={() => onScope(item.alcance === "proceso_lienzo" ? "proyecto" : "proceso_lienzo")}>{item.alcance === "proceso_lienzo" ? "Pasar a este proyecto" : "Pasar a proceso de Lienzo"}</button>}
      {mine && <span role="status">Guardando…</span>}
    </div>}
    {fixing && !closed && <form className="learning-verdict" onSubmit={e => {
      e.preventDefault();
      const body: Record<string, string> = { accion: "corregir", accion_nueva: action.trim() };
      if (text.trim() && text.trim() !== item.texto) body.texto_nuevo = text.trim();
      if (lienzo && scope !== (item.alcance ?? "proyecto")) body.alcance = scope;
      onReview(body, "Corregida: la nueva versión quedó vigente y reemplaza a la anterior.");
    }}>
      <label htmlFor={id + "-acc"}>Qué hay que hacer</label>
      <textarea id={id + "-acc"} required rows={2} maxLength={1000} value={action} onChange={e => setAction(e.target.value)} />
      <label htmlFor={id + "-txt"}>Por qué (la creencia)</label>
      <textarea id={id + "-txt"} rows={2} maxLength={2000} value={text} onChange={e => setText(e.target.value)} />
      {lienzo && <><label htmlFor={id + "-sc"}>Alcance</label>
        <select id={id + "-sc"} value={scope} onChange={e => setScope(e.target.value)}>
          <option value="proyecto">De este proyecto</option><option value="proceso_lienzo">De cómo se trabaja con Lienzo (vale para todos)</option>
        </select></>}
      <div className="learning-uses"><button type="submit" disabled={busy !== "" || !action.trim()}>Guardar corrección</button><button type="button" onClick={() => setFixing(false)}>Cancelar</button></div>
    </form>}
    {open && options.length > 0 && <details className="learning-evidence"><summary>Veredicto con una evidencia registrada</summary>
      <Verdict belief={{ id: item.creencia, texto: item.texto, estado: "propuesta", datos: {} }} evidence={options} busy={mine}
        onSubmit={body => onReview({ ...body, ruta: "veredicto" }, "Veredicto guardado.")} />
    </details>}
    <Chain item={item} />
  </li>;
}

function Block({ title, label, block, empty, children }: { title: string; label: string; block: ProjectBlock; empty: string; children: (x: Item) => JSX.Element }) {
  const waiting = block.items.filter(x => x.estado === "sin_veredicto").length;
  // filtro por estado (Ariel, 2026-10-22): sólo los estados presentes, con su cantidad; vacío = todas
  const [only, setOnly] = useState("");
  const counts = new Map<string, number>();
  for (const x of block.items) counts.set(x.estado, (counts.get(x.estado) ?? 0) + 1);
  const shown = only && counts.has(only) ? block.items.filter(x => x.estado === only) : block.items;
  return <section className="knowledge-section" aria-label={label}><h3>{title}</h3>
    <p className="knowledge-note">{block.total} {block.total === 1 ? "creencia" : "creencias"}{waiting ? ` · ${waiting} ${waiting === 1 ? "espera" : "esperan"} tu veredicto` : ""}.</p>
    {counts.size > 1 && <div className="learning-filter" role="group" aria-label={`Filtrar ${title} por estado`}>
      <button type="button" aria-pressed={!only || !counts.has(only)} onClick={() => setOnly("")}>Todas {block.items.length}</button>
      {[...counts].map(([state, n]) => <button key={state} type="button" aria-pressed={only === state} onClick={() => setOnly(state)}>{STATES[state] ?? state} {n}</button>)}
    </div>}
    {block.items.length === 0 ? <p className="knowledge-empty">{empty}</p> : <ul className="learning-cards">{shown.map(children)}</ul>}
  </section>;
}

/** Abre mostrando lo aprendido del proyecto, sin pedir contexto (Ariel, 2026-10-22: «el aprendizaje es por
 *  proyecto»). El contexto es un filtro opcional y plegado que se completa solo desde la sesión elegida o la
 *  viva más reciente del proyecto; la IA puede leerlo de un texto libre, pero nada se guarda sin consultar. */
export function Learning({ base, session }: { base: string; session?: string }) {
  const fieldId = useId();
  const projectBase = (id: string) => base.slice(0, base.lastIndexOf("/") + 1) + encodeURIComponent(id);
  const lienzoBase = projectBase("lienzo");
  const isLienzo = base === lienzoBase;
  const [context, setContext] = useState<Record<string, string>>({});
  const [sources, setSources] = useState<Record<string, string>>({});
  const [source, setSource] = useState<string | null>(null);
  const [filterOpen, setFilterOpen] = useState(false);
  // la sugerencia del contexto en vuelo, y si la persona ya editó o consultó: entonces no se aplica
  const suggestion = useRef<AbortController>();
  const touched = useRef(false);
  const [name, setName] = useState(readName);
  const [project, setProject] = useState<ProjectView>();
  const [side, setSide] = useState<{ evidence: Evidence[]; patterns: Patterns }>();
  const [projectError, setProjectError] = useState("");
  const [projectLoading, setProjectLoading] = useState(false);
  const [data, setData] = useState<Checklist>();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState("");
  const [freeText, setFreeText] = useState("");
  const [aiBusy, setAiBusy] = useState(false);
  const [aiNote, setAiNote] = useState("");
  const [aiError, setAiError] = useState("");
  const aiRequest = useRef<AbortController>();
  const [reasoning, setReasoning] = useState<Reasoning>();
  const [reasonError, setReasonError] = useState("");
  const [reasonBusy, setReasonBusy] = useState(false);
  const prologRequest = useRef<AbortController>();
  const [contrast, setContrast] = useState<Contrast>();
  const [contrastError, setContrastError] = useState("");
  const [contrastBusy, setContrastBusy] = useState(false);
  const contrastRequest = useRef<AbortController>();
  const request = useRef<AbortController>();
  const projectRequest = useRef<AbortController>();
  // el contexto vigente, no el de la pantalla donde se apretó: una recarga tras guardar usa lo que se ve
  const current = useRef(context);
  useEffect(() => { current.current = context; }, [context]);
  const consulted = useRef(false);
  useEffect(() => () => { request.current?.abort(); projectRequest.current?.abort(); prologRequest.current?.abort(); contrastRequest.current?.abort(); aiRequest.current?.abort(); }, []);
  // otro proyecto: el contraste anterior y su respuesta tardía no son de este
  useEffect(() => () => { contrastRequest.current?.abort(); setContrast(undefined); setContrastError(""); setContrastBusy(false); }, [base]);
  const person = name.trim();

  /** Las 100 evidencias más nuevas (la API pagina de a 100 desde la más vieja), la última primero. */
  const recentEvidence = async (signal: AbortSignal) => {
    const { total } = evidence(await api.get<unknown>(base + "/nodos?tipo=evidencia&limite=1", { signal }));
    const page = await api.get<unknown>(`${base}/nodos?tipo=evidencia&limite=100&desde=${Math.max(0, total - 100)}`, { signal });
    return evidence(page).nodos.reverse();
  };
  /** Lo aprendido del proyecto, sin contexto: lo primero que se ve. */
  const loadProject = async () => {
    projectRequest.current?.abort();
    const controller = new AbortController(); projectRequest.current = controller;
    setProjectLoading(true); setProjectError("");
    const opts = { signal: controller.signal };
    try {
      const [v, e, p] = await Promise.all([
        api.get<unknown>(base + "/creencias-proyecto", opts).then(projectView),
        recentEvidence(controller.signal),
        api.get<unknown>(base + "/patrones-desarrollo", opts).then(patterns),
      ]);
      if (!controller.signal.aborted) { setProject(v); setSide({ evidence: e, patterns: p }); }
    } catch (err: unknown) {
      if (!controller.signal.aborted) { setProject(undefined); setProjectError(failMsg("leer el aprendizaje")(err)); }
    } finally { if (!controller.signal.aborted) setProjectLoading(false); }
  };
  /** El filtro: qué aplica a lo que vas a hacer. Sólo cuando la persona consulta. */
  const load = async () => {
    prologRequest.current?.abort(); setReasoning(undefined); setReasonError(""); setReasonBusy(false);
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    consulted.current = true;
    setLoading(true); setError("");
    const params = new URLSearchParams();
    for (const [key] of CONTEXT) if (current.current[key]?.trim()) params.set(key, current.current[key].trim());
    params.set("limite", "20");
    try {
      const c = checklist(await api.get<unknown>(base + "/checklist?" + params.toString(), { signal: controller.signal }));
      if (!controller.signal.aborted) setData(c);
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
      await api.post(path, { ...body, por: "persona:" + person });
      setNotice(done);
      await loadProject();
      if (consulted.current) await load();
    } catch (err: unknown) { setError(failMsg("guardar")(err)); } finally { setBusy(""); }
  };
  /** El veredicto en un clic, en el proyecto dueño de la creencia (las de proceso viven en `lienzo`). */
  const review = (owner: string, item: Item) => (body: Record<string, string>, done: string) => {
    const { ruta, ...rest } = body;
    void write(item.creencia + (rest.accion ?? "veredicto"), `${owner}/creencias/${item.creencia}/${ruta ?? "revision"}`, rest, done);
  };
  const scope = (item: Item) => (alcance: string) => void write(item.creencia + "alcance", `${lienzoBase}/creencias/${item.creencia}/alcance`, { alcance },
    alcance === "proceso_lienzo" ? "Ahora vale para todos los proyectos." : "Ahora es sólo de este proyecto.");
  const edit = (key: string, value: string) => {
    prologRequest.current?.abort(); setReasoning(undefined); setReasonError(""); setReasonBusy(false);
    request.current?.abort(); setLoading(false); setData(undefined); setNotice(""); setSource(null);
    touched.current = true; suggestion.current?.abort();  // lo que escribe la persona gana a una sugerencia tardía
    setSources(s => { const { [key]: _, ...rest } = s; return rest; });
    setContext(c => ({ ...c, [key]: value }));
  };
  // al abrir (y al cambiar de proyecto o de sesión): lo aprendido, y el contexto sugerido para el filtro
  useEffect(() => {
    void Promise.resolve().then(loadProject);  // fuera del render del efecto, como la lectura de antes
    const controller = new AbortController();
    suggestion.current = controller; touched.current = false;
    const query = session ? "?session_id=" + encodeURIComponent(session) : "";
    void api.get<unknown>(base + "/contexto-sugerido" + query, { signal: controller.signal })
      .then(suggested, () => ({ contexto: {}, fuente: null, fuentes: {} }))
      .then(s => {
        if (controller.signal.aborted || touched.current) return;
        current.current = s.contexto; setContext(s.contexto); setSource(s.fuente); setSources(s.fuentes);
      });
    return () => controller.abort();
    // loadProject lee `base`: la primera lectura depende sólo del proyecto y de la sesión
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base, session]);
  /** La IA propone tipo, tecnología, área y fase desde el texto libre. Llena los campos; no consulta ni guarda. */
  const interpret = async () => {
    aiRequest.current?.abort();
    const controller = new AbortController(); aiRequest.current = controller;
    setAiBusy(true); setAiError(""); setAiNote("");
    try {
      const response = await fetch(base + "/interpretar-contexto", { method: "POST", signal: controller.signal,
        headers: { "X-Lienzo": "1", "Content-Type": "application/json" }, body: JSON.stringify({ texto: freeText.trim() }) });
      const result: unknown = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(obj(result) && typeof result.error === "string" ? result.error : "La IA no respondió: completá los campos a mano");
      const got = suggested(result).contexto;
      if (controller.signal.aborted) return;
      touched.current = true; suggestion.current?.abort();
      request.current?.abort(); setLoading(false); setData(undefined); setNotice(""); setSource(null);
      setContext(c => ({ ...c, ...got })); current.current = { ...current.current, ...got };
      setSources(s => ({ ...s, ...Object.fromEntries(Object.keys(got).map(key => [key, "la IA (Claude), desde tu texto"])) }));
      const dropped = obj(result) && obj(result.descartados) ? Object.keys(result.descartados) : [];
      setAiNote(Object.keys(got).length
        ? `La IA completó ${Object.keys(got).length} campos. Revisalos y consultá; no se guardó nada.${dropped.length ? ` Descartó ${dropped.join(", ")} por no ser del vocabulario.` : ""}`
        : "La IA no reconoció nada del vocabulario en tu texto: completá los campos a mano.");
    } catch (failure) { if (!controller.signal.aborted) setAiError(failure instanceof Error ? failure.message : "La IA no respondió: completá los campos a mano"); }
    finally { if (!controller.signal.aborted) setAiBusy(false); }
  };
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
  const evidenceOptions = side?.evidence ?? [];

  return <div className="knowledge-workspace">
    <form className="knowledge-query" onSubmit={e => { e.preventDefault(); touched.current = true; suggestion.current?.abort(); void load(); }}>
      <h2>Aprendizaje</h2>
      <p className="learning-lead">Lo que aprendió este proyecto.</p>
      <p className="knowledge-note">Aceptá, rechazá o corregí cada creencia en un clic: queda firmado con tu nombre y la revisión como evidencia. Leer no cambia nada.</p>
      <label htmlFor={fieldId + "-name"}>Tu nombre (firma veredictos y uso)</label>
      <input id={fieldId + "-name"} maxLength={100} value={name} onChange={e => { setName(e.target.value); saveName(e.target.value); }} />
      <details className="knowledge-context" open={filterOpen} onToggle={e => setFilterOpen(e.currentTarget.open)}>
        <summary>Filtrar por lo que vas a hacer (opcional) · {ctxLabels(context)}{source ? ` · completado desde ${source}` : ""}</summary>
        <p className="knowledge-note">Se completa solo desde la sesión elegida o la más reciente del proyecto. Una creencia que exige un dato que falta sale como «Falta contexto».</p>
        <label htmlFor={fieldId + "-free"}>¿Qué vas a hacer? (texto libre)</label>
        <textarea id={fieldId + "-free"} rows={3} maxLength={2000} value={freeText} onChange={e => { setFreeText(e.target.value); setAiNote(""); setAiError(""); }} />
        <div className="knowledge-query-actions"><button type="button" disabled={aiBusy || !freeText.trim()} onClick={() => void interpret()}>{aiBusy ? "La IA está leyendo…" : "Completar con IA"}</button>{aiBusy && <button type="button" onClick={() => { aiRequest.current?.abort(); setAiBusy(false); }}>Cancelar</button>}</div>
        {aiNote && <p role="status" className="knowledge-note">{aiNote}</p>}
        {aiError && <p role="alert" className="knowledge-error">{aiError}</p>}
        {CONTEXT.map(([key, title]) => <div key={key}><label htmlFor={fieldId + "-" + key}>{title}</label><input id={fieldId + "-" + key} maxLength={100} value={context[key] ?? ""} onChange={e => edit(key, e.target.value)} />
          {sources[key] && context[key]?.trim() && <small className="knowledge-note">de {sources[key]}</small>}</div>)}
        <div className="knowledge-query-actions"><button className="primary" type="submit" disabled={loading}>{loading ? "Consultando…" : "Ver qué aplica"}</button>{loading && <button type="button" onClick={cancel}>Cancelar consulta</button>}<button type="button" disabled={reasonBusy || loading} onClick={() => void infer()}>{reasonBusy ? "Razonando…" : "Contrastar con Prolog"}</button></div>
      </details>
      <div className="knowledge-query-actions"><button type="button" disabled={contrastBusy} onClick={() => void contrastCandidates()}>{contrastBusy ? "Contrastando…" : "Contrastar candidatos"}</button></div>
      <LearningReviewIA key={base} base={base} changed={async () => { await loadProject(); if (consulted.current) await load(); }} />
    </form>
    <div className="knowledge-results" aria-busy={loading || projectLoading}>
      {projectLoading && !project && <p role="status">Leyendo el aprendizaje del proyecto…</p>}
      {projectError && <div role="alert" className="knowledge-error">{projectError}</div>}
      {error && <div role="alert" className="knowledge-error">{error}</div>}
      {notice && <p role="status" className="knowledge-notice">{notice}</p>}
      {project && <>
        <Block title="De este proyecto" label="De este proyecto" block={project.proyecto}
          empty="Este proyecto todavía no tiene creencias propias. Nacen de los patrones de los encargos y del análisis de cómo se trabaja; una persona les da el veredicto.">
          {x => <BeliefCard key={x.creencia} item={x} busy={busy} lienzo={isLienzo} evidence={evidenceOptions} onReview={review(base, x)} onScope={isLienzo ? scope(x) : undefined} />}
        </Block>
        <Block title="De cómo se trabaja con Lienzo" label="De cómo se trabaja con Lienzo" block={project.lienzo}
          empty="Todavía no hay creencias de proceso de Lienzo. Valen para cualquier proyecto: coordinación, frentes, verificación y releases.">
          {x => <BeliefCard key={x.creencia} item={x} busy={busy} lienzo={isLienzo} evidence={isLienzo ? evidenceOptions : []} onReview={review(lienzoBase, x)} onScope={isLienzo ? scope(x) : undefined} />}
        </Block>
      </>}
      {reasonError && <p role="alert" className="knowledge-error">{reasonError}. No se ejecutó el razonamiento Prolog. Las creencias y el aprendizaje siguen disponibles.</p>}
      {reasoning && <section className="knowledge-section" aria-label="Razonamiento Prolog"><h3>Razonamiento Prolog</h3><p>{reasoning.motor} respondió · {reasoning.conclusiones.length} creencias analizadas · {reasoning.diferencias.length} diferencias con Python.</p><p className="knowledge-note">Consulta de sólo lectura sobre el mismo contexto y evidencia. No valida ni modifica creencias.</p>{reasoning.conclusiones.length === 0 && <p>No hay creencias registradas para contrastar.</p>}<ul>{reasoning.conclusiones.map(c => <li key={c.id}>{c.id}: {STATES[c.status] ?? c.status}{c.chains.map((path, i) => <div key={i}>{path.join(" → ")}</div>)}</li>)}</ul><details><summary>Snapshot y comparación</summary><p className="knowledge-value">{reasoning.snapshot}</p>{reasoning.diferencias.map(d => <p key={d.id}>{d.id}: Python {d.python} · Prolog {d.prolog}</p>)}</details></section>}
      {contrastError && <p role="alert" className="knowledge-error">{contrastError}. No se contrastaron los candidatos; nada cambió.</p>}
      {contrast && <ContrastSection c={contrast} />}
      {loading && <p role="status">Leyendo qué aplica a lo que vas a hacer…</p>}
      {data && <>
        <section className="knowledge-section" aria-label="Aplica a lo que vas a hacer"><h3>Aplica a lo que vas a hacer</h3>
          <p>{data.total} aplicables{data.total > data.items.length ? `; mostrando ${data.items.length}` : ""} · {ctxLabels(data.contexto)}.</p>
          {data.motor && <p className={data.motor.estado === "sostenido" || data.motor.estado === "sin_creencias" ? "knowledge-note" : "knowledge-notice"} role="status">{motorLine(data.motor)}</p>}
          {data.motor_proceso && <p className={data.motor_proceso.estado === "sostenido" || data.motor_proceso.estado === "sin_creencias" ? "knowledge-note" : "knowledge-notice"}>Proceso de Lienzo: {motorLine(data.motor_proceso)}</p>}
          {data.items.length === 0 ? <p className="knowledge-empty">Nada validado aplica a este contexto todavía. Abajo está por qué no aplica lo demás.</p>
            : <ul className="learning-cards">{data.items.map(item => <li key={item.creencia} className="learning-card">
              <div className="knowledge-node-status"><strong>{STATES[item.estado]}</strong>{item.revisar && <strong className="learning-flag">Revisar: no aplicó varias veces</strong>}</div>
              <p className="learning-action">{item.accion}</p>
              {item.proyecto && base !== projectBase(item.proyecto) && <p className="knowledge-note">De cómo se trabaja con Lienzo: vale para todos los proyectos.</p>}
              <p className="knowledge-note">{item.motivo}. Usos: {item.usos.sirvio} sirvió · {item.usos.no_aplico} no aplicó · {item.usos.ya_sabido} ya se sabía.</p>
              {item.sostenida ? <Why label="Sostenida por el motor lógico: ver la prueba" j={item.sostenida} />
                : item.sostenida === null && <p className="knowledge-note">Sin contraste del motor lógico.</p>}
              <Chain item={item} />
              <div className="learning-uses" role="group" aria-label={"Uso de " + item.creencia}>
                {USES.map(([value, text]) => <button key={value} type="button" disabled={busy !== ""} onClick={() => void write(item.creencia + value, `${item.proyecto ? projectBase(item.proyecto) : base}/creencias/${item.creencia}/uso`, { resultado: value }, `Uso registrado: ${text}.`)}>{text}</button>)}
              </div>
            </li>)}</ul>}
        </section>
        {data.cuestionadas_total > 0 && <section className="knowledge-section"><h3>Cuestionadas</h3>
          <p className="knowledge-note">Aplicarían por contexto y veredicto, pero el motor lógico no las sostiene. Revisalas antes de seguirlas.</p>
          <ul className="learning-cards">{data.cuestionadas.map(item => <li key={item.creencia} className="learning-card">
            <div className="knowledge-node-status"><strong className="learning-flag">Cuestionada</strong></div>
            <p className="learning-action">{item.accion}</p>
            <p className="knowledge-note">{item.motivo}.</p>
            {item.cuestionada_por?.map(q => <Why key={q.regla} label={`Regla cuestionada ${q.regla.slice(0, 8)}: ver la prueba`} j={q} />)}
            <Chain item={item} />
          </li>)}</ul>
          {data.cuestionadas_total > data.cuestionadas.length && <p className="knowledge-notice">Se muestran {data.cuestionadas.length} de {data.cuestionadas_total}.</p>}
        </section>}
        <section className="knowledge-section"><h3>No aplica, y por qué</h3>
          {data.no_aplican.length === 0 ? <p className="knowledge-empty">No hay otras creencias en este proyecto.</p>
            : <ul className="learning-cards">{data.no_aplican.map(item => <li key={item.creencia} className="learning-card">
              <div className="knowledge-node-status"><strong>{STATES[item.estado] ?? item.estado}</strong>{item.revisar && <strong className="learning-flag">Revisar</strong>}</div>
              <p className="learning-action">{item.accion}</p>
              <p className="knowledge-note">{item.motivo}.</p>
              <Chain item={item} />
            </li>)}</ul>}
          {data.no_aplican_total > data.no_aplican.length && <p className="knowledge-notice">Se muestran {data.no_aplican.length} de {data.no_aplican_total}.</p>}
        </section>
      </>}
      {side && <section className="knowledge-section"><h3>Patrones de trabajo</h3>
        <p>{side.patterns.revisados} encargos revisados · {side.patterns.sin_clasificar} sin clasificar.</p>
        {side.patterns.muestra_parcial && <p className="knowledge-notice">Muestra parcial: se revisaron los 500 encargos más recientes.</p>}
        <p className="knowledge-note">Los controles declarados no acreditan ejecución: cuentan los que tienen evidencia.</p>
        {side.patterns.patrones.length === 0 ? <p className="knowledge-empty">Todavía no hay encargos clasificados.</p>
          : <ul className="learning-cards">{side.patterns.patrones.map(p => {
            const ran = p.controles_evidencia.reduce((n, c) => n + (c.ejecutados?.length ?? 0) + (c.verificados?.length ?? 0), 0);
            const declared = Object.values(p.controles_declarados).reduce((a, b) => a + b, 0);
            return <li key={JSON.stringify(p.contexto)} className="learning-card">
              <p className="learning-action">{ctxText(p.contexto)}</p>
              <p className="knowledge-note">{p.encargos} encargos · {declared} controles declarados · {ran} con evidencia de ejecución.</p>
              <details><summary>Encargos de este patrón</summary><p className="knowledge-value">{p.fuentes.join(", ")}</p></details>
            </li>;
          })}</ul>}
      </section>}
    </div>
  </div>;
}
