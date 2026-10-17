import { useEffect, useMemo, useRef, useState } from "react";
import { api, rulesApi, sendNotice, sessionsApi } from "../api";
import { AGENTS } from "../agents";
import { coordinatorOf } from "../nl";
import type { Session } from "../types";
import { canWrite, needsPiReload, REPLY_TEMPLATE, shortName } from "../names";
import { useLocalFlag } from "../hooks/useLocalFlag";
import "../card.css";

const QUICK = ["Continuá", "sí", "no", "dale"];
const NOTIFY_KEY = "lienzo.send.notifyme";

interface Props {
  session: Session;
  /** las demas sesiones a las que se les puede escribir: App filtra con canWrite (sin las
   *  detenidas) y saca las de una PC caida. Entre ellas se busca a la coordinadora */
  others: Session[];
  toast: (msg: string, err?: boolean) => void;
  /** enfocar el textarea al montar (y al cambiar de sesion): "Darle trabajo" deja el cursor listo */
  autoFocus?: boolean;
}

export function SendBox({ session: s, others, toast, autoFocus = false }: Props) {
  const [text, setText] = useState("");
  const [attachments, setAttachments] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [connection, setConnection] = useState<{ command: string; session_id: string; expires_at: number } | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [drag, setDrag] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  // el Panel no se remonta al cambiar de tarjeta: el foco se repite por session_id, no solo al montar
  useEffect(() => {
    if (autoFocus) textRef.current?.focus();
  }, [autoFocus, s.session_id]);
  // "avisarme cuando termine": delegar en un gesto. Tras enviar, se crea la regla on_stop desde
  // esta sesion hacia la coordinadora (coordinatorOf: la marcada con estrella del mismo repo, o la
  // primera Claude del repo; igual que Conectar y el "avisame" del parser). Recordado por navegador;
  // apagado por defecto.
  const me = useMemo(() => coordinatorOf(s.repo, others, s.session_id), [others, s.repo, s.session_id]);
  const [notifyMe, , toggleNotify] = useLocalFlag(NOTIFY_KEY, false);

  const notifyRule = async () => {
    if (!notifyMe || !me) return;
    try {
      // el agente contesta varias veces (informe, aclaraciones): la regla se repite, con tope. Si ya
      // hay una activa hacia la coordinadora (de esta casilla o de Conectar), no se crea otra
      const active = (await rulesApi.list()).some(
        (r) => r.enabled && r.kind === "on_stop" && r.from === s.session_id && r.to === me.session_id,
      );
      if (active) return;
      await rulesApi.create({ kind: "on_stop", from: s.session_id, to: me.session_id, text: REPLY_TEMPLATE, repeat: true, max_fires: 20 });
      toast(`Cuando ${shortName(s)} termine, su respuesta va a ${shortName(me)}`);
    } catch (e) {
      // 409: ya existe esa regla, o la inversa (seria un bucle). El envio ya se hizo; se avisa y listo
      toast(`No se pudo crear la regla "cuando termine": ${(e as Error).message}`, true);
    }
  };

  /** Pegar con Ctrl+V: una captura viene en el portapapeles como archivo sin nombre util, asi que
   *  se le pone uno con la hora. Si lo pegado es texto, no se toca: sigue al textarea como siempre. */
  const paste = (e: React.ClipboardEvent) => {
    const files = Array.from(e.clipboardData?.files ?? []);
    if (!files.length) return;
    e.preventDefault();
    const stamp = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, "");
    upload(
      files.map((f, i) => {
        const ext = (f.type.split("/")[1] || "png").replace("jpeg", "jpg");
        const name = f.name && f.name !== "image.png" ? f.name : `pegado-${stamp}${files.length > 1 ? `-${i + 1}` : ""}.${ext}`;
        return f.name === name ? f : new File([f], name, { type: f.type });
      }),
    );
    toast(files.length === 1 ? "Imagen pegada, va como adjunto" : `${files.length} archivos pegados`);
  };

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
    if (busy || !canWrite(s)) return;
    if (s.pending_id) {
      toast("Hay un permiso pendiente, contestalo primero", true);
      return;
    }
    if (!t.trim() && attachments.length === 0) return;
    if (s.typing && !confirm("Están tipeando en esa terminal; lo que mandes se mezcla con lo que escriben. Enviar igual?")) return;
    setBusy(true);
    try {
      const r = await sessionsApi.send(s.session_id, { text: t, attachments });
      const notice = sendNotice(r);
      toast(notice.text, notice.attention);
      setText("");
      setAttachments([]);
      // La regla expresa el pedido de aviso, no acredita entrega. Armarla al aceptar
      // el envío evita perderla si el panel se cierra antes de la confirmación SSE.
      if (r.estado !== "rechazado") await notifyRule();
    } catch (e) {
      toast(`No se pudo enviar: ${(e as Error).message}`, true);
    } finally {
      setBusy(false);
    }
  };

  const disabled = busy || !!s.pending_id || !canWrite(s);

  const queue = s.envio?.puede && canWrite(s) && (
    (s.agent === "codex" && s.envio.transporte === "codex_queue") ||
    (s.agent === "claude" && s.envio.transporte === "claude_pipe")
  );
  if (s.agent === "claude" && s.external?.kind === "claude-desktop" && !queue) {
    return <div className="send">
      <p role="status">{s.envio?.motivo || "Falta conectar el adaptador de esta sesión Claude"}</p>
      <button disabled={connecting || !s.alive || !s.pid} onClick={async () => {
        setConnecting(true);
        try { setConnection(await sessionsApi.claudePipe(s.session_id)); }
        catch (e) { toast(`No se pudo conectar: ${(e as Error).message}`, true); }
        finally { setConnecting(false); }
      }}>Conectar esta sesión Claude</button>
      {connection?.session_id === s.session_id && <div>
        <p>Ejecutá este comando público desde esta sesión Claude y aprobalo allí. No contiene secretos.</p>
        <textarea readOnly aria-label="Comando público para conectar Claude" value={connection.command} />
        <p>Válido hasta {new Date(connection.expires_at * 1000).toLocaleTimeString()}. La escritura se habilita sólo al confirmar el adaptador vivo.</p>
      </div>}
    </div>;
  }
  if (s.envio && !s.envio.puede) {
    return <div className="send"><div className="small dim" role="status">{s.envio.motivo || "No se puede enviar a esta sesión"}</div></div>;
  }
  if (s.external && !queue) {
    return (
      <div className="send">
        <div className="small dim">
          {s.external.kind === "batch"
            ? "Esta sesión es una corrida headless (claude -p): no tiene consola, así que se puede leer pero no escribirle."
            : `Esta tarjeta es un agente que lanzó ${s.external.kind}: no se le escribe ni se lo cierra desde acá. Se controla desde su orquestador (o desde su plugin, si esta PC lo tiene).`}
        </div>
      </div>
    );
  }
  if (s.no_console && !s.orphan && !queue) {
    return (
      <div className="send">
        <div className="small dim">
          {s.backend === "tmux"
            ? `Esta sesión corre suelta, fuera de tmux: se puede leer, pero para escribirle desde acá tiene que correr adentro de tmux (./lienzo-new.sh ${s.agent}).`
            : "Esta sesión corre en el panel de Claude Code de VS Code o en una app de escritorio: no tiene consola, así que se puede leer pero no escribirle desde acá. Otra sesión de Claude sí puede hablarle con el canal nativo."}
        </div>
      </div>
    );
  }
  if (s.orphan && !queue) {
    return (
      <div className="send">
        <div className="small dim">
          Esta sesión perdió su terminal (el shell padre murió). El proceso sigue vivo y se puede leer,
          pero no hay consola donde escribirle. Reabrila con <code>{AGENTS[s.agent].resume}</code>.
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
      onPaste={paste}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        if (e.dataTransfer.files.length) upload(e.dataTransfer.files);
      }}
    >
      {s.typing && (
        <div className="typing-warn" role="alert">
          ⌨ están tipeando en esa terminal; lo que mandes se mezcla
        </div>
      )}
      <div className="row quick">
        {!needsPiReload(s) && QUICK.map((q) => (
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
          ref={textRef}
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
                : "Mensaje para la sesión. Enter envía, Shift+Enter salto. Podés pegar o arrastrar una imagen. Más de 500 caracteres o varias líneas viajan como adjunto .md"
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
        {me && (
          <label className="small notifyme pointer" title={`al terminar este pedido, su respuesta se manda sola a ${shortName(me)}`}>
            <input type="checkbox" checked={notifyMe} onChange={(e) => toggleNotify(e.target.checked)} /> avisarme cuando termine ({shortName(me)})
          </label>
        )}
        <button className="primary" disabled={disabled} onClick={() => send(text)}>
          Enviar
        </button>
      </div>
    </div>
  );
}
