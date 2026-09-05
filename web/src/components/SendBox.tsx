import { useRef, useState } from "react";
import { api } from "../api";
import type { Session } from "../types";

const QUICK = ["Continuá", "sí", "no", "dale"];

interface Props {
  session: Session;
  toast: (msg: string, err?: boolean) => void;
}

export function SendBox({ session: s, toast }: Props) {
  const [text, setText] = useState("");
  const [attachments, setAttachments] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const upload = async (files: FileList | File[]) => {
    for (const f of Array.from(files)) {
      try {
        const r = await api.upload(s.session_id, f);
        setAttachments((a) => [...a, r.path]);
      } catch (e) {
        toast(`adjunto: ${(e as Error).message}`, true);
      }
    }
  };

  const send = async (t: string) => {
    if (s.pending_id) {
      toast("Hay un permiso pendiente, contestalo primero", true);
      return;
    }
    if (!t.trim() && attachments.length === 0) return;
    setBusy(true);
    try {
      const r = await api.post<{ chars: number }>(`/sessions/${s.session_id}/send`, { text: t, attachments });
      toast(`Enviado (${r.chars} caracteres)`);
      setText("");
      setAttachments([]);
    } catch (e) {
      toast(`No se pudo enviar: ${(e as Error).message}`, true);
    } finally {
      setBusy(false);
    }
  };

  const disabled = busy || !!s.pending_id || !s.alive || !!s.orphan;

  if (s.orphan) {
    return (
      <div className="send">
        <div className="small dim">
          Esta sesión perdió su terminal de VS Code (el shell padre murió). El proceso sigue vivo y se puede leer,
          pero no hay consola donde escribirle. Si la necesitás, reabrila desde VS Code con <code>claude --resume</code>.
        </div>
      </div>
    );
  }

  return (
    <div
      className={`send ${drag ? "drag" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        if (e.dataTransfer.files.length) upload(e.dataTransfer.files);
      }}
    >
      <div className="row quick">
        {QUICK.map((q) => (
          <button key={q} disabled={disabled} onClick={() => send(q)}>
            {q}
          </button>
        ))}
        <span className="sp" />
        <label className="small pointer">
          📎 adjuntar
          <input ref={fileRef} type="file" multiple hidden onChange={(e) => e.target.files && upload(e.target.files)} />
        </label>
      </div>
      <textarea
        value={text}
        disabled={disabled}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            send(text);
          }
        }}
        placeholder={
          s.pending_id
            ? "Hay un permiso pendiente: contestalo arriba"
            : "Mensaje para la sesión. Enter envía, Shift+Enter salto. Más de 500 caracteres o varias líneas viajan como adjunto .md"
        }
      />
      <div className="row">
        <div className="att">
          {attachments.map((a) => (
            <span key={a} title={a}>
              {a.split(/[\\/]/).pop()}
            </span>
          ))}
        </div>
        <span className="sp" />
        <button className="primary" disabled={disabled} onClick={() => send(text)}>
          Enviar
        </button>
      </div>
    </div>
  );
}
