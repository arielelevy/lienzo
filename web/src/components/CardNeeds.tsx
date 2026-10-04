import { detail } from "../api";
import type { CardActions } from "../hooks/useCardActions";
import { hhmm } from "../nl";
import { needsLabel } from "../names";
import type { Pending, Session } from "../types";
import { Ask, askQuestions } from "./Ask";
import { PermissionButtons, PermissionPrompt } from "./PermissionPrompt";

interface Props {
  session: Session;
  pending?: Pending;
  /** la tarjeta muestra los botones rapidos: una ociosa no repite aca el aviso, va en esa fila */
  quick: boolean;
  writable: boolean;
  actions: Pick<CardActions, "busy" | "codaDecide" | "pickDialog" | "autorizarDenegado">;
  onDecide: (requestId: string, decision: "allow" | "deny") => Promise<void>;
  onAnswer: (requestId: string, answers: Record<string, string>) => Promise<void>;
}

/** Lo que la sesion pide, en la tarjeta: el permiso del hook (o la pregunta con opciones), el que
 *  se contesta en la terminal (CODA), lo que una regla le denego y el dialogo de la TUI. Va antes
 *  que la respuesta: Permitir/Denegar es lo primero visible. */
export function CardNeeds({ session: s, pending: p, quick, writable, actions, onDecide, onAnswer }: Props) {
  const { busy, codaDecide, pickDialog, autorizarDenegado } = actions;
  // pendiente que en realidad es una pregunta con opciones: se contesta eligiendo (Ask.tsx)
  const preguntas = askQuestions(p);
  return (
    <>
      {/* Si lo que espera es una pregunta con opciones, van las opciones: no hay nada que permitir */}
      {p && preguntas.length > 0 ? (
        <Ask pending={p} questions={preguntas} onAnswer={onAnswer} onDecide={onDecide} />
      ) : p ? (
        <PermissionPrompt tool={p.tool_name} detail={detail(p.tool_input)} note={`vence ${hhmm(new Date(p.expires_at))}`} onDecide={(d) => onDecide(p.request_id, d)} />
      ) : s.state === "te_necesita" && s.needs && !(quick && s.needs.kind === "idle") ? (
        /* ociosa con botones rapidos: el aviso va en una linea con los botones, mas abajo */
        <div className="needs terminal">
          <b>{needsLabel(s.needs)}</b>
          {s.needs.detail && <code>{s.needs.detail}</code>}
          {s.needs.coda_at && s.needs.where === "terminal" && writable ? (
            // CODA no tiene un hook que espere la respuesta: los botones teclean Enter o Esc en su
            // diálogo, y el server confirma antes en la pantalla que el diálogo siga abierto
            <PermissionButtons onDecide={codaDecide} note="se teclea en su terminal" />
          ) : (
            <div className="dim small">
              {s.needs.kind === "idle" ? "podés escribirle desde acá" : s.needs.where === "enviado" ? "respuesta enviada a la terminal" : s.needs.where === "terminal" ? "contestar en la terminal" : "esperando al lienzo"}
            </div>
          )}
        </div>
      ) : null}
      {/* permiso que una regla, una politica o un clasificador denego: no espera nada, pero si nadie
          lo ve el agente sigue sin eso (medido el 2026-10-04 en la otra PC) */}
      {s.last_denied && !p && (
        <div className="needs denied">
          <b>Denegado: {s.last_denied.tool}</b>
          {s.last_denied.detalle && <code>{s.last_denied.detalle}</code>}
          {s.last_denied.motivo && <div className="dim small">{s.last_denied.motivo}</div>}
          {writable && (
            <div className="btns">
              <button className="allow" onClick={(e) => { e.stopPropagation(); autorizarDenegado(); }}>Autorizar y que reintente</button>
            </div>
          )}
        </div>
      )}
      {/* diálogo de la TUI ("Switch model?"): no es un permiso, no dispara hooks y nadie lo ve
          desde afuera; se lee de la pantalla cada 5 s. Un permiso pendiente le gana (el server ya
          no publica el diálogo en ese caso) */}
      {!p && s.dialog && writable && (
        <div className="needs ask tui">
          <b>Espera que elijas en la terminal</b>
          <div className="q">
            <div className="qtext">{s.dialog.question}</div>
            {s.dialog.detail && <div className="dim small">{s.dialog.detail}</div>}
            {s.dialog.options.map((o) => (
              <button
                key={o.n}
                type="button"
                className={`opt ${o.n === s.dialog!.selected ? "on" : ""}`}
                disabled={busy}
                data-always-tab=""
                title={o.n === s.dialog!.selected ? "la que está marcada en la terminal" : "se teclea el número en su terminal"}
                onClick={(e) => {
                  e.stopPropagation();
                  pickDialog(o.n, o.text);
                }}
              >
                <span className="olabel">{o.n}. {o.text}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
