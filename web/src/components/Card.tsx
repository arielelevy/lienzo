import { useCallback, useEffect, useRef, useState } from "react";
import { ago, api, detail } from "../api";
import { hhmm } from "../nl";
import type { Link, Pending, Rule, Session } from "../types";
import "../card.css";

export type ToastFn = (msg: string, err?: boolean) => void;

/** Toast: si el componente recibe el global por props lo usa; si no, muestra uno chico propio
 *  (posicionado dentro del contenedor, que tiene que ser position: relative). */
export function useLocalToast(external?: ToastFn) {
  const [msg, setMsg] = useState<{ text: string; err: boolean } | null>(null);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const toast = useCallback<ToastFn>(
    (text, err = false) => {
      if (external) {
        external(text, err);
        return;
      }
      setMsg({ text, err });
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setMsg(null), 2500);
    },
    [external],
  );
  const node =
    msg && !external ? (
      <div className={`ctoast ${msg.err ? "err" : ""}`} role="status">
        {msg.text}
      </div>
    ) : null;
  return { toast, node };
}

export async function copyText(text: string, toast: ToastFn) {
  try {
    await navigator.clipboard.writeText(text);
    toast("copiado");
  } catch (e) {
    toast(`no se pudo copiar: ${(e as Error).message}`, true);
  }
}

function ruleLabel(r: Rule, sid: string, sessions: Record<string, Session>): string {
  // nombre corto de la otra sesion: el titulo si lo hay (dos sesiones del mismo repo se confunden)
  const other = (id: string | null) => {
    const o = id ? sessions[id] : undefined;
    if (!o) return "?";
    return o.title ? `${o.repo} · ${o.title.slice(0, 28)}` : `${o.repo} · ${o.session_id.slice(0, 8)}`;
  };
  if (r.kind === "at") {
    const t = r.at ? hhmm(new Date(r.at)) : "?";
    if (r.to === sid) return r.from && r.from !== sid ? `⏰ ${t} → "${r.text}" (desde ${other(r.from)})` : `⏰ ${t} → "${r.text}"`;
    return `⏰ ${t} → "${r.text}" a ${other(r.to)}`;
  }
  const count = r.repeat ? ` (${r.fired}/${r.max_fires})` : "";
  return r.from === sid ? `⏹ al terminar → ${other(r.to)}${count}` : `⏹ recibe de ${other(r.from)} al terminar${count}`;
}

const PROMPT_CHARS = 90;

/** Primera linea del pedido, o los primeros 90 caracteres; `cut` dice si quedo algo afuera. */
function foldPrompt(p: string): { head: string; cut: boolean } {
  const text = (p || "").trim();
  const nl = text.indexOf("\n");
  let head = nl >= 0 ? text.slice(0, nl) : text;
  let cut = nl >= 0;
  if (head.length > PROMPT_CHARS) {
    head = head.slice(0, PROMPT_CHARS - 1) + "…";
    cut = true;
  }
  return { head, cut };
}

const QUICK = ["Continuá", "sí", "no"];

interface Props {
  session: Session;
  pending?: Pending;
  rules?: Rule[];
  /** reenvios que tocan a esta sesion (llegan por SSE); alimentan el chip "informe de" */
  links?: Link[];
  sessions?: Record<string, Session>;
  onDeleteRule?: (id: string) => void;
  selected: boolean;
  onSelect: () => void;
  onDecide: (requestId: string, decision: "allow" | "deny") => void;
  onDrop: () => void;
  onGrip?: (e: React.MouseEvent) => void;
  onPress?: (e: React.MouseEvent) => void;
  /** toast global; si no viene, la tarjeta muestra uno propio */
  toast?: ToastFn;
}

const RECENT_MS = 30 * 60 * 1000;

export function Card({ session: s, pending: p, rules = [], links = [], sessions = {}, onDeleteRule, selected, onSelect, onDecide, onDrop, onGrip, onPress, toast: extToast }: Props) {
  const { toast, node: toastNode } = useLocalToast(extToast);
  const [promptOpen, setPromptOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  // ultimo reenvio recibido en la ultima media hora: "ya te llego el informe de X"
  const recent = links
    .filter((l) => l.to === s.session_id && l.kind !== "native" && Date.now() - new Date(l.ts).getTime() < RECENT_MS)
    .sort((a, b) => b.ts.localeCompare(a.ts))[0];
  const recentFrom = recent ? sessions[recent.from]?.repo ?? "otra sesión" : "";

  const { head, cut } = foldPrompt(s.last_prompt);
  const canWrite = !!s.alive && !s.orphan && !s.no_console;
  // ociosa: termino, o espera input en la terminal; con consola y sin permiso pendiente
  const idle = canWrite && !s.pending_id && !p && (s.state === "termino" || (s.state === "te_necesita" && s.needs?.kind === "idle"));

  const quickSend = async (text: string) => {
    setBusy(true);
    try {
      const r = await api.post<{ chars: number }>(`/sessions/${s.session_id}/send`, { text, attachments: [] });
      toast(`Enviado (${r.chars} caracteres)`);
    } catch (e) {
      toast(`No se pudo enviar: ${(e as Error).message}`, true);
    } finally {
      setBusy(false);
    }
  };

  const startRename = () => {
    setDraft(s.title || "");
    setEditing(true);
  };
  const saveTitle = async () => {
    const title = draft.trim();
    setEditing(false);
    if (!title || title === (s.title || "")) return;
    try {
      const r = await fetch(`/sessions/${s.session_id}/title`, {
        method: "PUT",
        headers: { "X-Lienzo": "1", "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
      if (r.status === 404) {
        toast("reiniciá el server", true);
        return;
      }
      if (!r.ok) {
        const j = (await r.json().catch(() => ({}))) as { error?: string };
        throw new Error(j.error || String(r.status));
      }
      toast("título guardado");
    } catch (e) {
      toast(`No se pudo renombrar: ${(e as Error).message}`, true);
    }
  };

  return (
    <div
      className={`card ${selected ? "sel" : ""}`}
      role="button"
      tabIndex={0}
      aria-label={`${s.repo}: ${s.title || s.last_prompt || "sin título"}`}
      aria-pressed={selected}
      onClick={onSelect}
      onKeyDown={(e) => {
        // Enter sobre la tarjeta misma abre el panel; los botones de adentro manejan su propio Enter
        if (e.key === "Enter" && e.target === e.currentTarget) {
          e.preventDefault();
          onSelect();
        }
      }}
      data-sid={s.session_id}
      onMouseDown={(e) => {
        // arrastre desde cualquier parte de la tarjeta, salvo controles y el agarre (que ya arrastra)
        const t = e.target as HTMLElement;
        if (e.button !== 0 || t.closest("button, a, input, textarea, .x, .grip, code")) return;
        onPress?.(e);
      }}
    >
      <button
        type="button"
        className="x"
        title="quitar tarjeta"
        aria-label="quitar tarjeta"
        onClick={(e) => {
          e.stopPropagation();
          onDrop();
        }}
      >
        ✕
      </button>
      <div className="top">
        <span className={`badge ${s.agent}`}>{s.agent}</span>
        <span className="repo">{s.repo}</span>
        {s.branch && <span>⎇ {s.branch}</span>}
        <span className="right">{ago(s.state_since)}</span>
      </div>
      <div
        className="title"
        title={editing ? undefined : "doble click para renombrar"}
        onDoubleClick={(e) => {
          e.stopPropagation();
          startRename();
        }}
      >
        {editing ? (
          <input
            ref={inputRef}
            value={draft}
            aria-label="nuevo título"
            onChange={(e) => setDraft(e.target.value)}
            onClick={(e) => e.stopPropagation()}
            onBlur={() => setEditing(false)}
            onKeyDown={(e) => {
              e.stopPropagation();
              if (e.key === "Enter") {
                e.preventDefault();
                saveTitle();
              } else if (e.key === "Escape") {
                e.preventDefault();
                setEditing(false);
              }
            }}
          />
        ) : (
          s.title || s.last_prompt || "(sin título)"
        )}
      </div>
      {s.title && s.last_prompt && (
        <div className={`prompt ${promptOpen ? "open" : ""}`}>
          <span className="ptext">› {promptOpen ? s.last_prompt : head}</span>
          {cut && (
            <button
              type="button"
              className="more"
              aria-expanded={promptOpen}
              onClick={(e) => {
                e.stopPropagation();
                setPromptOpen((o) => !o);
              }}
            >
              {promptOpen ? "menos" : "…más"}
            </button>
          )}
        </div>
      )}
      {recent && (
        <div className="chip" title={recent.text}>
          ✓ informe de {recentFrom} hace {ago(recent.ts)}
        </div>
      )}
      {s.last_error ? (
        <div className="error">⚠ {s.last_error}</div>
      ) : (
        <div className="replyrow">
          <div className="reply">{s.last_reply}</div>
          {s.last_reply && (
            <button
              type="button"
              className="copy"
              title="copiar la última respuesta"
              aria-label="copiar la última respuesta"
              onClick={(e) => {
                e.stopPropagation();
                copyText(s.last_reply, toast);
              }}
            >
              📋
            </button>
          )}
        </div>
      )}
      {s.suggestion && <div className="sugg" title="leído de la caja de entrada de la terminal">💡 {s.suggestion}</div>}
      {rules.map((r) => (
        <div key={r.id} className="rule" title={r.kind === "at" ? "programado" : "cuando termine el turno"}>
          <span>{ruleLabel(r, s.session_id, sessions)}</span>
          <button
            type="button"
            className="del"
            title="quitar"
            aria-label="quitar conexión"
            onClick={(e) => {
              e.stopPropagation();
              if (confirm("Quitar esta conexión?")) onDeleteRule?.(r.id);
            }}
          >
            ✕
          </button>
        </div>
      ))}

      {p ? (
        <div className="needs" onClick={(e) => e.stopPropagation()}>
          <b>Pide permiso: {p.tool_name}</b>
          <code>{detail(p.tool_input)}</code>
          <div className="btns">
            <button className="allow" onClick={() => onDecide(p.request_id, "allow")}>Permitir</button>
            <button className="deny" onClick={() => onDecide(p.request_id, "deny")}>Denegar</button>
            <span className="dim small">vence {new Date(p.expires_at).toLocaleTimeString()}</span>
          </div>
        </div>
      ) : s.state === "te_necesita" && s.needs ? (
        <div className="needs terminal">
          <b>
            {s.needs.kind === "idle"
              ? "Espera tu input"
              : s.needs.kind === "permission"
                ? `Pide permiso: ${s.needs.tool ?? ""}`
                : s.needs.kind}
          </b>
          {s.needs.detail && <code>{s.needs.detail}</code>}
          <div className="dim small">
            {s.needs.kind === "idle" ? "podés escribirle desde acá" : s.needs.where === "terminal" ? "contestar en VS Code" : "esperando al lienzo"}
          </div>
        </div>
      ) : null}

      {idle && (
        <div className="quickact" onClick={(e) => e.stopPropagation()}>
          {QUICK.map((q) => (
            <button key={q} type="button" disabled={busy} title={`enviar "${q}" a la terminal`} onClick={() => quickSend(q)}>
              {q}
            </button>
          ))}
          <span className="hint">directo a la terminal</span>
        </div>
      )}

      <div className="meta">
        <span>PID {s.pid ?? "?"}</span>
        <span>{s.source === "sweep" ? "barrido" : "hooks"}</span>
        {s.alive === false && <span>proceso muerto</span>}
        {s.orphan && <span className="warn" title="su terminal de VS Code se cerró; el proceso sigue pero no hay dónde escribirle">sin terminal</span>}
        {s.no_console && !s.orphan && <span className="warn" title="panel de Claude Code de VS Code o app de escritorio: se ve, no se le escribe">sin consola</span>}
        <span>{s.session_id.slice(0, 8)}</span>
      </div>
      {onGrip && canWrite && (
        <button
          type="button"
          className="grip"
          title="arrastrá hasta otra tarjeta para reenviarle la última respuesta"
          aria-label="arrastrar para conectar con otra tarjeta"
          onClick={(e) => e.stopPropagation()}
          onMouseDown={(e) => {
            e.stopPropagation();
            e.preventDefault();
            onGrip(e);
          }}
        >
          ⇢
        </button>
      )}
      {toastNode}
    </div>
  );
}
