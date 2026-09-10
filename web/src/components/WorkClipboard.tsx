import { useCallback, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import { api } from "../api";
import { canWrite, shortName } from "../names";
import type { DigestResponse, Session } from "../types";

type Work = { from: string; name: string; text: string };
let clipboard: Work | null = null;
let copying = false;
const watchers = new Set<() => void>();
const subscribe = (cb: () => void) => { watchers.add(cb); return () => { watchers.delete(cb); }; };

export function useWorkClipboard(s: Session, pending: boolean, toast: (text: string, error?: boolean) => void) {
  const work = useSyncExternalStore(subscribe, () => clipboard);
  const [draft, setDraft] = useState<Work | null>(null);
  const [busy, setBusy] = useState(false);
  const sending = useRef(false);
  const openDialog = useCallback((el: HTMLDialogElement | null) => {
    if (el && !el.open) el.showModal();
  }, []);
  const canCopy = !!(s.last_prompt || s.last_reply);
  const canPaste = !!work && work.from !== s.session_id && canWrite(s) && !pending;
  const copy = async () => {
    if (!canCopy || copying) return;
    copying = true;
    try {
      const d = await api.get<DigestResponse>(`/sessions/${s.session_id}/digest?n=5`);
      const turns = d.turns.map((t) => [
        `Pedido: ${t.prompt}`, ...(t.says || []), t.final,
        t.files.length ? `Archivos: ${t.files.join(", ")}` : "",
        t.commands.length ? `Comandos: ${t.commands.join("\n")}` : "",
        ...t.errors.map((e) => `Error: ${e}`), ...t.questions.map((q) => `Pregunta pendiente: ${q}`),
      ].filter(Boolean).join("\n")).join("\n\n");
      clipboard = {
        from: s.session_id, name: shortName(s),
        text: [`Continuá este trabajo desde el estado que se describe abajo. Revisá lo que falta antes de actuar.`,
          `Origen: ${shortName(s)} (${s.agent})`, `Carpeta: ${s.cwd || s.repo}`, s.branch ? `Rama: ${s.branch}` : "",
          `Último pedido: ${s.last_prompt}`, `Última respuesta: ${s.last_reply}`,
          turns ? `Contexto de los últimos 5 turnos disponibles:\n${turns}` : "Sin historial adicional disponible.",
        ].filter(Boolean).join("\n\n"),
      };
      for (const cb of watchers) cb();
      toast("Trabajo copiado. Elegí otra tarjeta y pegalo con Ctrl+V o desde su menú.");
    } catch (e) {
      toast(`No se pudo copiar el trabajo: ${(e as Error).message}`, true);
    } finally { copying = false; }
  };
  const paste = () => { if (canPaste && work) setDraft({ ...work }); };
  const send = async () => {
    if (!draft || sending.current || !canWrite(s) || pending || !draft.text.trim()) return;
    sending.current = true;
    setBusy(true);
    try {
      await api.post(`/sessions/${s.session_id}/send`, { text: draft.text, from: draft.from, attachments: [] });
      setDraft(null);
      toast(`Trabajo enviado a ${shortName(s)}`);
    } catch (e) {
      toast(`No se pudo pegar el trabajo: ${(e as Error).message}`, true);
    } finally { sending.current = false; setBusy(false); }
  };
  const preview = draft && createPortal(
    <dialog ref={openDialog}
      aria-label="Pegar trabajo" className="workpreview"
      onCancel={(e) => { e.preventDefault(); if (!busy) setDraft(null); }}
      onKeyDown={(e) => e.stopPropagation()} onClick={(e) => e.stopPropagation()}>
      <h2>Pegar trabajo en {shortName(s)}</h2>
      <p>Desde {draft.name}. Se copia el contexto; la sesión de origen sigue abierta y no se detiene.</p>
      <textarea autoFocus aria-label="Trabajo a enviar" value={draft.text} disabled={busy}
        onChange={(e) => setDraft({ ...draft, text: e.target.value })} />
      <div className="row">
        <button disabled={busy} onClick={() => setDraft(null)}>Cancelar</button>
        <button className="primary" disabled={busy || !canWrite(s) || pending || !draft.text.trim()} onClick={send}>
          {busy ? "Enviando…" : "Enviar trabajo"}
        </button>
      </div>
    </dialog>, document.body,
  );
  return { canCopy, canPaste, copy, paste, preview };
}
