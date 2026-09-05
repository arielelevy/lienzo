import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { parseConnection } from "../nl";
import type { DigestResponse, Session } from "../types";

const DEFAULT_TEMPLATE = "Mensaje de {repo} ({agente}) sobre '{titulo}':\n{respuesta}";
const KEY = "lienzo.forward.template";
type Mode = "now" | "on_stop" | "at";

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
  const d = new Date();
  d.setHours(Number(m[1]), Number(m[2]), 0, 0);
  if (d.getTime() <= Date.now()) d.setDate(d.getDate() + 1); // ya paso hoy: manana
  return d.toISOString();
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
  const [hhmm, setHhmm] = useState(() => {
    const d = new Date(Date.now() + 60 * 60 * 1000);
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  });
  const [repeat, setRepeat] = useState(false);
  const [maxFires, setMaxFires] = useState(5);
  const [busy, setBusy] = useState(false);
  const targetSession = useMemo(() => targets.find((o) => o.session_id === target), [targets, target]);

  useEffect(() => {
    if (mode !== "at" && target === from.session_id) setTarget(others[0]?.session_id ?? "");
  }, [mode, target, from.session_id, others]);

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
        toast(`Enviado a ${targetSession.repo} (${r.chars} caracteres)`);
      } else if (mode === "on_stop") {
        await api.post("/rules", {
          kind: "on_stop",
          from: from.session_id,
          to: targetSession.session_id,
          text: template,
          repeat,
          max_fires: repeat ? maxFires : 1,
        });
        toast(`Cuando ${from.repo} termine, su respuesta va a ${targetSession.repo}`);
      } else {
        const at = nextTimeIso(hhmm);
        if (!at) {
          toast("Hora inválida", true);
          return;
        }
        await api.post("/rules", { kind: "at", from: null, to: targetSession.session_id, text: atText, at });
        toast(`A las ${hhmm} se manda "${atText}" a ${targetSession.repo}`);
      }
      onDone();
    } catch (e) {
      toast(`No se pudo: ${(e as Error).message}`, true);
    } finally {
      setBusy(false);
    }
  };

  const noOthers = !others.length && mode !== "at";

  // "escribilo": una frase se interpreta como conexion y precarga los controles de abajo
  const [phrase, setPhrase] = useState("");
  const parsed = useMemo(() => parseConnection(phrase, from, others), [phrase, from, others]);
  const applyParsed = () => {
    if (parsed.kind === "none") return;
    setMode(parsed.kind);
    if (parsed.kind === "at") {
      setHhmm(`${String(parsed.at.getHours()).padStart(2, "0")}:${String(parsed.at.getMinutes()).padStart(2, "0")}`);
      setAtText(parsed.text);
      setTarget(parsed.to ? parsed.to.session_id : from.session_id);
    } else if (parsed.to) {
      setTarget(parsed.to.session_id);
      if (parsed.kind === "on_stop") {
        setRepeat(parsed.repeat);
        setMaxFires(parsed.maxFires);
      }
    }
  };
  const parsedOk = parsed.kind !== "none" && (parsed.kind === "at" || parsed.to);

  return (
    <div className="fwd">
      <div className="row nl">
        <input
          type="text"
          value={phrase}
          onChange={(e) => setPhrase(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && parsedOk) {
              e.preventDefault();
              applyParsed();
            }
          }}
          placeholder={`Escribilo: "continuá a las 16:00", "en 30 min seguí", "cuando termine mandale a ${others[0]?.repo ?? "MAPO"}"`}
          style={{ flex: 1 }}
        />
        <button disabled={!parsedOk} onClick={applyParsed} title="cargar lo entendido en los controles de abajo">Interpretar</button>
      </div>
      {phrase && <div className={`small ${parsedOk ? "ok" : "dim"}`}>{parsedOk ? `Entendí: ${parsed.summary}` : parsed.summary}</div>}
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
      </div>

      <div className="small dim">
        {mode === "now" && "Manda ya la última respuesta de esta sesión a la otra, como si la tipearas ahí."}
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

          {mode === "at" ? (
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
              {mode === "now" && <textarea value={text} onChange={(e) => setText(e.target.value)} rows={6} />}
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

          <div className="row">
            <span className="small dim">
              {mode === "now" ? "Si supera 500 caracteres viaja como adjunto .md" : "La regla se ve como flecha punteada; click en el círculo la quita"}
            </span>
            <span className="sp" />
            <button onClick={onDone}>Cancelar</button>
            <button className="primary" disabled={busy || !targetSession || (mode === "now" && !text.trim()) || (mode === "at" && !atText.trim())} onClick={submit}>
              {mode === "now" ? "Enviar ahora" : mode === "on_stop" ? "Conectar" : "Programar"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
