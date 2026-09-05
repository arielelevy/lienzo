import ReactMarkdown from "react-markdown";
import type { DigestTurn } from "../types";

export function Digest({ turn: t }: { turn: DigestTurn }) {
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
        {t.ts_start} {t.ended ? "" : "· en curso"}
      </div>
      <div className="p">› {t.prompt}</div>
      {t.final && (
        <div className="f md">
          <ReactMarkdown>{t.final}</ReactMarkdown>
        </div>
      )}
      {t.files.length > 0 && (
        <>
          <div className="k">archivos</div>
          {list(t.files)}
        </>
      )}
      {t.commands.length > 0 && (
        <>
          <div className="k">comandos</div>
          {list(t.commands)}
        </>
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
      {(t.peers?.length ?? 0) > 0 && (
        <>
          <div className="k">mensajes a otras sesiones</div>
          {list(t.peers!)}
        </>
      )}
      <div className="stats">
        {t.tools} herramientas · {t.reads} lecturas
        {t.subagents ? ` · ${t.subagents} líneas de subagente` : ""}
      </div>
    </div>
  );
}
