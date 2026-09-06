import { useCallback, useEffect, useRef, useState } from "react";
import { ago, api, detail } from "../api";
import { hhmm } from "../nl";
import { canWrite, foldPrompt, foldSentence, groupRules, isFree, linkSentences, periodLabel, plainText, ruleSentence, ruleSummary, shortName, titleIsPrompt, whenLabel, type RuleGroup } from "../names";
import type { Link, Pending, Rule, Session } from "../types";
import "../card.css";

/** Los nombres y textos viven en names.ts; App, Board, Forward, SendBox, Arrows y Panel los
 *  siguen importando de aca. */
export { shortName, plainText, whenLabel, periodLabel };

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

/** el server que corre es anterior a esa ruta (404 crudo, o su JSON "ruta desconocida") */
const noRoute = (m: string) => m === "404" || m === "ruta desconocida";

/** Renombrar en el lugar: `start` abre un input con el titulo actual (seleccionado); Enter guarda
 *  por PUT /sessions/<sid>/title, Escape o blur cancelan. Devuelve el input listo para poner donde
 *  iba el titulo. */
function useRename(s: Session, toast: ToastFn) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);
  const start = () => {
    setDraft(s.title || "");
    setEditing(true);
  };
  const save = async () => {
    const title = draft.trim();
    setEditing(false);
    if (!title || title === (s.title || "")) return;
    try {
      await api.put(`/sessions/${s.session_id}/title`, { title });
      toast("título guardado");
    } catch (e) {
      const m = (e as Error).message;
      toast(noRoute(m) ? "reiniciá el server" : `No se pudo renombrar: ${m}`, true);
    }
  };
  const input = editing ? (
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
          save();
        } else if (e.key === "Escape") {
          e.preventDefault();
          setEditing(false);
        }
      }}
    />
  ) : null;
  return { editing, start, input };
}

/** Chips de las conexiones que tocan la tarjeta: hasta tres grupos con su ✕ (confirmando), y un
 *  "+N más" que manda al panel. El ⚠ marca dos programadas al mismo minuto. */
function CardRules({ groups, onDelete }: { groups: { shown: RuleGroup[]; hidden: number }; onDelete?: (id: string) => void }) {
  return (
    <>
      {groups.shown.map((g) => (
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
              if (confirm(q)) g.ids.forEach((id) => onDelete?.(id));
            }}
          >
            ✕
          </button>
        </div>
      ))}
      {groups.hidden > 0 && (
        <div className="rule dim small" title="abrí el panel, pestaña Conexiones, para ver todas">
          +{groups.hidden} más
        </div>
      )}
    </>
  );
}

/** Las conexiones de la tarjeta elegida, en palabras: una frase por linea. Lo ya recibido no se
 *  puede quitar; cada regla lleva su ✕, como el chip. */
function CardWords({ sid, rules, links, sessions, onDelete }: { sid: string; rules: Rule[]; links: Link[]; sessions: Record<string, Session>; onDelete?: (id: string) => void }) {
  const said = linkSentences(links, sid, sessions);
  if (!rules.length && !said.length) return null;
  return (
    <div className="words">
      {said.map((t) => (
        <div key={t} className="w done">
          {t}
        </div>
      ))}
      {rules.map((r) => (
        <div key={r.id} className="w">
          <span>{ruleSentence(r, sid, sessions)}</span>
          <button
            type="button"
            className="del"
            title="quitar"
            aria-label="quitar conexión"
            onClick={(e) => {
              e.stopPropagation();
              if (confirm("Quitar esta conexión?")) onDelete?.(r.id);
            }}
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}

/** Envoltorio con que el lienzo manda un texto largo: la sugerencia que arranca asi es nuestra. */
const ATTACH_WRAPPER = "Leé el archivo adjunto y respondé";
/** "usando Bash": la transcripcion dice que herramienta corre; es actividad, no una respuesta */
const WORKING_RE = /^usando \S+/;

const QUICK = ["Continuá", "sí", "no"];

const RECENT_MS = 30 * 60 * 1000;

/** Por debajo de este ancho la tarjeta no alcanza para el pedido y la respuesta: pasa a modo
 *  compacto (agente, repo, estado, titulo en una linea y un contador de conexiones). Pasa con el
 *  panel abierto y varias columnas: el tablero tiene que seguir sirviendo de indice. */
const COMPACT_W = 200;

/** Ancho real de la tarjeta, medido con un ResizeObserver sobre ella misma: sale de la subcolumna
 *  en que cayo, no del ancho de la ventana (con el panel abierto el tablero mide la mitad, y
 *  encima depende de cuantas columnas esten abiertas). El contenido cambia el alto, nunca el
 *  ancho, asi que no hay realimentacion. */
function useCompact(ref: React.RefObject<HTMLElement | null>): boolean {
  const [compact, setCompact] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const o = new ResizeObserver(() => setCompact(el.offsetWidth > 0 && el.offsetWidth < COMPACT_W));
    o.observe(el);
    return () => o.disconnect();
  }, [ref]);
  return compact;
}

interface Props {
  session: Session;
  pending?: Pending;
  rules?: Rule[];
  /** reenvios que tocan a esta sesion (llegan por SSE); alimentan el chip "informe de" */
  links?: Link[];
  sessions?: Record<string, Session>;
  onDeleteRule?: (id: string) => void;
  /** su panel esta abierto */
  selected: boolean;
  /** elegida con un click en el tablero: se resalta y muestra sus conexiones en palabras */
  picked?: boolean;
  /** un click: elegir la tarjeta, sin abrir nada */
  onPick?: () => void;
  /** doble click (o Enter): abrir el panel */
  onSelect: () => void;
  onDecide: (requestId: string, decision: "allow" | "deny") => void;
  onDrop: () => void;
  onGrip?: (e: React.MouseEvent) => void;
  onPress?: (e: React.MouseEvent) => void;
  /** toast global; si no viene, la tarjeta muestra uno propio */
  toast?: ToastFn;
}

export function Card({ session: s, pending: p, rules = [], links = [], sessions = {}, onDeleteRule, selected, picked = false, onPick, onSelect, onDecide, onDrop, onGrip, onPress, toast: extToast }: Props) {
  const { toast, node: toastNode } = useLocalToast(extToast);
  const [promptOpen, setPromptOpen] = useState(false);
  const [errorOpen, setErrorOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const rename = useRename(s, toast);
  const rootRef = useRef<HTMLDivElement>(null);
  // columna angosta: la tarjeta se reduce a indice. Un permiso pendiente nunca se compacta: es la
  // unica accion que vence y solo se puede contestar desde la tarjeta
  const compact = useCompact(rootRef) && !p;

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
  const writable = canWrite(s);
  // pregunta abierta: la ultima respuesta termina en "?" (la linea de actividad "usando X" no cuenta)
  const asks = !working && /\?\s*$/.test((s.last_reply || "").trim());
  // botones rapidos: solo si la sesion espera input de verdad o pregunto algo. Una que entrego un
  // informe y no pregunto nada no tiene nada que continuar ni que contestar: alcanza la caja del panel
  const quick = writable && !s.pending_id && !p && (s.needs?.kind === "idle" || asks);
  // libre: viva, con consola y sin ningun pedido todavia (sesion recien abierta). No hay nada que
  // continuar ni que contestar: en vez de los botones rapidos, un solo "Darle trabajo" que abre el
  // panel con el cursor en la caja
  const free = !p && isFree(s);
  const freeTitle = `abierta hace ${ago(s.started)}, sin ningún pedido todavía`;
  const freeText = `Libre · sin pedidos todavía · desde hace ${ago(s.started)}`;
  // compacto: los chips de conexiones no entran, va un contador con el detalle en el title
  const summary = compact ? ruleSummary(rules, s.session_id, sessions) : null;
  // elegida con un click y con lugar para leerlas: las conexiones en palabras, una por linea,
  // en vez de los chips abreviados
  const words = picked && !compact;

  // limite de uso con hora de vuelta (Codex): un click deja programado "Continuar" un minuto
  // despues; si ya hay una regla a esa hora (manual o automatica) el chip de abajo la muestra
  const limitAt = s.limit_until ? new Date(new Date(s.limit_until).getTime() + 60_000) : null;
  // 30 s de margen: si la regla ya disparo y el navegador va unos segundos adelantado, no se ofrece
  // programar otra; y si el server ya la creo solo, tampoco
  const limitPending = !!limitAt && limitAt.getTime() > Date.now() + 30_000 && s.continue_scheduled_for !== s.limit_until;
  const hasContinue =
    !!limitAt && rules.some((r) => r.kind === "at" && r.to === s.session_id && !!r.at && Math.abs(new Date(r.at).getTime() - limitAt.getTime()) < 5 * 60_000);

  /** accion contra el server con los botones deshabilitados mientras dura: `fn` devuelve el texto
   *  del toast de exito, `fail` arma el de error a partir del mensaje */
  const act = async (fn: () => Promise<string>, fail: (m: string) => string) => {
    setBusy(true);
    try {
      toast(await fn());
    } catch (e) {
      toast(fail((e as Error).message), true);
    } finally {
      setBusy(false);
    }
  };
  const scheduleContinue = () =>
    limitAt &&
    act(async () => {
      await api.post("/rules", { kind: "at", from: null, to: s.session_id, text: "Continuar", at: limitAt.toISOString() });
      return `A las ${hhmm(limitAt)} se le escribe "Continuar"`;
    }, (m) => `No se pudo programar: ${m}`);
  const quickSend = (text: string) =>
    act(async () => {
      const r = await api.post<{ chars: number }>(`/sessions/${s.session_id}/send`, { text, attachments: [] });
      return `Enviado (${r.chars} caracteres)`;
    }, (m) => `No se pudo enviar: ${m}`);
  // estrella de coordinadora: a lo sumo una por repo; recibe los avisos "cuando termine" del
  // SendBox y el "avisame" del parser. Un server anterior a la ruta contesta 404 y la estrella solo avisa
  const toggleCoordinator = () => {
    const on = !s.coordinator;
    return act(async () => {
      await api.put(`/sessions/${s.session_id}/coordinator`, { on });
      return on ? `${shortName(s)} es la coordinadora de ${s.repo}` : `${shortName(s)} ya no es la coordinadora`;
    }, (m) => (noRoute(m) ? "El server que corre no tiene esta ruta todavía: reiniciá el server" : `No se pudo: ${m}`));
  };

  return (
    <div
      ref={rootRef}
      className={`card ${selected ? "sel" : ""} ${picked ? "picked" : ""} ${free ? "free" : ""} ${compact ? "compact" : ""}`}
      role="button"
      tabIndex={0}
      aria-label={`${s.repo}: ${s.title || s.last_prompt || (free ? "libre, sin pedidos todavía" : "sin título")}`}
      aria-pressed={picked || selected}
      /* un click elige la tarjeta (instantáneo, no abre nada); el doble click abre el panel */
      onClick={() => onPick?.()}
      onDoubleClick={(e) => {
        /* doble click sobre un control (✕, estrella, lápiz, chips) no abre el panel */
        if ((e.target as HTMLElement).closest("button, a, input, textarea, code")) return;
        onSelect();
      }}
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
        {s.branch && !compact && <span className="branch">⎇ {s.branch}</span>}
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
          {s.agent === "claude" && writable && (
            <button
              type="button"
              className={`star ${s.coordinator ? "on" : ""}`}
              disabled={busy}
              title={s.coordinator ? "coordinadora del repo: recibe los avisos 'cuando termine' y 'avisame' (click para quitarle el rol)" : "marcar como coordinadora del repo: recibe los avisos 'cuando termine' y 'avisame'"}
              aria-label={s.coordinator ? "coordinadora del repo" : "marcar como coordinadora"}
              aria-pressed={!!s.coordinator}
              onClick={(e) => {
                e.stopPropagation();
                toggleCoordinator();
              }}
            >
              {s.coordinator ? "★" : "☆"}
            </button>
          )}
          {/* renombrar: el doble click sobre el título ahora abre el panel, así que el lápiz es
              la puerta al modo de renombrar en el lugar */}
          {writable && (
            <button
              type="button"
              className="pencil"
              title="renombrar la tarjeta"
              aria-label="renombrar la tarjeta"
              onClick={(e) => {
                e.stopPropagation();
                rename.start();
              }}
              onDoubleClick={(e) => e.stopPropagation()}
            >
              ✎
            </button>
          )}
          {/* en compacto no entra el "hace X" junto al agente, el repo y el estado */}
          {!compact && ago(s.state_since)}
          {onGrip && writable && (
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
      <div className={`title ${dupPrompt ? "plain" : ""}`}>
        {rename.input ??
          (compact ? (
            <>
              <span className="ttext">{s.title || (free ? "Libre · sin pedidos" : head || "(sin título)")}</span>
              {summary && (
                <span className="rulecount" title={summary.title}>
                  {summary.text}
                </span>
              )}
            </>
          ) : free && !s.title ? (
            <span className="freeline" title={freeTitle}>
              {freeText}
            </span>
          ) : (
            s.title || s.last_prompt || "(sin título)"
          ))}
      </div>
      {/* de acá para abajo, todo lo que el modo compacto no muestra: pedido, respuesta, chips,
          botones rápidos, copiar y la meta. Click abre el panel, que sí lo muestra todo. */}
      {!compact && (
      <>
      {free && s.title && (
        <div className="freeline" title={freeTitle}>
          {freeText}
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
      {recent && !words && (
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
      ) : s.state === "te_necesita" && s.needs && !(quick && s.needs.kind === "idle") ? (
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
      {limitPending && !hasContinue && writable && limitAt && (
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
      {words ? (
        <CardWords sid={s.session_id} rules={rules} links={links} sessions={sessions} onDelete={onDeleteRule} />
      ) : (
        <CardRules groups={groupRules(rules, s.session_id, sessions)} onDelete={onDeleteRule} />
      )}
      {free ? (
        <div className="quickact freeact" onClick={(e) => e.stopPropagation()}>
          <button type="button" title="abre el panel con el cursor en la caja de envío" onClick={onSelect}>
            Darle trabajo
          </button>
        </div>
      ) : quick && (
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
      </>
      )}
      {toastNode}
    </div>
  );
}
