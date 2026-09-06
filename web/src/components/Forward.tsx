import { useEffect, useMemo, useState } from "react";
import { ApiError, ago, api } from "../api";
import { coordinatorOf, everySeconds, fmtEvery, hhmm as fmtHhmm, nextAt, parseConnection, splitEvery, type EveryUnit } from "../nl";
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
 *  - programar: manda un texto fijo a B (o a la misma A) a las HH:MM, una vez o cada tanto con tope.
 *    Para el "Continua" de las 14:36, o "cada 30 min continuá hasta 5 veces".
 *  Nada es automatico sin que lo pidas, y los modos repetidos tienen tope.
 *  Con initialTarget === from (la tarjeta se solto sobre si misma) arranca en "programar" a la propia
 *  sesion: es el unico modo con sentido para un bucle. */
export function Forward({ from, others, initialTarget, toast, onDone }: Props) {
  const onItself = initialTarget === from.session_id;
  const [mode, setMode] = useState<Mode>(onItself ? "at" : "now");
  const targets = useMemo(() => (mode === "at" ? [from, ...others] : others), [mode, from, others]);
  const [target, setTarget] = useState(
    onItself ? from.session_id : initialTarget && others.some((o) => o.session_id === initialTarget) ? initialTarget : others[0]?.session_id ?? "",
  );
  const [template, setTemplate] = useState(loadTemplate);
  const [reply, setReply] = useState(from.last_reply || "");
  // lo que se manda en "ahora": la plantilla rellena, salvo que el usuario la haya editado a mano
  // (entonces el digest que llega despues no la pisa)
  const [textEdit, setTextEdit] = useState<string | null>(null);
  const text = textEdit ?? fill(template, from, reply);
  const [atText, setAtText] = useState("Continuá");
  const [nativeText, setNativeText] = useState("");
  const [hhmm, setHhmm] = useState(() => fmtHhmm(new Date(Date.now() + 60 * 60 * 1000)));
  const [repeat, setRepeat] = useState(false);
  // tope compartido: "cuando termine, hasta N veces" y "cada tanto, hasta N veces"
  const [maxFires, setMaxFires] = useState(5);
  // modo programar, periodico: apagado por defecto; con every_s el backend saltea (sin contar) los
  // disparos que caen con el destino trabajando, salvo que skipBusy se apague
  const [every, setEvery] = useState(false);
  const [everyQty, setEveryQty] = useState(30);
  const [everyUnit, setEveryUnit] = useState<EveryUnit>("min");
  const [skipBusy, setSkipBusy] = useState(true);
  const everySec = everySeconds(everyQty, everyUnit);
  const setEverySec = (sec: number) => {
    const e = splitEvery(sec);
    setEveryQty(e.everyN);
    setEveryUnit(e.everyUnit);
  };
  // "yo": la primera sesion de Claude del tablero con el mismo repo que el origen (la que coordina).
  // Si no existe, o es el mismo destino, el checkbox no aparece.
  const me = useMemo(() => coordinatorOf(from.repo, others, from.session_id), [others, from.repo, from.session_id]);
  const [notifyMe, setNotifyMe] = useState(false);
  const [busy, setBusy] = useState(false);
  // 409 del server: ya hay una programada a ±2 min hacia el mismo destino. Se muestra en el dialogo
  // y "Reemplazar" repite el POST con replace: true (dos mensajes al mismo minuto nunca es lo que uno quiere)
  const [conflict, setConflict] = useState<{ at: string; text: string } | null>(null);
  const targetSession = useMemo(() => targets.find((o) => o.session_id === target), [targets, target]);

  useEffect(() => {
    if (mode !== "at" && target === from.session_id) setTarget(others[0]?.session_id ?? "");
  }, [mode, target, from.session_id, others]);

  useEffect(() => {
    let cancelled = false;
    api.get<DigestResponse>(`/sessions/${from.session_id}/digest?n=5`).then((d) => {
      if (cancelled) return;
      const last = [...d.turns].reverse().find((t) => t.final && t.final.trim());
      if (last) setReply(last.final);
    }).catch(() => null);
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [from.session_id]);

  const applyTemplate = (tpl: string) => {
    setTemplate(tpl);
    setTextEdit(null);
    try {
      localStorage.setItem(KEY, tpl);
    } catch {
      /* sin storage, no importa */
    }
  };

  const submit = async (replace = false) => {
    if (!targetSession) return;
    setBusy(true);
    setConflict(null);
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
        const base = { kind: "at", from: src, to: targetSession.session_id, text: atText, at, ...(replace ? { replace: true } : {}) };
        try {
          if (every) {
            const fires = Math.min(50, Math.max(1, maxFires));
            await api.post("/rules", { ...base, every_s: everySec, max_fires: fires, skip_busy: skipBusy });
            toast(`Cada ${fmtEvery(everySec)} desde las ${hhmm} se manda "${atText}" a ${shortName(targetSession)} (hasta ${fires} ${fires === 1 ? "vez" : "veces"})`);
          } else {
            await api.post("/rules", base);
            toast(`A las ${hhmm} se manda "${atText}" a ${shortName(targetSession)}`);
          }
        } catch (e) {
          // 409 con replace: el body trae la programada que choca (at, text)
          const b = e instanceof ApiError && e.status === 409 && e.body.replace === true ? e.body : null;
          if (!b) throw e;
          setConflict({ at: fmtHhmm(new Date(String(b.at))), text: String(b.text ?? "") });
          return;
        }
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
  // el resumen nombra al destino que ya tiene el dialogo cuando la frase no dice ninguno
  const currentLabel = targetSession ? (targetSession.session_id === from.session_id ? "esta sesión" : shortName(targetSession)) : undefined;
  const parsed = useMemo(() => parseConnection(phrase, from, others, { current: currentLabel, name: shortName }), [phrase, from, others, currentLabel]);
  // "avisame" ya viene resuelto a la coordinadora (coordinatorOf); si no hay ninguna, la frase no alcanza
  const parsedOk = parsed.kind !== "none" && (parsed.kind === "at" || !!parsed.to);
  useEffect(() => {
    // solo cuando cambia la frase: `others`/`from` llegan nuevos con cada evento SSE y no deben
    // pisar lo que el usuario ajusto a mano. Si no se entiende nada, los controles quedan como
    // estaban (el resumen lo dice); si se entiende el modo pero falta el destino, el radio cambia
    // igual para que no contradiga al resumen
    const p = parseConnection(phrase, from, others);
    if (p.kind === "none") return;
    setMode(p.kind);
    const to = p.to;
    if (p.kind === "at") {
      setHhmm(fmtHhmm(p.at));
      setAtText(p.text);
      if (p.toSelf) setTarget(from.session_id);
      else if (to) setTarget(to.session_id);
      setEvery(!!p.every);
      if (p.every) {
        setEverySec(p.every);
        setMaxFires(p.maxFires);
      }
    } else if (to) {
      setTarget(to.session_id);
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
          placeholder={
            onItself
              ? 'Escribilo: "continuá a las 9", "cada 30 min continuá", "en 2 h seguí hasta 3 veces"'
              : `Escribilo: "continuá a las 16:00", "cada 30 min seguí", "cuando termine mandale a ${others[0]?.repo ?? "MAPO"}"`
          }
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
          <input type="radio" checked={mode === "at"} onChange={() => setMode("at")} /> Programar
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
        {mode === "at" &&
          "A la hora indicada se manda un texto fijo a la sesión elegida (puede ser esta misma). Sirve para el \"Continuá\" cuando vuelven los créditos. Con \"repetir cada\" se vuelve a mandar cada tanto, hasta un tope de veces; los disparos que caen con la sesión trabajando se saltean sin contar."}
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
            <>
              <div className="row">
                <span className="small dim">{every ? "Primera vez" : "Hora"}</span>
                <input type="time" value={hhmm} onChange={(e) => setHhmm(e.target.value)} />
                <span className="small dim">Texto</span>
                <input type="text" value={atText} onChange={(e) => setAtText(e.target.value)} style={{ flex: 1 }} />
              </div>
              <div className="row">
                <label className="small">
                  <input type="checkbox" checked={every} onChange={(e) => setEvery(e.target.checked)} /> repetir cada
                </label>
                <input type="number" min={1} max={999} value={everyQty} disabled={!every} onChange={(e) => setEveryQty(Math.max(1, Number(e.target.value) || 1))} style={{ width: 60 }} />
                <select value={everyUnit} disabled={!every} onChange={(e) => setEveryUnit(e.target.value as EveryUnit)}>
                  <option value="min">min</option>
                  <option value="h">h</option>
                </select>
                {every && (
                  <>
                    <span className="small dim">hasta</span>
                    <input type="number" min={1} max={50} value={maxFires} onChange={(e) => setMaxFires(Math.min(50, Math.max(1, Number(e.target.value) || 1)))} style={{ width: 60 }} />
                    <span className="small dim">veces</span>
                    <label className="small" title="si está trabajando, ese disparo se saltea y no cuenta">
                      <input type="checkbox" checked={skipBusy} onChange={(e) => setSkipBusy(e.target.checked)} /> sólo si está libre
                    </label>
                  </>
                )}
              </div>
            </>
          ) : (
            <>
              <details open={mode === "on_stop"}>
                <summary className="small dim pointer">plantilla ({"{repo} {agente} {titulo} {pedido} {respuesta}"})</summary>
                <textarea value={template} onChange={(e) => applyTemplate(e.target.value)} rows={3} />
              </details>
              {mode === "now" && (
                <textarea value={text} onChange={(e) => setTextEdit(e.target.value)} rows={6} />
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

          {conflict && (
            <div className="row conflict">
              <span className="small">
                Ya hay una programada a las {conflict.at} ("{conflict.text}").
              </span>
              <button className="primary" disabled={busy} onClick={() => submit(true)} title="quita la existente y deja esta">
                Reemplazar
              </button>
              <button disabled={busy} onClick={() => setConflict(null)} title="deja la que ya está y no crea esta">
                Cancelar
              </button>
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
              onClick={() => submit()}
            >
              {mode === "now" ? "Enviar ahora" : mode === "on_stop" ? "Conectar" : mode === "native" ? "Abrir canal" : "Programar"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
