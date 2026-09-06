import { useEffect, useMemo, useRef, useState } from "react";
import { ago, api } from "../api";
import { hhmm as fmtHhmm, nextAt, parseConnection } from "../nl";
import type { DigestResponse, Session } from "../types";
import { shortName } from "./Card";

const DEFAULT_TEMPLATE = "Mensaje de {repo} ({agente}) sobre '{titulo}':\n{respuesta}";
const KEY = "lienzo.forward.template";
type Mode = "now" | "on_stop" | "at" | "native";

/** Instruccion que se le inyecta a A para que abra el canal nativo de Claude Code con B.
 *  Los nombres internos (lienzo-04, mapo-bf) no se pueden mapear desde afuera: A los resuelve
 *  con ListAgents a partir del repo y el titulo de B. */
function nativeInstruction(b: Session, text: string): string {
  const who = b.title ? `"${b.title}" (repo ${b.repo})` : `repo ${b.repo}`;
  return `Abrí un canal con otra sesión de Claude Code de esta máquina. Usá ListAgents y ubicá la sesión que corresponde a ${who}, que arrancó hace ${ago(b.started)}; no sos vos. Mandale con SendMessage lo siguiente y seguí la conversación por ese mismo canal (respondiéndole con SendMessage) hasta cerrar el tema; al final resumime acá qué quedó: ${text}`;
}

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

function nextTimeIso(hhmm: string): string | null {
  const m = hhmm.match(/^(\d{1,2}):(\d{2})$/);
  if (!m) return null;
  return nextAt(Number(m[1]), Number(m[2])).toISOString(); // ya paso hoy: manana
}

interface Props {
  from: Session;
  others: Session[];
  initialTarget?: string;
  toast: (msg: string, err?: boolean) => void;
  onDone: () => void;
}

/** Conectar sesiones. Tres modos:
 *  - ahora: manda la ultima respuesta de A a B, ya.
 *  - cuando termine: cada vez que A cierra un turno, su respuesta va a B (una vez o hasta N veces).
 *  - a una hora: manda un texto fijo a B (o a la misma A) a las HH:MM. Para el "Continua" de las 14:36.
 *  Nada es automatico sin que lo pidas, y los modos repetidos tienen tope. */
export function Forward({ from, others, initialTarget, toast, onDone }: Props) {
  const [mode, setMode] = useState<Mode>("now");
  const targets = useMemo(() => (mode === "at" ? [from, ...others] : others), [mode, from, others]);
  const [target, setTarget] = useState(
    initialTarget && others.some((o) => o.session_id === initialTarget) ? initialTarget : others[0]?.session_id ?? "",
  );
  const [template, setTemplate] = useState(loadTemplate);
  const [reply, setReply] = useState(from.last_reply || "");
  const [text, setText] = useState(() => fill(loadTemplate(), from, from.last_reply || ""));
  const [atText, setAtText] = useState("Continuá");
  const [nativeText, setNativeText] = useState("");
  const [hhmm, setHhmm] = useState(() => fmtHhmm(new Date(Date.now() + 60 * 60 * 1000)));
  // si el usuario ya toco el texto, el digest que llega despues no lo pisa
  const dirtyRef = useRef(false);
  const [repeat, setRepeat] = useState(false);
  const [maxFires, setMaxFires] = useState(5);
  // "yo": la primera sesion de Claude del tablero con el mismo repo que el origen (la que coordina).
  // Si no existe, o es el mismo destino, el checkbox no aparece.
  const me = useMemo(() => others.find((o) => o.agent === "claude" && o.repo === from.repo && o.session_id !== from.session_id), [others, from.repo, from.session_id]);
  const [notifyMe, setNotifyMe] = useState(false);
  const [busy, setBusy] = useState(false);
  const targetSession = useMemo(() => targets.find((o) => o.session_id === target), [targets, target]);

  useEffect(() => {
    if (mode !== "at" && target === from.session_id) setTarget(others[0]?.session_id ?? "");
  }, [mode, target, from.session_id, others]);

  useEffect(() => {
    let cancelled = false;
    api.get<DigestResponse>(`/sessions/${from.session_id}/digest?n=5`).then((d) => {
      if (cancelled) return;
      const last = [...d.turns].reverse().find((t) => t.final && t.final.trim());
      if (last) {
        setReply(last.final);
        if (!dirtyRef.current) setText(fill(template, from, last.final));
      }
    }).catch(() => null);
    return () => {
      cancelled = true;
    };
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

  const submit = async () => {
    if (!targetSession) return;
    setBusy(true);
    try {
      if (mode === "now") {
        if (targetSession.pending_id) {
          toast("La sesión destino tiene un permiso pendiente", true);
          return;
        }
        const r = await api.post<{ chars: number }>(`/sessions/${targetSession.session_id}/send`, {
          text,
          attachments: [],
          from: from.session_id,
        });
        toast(`Enviado a ${shortName(targetSession)} (${r.chars} caracteres)`);
      } else if (mode === "native") {
        // se le habla a A (esta sesion) para que abra el canal con B; la flecha doble es A <-> B
        await api.post(`/sessions/${from.session_id}/send`, {
          text: nativeInstruction(targetSession, nativeText),
          attachments: [],
          link_to: targetSession.session_id,
          native: true,
        });
        toast(`${shortName(from)} va a abrir el canal con ${shortName(targetSession)}`);
      } else if (mode === "on_stop") {
        const rule = { kind: "on_stop", from: from.session_id, text: template, repeat, max_fires: repeat ? maxFires : 1 };
        await api.post("/rules", { ...rule, to: targetSession.session_id });
        const alsoMe = notifyMe && me && me.session_id !== targetSession.session_id ? me : null;
        if (alsoMe) await api.post("/rules", { ...rule, to: alsoMe.session_id });
        toast(`Cuando ${shortName(from)} termine, su respuesta va a ${shortName(targetSession)}${alsoMe ? ` y a ${shortName(alsoMe)}` : ""}`);
      } else {
        const at = nextTimeIso(hhmm);
        if (!at) {
          toast("Hora inválida", true);
          return;
        }
        // el origen queda registrado (si no es la misma sesion) para dibujar la flecha A -> B
        const src = targetSession.session_id === from.session_id ? null : from.session_id;
        await api.post("/rules", { kind: "at", from: src, to: targetSession.session_id, text: atText, at });
        toast(`A las ${hhmm} se manda "${atText}" a ${shortName(targetSession)}`);
      }
      onDone();
    } catch (e) {
      toast(`No se pudo: ${(e as Error).message}`, true);
    } finally {
      setBusy(false);
    }
  };

  const noOthers = !others.length && mode !== "at";

  // "escribilo": la frase se interpreta mientras se escribe y mueve los controles de abajo;
  // Enter crea la conexion directamente
  const [phrase, setPhrase] = useState("");
  const parsed = useMemo(() => parseConnection(phrase, from, others), [phrase, from, others]);
  const parsedOk = parsed.kind !== "none" && (parsed.kind === "at" || !!parsed.to);
  useEffect(() => {
    // solo cuando cambia la frase: `others`/`from` llegan nuevos con cada evento SSE y no deben
    // pisar lo que el usuario ajusto a mano
    const p = parseConnection(phrase, from, others);
    if (p.kind === "none" || (p.kind !== "at" && !p.to)) return;
    setMode(p.kind);
    if (p.kind === "at") {
      setHhmm(fmtHhmm(p.at));
      setAtText(p.text);
      if (p.toSelf) setTarget(from.session_id);
      else if (p.to) setTarget(p.to.session_id);
    } else if (p.to) {
      setTarget(p.to.session_id);
      if (p.kind === "on_stop") {
        setRepeat(p.repeat);
        setMaxFires(p.maxFires);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phrase]);

  // si el destino deja de ser Claude, el canal nativo no aplica
  useEffect(() => {
    if (mode === "native" && !(from.agent === "claude" && targetSession?.agent === "claude")) setMode("now");
  }, [mode, from.agent, targetSession?.agent]);

  return (
    <div className="fwd">
      <div className="row nl">
        <input
          type="text"
          value={phrase}
          autoFocus
          onChange={(e) => setPhrase(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && parsedOk && !busy) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder={`Escribilo: "continuá a las 16:00", "en 30 min seguí", "cuando termine mandale a ${others[0]?.repo ?? "MAPO"}"`}
          style={{ flex: 1 }}
        />
      </div>
      {phrase && (
        <div className={`small ${parsedOk ? "ok" : "dim"}`}>
          {parsedOk ? `Entendí: ${parsed.summary} · Enter para confirmar` : parsed.summary}
        </div>
      )}
      <div className="row modes">
        <label className={mode === "now" ? "on" : ""}>
          <input type="radio" checked={mode === "now"} onChange={() => setMode("now")} /> Ahora
        </label>
        <label className={mode === "on_stop" ? "on" : ""}>
          <input type="radio" checked={mode === "on_stop"} onChange={() => setMode("on_stop")} /> Cuando {from.repo} termine
        </label>
        <label className={mode === "at" ? "on" : ""}>
          <input type="radio" checked={mode === "at"} onChange={() => setMode("at")} /> A una hora
        </label>
        {from.agent === "claude" && targetSession?.agent === "claude" && (
          <label className={mode === "native" ? "on" : ""} title="las dos son Claude Code: pueden hablarse entre sí con SendMessage">
            <input type="radio" checked={mode === "native"} onChange={() => setMode("native")} /> ⇄ Canal nativo
          </label>
        )}
      </div>

      <div className="small dim">
        {mode === "now" && "Manda ya la última respuesta de esta sesión a la otra, como si la tipearas ahí."}
        {mode === "native" && "Las dos son Claude Code: esta sesión ubica a la otra con ListAgents y le habla con SendMessage. Los mensajes llegan aunque la otra esté trabajando, y se responden por el mismo canal. Vos les das el tema; ellas conversan."}
        {mode === "on_stop" && "Cada vez que esta sesión cierre un turno, su respuesta final se manda a la otra con la plantilla. Una vez, o hasta un tope."}
        {mode === "at" && "A la hora indicada se manda un texto fijo a la sesión elegida (puede ser esta misma). Sirve para el \"Continuá\" cuando vuelven los créditos."}
      </div>

      {noOthers ? (
        <div className="empty">No hay otra sesión viva a la que conectar.</div>
      ) : (
        <>
          <div className="row">
            <span className="small dim">{mode === "at" ? "Mandar a" : "Destino"}</span>
            <select value={target} onChange={(e) => setTarget(e.target.value)}>
              {targets.map((o) => (
                <option key={o.session_id} value={o.session_id}>
                  {o.session_id === from.session_id ? "esta misma sesión · " : ""}
                  {o.agent} · {o.repo} · {o.title || o.last_prompt || o.session_id.slice(0, 8)}
                </option>
              ))}
            </select>
          </div>

          {mode === "native" ? (
            <textarea
              value={nativeText}
              onChange={(e) => setNativeText(e.target.value)}
              rows={4}
              placeholder="El tema de la conversación. Ej: “Revisá lo que hizo la otra sesión en web/src y acordá con ella los cambios; que ella los aplique.”"
            />
          ) : mode === "at" ? (
            <div className="row">
              <span className="small dim">Hora</span>
              <input type="time" value={hhmm} onChange={(e) => setHhmm(e.target.value)} />
              <span className="small dim">Texto</span>
              <input type="text" value={atText} onChange={(e) => setAtText(e.target.value)} style={{ flex: 1 }} />
            </div>
          ) : (
            <>
              <details open={mode === "on_stop"}>
                <summary className="small dim pointer">plantilla ({"{repo} {agente} {titulo} {pedido} {respuesta}"})</summary>
                <textarea value={template} onChange={(e) => applyTemplate(e.target.value)} rows={3} />
              </details>
              {mode === "now" && (
                <textarea
                  value={text}
                  onChange={(e) => {
                    dirtyRef.current = true;
                    setText(e.target.value);
                  }}
                  rows={6}
                />
              )}
            </>
          )}

          {mode === "on_stop" && (
            <div className="row">
              <label className="small">
                <input type="radio" checked={!repeat} onChange={() => setRepeat(false)} /> una vez
              </label>
              <label className="small">
                <input type="radio" checked={repeat} onChange={() => setRepeat(true)} /> cada vez que termine, hasta
              </label>
              <input type="number" min={1} max={50} value={maxFires} disabled={!repeat} onChange={(e) => setMaxFires(Number(e.target.value))} style={{ width: 60 }} />
              <span className="small dim">veces</span>
            </div>
          )}
          {mode === "on_stop" && me && me.session_id !== targetSession?.session_id && (
            <div className="row">
              <label className="small" title={`crea una segunda regla igual hacia ${shortName(me)}`}>
                <input type="checkbox" checked={notifyMe} onChange={(e) => setNotifyMe(e.target.checked)} /> avisarme también acá ({shortName(me)})
              </label>
            </div>
          )}

          <div className="row">
            <span className="small dim">
              {mode === "now"
                ? "Si supera 500 caracteres viaja como adjunto .md"
                : mode === "native"
                  ? "Queda una flecha doble entre las dos; el digest muestra los mensajes que se cruzan"
                  : "La regla se ve como flecha punteada; click en el círculo la quita"}
            </span>
            <span className="sp" />
            <button onClick={onDone}>Cancelar</button>
            <button
              className="primary"
              disabled={busy || !targetSession || (mode === "now" && !text.trim()) || (mode === "at" && !atText.trim()) || (mode === "native" && !nativeText.trim())}
              onClick={submit}
            >
              {mode === "now" ? "Enviar ahora" : mode === "on_stop" ? "Conectar" : mode === "native" ? "Abrir canal" : "Programar"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
