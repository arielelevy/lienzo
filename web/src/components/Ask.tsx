import { useState } from "react";
import { hhmm } from "../nl";
import type { AskQuestion, Pending } from "../types";

/** Bloque de una pregunta con opciones (AskUserQuestion), en la tarjeta y en el panel.
 *
 *  AskUserQuestion llega por el mismo hook que cualquier permiso, pero no es un permiso: no hay
 *  nada que permitir ni que denegar, hay una opción que elegir. Con los botones Permitir/Denegar
 *  el lienzo no podía contestarla — permitir sólo devolvía la pregunta al selector de la terminal
 *  y a los 60 s el pedido vencía. Acá van las opciones tal como las escribió el agente, y la
 *  elegida viaja en `answers` del propio input de la herramienta (ver `answered_input` en hook.py).
 *
 *  Una sola pregunta de una sola opción se contesta con un toque, sin confirmar: es el caso
 *  común y en el celular es lo único que se puede pedir. Con varias preguntas, con multiSelect o
 *  con texto escrito, primero se arma la respuesta y después se manda con "Contestar". */
export function Ask({ pending, questions, onAnswer, onDecide }: Props) {
  const [sel, setSel] = useState<Record<string, string[]>>({});
  const [otro, setOtro] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const solo = questions.length === 1 && !questions[0].multiSelect;

  /** Lo que se le contesta a una pregunta: el texto escrito le gana a las opciones marcadas. */
  const valor = (q: AskQuestion): string => (otro[q.question]?.trim() || (sel[q.question] ?? []).join(", ")).trim();
  const armado = Object.fromEntries(questions.map((q) => [q.question, valor(q)]).filter(([, v]) => v));
  const faltan = questions.length - Object.keys(armado).length;

  const mandar = async (answers: Record<string, string>) => {
    if (busy || !Object.keys(answers).length) return;
    setBusy(true);
    try {
      await onAnswer(pending.request_id, answers);
    } finally {
      setBusy(false);
    }
  };

  const tocar = (q: AskQuestion, label: string) => {
    // una sola pregunta de una sola opción y nada escrito: el toque ES la respuesta
    if (solo && !otro[q.question]?.trim()) return mandar({ [q.question]: label });
    setSel((s) => {
      const hay = s[q.question] ?? [];
      if (!q.multiSelect) return { ...s, [q.question]: hay[0] === label ? [] : [label] };
      return { ...s, [q.question]: hay.includes(label) ? hay.filter((l) => l !== label) : [...hay, label] };
    });
  };

  return (
    /* el bloque entero NO frena la propagacion: ocupa media tarjeta y frenarlo dejaba el doble
       click sin abrir el panel (la misma razon que en el bloque de permiso). La frenan uno por uno
       los controles, que son los que tienen que responder al click sin elegir la tarjeta. */
    <div className="needs ask">
      <b>{questions.length > 1 ? `Te hace ${questions.length} preguntas` : "Te hace una pregunta"}</b>
      {questions.map((q) => (
        <div className="q" key={q.question}>
          <div className="qtext">{q.question}</div>
          {q.multiSelect && <div className="dim small">se puede elegir más de una</div>}
          {(q.options ?? []).map((o) => {
            const on = (sel[q.question] ?? []).includes(o.label);
            return (
              <button
                type="button"
                key={o.label}
                className={`opt ${on ? "on" : ""}`}
                disabled={busy}
                data-always-tab=""
                onClick={(e) => {
                  e.stopPropagation();
                  tocar(q, o.label);
                }}
              >
                <span className="olabel">{o.label}</span>
                {o.description && <span className="odesc">{o.description}</span>}
              </button>
            );
          })}
          <input
            className="otro"
            type="text"
            placeholder="…o escribí otra cosa"
            value={otro[q.question] ?? ""}
            disabled={busy}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => setOtro((s) => ({ ...s, [q.question]: e.target.value }))}
            onKeyDown={(e) => {
              // la tarjeta escucha teclas (Esc, doble click): lo que se escribe acá es de la caja
              e.stopPropagation();
              if (e.key === "Enter" && valor(q)) void mandar(armado);
            }}
          />
        </div>
      ))}
      <div className="btns">
        <button
          className="allow"
          disabled={busy || !Object.keys(armado).length}
          onClick={(e) => {
            e.stopPropagation();
            void mandar(armado);
          }}
        >
          Contestar
        </button>
        {faltan > 0 && Object.keys(armado).length > 0 && <span className="dim small">quedan {faltan} sin contestar</span>}
        <button
          className="term"
          disabled={busy}
          title="deja la pregunta en la terminal y libera al agente de la espera"
          onClick={(e) => {
            e.stopPropagation();
            onDecide(pending.request_id, "allow");
          }}
        >
          Contestar en la terminal
        </button>
        <span className="dim small">vence {hhmm(new Date(pending.expires_at))}</span>
      </div>
    </div>
  );
}

interface Props {
  pending: Pending;
  /** las preguntas ya validadas (`askQuestions`): el componente no se dibuja sin al menos una */
  questions: AskQuestion[];
  onAnswer: (requestId: string, answers: Record<string, string>) => Promise<void>;
  onDecide: (requestId: string, decision: "allow" | "deny") => void;
}

/** Las preguntas de un pendiente, o [] si no es un AskUserQuestion. El tool_input viene del hook
 *  y se dibuja: se valida forma por forma, que un `options` que no sea lista rompe el tablero. */
export function askQuestions(p: Pending | undefined): AskQuestion[] {
  if (!p || p.tool_name !== "AskUserQuestion") return [];
  const inp = p.tool_input as { questions?: unknown } | null;
  if (!inp || typeof inp !== "object" || !Array.isArray(inp.questions)) return [];
  const out: AskQuestion[] = [];
  for (const raw of inp.questions) {
    if (!raw || typeof raw !== "object") continue;
    const q = raw as Record<string, unknown>;
    if (typeof q.question !== "string" || !q.question.trim()) continue;
    const options = Array.isArray(q.options)
      ? q.options
          .filter((o): o is Record<string, unknown> => !!o && typeof o === "object" && typeof o.label === "string")
          .map((o) => ({ label: String(o.label), description: typeof o.description === "string" ? o.description : "" }))
      : [];
    out.push({ question: q.question, header: typeof q.header === "string" ? q.header : "", multiSelect: !!q.multiSelect, options });
  }
  return out;
}
