import { useEffect, useId, useRef, useState } from "react";
import { api } from "../api";

type Item = { id: string; proyecto: string; accion: string; motivo: string; deshecho: boolean };
type Batch = { id: string | null; fecha?: string; agente?: string; hay_mas?: boolean; items: Item[]; no_evaluables?: { id: string; texto: string }[] };

/** AB: sólo el botón y el resumen; la vista de Aprendizaje conserva su organización. */
export default function LearningReviewIA({ base, changed }: { base: string; changed: () => Promise<void> }) {
  const label = useId();
  const [agent, setAgent] = useState("claude");
  const [batches, setBatches] = useState<Batch[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const reading = useRef<AbortController>();
  useEffect(() => {
    const controller = new AbortController();
    reading.current = controller;
    void api.get<Batch[]>(base + "/revision-ia", { signal: controller.signal }).then(
      data => { if (!controller.signal.aborted && Array.isArray(data)) setBatches(data); },
      e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "No se pudo leer la tanda anterior"); },
    );
    return () => controller.abort();
  }, [base]);
  const act = async (path: string, body: object) => {
    reading.current?.abort();
    setBusy(true); setError(""); setNote("");
    try {
      const result = await api.post<Batch>(path, body);
      if (!result.id) setNote("No hay propuestas pendientes.");
      else setBatches(rows => [result, ...rows.filter(row => row.id !== result.id)].slice(0, 10));
      await changed();
    } catch (e) { setError(e instanceof Error ? e.message : "La revisión IA falló; consultá la tanda antes de reintentar"); }
    finally { setBusy(false); }
  };
  // «todo»: sigue tanda tras tanda mientras el server diga que quedan; un error o una tanda vacía la cortan
  const reviewAll = async () => {
    reading.current?.abort();
    setBusy(true); setError(""); setNote("");
    let done = 0;
    try {
      for (let round = 0; round < 10; round++) {
        setNote(round ? `Tanda ${round + 1}…` : "");
        const result = await api.post<Batch>(base + "/revision-ia", { agente: agent });
        if (!result.id) break;
        done += result.items.length;
        setBatches(rows => [result, ...rows.filter(row => row.id !== result.id)].slice(0, 10));
        if (!result.hay_mas || !result.items.length) break;
      }
      setNote(done ? `Revisadas ${done} propuestas.` : "No hay propuestas pendientes.");
    } catch (e) {
      setNote(done ? `Revisadas ${done} propuestas antes del error.` : "");
      setError(e instanceof Error ? e.message : "La revisión IA falló; consultá la tanda antes de reintentar");
    } finally {
      await changed();
      setBusy(false);
    }
  };
  return <section aria-label="Revisión delegada a IA" aria-busy={busy}>
    <label htmlFor={label}>IA que revisa</label>
    <select id={label} value={agent} disabled={busy} onChange={e => setAgent(e.target.value)}>
      <option value="claude">Claude</option><option value="codex">Codex</option>
    </select>
    <button type="button" disabled={busy} onClick={() => void reviewAll()}>
      {busy ? "Procesando tandas…" : "Revisar todo con IA"}
    </button>
    <p className="knowledge-note">Revisa todas las propuestas de este proyecto y de proceso de Lienzo, de a tandas de hasta 20 (90 s cada una). Aplica los veredictos con la firma delegada de Ariel. Podés deshacerlos.</p>
    {error && <p role="alert" className="knowledge-error">{error}</p>}
    {note && <p role="status">{note}</p>}
    {batches.map(batch => <div key={batch.id} role="group" aria-label={"Tanda " + batch.id}>
      <p>Revisión con {batch.agente} · {batch.items.length} propuestas{batch.fecha ? " · " + new Date(batch.fecha).toLocaleString() : ""}.</p>
      {batch.hay_mas && <p role="status">Quedan propuestas: revisá otra tanda.</p>}
      {!!batch.no_evaluables?.length && <p role="status">{batch.no_evaluables.length} quedaron sin revisar: su evidencia adjunta no se pudo leer entera.</p>}
      <button type="button" disabled={busy || batch.items.every(i => i.deshecho)} onClick={() => void act(`${base}/revision-ia/${batch.id}/deshacer`, {})}>Deshacer toda la tanda</button>
      <ul>{batch.items.map(item => <li key={item.id}>
        <span>{item.proyecto} · {item.accion}: {item.motivo}{item.deshecho ? " · Deshecho" : ""}</span>{" "}
        <button type="button" aria-label={"Deshacer " + item.id} disabled={busy || item.deshecho}
          onClick={() => void act(`${base}/revision-ia/${batch.id}/deshacer`, { creencia: item.id })}>Deshacer</button>
      </li>)}</ul>
    </div>)}
  </section>;
}
