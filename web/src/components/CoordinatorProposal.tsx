import { useState } from "react";
import { api, failMsg, sessionsApi } from "../api";
import type { Session } from "../types";

export function CoordinatorProposal({ session: s }: { session: Session }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const p = s.coordinator_proposal;
  if (!p || !s.alive || s.stopped_by) return null;
  const apply = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try { await action(); }
    catch (e) { setError(failMsg("guardar la propuesta")(e)); }
    finally { setBusy(false); }
  };
  return <section className="sugg" aria-label="Propuesta de coordinadora" onClick={e => e.stopPropagation()}>
    <p>{p.reason}</p>
    <p>Título propuesto: {p.title}</p>
    {p.kind === "role" && !s.coordinator && <button type="button" disabled={busy} onClick={() => void apply(() => sessionsApi.coordinator(s.session_id, true))}>Marcar coordinadora</button>}
    {s.coordinator && <button type="button" disabled={busy} onClick={() => void apply(() => sessionsApi.title(s.session_id, p.title))}>Usar título propuesto</button>}
    <button type="button" disabled={busy} onClick={() => void apply(() => api.post(`/sessions/${encodeURIComponent(s.session_id)}/orphan`, { dismiss_proposal: true }))}>Descartar propuesta</button>
    {error && <p role="alert">{error}</p>}
  </section>;
}
