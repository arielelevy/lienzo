import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, failMsg } from "../api";
import "../knowledge.css";

type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
type RecordData = { [key: string]: Json };
interface Project { id: string; nombre?: string }
interface Topic { id: string; texto: string }
type View = "briefing" | "preguntar" | "vista" | "pendientes";
const VIEWS: { id: View; label: string }[] = [
  { id: "briefing", label: "Briefing" }, { id: "preguntar", label: "Buscar" },
  { id: "vista", label: "Vista por tema" }, { id: "pendientes", label: "Pendientes y avisos" },
];
const LABELS: Record<string, string> = {
  vigente: "Vigente", abierto: "Abierto", otros: "Relacionado", candidatos: "Resultados",
  pendientes: "Pendientes de veredicto", avisos: "Avisos", temas_sin_resolver: "Temas sin resolver",
  cambios: "Cambios desde el cierre", apoyos_rechazados: "Apoyos rechazados",
  reglas_cuestionadas: "Reglas cuestionadas", recurrencias: "Recurrencias",
  texto: "Texto", tipo: "Tipo", estado: "Estado", id: "ID", datos: "Datos",
  motivo: "Motivo", donde: "Ubicación", archivo: "Archivo", referencia: "Referencia",
  autor: "Autor", fecha: "Fecha", origen: "Origen", estado_por: "Veredicto de",
  estado_fecha: "Fecha del estado", procedencia: "Procedencia", puntaje: "Puntaje de búsqueda",
  salto: "Saltos", vinculos: "Vínculos", relacion: "Relación", de: "Desde", a: "Hacia",
  ronda: "Ronda", tardia: "Entrega tardía", cadenas: "Cadenas de respaldo",
  respaldos_caidos: "Respaldos rechazados", episodios: "Episodios", total: "Total",
  truncado: "Resultado recortado", desde_seq: "Desde el cambio", seq: "Cambio",
  ronda_cerrada: "Ronda cerrada", disponible: "Disponible", error: "Error",
  metrica: "Métrica", valor: "Valor", unidad: "Unidad", condicion: "Condiciones",
  aliases: "Otros nombres", para_quien: "Para quién", vigente_desde: "Vigente desde",
};
function label(key: string) { return Object.hasOwn(LABELS, key) ? LABELS[key] : key.replaceAll("_", " "); }
function record(value: unknown): value is RecordData { return value !== null && typeof value === "object" && !Array.isArray(value); }
function projects(value: unknown): Project[] {
  if (!Array.isArray(value) || value.some(p => !record(p) || typeof p.id !== "string" || (p.nombre !== undefined && typeof p.nombre !== "string")))
    throw new Error("La lista de proyectos no tiene el formato esperado");
  return value as Project[];
}
function topics(value: unknown): Topic[] {
  if (!record(value) || !Array.isArray(value.temas) || value.temas.some(t => !record(t) || typeof t.id !== "string" || typeof t.texto !== "string"))
    throw new Error("La lista de temas no tiene el formato esperado");
  return value.temas as unknown as Topic[];
}
function response(value: unknown, view: View): RecordData {
  if (!record(value)) throw new Error("La consulta no devolvió un objeto válido");
  const lists = view === "briefing" ? ["vigente", "abierto", "otros"] : view === "preguntar" ? ["candidatos"] : view === "pendientes" ? ["pendientes"] : [];
  if (lists.some(k => !Array.isArray(value[k])) || (view === "vista" && typeof value.markdown !== "string"))
    throw new Error("La consulta no tiene el formato esperado");
  if (view === "preguntar" && (!Number.isInteger(value.offset) || Number(value.offset) < 0 || !Number.isInteger(value.limite) || Number(value.limite) < 1 || !Number.isInteger(value.total) || Number(value.total) < 0 || (value.siguientes !== null && (!Number.isInteger(value.siguientes) || Number(value.siguientes) <= Number(value.offset)))))
    throw new Error("La búsqueda no devolvió una paginación válida");
  return value;
}

/** Las lecturas automáticas sólo cargan catálogos. El cleanup cancela también respuestas tardías. */
function useCatalog<T>(path: string, parse: (data: unknown) => T) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    void api.get<unknown>(path, { signal: controller.signal }).then(parse).then(result => {
      if (!controller.signal.aborted) setData(result);
    }).catch((err: unknown) => {
      if (!controller.signal.aborted) setError(failMsg("leer el catálogo")(err));
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [path, parse, revision]);
  return { data, error, loading, reload: () => { setData(undefined); setError(""); setLoading(true); setRevision(r => r + 1); } };
}

function Markdown({ text }: { text: string }) {
  return <div className="knowledge-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{
    a: ({ children, href }) => <a href={href} target="_blank" rel="noreferrer noopener">{children}</a>,
    img: ({ alt }) => <span>[Imagen: {alt || "sin descripción"}]</span>,
  }}>{text}</ReactMarkdown></div>;
}
function Value({ value }: { value: Json }) {
  if (value === null) return <span className="knowledge-muted">Sin dato</span>;
  if (typeof value === "boolean") return <span>{value ? "Sí" : "No"}</span>;
  if (typeof value !== "object") return <span className="knowledge-value">{String(value)}</span>;
  if (Array.isArray(value)) return value.length ? <ul className="knowledge-values">{value.map((v, i) => <li key={i}><Value value={v} /></li>)}</ul> : <span className="knowledge-muted">Sin elementos</span>;
  return <div>{typeof value.error === "string" && <p role="alert" className="knowledge-error">{value.error}</p>}<dl className="knowledge-fields">{Object.entries(value).filter(([k]) => k !== "error").map(([k, v]) => <div key={k}><dt>{label(k)}</dt><dd><Value value={v} /></dd></div>)}</dl></div>;
}
function Nodes({ value, empty }: { value: Json; empty: string }) {
  if (!Array.isArray(value)) return <Value value={value} />;
  if (!value.length) return <p className="knowledge-empty">{empty}</p>;
  return <ul className="knowledge-nodes">{value.map((node, i) => {
    if (!record(node) || typeof node.texto !== "string") return <li key={i}><Value value={node} /></li>;
    const { texto, tipo, estado, id, tardia, ...extra } = node;
    return <li key={typeof id === "string" ? id : i}>
      <div className="knowledge-node-status"><span>{typeof tipo === "string" ? label(tipo) : "Registro"}</span>{typeof estado === "string" && <strong>{label(estado)}</strong>}{tardia === true && <strong>Entrega tardía</strong>}</div>
      <Markdown text={texto as string} />
      <details><summary>Origen y respaldo{typeof id === "string" ? " · " + id : ""}</summary><Value value={extra} /></details>
    </li>;
  })}</ul>;
}
function Readout({ data, view }: { data: RecordData; view: View }) {
  if (view === "vista") return <Markdown text={data.markdown as string} />;
  const groups = view === "briefing" ? ["vigente", "abierto", "otros"] : view === "preguntar" ? ["candidatos"] : ["pendientes"];
  return <>
    {view === "preguntar" && <p className="knowledge-note">{typeof data.total === "number" ? data.total : (data.candidatos as Json[]).length} resultados. Son candidatos con su respaldo; una búsqueda vacía no prueba que algo no exista.</p>}
    {Array.isArray(data.temas_sin_resolver) && data.temas_sin_resolver.length > 0 && <section className="knowledge-notice"><h3>Temas sin resolver</h3><Value value={data.temas_sin_resolver} /></section>}
    {data.truncado === true && <p className="knowledge-notice">El servidor recortó este resultado. Puede haber más registros.</p>}
    {groups.map(k => <section key={k} className="knowledge-section"><h3>{label(k)}</h3><Nodes value={data[k]} empty={k === "candidatos" ? "No hay coincidencias. Probá otras palabras, temas o archivos." : "Sin registros en esta sección."} /></section>)}
    {view === "briefing" && data.cambios !== null && data.cambios !== undefined && <section className="knowledge-section"><h3>Cambios desde el cierre</h3><Value value={data.cambios} /></section>}
    {data.avisos !== undefined && <section className="knowledge-section"><h3>Avisos</h3><Value value={data.avisos} /></section>}
  </>;
}
function lines(text: string) { return text.split(/\r?\n/).map(s => s.trim()).filter(Boolean); }

function ProjectPanel({ id }: { id: string }) {
  const base = "/conocimiento/" + encodeURIComponent(id);
  const catalog = useCatalog(base + "/temas", topics);
  const [view, setView] = useState<View>("briefing");
  const [queries, setQueries] = useState("");
  const [files, setFiles] = useState("");
  const [themes, setThemes] = useState("");
  const [theme, setTheme] = useState("");
  const [hops, setHops] = useState("1");
  const [data, setData] = useState<RecordData>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const request = useRef<AbortController>();
  const fieldId = useId();
  useEffect(() => () => request.current?.abort(), []);
  const clear = () => { request.current?.abort(); setLoading(false); setData(undefined); setError(""); };
  const selectView = (next: View) => { clear(); setView(next); };
  const query = async (offset = 0, keepPage = false) => {
    request.current?.abort(); setError("");
    if (!keepPage) setData(undefined);
    const q = lines(queries), archives = lines(files), refs = lines(themes);
    if (q.length > 10) { setError("Usá hasta 10 consultas, una por línea."); return; }
    if (view === "preguntar" && !q.length && !archives.length && !refs.length) { setError("Escribí una consulta, un archivo o un tema para buscar."); return; }
    if (view === "vista" && !theme) { setError("Elegí un tema para generar la vista."); return; }
    const controller = new AbortController(); request.current = controller; setLoading(true);
    const params = new URLSearchParams();
    if (view === "briefing" || view === "preguntar") {
      q.forEach(x => params.append("q", x)); archives.forEach(x => params.append("archivos", x)); refs.forEach(x => params.append("temas", x));
    }
    if (view === "preguntar") { params.set("saltos", hops); params.set("offset", String(offset)); params.set("limite", "100"); }
    if (view === "vista") params.set("tema", theme);
    try {
      const result = response(await api.get<unknown>(base + "/" + view + "?" + params.toString(), { signal: controller.signal }), view);
      if (view === "pendientes") {
        // Mostrar los pendientes aunque falle la lectura independiente de avisos.
        try { result.avisos = await api.get<Json>(base + "/avisos", { signal: controller.signal }); }
        catch (err: unknown) { if (!controller.signal.aborted) result.avisos = { error: failMsg("leer los avisos")(err) }; }
      }
      if (!controller.signal.aborted) setData(result);
    } catch (err: unknown) {
      if (!controller.signal.aborted) setError(failMsg("consultar la memoria")(err));
    } finally { if (!controller.signal.aborted) setLoading(false); }
  };
  return <div className="knowledge-body">
    <nav className="knowledge-nav" aria-label="Consultas de memoria">{VIEWS.map(v => <button key={v.id} type="button" aria-pressed={view === v.id} onClick={() => selectView(v.id)}>{v.label}</button>)}</nav>
    <div className="knowledge-workspace">
      <form className="knowledge-query" onSubmit={e => { e.preventDefault(); void query(); }}>
        <h2>{VIEWS.find(v => v.id === view)!.label}</h2>
        {(view === "briefing" || view === "preguntar") && <>
          <label htmlFor={fieldId + "-queries"}>Consultas, una por línea</label><textarea id={fieldId + "-queries"} value={queries} rows={2} placeholder='"base compartida" OR bloqueo' onChange={e => { clear(); setQueries(e.target.value); }} />
          <p className="knowledge-note">Usá palabras o expresiones de búsqueda: comillas para una frase, OR para alternativas y * para prefijos.</p>
          <details className="knowledge-filters"><summary>Filtrar por archivos o temas</summary>
            <label htmlFor={fieldId + "-files"}>Archivos o carpetas, uno por línea</label><textarea id={fieldId + "-files"} value={files} rows={2} placeholder="web/src/components/" onChange={e => { clear(); setFiles(e.target.value); }} />
            <label htmlFor={fieldId + "-themes"}>Temas, uno por línea</label><textarea id={fieldId + "-themes"} value={themes} rows={2} onChange={e => { clear(); setThemes(e.target.value); }} />
            {catalog.data && catalog.data.length > 0 && <p className="knowledge-note">Temas disponibles: {catalog.data.map(t => t.texto).join(", ")}</p>}
          </details>
          {view === "preguntar" && <label className="knowledge-hops">Relaciones a recorrer<select aria-label="Saltos de relaciones" value={hops} onChange={e => { clear(); setHops(e.target.value); }}><option value="0">Sin expandir</option><option value="1">Un salto</option><option value="2">Dos saltos</option></select></label>}
        </>}
        {view === "vista" && <><label htmlFor={fieldId + "-theme"}>Tema de la vista</label><select id={fieldId + "-theme"} value={theme} onChange={e => { clear(); setTheme(e.target.value); }}><option value="">Elegí un tema</option>{catalog.data?.map(t => <option key={t.id} value={t.id}>{t.texto}</option>)}</select>{catalog.loading && <p role="status">Cargando temas…</p>}{catalog.data?.length === 0 && <p className="knowledge-note">Este proyecto no tiene temas registrados.</p>}</>}
        {catalog.error && <div className="knowledge-error" role="alert"><p>{catalog.error}</p><button type="button" onClick={catalog.reload}>Reintentar temas</button></div>}
        {view === "pendientes" && <p className="knowledge-note">Leé lo que espera veredicto y los apoyos rechazados. Consultar no cambia estados.</p>}
        <div className="knowledge-query-actions"><button className="primary" type="submit" disabled={loading}>{loading ? "Consultando…" : view === "briefing" ? "Leer briefing" : view === "vista" ? "Generar vista" : view === "pendientes" ? "Leer pendientes y avisos" : "Buscar"}</button>{loading && <button type="button" onClick={clear}>Cancelar consulta</button>}</div>
      </form>
      <div className="knowledge-results" aria-busy={loading}>
        {loading && <p role="status">Leyendo la memoria del proyecto…</p>}
        {error && <div role="alert" className="knowledge-error">{error}</div>}
        {!loading && !error && !data && <p className="knowledge-empty">Elegí los filtros y consultá. Los resultados conservan el estado y su respaldo.</p>}
        {data && <Readout data={data} view={view} />}
        {view === "preguntar" && data && <nav className="knowledge-pagination" aria-label="Páginas de resultados">
          <p>{(data.candidatos as Json[]).length ? "Mostrando " + (Number(data.offset) + 1) + "–" + (Number(data.offset) + (data.candidatos as Json[]).length) + " de " + data.total : "Sin resultados en esta página"}</p>
          <div><button type="button" disabled={loading || Number(data.offset) === 0} onClick={() => { void query(Math.max(0, Number(data.offset) - Number(data.limite)), true); }}>Anterior</button>
          <button type="button" disabled={loading || data.siguientes === null} onClick={() => { if (typeof data.siguientes === "number") void query(data.siguientes, true); }}>Más resultados</button></div>
        </nav>}
      </div>
    </div>
  </div>;
}

/** Panel de sólo consulta. El proyecto se elige explícitamente, sin crear ni cambiar registros. */
export function Knowledge({ onClose }: { onClose: () => void }) {
  const catalog = useCatalog("/conocimiento/proyectos", projects);
  const [project, setProject] = useState("");
  const box = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  const titleId = useId();
  useEffect(() => { close.current = onClose; }, [onClose]);
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const root = document.getElementById("root"), wasInert = root?.inert;
    if (root) root.inert = true;
    box.current?.querySelector<HTMLElement>("button")?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); event.stopImmediatePropagation(); close.current(); return; }
      if (event.key !== "Tab") return;
      const focusable = [...(box.current?.querySelectorAll<HTMLElement>('button:not(:disabled), select:not(:disabled), input:not(:disabled), textarea:not(:disabled), a[href], summary, [tabindex="0"]') ?? [])].filter(el => el.getClientRects().length > 0);
      const first = focusable[0], last = focusable.at(-1);
      if (!first || !last) { event.preventDefault(); box.current?.focus(); return; }
      if (!box.current?.contains(document.activeElement) || (event.shiftKey && document.activeElement === first)) { event.preventDefault(); (event.shiftKey ? last : first).focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", keydown, true);
    return () => { document.removeEventListener("keydown", keydown, true); if (root) root.inert = wasInert ?? false; if (previous?.isConnected) previous.focus(); };
  }, []);
  const selected = catalog.data?.some(p => p.id === project) ? project : "";
  return createPortal(<div className="gate knowledge-gate" onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div ref={box} className="knowledge" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
      <div className="knowledge-heading"><div><h1 id={titleId}>Memoria del proyecto</h1><p>Decisiones, hallazgos y respaldos, con su estado actual.</p></div><button type="button" aria-label="Cerrar memoria" onClick={onClose}>Cerrar</button></div>
      <div className="knowledge-project"><label htmlFor={titleId + "-project"}>Proyecto</label><select id={titleId + "-project"} value={selected} disabled={catalog.loading} onChange={e => setProject(e.target.value)}><option value="">Elegí un proyecto</option>{catalog.data?.map(p => <option key={p.id} value={p.id}>{p.nombre || p.id}</option>)}</select><button type="button" onClick={catalog.reload} disabled={catalog.loading}>Actualizar proyectos</button></div>
      {catalog.loading && <p className="knowledge-feedback" role="status">Cargando proyectos…</p>}
      {catalog.error && <div className="knowledge-feedback knowledge-error" role="alert">{catalog.error}</div>}
      {catalog.data?.length === 0 && <p className="knowledge-feedback">No hay proyectos registrados. La coordinadora puede registrar uno desde el lienzo.</p>}
      {catalog.data && catalog.data.length > 0 && !selected && <p className="knowledge-feedback">Elegí el proyecto que querés consultar.</p>}
      {selected && <ProjectPanel key={selected} id={selected} />}
    </div>
  </div>, document.body);
}
