import { useEffect, useRef, useState } from "react";
import { sessionsApi } from "../api";
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
  const areaRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (composing) areaRef.current?.focus();
  }, [composing]);

  // sin tarjetas marcadas no hay barra, y al volver a marcar empieza limpia
  if (sids.length === 0) {
    if (composing || text || result) {
      setComposing(false);
      setText("");
      setResult(null);
    }
    return null;
  }

  const run = async (what: string, call: (sid: string) => Promise<unknown>) => {
    setBusy(true);
    setResult(null);
    const fails: Fail[] = [];
    let ok = 0;
    for (const sid of sids) {
      try {
        await call(sid);
        ok++;
      } catch (e) {
        fails.push({ sid, name: shortName(sessions[sid]), reason: (e as Error).message });
      }
    }
    setBusy(false);
    setResult({ what, ok, fails });
    return fails.length === 0;
  };

  const send = async () => {
    const t = text.trim();
    if (!t || busy) return;
    const todas = await run("Envío", (sid) => sessionsApi.send(sid, { text: t, attachments: [] }));
    if (todas) {
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
            <button type="button" className="primary" disabled={busy || !text.trim()} onClick={() => void send()}>
              {busy ? "Enviando…" : `Enviar a ${n}`}
            </button>
            <button type="button" disabled={busy} onClick={() => setComposing(false)}>
              Cancelar
            </button>
            <span className="dim small">Ctrl + Enter envía</span>
          </div>
        </div>
      )}
      <div className="selresult" role="status" aria-live="polite">
        {result && (
          <>
            <b>
              {result.what}: {result.ok} ok / {result.fails.length} fallaron
            </b>
            {result.fails.length > 0 && (
              <ul>
                {result.fails.map((f) => (
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
