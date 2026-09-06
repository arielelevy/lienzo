import { useCallback, useEffect, useRef, useState } from "react";
import { ago, api, detail } from "../api";
import { hhmm } from "../nl";
import { periodLabel, periodicCount } from "../arrows-geometry";
import type { Link, Pending, Rule, Session } from "../types";
import "../card.css";

/** "cada 30 min", "cada hora", "cada día": definida en arrows-geometry (modulo puro, sin React)
 *  y reexportada desde aca, que es de donde la toman Panel y Arrows. */
export { periodLabel };

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

/** Nombre corto de una sesion: "repo · titulo" (titulo cortado a 24) o "repo · id" si no tiene. */
export function shortName(o: Session | undefined, fallback = "otra sesión"): string {
  if (!o) return fallback;
  const t = (o.title || "").trim();
  if (!t) return `${o.repo} · ${o.session_id.slice(0, 8)}`;
  return `${o.repo} · ${t.length > 24 ? t.slice(0, 23).trimEnd() + "…" : t}`;
}

/** minuto (ms truncados) en que dispara una regla "at"; null si no tiene hora */
const minuteOf = (r: Rule): number | null => (r.kind === "at" && r.at ? Math.floor(new Date(r.at).getTime() / 60_000) : null);

/** Reglas "at" que le escriben a esta sesion y caen en el mismo minuto que otra: dos inyecciones
 *  a la misma consola en el mismo minuto (el server no lo impide todavia; la tarjeta lo marca). */
export function clashingAt(rules: Rule[], sid: string): Set<string> {
  const byMinute = new Map<number, string[]>();
  for (const r of rules) {
    if (!r.enabled || r.to !== sid) continue;
    const m = minuteOf(r);
    if (m === null) continue;
    const arr = byMinute.get(m);
    if (arr) arr.push(r.id);
    else byMinute.set(m, [r.id]);
  }
  const out = new Set<string>();
  for (const ids of byMinute.values()) if (ids.length > 1) ids.forEach((id) => out.add(id));
  return out;
}

/** "22:19" si es hoy; "vie 11/9 22:19" si es otro dia: un "Continuar" programado para dentro de
 *  cinco dias no puede leerse como si fuera esta noche. */
export function whenLabel(iso: string): string {
  const d = new Date(iso);
  const t = hhmm(d);
  const today = new Date();
  if (d.toDateString() === today.toDateString()) return t;
  const wd = d.toLocaleDateString("es-AR", { weekday: "short" }).replace(".", "");
  return `${wd} ${d.getDate()}/${d.getMonth() + 1} ${t}`;
}

/** Reglas con la misma etiqueta agrupadas (×N), como maximo `max` grupos. `clash` marca los grupos
 *  con alguna regla que comparte minuto con otra de la tarjeta. */
function groupRules(rules: Rule[], sid: string, sessions: Record<string, Session>, max = 3) {
  const clashing = clashingAt(rules, sid);
  const groups = new Map<string, { label: string; kind: Rule["kind"]; ids: string[]; clash: boolean }>();
  for (const r of rules) {
    const label = ruleLabel(r, sid, sessions);
    const g = groups.get(label);
    if (g) {
      g.ids.push(r.id);
      g.clash ||= clashing.has(r.id);
    } else groups.set(label, { label, kind: r.kind, ids: [r.id], clash: clashing.has(r.id) });
  }
  const all = [...groups.values()];
  return { shown: all.slice(0, max), hidden: all.slice(max).reduce((n, g) => n + g.ids.length, 0) };
}

/** Etiqueta del chip de una regla vista desde la tarjeta `sid`. Una "at" periodica dice el periodo,
 *  la proxima hora si esta en el futuro y cuantas veces fue: `↻ cada 30 min · próx. 09:30 → "Continuá" (1/5)`. */
export function ruleLabel(r: Rule, sid: string, sessions: Record<string, Session>, now = Date.now()): string {
  const other = (id: string | null) => shortName(id ? sessions[id] : undefined, "?");
  if (r.kind === "at") {
    let head: string;
    let tail = "";
    if (r.every_s) {
      const next = r.at && new Date(r.at).getTime() > now ? ` · próx. ${whenLabel(r.at)}` : "";
      head = `↻ ${periodLabel(r.every_s)}${next}`;
      tail = ` ${periodicCount(r.fired, r.max_fires, null)}`;
    } else {
      head = `⏰ ${r.at ? whenLabel(r.at) : "?"}`;
    }
    if (r.to === sid) return r.from && r.from !== sid ? `${head} → "${r.text}"${tail} (desde ${other(r.from)})` : `${head} → "${r.text}"${tail}`;
    return `${head} → "${r.text}"${tail} a ${other(r.to)}`;
  }
  const count = r.repeat ? ` (${r.fired}/${r.max_fires})` : "";
  return r.from === sid ? `⏹ al terminar → ${other(r.to)}${count}` : `⏹ recibe de ${other(r.from)} al terminar${count}`;
}

/** Markdown a texto plano legible para la tarjeta (que no renderiza markdown, por peso y altura):
 *  saca `**`, `__`, `` ` `` y cercos de codigo, `#` de encabezados, marcadores de lista al inicio
 *  de linea (`- `, `* `, `1. `), citas `>`, reglas `---`, deja el texto de los links
 *  `[texto](url)`, y colapsa lineas en blanco repetidas. La vista Conversacion del panel no la
 *  usa: ahi si se renderiza con react-markdown. */
export function plainText(md: string): string {
  let t = (md || "").replace(/\r\n?/g, "\n");
  t = t.replace(/^\s*```[^\n]*$/gm, ""); // cercos de codigo (la linea entera)
  t = t.replace(/^\s*[-*_]{3,}\s*$/gm, ""); // reglas horizontales
  t = t.replace(/^#{1,6}\s+/gm, ""); // encabezados
  t = t.replace(/^(\s*)(?:[-*+]|\d+[.)])\s+/gm, "$1"); // marcadores de lista, con su sangria
  t = t.replace(/^\s*>\s?/gm, ""); // citas
  t = t.replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1"); // links e imagenes: queda el texto
  t = t.replace(/(\*\*|__)(?=\S)([\s\S]*?\S)\1/g, "$2"); // negrita
  t = t.replace(/`([^`\n]*)`/g, "$1"); // codigo inline
  t = t.replace(/[ \t]+$/gm, "").replace(/\n{3,}/g, "\n\n"); // lineas en blanco repetidas
  return t.trim();
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

/** Primera oracion (hasta el primer . ! ? seguido de espacio o fin), tope de 90 caracteres. */
function foldSentence(text: string): { head: string; cut: boolean } {
  const t = (text || "").trim();
  const m = t.match(/^(.*?[.!?])(?:\s|$)/s);
  let head = m ? m[1] : t.split("\n")[0];
  if (head.length > PROMPT_CHARS) head = head.slice(0, PROMPT_CHARS - 1) + "…";
  return { head, cut: head.length < t.length };
}

/** Envoltorio con que el lienzo manda un texto largo: la sugerencia que arranca asi es nuestra. */
const ATTACH_WRAPPER = "Leé el archivo adjunto y respondé";
/** "usando Bash": la transcripcion dice que herramienta corre; es actividad, no una respuesta */
const WORKING_RE = /^usando \S+/;

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

/** El titulo salio del pedido (el server lo marca, o coincide con su primera linea, aun cortada):
 *  la linea "› pedido" diria lo mismo. */
function titleIsPrompt(s: Session): boolean {
  const title = (s.title || "").trim();
  if (!title) return false;
  if ((s as Session & { title_source?: string | null }).title_source === "prompt") return true;
  const first = (s.last_prompt || "").split("\n").map((l) => l.trim()).find(Boolean) ?? "";
  if (!first) return false;
  const t = title.replace(/…$/, "").replace(/\.\.\.$/, "").trimEnd();
  return first === title || (t.length >= 8 && first.startsWith(t));
}

export function Card({ session: s, pending: p, rules = [], links = [], sessions = {}, onDeleteRule, selected, onSelect, onDecide, onDrop, onGrip, onPress, toast: extToast }: Props) {
  const { toast, node: toastNode } = useLocalToast(extToast);
  const [promptOpen, setPromptOpen] = useState(false);
  const [errorOpen, setErrorOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  // el click simple espera 280 ms antes de abrir el panel; el doble click sobre el titulo lo
  // cancela y renombra en el lugar (mismo truco que las flechas en Arrows)
  const clickTimer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(clickTimer.current), []);

  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  // ultimo reenvio recibido en la ultima media hora: "ya te llego el informe de X"
  const recent = links
    .filter((l) => l.to === s.session_id && l.kind !== "native" && Date.now() - new Date(l.ts).getTime() < RECENT_MS)
    .sort((a, b) => b.ts.localeCompare(a.ts))[0];
  // remitente como "repo · título" (varias sesiones comparten repo); título largo cortado a 24
  const recentFrom = recent ? shortName(sessions[recent.from]) : "";

  // la tarjeta muestra texto plano: sin asteriscos ni almohadillas del markdown de la respuesta
  const promptText = plainText(s.last_prompt);
  const replyText = plainText(s.last_reply);
  const { head, cut } = foldPrompt(promptText);
  const dupPrompt = titleIsPrompt(s);
  const err = foldSentence(s.last_error || "");
  const working = WORKING_RE.test(s.last_reply || "");
  const suggestion = s.suggestion && !s.suggestion.trim().startsWith(ATTACH_WRAPPER) ? s.suggestion : null;
  const ruleGroups = groupRules(rules, s.session_id, sessions);
  const canWrite = !!s.alive && !s.orphan && !s.no_console;
  // ociosa: termino, o espera input en la terminal; con consola y sin permiso pendiente
  const idle = canWrite && !s.pending_id && !p && (s.state === "termino" || (s.state === "te_necesita" && s.needs?.kind === "idle"));
  // libre: viva, con consola y sin ningun pedido todavia (sesion recien abierta). No hay nada que
  // continuar ni que contestar: en vez de los botones rapidos, un solo "Darle trabajo" que abre el
  // panel con el cursor en la caja
  const free = canWrite && !p && !(s.last_prompt || "").trim() && !(s.last_reply || "").trim();

  // limite de uso con hora de vuelta (Codex): un click deja programado "Continuar" un minuto
  // despues; si ya hay una regla a esa hora (manual o automatica) el chip de abajo la muestra
  const limitAt = s.limit_until ? new Date(new Date(s.limit_until).getTime() + 60_000) : null;
  // 30 s de margen: si la regla ya disparo y el navegador va unos segundos adelantado, no se ofrece
  // programar otra; y si el server ya la creo solo, tampoco
  const limitPending = !!limitAt && limitAt.getTime() > Date.now() + 30_000 && s.continue_scheduled_for !== s.limit_until;
  const hasContinue =
    !!limitAt && rules.some((r) => r.kind === "at" && r.to === s.session_id && !!r.at && Math.abs(new Date(r.at).getTime() - limitAt.getTime()) < 5 * 60_000);
  const scheduleContinue = async () => {
    if (!limitAt) return;
    setBusy(true);
    try {
      await api.post("/rules", { kind: "at", from: null, to: s.session_id, text: "Continuar", at: limitAt.toISOString() });
      toast(`A las ${hhmm(limitAt)} se le escribe "Continuar"`);
    } catch (e) {
      toast(`No se pudo programar: ${(e as Error).message}`, true);
    } finally {
      setBusy(false);
    }
  };

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

  // estrella de coordinadora: a lo sumo una por repo; recibe los avisos "cuando termine" del
  // SendBox y el "avisame" del parser. PUT /sessions/<sid>/coordinator; un server anterior a la
  // ruta contesta 404 y la estrella solo avisa
  const toggleCoordinator = async () => {
    const on = !s.coordinator;
    setBusy(true);
    try {
      await api.put(`/sessions/${s.session_id}/coordinator`, { on });
      toast(on ? `${shortName(s)} es la coordinadora de ${s.repo}` : `${shortName(s)} ya no es la coordinadora`);
    } catch (e) {
      const m = (e as Error).message;
      toast(m === "404" || m === "ruta desconocida" ? "El server que corre no tiene esta ruta todavía: reiniciá el server" : `No se pudo: ${m}`, true);
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
      className={`card ${selected ? "sel" : ""} ${free ? "free" : ""}`}
      role="button"
      tabIndex={0}
      aria-label={`${s.repo}: ${s.title || s.last_prompt || (free ? "libre, sin pedidos todavía" : "sin título")}`}
      aria-pressed={selected}
      onClick={() => {
        window.clearTimeout(clickTimer.current);
        clickTimer.current = window.setTimeout(onSelect, 280);
      }}
      onDoubleClick={() => window.clearTimeout(clickTimer.current)}
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
        {s.branch && <span className="branch">⎇ {s.branch}</span>}
        <span className="right">
          {/* estado como icono: corriendo y termino comparten la columna "Trabajo"; la huerfana va a
              "Muerta" con esta etiqueta, para distinguirla de un proceso muerto de verdad */}
          {s.orphan ? (
            <span className="st orphan" title="el proceso sigue, pero su terminal de VS Code se cerró: no hay dónde escribirle">
              sin terminal
            </span>
          ) : s.alive === false ? null : s.state === "corriendo" ? (
            <span className="st run" role="img" aria-label="corriendo" title="corriendo" />
          ) : s.state === "termino" ? (
            <span className="st done" role="img" aria-label="terminó" title="terminó">
              ✓
            </span>
          ) : null}
          {s.agent === "claude" && canWrite && (
            <button
              type="button"
              className={`star ${s.coordinator ? "on" : ""}`}
              disabled={busy}
              title={s.coordinator ? "coordinadora del repo: recibe los avisos 'cuando termine' y 'avisame' (click para quitarle el rol)" : "marcar como coordinadora del repo: recibe los avisos 'cuando termine' y 'avisame'"}
              aria-label={s.coordinator ? "coordinadora del repo" : "marcar como coordinadora"}
              aria-pressed={!!s.coordinator}
              onClick={(e) => {
                e.stopPropagation();
                window.clearTimeout(clickTimer.current);
                toggleCoordinator();
              }}
            >
              {s.coordinator ? "★" : "☆"}
            </button>
          )}
          {ago(s.state_since)}
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
        </span>
      </div>
      <div
        className={`title ${dupPrompt ? "plain" : ""}`}
        title={editing ? undefined : "doble click para renombrar"}
        onDoubleClick={(e) => {
          e.stopPropagation();
          window.clearTimeout(clickTimer.current);
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
        ) : free && !s.title ? (
          <span className="freeline" title={`abierta hace ${ago(s.started)}, sin ningún pedido todavía`}>
            Libre · sin pedidos todavía · desde hace {ago(s.started)}
          </span>
        ) : (
          s.title || s.last_prompt || "(sin título)"
        )}
      </div>
      {free && s.title && (
        <div className="freeline" title={`abierta hace ${ago(s.started)}, sin ningún pedido todavía`}>
          Libre · sin pedidos todavía · desde hace {ago(s.started)}
        </div>
      )}
      {/* el pedido no se repite si el titulo ya es su primera linea; si hay mas texto queda el "…más" */}
      {s.title && s.last_prompt && (!dupPrompt || cut) && (
        <div className={`prompt ${promptOpen ? "open" : ""}`}>
          {(!dupPrompt || promptOpen) && <span className="ptext">› {promptOpen ? promptText : head}</span>}
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
              {promptOpen ? "menos" : dupPrompt ? "…ver el pedido" : "…más"}
            </button>
          )}
        </div>
      )}
      {recent && (
        <div className="chip recent" title={`informe de ${recentFrom}: ${plainText(recent.text)}`}>
          ✓ {recentFrom} · hace {ago(recent.ts)}
        </div>
      )}
      {/* lo que pide la sesion va antes que la respuesta: Permitir/Denegar es lo primero visible */}
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
      ) : s.state === "te_necesita" && s.needs && !(idle && s.needs.kind === "idle") ? (
        /* ociosa con botones rapidos: el aviso va en una linea con los botones, mas abajo */
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
      {s.last_error ? (
        <div className={`error ${errorOpen ? "open" : ""}`}>
          <span className="etext">⚠ {errorOpen ? s.last_error : err.head}</span>
          {err.cut && (
            <button
              type="button"
              className="more"
              aria-expanded={errorOpen}
              onClick={(e) => {
                e.stopPropagation();
                setErrorOpen((o) => !o);
              }}
            >
              {errorOpen ? "menos" : "…más"}
            </button>
          )}
        </div>
      ) : working ? (
        <div className="reply working" title="lo que está haciendo ahora, según la transcripción">
          <span className="wdot" aria-hidden="true" />
          {s.last_reply}
        </div>
      ) : free ? null : (
        <div className="replyrow">
          <div className="reply">{replyText}</div>
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
      {limitPending && !hasContinue && canWrite && limitAt && (
        <div className="limitrow" onClick={(e) => e.stopPropagation()}>
          <button
            type="button"
            disabled={busy}
            title={`a las ${hhmm(limitAt)} se escribe "Continuar" en su terminal (un minuto después de que vuelva el cupo)`}
            onClick={scheduleContinue}
          >
            ⏰ Continuar a las {hhmm(limitAt)}
          </button>
        </div>
      )}
      {suggestion && <div className="sugg" title="leído de la caja de entrada de la terminal">💡 {suggestion}</div>}
      {ruleGroups.shown.map((g) => (
        <div key={g.label} className={`rule ${g.clash ? "clash" : ""}`} title={g.kind === "at" ? (g.label.startsWith("↻") ? "periódica" : "programado") : "cuando termine el turno"}>
          {g.clash && (
            <span className="warn" role="img" aria-label="dos mensajes programados al mismo minuto" title="dos mensajes programados al mismo minuto">
              ⚠
            </span>
          )}
          <span>
            {g.label}
            {g.ids.length > 1 && <span className="dim"> ×{g.ids.length}</span>}
          </span>
          <button
            type="button"
            className="del"
            title={g.ids.length > 1 ? `quitar las ${g.ids.length}` : "quitar"}
            aria-label="quitar conexión"
            onClick={(e) => {
              e.stopPropagation();
              const q = g.ids.length > 1 ? `Quitar estas ${g.ids.length} conexiones iguales?` : "Quitar esta conexión?";
              if (confirm(q)) g.ids.forEach((id) => onDeleteRule?.(id));
            }}
          >
            ✕
          </button>
        </div>
      ))}
      {ruleGroups.hidden > 0 && (
        <div className="rule dim small" title="abrí el panel, pestaña Conexiones, para ver todas">
          +{ruleGroups.hidden} más
        </div>
      )}
      {free ? (
        <div className="quickact freeact" onClick={(e) => e.stopPropagation()}>
          <button
            type="button"
            title="abre el panel con el cursor en la caja de envío"
            onClick={() => {
              window.clearTimeout(clickTimer.current);
              onSelect();
            }}
          >
            Darle trabajo
          </button>
        </div>
      ) : idle && (
        <div className="quickact" onClick={(e) => e.stopPropagation()}>
          {s.state === "te_necesita" && <span className="dim small">Espera tu input</span>}
          {QUICK.map((q) => (
            <button key={q} type="button" disabled={busy} title="se escribe en su terminal" onClick={() => quickSend(q)}>
              {q}
            </button>
          ))}
        </div>
      )}

      <div className="meta">
        <span>PID {s.pid ?? "?"}</span>
        <span>{s.source === "sweep" ? "barrido" : "hooks"}</span>
        {s.alive === false && <span>proceso muerto</span>}
        {s.no_console && !s.orphan && <span className="warn" title="panel de Claude Code de VS Code o app de escritorio: se ve, no se le escribe">sin consola</span>}
        <span>{s.session_id.slice(0, 8)}</span>
      </div>
      {toastNode}
    </div>
  );
}
