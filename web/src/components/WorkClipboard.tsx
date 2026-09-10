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

/** Lo que la copia le manda a la de origen cuando termina, en modo "Duplicar": un solo sentido y una
 *  sola vez, porque la conexión en los dos sentidos es el bucle A↔B que el server rechaza. */
const REPORT_TEMPLATE = "Informe de {repo} ({agente}), que trabajó en paralelo sobre '{titulo}':\n{respuesta}";

export function useWorkClipboard(s: Session, pending: boolean, toast: (text: string, error?: boolean) => void) {
  const work = useSyncExternalStore(subscribe, () => clipboard);
  const [draft, setDraft] = useState<Work | null>(null);
  const [duplicate, setDuplicate] = useState(false);
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
  const paste = () => { if (canPaste && work) { setDuplicate(false); setDraft({ ...work }); } };
  const send = async () => {
    if (!draft || sending.current || !canWrite(s) || pending || !draft.text.trim()) return;
    sending.current = true;
    setBusy(true);
    try {
      // copycat: la copia hereda el título; stop_origin: la de origen recibe un Esc y queda "stopped"
      const r = await api.post<{ interrupted?: boolean }>(`/sessions/${s.session_id}/send`, {
        text: draft.text, from: draft.from, attachments: [], copycat: true, stop_origin: !duplicate,
      });
      let extra = "";
      if (duplicate) {
        try {
          await api.post("/rules", { kind: "on_stop", from: s.session_id, to: draft.from, text: REPORT_TEMPLATE, max_fires: 1 });
          extra = `; cuando termine, su informe va a ${draft.name}`;
        } catch (e) {
          extra = `; no se pudo conectar el informe de vuelta: ${(e as Error).message}`;
        }
      } else {
        extra = r?.interrupted ? `; ${draft.name} detenida` : `; ${draft.name} no estaba corriendo, no se tocó`;
      }
      setDraft(null);
      toast(`Trabajo enviado a ${shortName(s)}${extra}`);
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
      <p>
        Desde {draft.name}. Esta tarjeta hereda el título con la marca copycat y, salvo que dupliques,
        {" "}{draft.name} recibe un Esc si está corriendo y queda como detenida, para que no lo hagan las dos.
      </p>
      <textarea autoFocus aria-label="Trabajo a enviar" value={draft.text} disabled={busy}
        onChange={(e) => setDraft({ ...draft, text: e.target.value })} />
      <label className="dup">
        <input type="checkbox" checked={duplicate} disabled={busy} onChange={(e) => setDuplicate(e.target.checked)} />
        {" "}Duplicar: las dos siguen trabajando, y cuando esta termine le manda su informe a {draft.name} (una vez)
      </label>
      <div className="row">
        <button disabled={busy} onClick={() => setDraft(null)}>Cancelar</button>
        <button className="primary" disabled={busy || !canWrite(s) || pending || !draft.text.trim()} onClick={send}>
          {busy ? "Enviando…" : duplicate ? "Duplicar trabajo" : "Enviar y detener origen"}
        </button>
      </div>
    </dialog>, document.body,
  );
  return { canCopy, canPaste, copy, paste, preview };
}
