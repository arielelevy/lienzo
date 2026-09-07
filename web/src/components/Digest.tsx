import ReactMarkdown from "react-markdown";
import { whenLabel } from "../names";
import type { DigestTurn } from "../types";
import { copyText, useLocalToast, type ToastFn } from "./Card";

export function Digest({ turn: t, toast: extToast }: { turn: DigestTurn; toast?: ToastFn }) {
  const { toast, node: toastNode } = useLocalToast(extToast);
  const list = (items: string[], cls?: string) => (
    <ul>
      {items.map((x, i) => (
        <li key={i} className={cls}>
          {x}
        </li>
      ))}
    </ul>
  );
  return (
    <div className="dg">
      <div className="ts">
        {/* cruda del server venia en UTC y con milisegundos */}
        {t.ts_start ? whenLabel(t.ts_start, true) : "sin hora"} {t.ended ? "" : "· en curso"}
      </div>
      <div className="p">› {t.prompt}</div>
      {/* Lo que el agente fue diciendo en el turno, antes de la respuesta. Sin esto Destacados
          mostraba el pedido y una sola frase: en un turno en curso, esa frase es el ultimo aviso
          de avance y lo que explicaba el problema quedaba afuera (medido: 55% de los turnos dicen
          mas de una cosa). Van atenuados, que la respuesta se siga leyendo como la respuesta, y
          enteros: lo largo lo resuelve el scroll del panel, no un recorte con puntos suspensivos. */}
      {!!t.says?.length && (
        <div className="said">
          {t.says.map((x, i) => (
            <div className="md" key={i}>
              <ReactMarkdown>{x}</ReactMarkdown>
            </div>
          ))}
        </div>
      )}
      {t.final && (
        <>
          <div className="f md">
            <ReactMarkdown>{t.final}</ReactMarkdown>
          </div>
          <div className="frow">
            <button
              type="button"
              className="copy"
              title="copiar la respuesta final"
              aria-label="copiar la respuesta final"
              onClick={() => copyText(t.final, toast)}
            >
              📋 copiar
            </button>
          </div>
        </>
      )}
      {t.files.length > 0 && (
        <details className="fold">
          <summary className="k">archivos ({t.files.length})</summary>
          {list(t.files)}
        </details>
      )}
      {t.commands.length > 0 && (
        <details className="fold">
          <summary className="k">comandos ({t.commands.length})</summary>
          {list(t.commands)}
        </details>
      )}
      {t.errors.length > 0 && (
        <>
          <div className="k">errores</div>
          {list(t.errors, "err")}
        </>
      )}
      {t.questions.length > 0 && (
        <>
          <div className="k">preguntas</div>
          {list(t.questions)}
        </>
      )}
      {!!t.peers?.length && (
        <>
          <div className="k">mensajes a otras sesiones</div>
          {list(t.peers)}
        </>
      )}
      <div className="stats">
        {t.tools} herramientas · {t.reads} lecturas
        {t.subagents ? ` · ${t.subagents} líneas de subagente` : ""}
      </div>
      {toastNode}
    </div>
  );
}
