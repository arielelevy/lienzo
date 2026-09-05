import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { DigestResponse, Session } from "../types";

const DEFAULT_TEMPLATE = "Mensaje de {repo} ({agente}) sobre '{titulo}':\n{respuesta}";
const KEY = "lienzo.forward.template";

function loadTemplate(): string {
  try {
    return localStorage.getItem(KEY) || DEFAULT_TEMPLATE;
  } catch {
    return DEFAULT_TEMPLATE;
  }
}

function fill(tpl: string, s: Session, reply: string): string {
  return tpl
    .replaceAll("{repo}", s.repo)
    .replaceAll("{agente}", s.agent)
    .replaceAll("{titulo}", s.title || "")
    .replaceAll("{pedido}", s.last_prompt || "")
    .replaceAll("{respuesta}", reply);
}

interface Props {
  from: Session;
  others: Session[];
  initialTarget?: string;
  toast: (msg: string, err?: boolean) => void;
  onDone: () => void;
}

/** Reenvio manual: la ultima respuesta de esta sesion como pedido a otra, con plantilla editable.
 *  No hay vinculo automatico: cada reenvio es un click, para que dos agentes no se contesten solos. */
export function Forward({ from, others, initialTarget, toast, onDone }: Props) {
  const [target, setTarget] = useState(
    initialTarget && others.some((o) => o.session_id === initialTarget) ? initialTarget : others[0]?.session_id ?? "",
  );
  const [template, setTemplate] = useState(loadTemplate);
  // la respuesta a reenviar es la ultima respuesta FINAL de la transcripcion, no el estado en
  // vivo ("usando Bash") que muestra la tarjeta mientras corre
  const [reply, setReply] = useState(from.last_reply || "");
  const [text, setText] = useState(() => fill(loadTemplate(), from, from.last_reply || ""));
  const [busy, setBusy] = useState(false);
  const targetSession = useMemo(() => others.find((o) => o.session_id === target), [others, target]);

  useEffect(() => {
    api.get<DigestResponse>(`/sessions/${from.session_id}/digest?n=5`).then((d) => {
      const last = [...d.turns].reverse().find((t) => t.final && t.final.trim());
      if (last) {
        setReply(last.final);
        setText(fill(template, from, last.final));
      }
    }).catch(() => null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [from.session_id]);

  const applyTemplate = (tpl: string) => {
    setTemplate(tpl);
    setText(fill(tpl, from, reply));
    try {
      localStorage.setItem(KEY, tpl);
    } catch {
      /* sin storage, no importa */
    }
  };

  const send = async () => {
    if (!targetSession) return;
    if (targetSession.pending_id) {
      toast("La sesión destino tiene un permiso pendiente", true);
      return;
    }
    setBusy(true);
    try {
      const r = await api.post<{ chars: number }>(`/sessions/${targetSession.session_id}/send`, {
        text,
        attachments: [],
        from: from.session_id, // el server registra el vinculo y el tablero dibuja la flecha
      });
      toast(`Reenviado a ${targetSession.repo} (${r.chars} caracteres)`);
      onDone();
    } catch (e) {
      toast(`No se pudo reenviar: ${(e as Error).message}`, true);
    } finally {
      setBusy(false);
    }
  };

  if (!others.length) return <div className="fwd empty">No hay otra sesión viva a la que reenviar.</div>;

  return (
    <div className="fwd">
      <div className="row">
        <span className="small dim">Reenviar a</span>
        <select value={target} onChange={(e) => setTarget(e.target.value)}>
          {others.map((o) => (
            <option key={o.session_id} value={o.session_id}>
              {o.agent} · {o.repo} · {o.title || o.last_prompt || o.session_id.slice(0, 8)}
            </option>
          ))}
        </select>
      </div>
      <details>
        <summary className="small dim pointer">plantilla ({"{repo} {agente} {titulo} {pedido} {respuesta}"})</summary>
        <textarea value={template} onChange={(e) => applyTemplate(e.target.value)} rows={3} />
      </details>
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={6} />
      <div className="row">
        <span className="small dim">Si supera 500 caracteres viaja como adjunto .md</span>
        <span className="sp" />
        <button onClick={onDone}>Cancelar</button>
        <button className="primary" disabled={busy || !text.trim() || !targetSession} onClick={send}>
          Reenviar
        </button>
      </div>
    </div>
  );
}
