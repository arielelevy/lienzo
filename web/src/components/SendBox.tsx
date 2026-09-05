import { useRef, useState } from "react";
import { api } from "../api";
import type { Session } from "../types";
import "../card.css";

const QUICK = ["Continuá", "sí", "no", "dale"];

/** alguien esta escribiendo en esa terminal: lo que se mande se mezcla con lo suyo */
const isTyping = (s: Session): boolean => !!s.typing;

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
    if (isTyping(s) && !confirm("Están tipeando en esa terminal; lo que mandes se mezcla con lo que escriben. Enviar igual?")) return;
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

  const disabled = busy || !!s.pending_id || !s.alive || !!s.orphan || !!s.no_console;

  if (s.no_console && !s.orphan) {
    return (
      <div className="send">
        <div className="small dim">
          Esta sesión corre en el panel de Claude Code de VS Code o en una app de escritorio: no tiene consola, así que se
          puede leer pero no escribirle desde acá. Otra sesión de Claude sí puede hablarle con el canal nativo.
        </div>
      </div>
    );
  }
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
      {isTyping(s) && (
        <div className="typing-warn" role="alert">
          ⌨ están tipeando en esa terminal; lo que mandes se mezcla
        </div>
      )}
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
      <div className="inputwrap">
        {/* sugerencia leida de la terminal: gris detras del texto, Tab la acepta (como en Claude Code) */}
        {!text && s.suggestion && !s.pending_id && <div className="ghost">{s.suggestion}<span className="tabhint">Tab</span></div>}
        <textarea
          value={text}
          disabled={disabled}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Tab" && !text && s.suggestion) {
              e.preventDefault();
              setText(s.suggestion);
              return;
            }
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(text);
            }
          }}
          placeholder={
            s.pending_id
              ? "Hay un permiso pendiente: contestalo arriba"
              : s.suggestion
                ? ""
                : "Mensaje para la sesión. Enter envía, Shift+Enter salto. Más de 500 caracteres o varias líneas viajan como adjunto .md"
          }
        />
      </div>
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
