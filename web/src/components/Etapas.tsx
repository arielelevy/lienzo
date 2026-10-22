import { useEffect, useId, useRef, useState } from "react";
import { api, failMsg } from "../api";
import "../etapas.css";

/** Etapas por encargo (Prime Agent, decisión 15 de Ariel): pendiente → implementación → revisión →
 *  verificación → aprobado. Leer no cambia nada. El cierre de un turno o la respuesta del agente sólo
 *  llevan un encargo a revisión; pasar a verificación, aprobar o devolver lo firma una persona, con
 *  evidencia recibida en esa etapa (o motivo, al devolver), en una sola escritura, y después se vuelve a leer. */
type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
interface Node { id: string; texto: string; estado: string | null; estado_fecha?: string | null; estado_por?: string | null; ronda?: string | null; fecha: string; datos: { [key: string]: Json } }
interface Link { de: string; relacion: string; a: string; fecha: string; autor: string }
interface Change { seq: number; accion: string; autor: string; motivo: string; fecha: string; nuevo: { estado?: string } | null; origen?: { evidencia?: string | string[] } | null }
interface Detail extends Node { vinculos: { salen: Link[]; entran: Link[] }; cambios: Change[] }
interface Page { total: number; nodos: Node[] }

export const ETAPAS = [["pendiente", "Pendiente"], ["implementacion", "Implementación"], ["revision", "Revisión"], ["verificacion", "Verificación"], ["aprobado", "Aprobado"]] as const;
const DE_ESTADO: Record<string, string> = { enviado: "implementacion", entregado: "revision", verificando: "verificacion" };
/** La etapa por el estado, como `conocimiento.etapa_encargo`: un estado sin etapa (sin_entrega) queda como tal. */
export function etapa(estado: string | null): string { return DE_ESTADO[estado ?? ""] ?? estado ?? "pendiente"; }
const etapaLabel = (estado: string) => ETAPAS.find(([id]) => id === etapa(estado))?.[1] ?? estado;
const NAME_KEY = "lienzo.persona";

const obj = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
function page(v: unknown): Page {
  if (!obj(v) || !Number.isInteger(v.total) || !Array.isArray(v.nodos) || v.nodos.some(n => !obj(n) || typeof n.id !== "string" || typeof n.texto !== "string" || typeof n.fecha !== "string" || !obj(n.datos)))
    throw new Error("La lista de nodos no tiene el formato esperado");
  return v as unknown as Page;
}
function detail(v: unknown): Detail {
  if (!obj(v) || typeof v.id !== "string" || !obj(v.vinculos) || !Array.isArray(v.vinculos.salen) || !Array.isArray(v.vinculos.entran) || !Array.isArray(v.cambios))
    throw new Error("El encargo no tiene el formato esperado");
  return v as unknown as Detail;
}
function storedName() { try { return localStorage.getItem(NAME_KEY) ?? ""; } catch { return ""; } }
const title = (n: Node) => n.texto.split(/\r?\n/).map(s => s.replace(/^#+\s*/, "").trim()).find(Boolean) ?? n.id;
const when = (iso?: string | null) => iso ? new Date(iso).toLocaleString("es-AR", { dateStyle: "short", timeStyle: "short" }) : "";
const cited = (c: Change) => { const e = c.origen?.evidencia; return Array.isArray(e) ? e : e ? [e] : []; };

function Stepper({ estado }: { estado: string | null }) {
  const pos = ETAPAS.findIndex(([id]) => id === etapa(estado));
  return <ol className="etapas-stepper" aria-label="Etapas del encargo">
    {ETAPAS.map(([id, label], i) => <li key={id} className={i < pos ? "hecha" : i === pos ? "actual" : ""} aria-current={i === pos ? "step" : undefined}>{label}</li>)}
  </ol>;
}

/** Lo que respalda al encargo: informes que le responden, evidencia (vinculada o citada al cambiar de etapa) e historial. */
function Evidence({ d, names }: { d: Detail; names: Record<string, string> }) {
  const informes = d.vinculos.entran.filter(v => v.relacion === "responde_a");
  const evidencia = d.vinculos.salen.filter(v => v.relacion === "apoya");
  const estados = d.cambios.filter(c => c.accion === "estado" && c.nuevo?.estado);
  const name = (id: string) => names[id] ?? id;
  return <div className="etapas-evidence">
    <h4>Informes</h4>
    {informes.length ? <ul>{informes.map(v => <li key={v.de}>{name(v.de)} · {when(v.fecha)}</li>)}</ul> : <p className="knowledge-empty">Sin informes.</p>}
    {evidencia.length > 0 && <><h4>Evidencia vinculada</h4><ul>{evidencia.map(v => <li key={v.a}>{name(v.a)} · {v.autor} · {when(v.fecha)}</li>)}</ul></>}
    <h4>Historial de etapas</h4>
    <ul>{estados.map(c => <li key={c.seq}>{when(c.fecha)} · {etapaLabel(c.nuevo!.estado!)} · {c.autor}{c.motivo ? ` · ${c.motivo}` : ""}{cited(c).length ? ` · evidencia: ${cited(c).map(name).join(", ")}` : ""}</li>)}</ul>
  </div>;
}

function Actions({ node, evidence, busy, act }: { node: Node; evidence: Node[]; busy: boolean; act: (n: Node, estado: string, ev: string, motivo: string) => void }) {
  const [ev, setEv] = useState("");
  const [motivo, setMotivo] = useState("");
  const id = useId();
  const e = etapa(node.estado);
  if (e !== "revision" && e !== "verificacion") return null;
  // sólo la evidencia recibida desde que el encargo entró en esta etapa la respalda (el server lo exige)
  const propias = evidence.filter(n => !node.estado_fecha || n.fecha >= node.estado_fecha);
  const [estado, label] = e === "revision" ? ["verificando", "Pasar a verificación"] : ["aprobado", "Aprobar"];
  return <form className="learning-verdict" onSubmit={x => x.preventDefault()}>
    <label htmlFor={id + "-ev"}>Evidencia de esta etapa</label>
    <select id={id + "-ev"} value={ev} onChange={x => setEv(x.target.value)}>
      <option value="">Elegí una evidencia</option>
      {propias.map(n => <option key={n.id} value={n.id}>{n.texto}</option>)}
    </select>
    {propias.length === 0 && <p className="knowledge-note">No hay evidencia recibida en esta etapa: sin evidencia no se avanza.</p>}
    <label htmlFor={id + "-motivo"}>Motivo</label>
    <textarea id={id + "-motivo"} rows={2} value={motivo} onChange={x => setMotivo(x.target.value)} />
    <div className="learning-uses">
      <button type="button" className="primary" disabled={busy || !ev} onClick={() => act(node, estado, ev, motivo)}>{label}</button>
      <button type="button" disabled={busy || !motivo.trim()} onClick={() => act(node, "enviado", "", motivo)}>Devolver a implementación</button>
    </div>
  </form>;
}

export function Etapas({ base }: { base: string }) {
  const [encargos, setEncargos] = useState<Node[]>();
  const [rondas, setRondas] = useState<Record<string, string>>({});
  const [evidence, setEvidence] = useState<Node[]>([]);
  const [names, setNames] = useState<Record<string, string>>({});
  const [details, setDetails] = useState<Record<string, Detail>>({});
  const [person, setPerson] = useState(storedName);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const request = useRef<AbortController | null>(null);
  const opened = useRef(new Set<string>());
  const personId = useId();
  useEffect(() => () => request.current?.abort(), []);

  const recent = async (tipo: string, signal: AbortSignal) => {
    const first = page(await api.get<unknown>(`${base}/nodos?tipo=${tipo}&limite=100`, { signal }));
    if (first.total <= 100) return first.nodos;
    return page(await api.get<unknown>(`${base}/nodos?tipo=${tipo}&limite=100&desde=${first.total - 100}`, { signal })).nodos;
  };
  const readDetail = async (nid: string, signal?: AbortSignal) => detail(await api.get<unknown>(`${base}/nodos/${encodeURIComponent(nid)}`, { signal }));
  const load = async () => {
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    setLoading(true); setError("");
    try {
      const [e, r, ev, inf] = await Promise.all(["encargo", "ronda", "evidencia", "informe"].map(t => recent(t, controller.signal)));
      // la evidencia que ya estaba abierta se vuelve a leer: si no, quedaría la de antes del cambio
      const abiertos = await Promise.all([...opened.current].map(id => readDetail(id, controller.signal)));
      if (controller.signal.aborted) return;
      setEncargos(e.reverse());
      setRondas(Object.fromEntries(r.map(n => [n.id, title(n)])));
      setEvidence([...ev].reverse());
      setNames(Object.fromEntries([...ev, ...inf].map(n => [n.id, n.texto])));
      setDetails(Object.fromEntries(abiertos.map(d => [d.id, d])));
    } catch (err: unknown) {
      if (!controller.signal.aborted) { setEncargos(undefined); setError(failMsg("leer los encargos")(err)); }
    } finally { if (!controller.signal.aborted) setLoading(false); }
  };
  const toggle = async (n: Node, open: boolean) => {
    if (!open) { opened.current.delete(n.id); return; }
    opened.current.add(n.id);
    try {
      const d = await readDetail(n.id);
      setDetails(x => ({ ...x, [n.id]: d }));
    } catch (err: unknown) { setError(failMsg("leer la evidencia del encargo")(err)); }
  };
  const act = async (n: Node, estado: string, ev: string, motivo: string) => {
    const who = person.trim();
    if (!who) { setError("Escribí tu nombre: cada etapa queda firmada por una persona."); return; }
    try { localStorage.setItem(NAME_KEY, who); } catch { /* sin almacenamiento, se firma igual */ }
    setBusy(n.id); setError(""); setNotice("");
    try {
      // una sola escritura: el estado con la evidencia citada en su origen (el respaldo de la etapa)
      await api.post(`${base}/nodos/${encodeURIComponent(n.id)}/estado`,
        { estado, por: "persona:" + who, motivo: motivo.trim(), ...(ev ? { origen: { evidencia: ev } } : {}) });
      setNotice(estado === "enviado" ? `${title(n)} volvió a implementación.` : `${title(n)} pasó a ${estado === "aprobado" ? "aprobado" : "verificación"}.`);
      await load();
    } catch (err: unknown) { setError(failMsg("cambiar la etapa")(err)); } finally { setBusy(""); }
  };

  const groups = new Map<string, Node[]>();
  for (const n of encargos ?? []) groups.set(n.ronda ?? "", [...(groups.get(n.ronda ?? "") ?? []), n]);
  return <div className="knowledge-workspace">
    <form className="knowledge-query" onSubmit={e => { e.preventDefault(); void load(); }}>
      <h2>Etapas por encargo</h2>
      <p className="knowledge-note">Cada encargo recorre pendiente, implementación, revisión, verificación y aprobado. Un turno cerrado o la respuesta del agente sólo lo llevan a revisión: avanzar o aprobar lo firma una persona, con evidencia recibida en esa etapa.</p>
      <label htmlFor={personId}>Tu nombre (firma las etapas)</label>
      <input id={personId} value={person} onChange={e => setPerson(e.target.value)} autoComplete="name" />
      <div className="knowledge-query-actions"><button className="primary" type="submit" disabled={loading}>{loading ? "Leyendo…" : encargos ? "Volver a leer" : "Leer encargos"}</button></div>
    </form>
    <div className="knowledge-results" aria-busy={loading}>
      {error && <div className="knowledge-error" role="alert">{error}</div>}
      {notice && <div className="knowledge-notice" role="status">{notice}</div>}
      {encargos?.length === 0 && <p className="knowledge-empty">Este proyecto no tiene encargos registrados.</p>}
      {[...groups].map(([ronda, list]) => <section key={ronda} className="knowledge-section" aria-label={"Ronda " + (rondas[ronda] ?? ronda)}>
        <h3>{rondas[ronda] ?? (ronda || "Sin ronda")}</h3>
        <ul className="learning-cards">{list.map(n => {
          const e = etapa(n.estado);
          const devuelto = n.datos.devuelto_revision;
          const letra = typeof n.datos.letra === "string" ? n.datos.letra : "";
          return <li key={n.id} className="learning-card etapas-card" data-etapa={e}>
            <p className="learning-action">{letra ? `${letra} · ` : ""}{title(n)}</p>
            {e === "sin_entrega" ? <p className="learning-flag">Sin entrega: fuera del recorrido hasta que la coordinadora lo reabra.</p> : <Stepper estado={n.estado} />}
            <p className="knowledge-note">{n.estado_por ? `Último cambio: ${n.estado_por} · ${when(n.estado_fecha)}` : `Creado ${when(n.fecha)}`}{typeof devuelto === "number" ? ` · devuelto tras el informe r${devuelto}` : ""}</p>
            <details className="learning-evidence" onToggle={x => void toggle(n, (x.target as HTMLDetailsElement).open)}>
              <summary>Ver evidencia · {letra || n.id}</summary>
              {details[n.id] ? <Evidence d={details[n.id]} names={names} /> : <p role="status">Leyendo…</p>}
            </details>
            {/* la etapa nueva arranca con el formulario vacío: la evidencia y el motivo de la anterior no se arrastran */}
            <Actions key={`${n.estado}-${n.estado_fecha}`} node={n} evidence={evidence} busy={busy === n.id} act={act} />
          </li>;
        })}</ul>
      </section>)}
    </div>
  </div>;
}
