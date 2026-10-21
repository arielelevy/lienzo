import { useEffect, useRef, useState } from "react";
import { ApiError, sendNotice, sessionsApi, type SendResult } from "../api";
import { shortName } from "../names";
import type { Session } from "../types";

interface Fail {
  sid: string;
  name: string;
  reason: string;
}

interface Result {
  what: string;
  ok: number;
  fails: Fail[];
  pending: Fail[];
}

interface SendBatch {
  text: string;
  result: Result;
}

// Un timeout, error de transporte o 5xx puede llegar después de escribir: no prueba rechazo.
function rejectedBeforeSend(error: unknown): boolean {
  return error instanceof ApiError && (error.body.estado === "rechazado" ||
    (!error.body.estado && [400, 401, 403, 404, 409, 413, 429].includes(error.status)));
}

interface Props {
  /** session_ids marcados que todavia existen, en el orden en que se marcaron */
  sids: string[];
  sessions: Record<string, Session>;
  onClear: () => void;
  /** las tarjetas que se ven ahora (pasan todos los filtros, de cualquier PC o proyecto) y todavia
   *  no estan marcadas: el boton «Marcar las visibles» las suma */
  visibleToMark: string[];
  onMarkVisible: () => void;
}

/** Barra flotante de la seleccion multiple: aparece con una o mas tarjetas marcadas (Ctrl + click,
 *  o Ctrl + click en el chip de un proyecto). «Enviar a todas» y «Interrumpir» van de a una, en
 *  orden, contra las mismas rutas que usa una tarjeta sola (`POST /sessions/<sid>/send` e
 *  `.../interrupt`); las de otra PC entran igual porque el server enruta solo. Si una falla, las
 *  demas siguen, y al final se cuenta «N ok / M fallaron» con el motivo de cada una. */
export function SelectionBar({ sids, sessions, onClear, visibleToMark, onMarkVisible }: Props) {
  const [composing, setComposing] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [batch, setBatch] = useState<SendBatch | null>(null);
  const running = useRef(false);
  const areaRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (composing) areaRef.current?.focus();
  }, [composing]);

  // sin tarjetas marcadas no hay barra, y al volver a marcar empieza limpia
  if (sids.length === 0) {
    if (composing || text || result || batch) {
      setComposing(false);
      setText("");
      setResult(null);
      setBatch(null);
    }
    return null;
  }

  const run = async (what: string, call: (sid: string) => Promise<unknown>, targets = sids, previous?: Result) => {
    if (running.current) return null;
    running.current = true;
    setBusy(true);
    setResult(null);
    const fails: Fail[] = previous?.fails.filter(f => !targets.includes(f.sid)) ?? [];
    const pending: Fail[] = [...(previous?.pending ?? [])];
    let ok = previous?.ok ?? 0;
    for (const sid of targets) {
      try {
        const response = await call(sid);
        if (what === "Envío") {
          const notice = sendNotice(response as SendResult);
          if (!notice.confirmed) {
            const rejected = (response as SendResult).estado === "rechazado";
            const list = rejected ? fails : pending;
            list.push({ sid, name: shortName(sessions[sid]), reason: `${notice.text}. ${rejected ? "Podés reintentar el rechazo." : "No reenvíes el texto."}` });
            continue;
          }
        }
        ok++;
      } catch (e) {
        const uncertain = what === "Envío" && !rejectedBeforeSend(e);
        (uncertain ? pending : fails).push({ sid, name: shortName(sessions[sid]),
          reason: `${(e as Error).message}${uncertain ? ". No reenvíes el texto." : ""}` });
      }
    }
    setBusy(false);
    running.current = false;
    const next = { what, ok, fails, pending };
    setResult(next);
    return next;
  };

  // El lote conserva texto y resultados aunque se cierre el editor. Agregar tarjetas no amplía
  // silenciosamente un reintento; los rechazos desmarcados tampoco se envían.
  const retry = batch?.result.fails.filter(f => sids.includes(f.sid) && sessions[f.sid]).map(f => f.sid) ?? [];
  const send = async () => {
    const t = batch ? batch.text : text.trim();
    const targets = batch ? retry : [...sids];
    if (!t || busy || running.current || !targets.length) return;
    const outcome = await run("Envío", (sid) => sessionsApi.send(sid, { text: t, attachments: [] }), targets, batch?.result);
    if (!outcome) return;
    setBatch({ text: t, result: outcome });
    if (outcome.fails.length === 0 && outcome.pending.length === 0) {
      setText("");
      setComposing(false);
    }
  };
  const interrupt = () => {
    if (!busy) void run("Interrupción", (sid) => sessionsApi.interrupt(sid));
  };

  const n = sids.length;
  return (
    <div className="selbar" role="region" aria-label="selección de tarjetas">
      <div className="selrow">
        <span className="selcount" role="status" aria-live="polite">
          {n} {n === 1 ? "tarjeta" : "tarjetas"}
        </span>
        <button
          type="button"
          disabled={busy || visibleToMark.length === 0}
          title={visibleToMark.length ? `suma las ${visibleToMark.length} que se ven y no están marcadas, según los filtros de ahora` : "ya están marcadas todas las que se ven"}
          onClick={onMarkVisible}
        >
          Marcar las visibles
        </button>
        <button type="button" aria-expanded={composing} disabled={busy} onClick={() => setComposing((v) => !v)}>
          Enviar a todas
        </button>
        <button type="button" disabled={busy} title="un Esc en la terminal de cada tarjeta marcada" onClick={interrupt}>
          Interrumpir
        </button>
        <button type="button" disabled={busy} onClick={onClear} title="desmarcar todas (Esc)">
          Limpiar
        </button>
      </div>
      {composing && (
        <div className="selsend">
          <textarea
            ref={areaRef}
            value={text}
            readOnly={busy || batch !== null}
            aria-label={`texto para enviar a ${n} ${n === 1 ? "tarjeta" : "tarjetas"}`}
            placeholder="Lo que se les escribe a todas…"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              // Esc cierra la caja y no le llega al tablero: pela una capa por vez
              if (e.key === "Escape") {
                e.stopPropagation();
                setComposing(false);
              } else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                void send();
              }
            }}
          />
          <div className="selrow">
            <button type="button" className="primary" disabled={busy || !text.trim() || (batch !== null && retry.length === 0)} onClick={() => void send()}>
              {busy ? "Enviando…" : batch ? (retry.length ? `Reintentar ${retry.length} ${retry.length === 1 ? "rechazo" : "rechazos"}` : "Sin rechazos para reintentar") : `Enviar a ${n}`}
            </button>
            {batch && <button type="button" disabled={busy} onClick={() => {
              setBatch(null);
              setResult(null);
              areaRef.current?.focus();
            }}>Nuevo lote a todas</button>}
            <button type="button" disabled={busy} onClick={() => setComposing(false)}>
              Cancelar
            </button>
            <span className="dim small">Ctrl + Enter envía</span>
          </div>
          {batch && <p className="dim small">El reintento conserva el texto y sólo incluye rechazos. Un nuevo lote vuelve a incluir todas las tarjetas seleccionadas.</p>}
        </div>
      )}
      <div className="selresult" role="status" aria-live="polite">
        {result && (
          <>
            <b>
              {result.what}: {result.ok} ok / {result.pending.length > 0 ? `${result.pending.length} pendientes / ` : ""}{result.fails.length} fallaron
            </b>
            {result.fails.length + result.pending.length > 0 && (
              <ul>
                {[...result.pending, ...result.fails].map((f) => (
                  <li key={f.sid}>
                    {f.name}: {f.reason}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </div>
  );
}
