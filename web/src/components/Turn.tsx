import { useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import { detail } from "../api";
import { whenLabel, copyLabel, useCopyState} from "../names";
import type { Block, Turn } from "../types";

type ToolB = Extract<Block, { kind: "tool" }>;

/** lineas del resultado que se muestran al abrir una herramienta */
const RESULT_LINES = 40;
/** cuantas herramientas seguidas hacen falta para que se plieguen en una sola linea */
const RUN_FOLD = 3;
/** hasta donde se corta la linea de una herramienta cerrada */
const LINE_MAX = 160;

/** Boton que avisa solo, cambiando su texto dos segundos, en vez de depender del toast global: el
 *  Panel no le pasa `toast` a los turnos. El estado sale de `useCopyState`, el mismo que usa el
 *  Copiar de la URL del tunel. */
function CopyBtn({ text, title }: { text: string; title: string }) {
  const { state, copy } = useCopyState();
  return (
    <button type="button" className="copy" title={title} aria-label={title} onClick={() => copy(text)}>
      {copyLabel(state, "📋 copiar").toLowerCase()}
    </button>
  );
}

/** El `cd <ruta> &&` con el que arrancan casi todos los comandos: se repite en cada linea, mide
 *  mas que el comando en si y lo empuja fuera de la vista. Se saca solo de lo que se ve con la
 *  herramienta cerrada; abierta, y en el tooltip, el comando sigue entero. */
const dropCd = (t: string) => t.replace(/^cd\s+(?:"[^"]*"|'[^']*'|\S+)\s*&&\s*/, "");

/** La entrada de una herramienta en texto plano, un `clave: valor` por linea y los strings sin
 *  escapar. Con `JSON.stringify` un comando de varias lineas quedaba en una sola, con los saltos
 *  como `\n` y las comillas escapadas: ilegible justo en el dato que uno viene a buscar. */
const inputText = (inp: Record<string, unknown>) =>
  Object.entries(inp)
    .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join("\n");

function ToolBlock({ b }: { b: ToolB }) {
  const [open, setOpen] = useState(false);
  const err = b.result?.is_error;
  const raw = (detail(b.input) || "").split("\n")[0];
  const short = dropCd(raw);
  const line = short.length > LINE_MAX ? `${short.slice(0, LINE_MAX)}…` : short;
  const lines = b.result ? b.result.text.split("\n") : [];
  const cut = Math.max(0, lines.length - RESULT_LINES);
  return (
    <div className={`tool ${err ? "err" : ""} ${open ? "open" : ""}`} style={{ cursor: "auto" }}>
      {/* el toggle vive en el encabezado y no en todo el bloque: con el resultado abierto, un click
          para seleccionar texto lo cerraba y no se podia copiar nada de lo que la herramienta dijo.
          Una sola linea con puntos suspensivos: los comandos con rutas largas ocupaban tres */}
      <div
        onClick={() => setOpen(!open)}
        title={open ? "cerrar" : raw}
        style={{ cursor: "pointer", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}
      >
        <span style={{ fontSize: 8, marginRight: 4, display: "inline-block", transform: open ? "rotate(90deg)" : undefined }}>▸</span>
        <b>{b.name}</b>: {line}
      </div>
      {open && (
        <pre>
          {inputText(b.input)}
          {"\n\n--- resultado ---\n"}
          {b.result ? lines.slice(0, RESULT_LINES).join("\n") : "(sin resultado todavía)"}
          {cut > 0 ? `\n… y ${cut} líneas más (el resto no se trae)` : ""}
        </pre>
      )}
    </div>
  );
}

/** Una corrida de trabajo (herramientas y pensamiento, que vienen intercalados uno a uno) plegada
 *  en una linea que dice cuantas son y de que tipo. Sin esto la pestaña es una pared: medido en una
 *  sesion de cuatro turnos, 91 herramientas contra seis parrafos de texto, y lo que el agente dijo
 *  se pierde entre los comandos. El pensamiento va adentro del pliegue porque parte la corrida en
 *  pedazos de a uno; el resumen dice cuanto hay, para que se sepa donde buscarlo. */
function ToolRun({ run }: { run: Block[] }) {
  const tools = run.filter((b): b is ToolB => b.kind === "tool");
  const thinks = run.length - tools.length;
  const byName = new Map<string, number>();
  for (const t of tools) byName.set(t.name, (byName.get(t.name) ?? 0) + 1);
  const kinds = [...byName].map(([n, c]) => (c > 1 ? `${n} ×${c}` : n)).join(" · ");
  const failed = tools.filter((t) => t.result?.is_error).length;
  return (
    <details className="fold">
      <summary className="tool">
        <span>
          {tools.length} herramientas · {kinds}
          {thinks > 0 && ` · ${thinks} de pensamiento`}
          {failed > 0 && <span className="errtxt"> · {failed} con error</span>}
        </span>
      </summary>
      {run.map((b, k) => oneBlock(b, k))}
    </details>
  );
}

/** etiqueta al principio de un bloque que no es la respuesta, para que no se confunda con ella.
 *  Va adentro del bloque a proposito: `.think` esta oculto salvo que el toggle este prendido, y
 *  una etiqueta por fuera aparecia sola, sin nada que etiquetar. */
const tag = (t: string) => (
  <span style={{ fontStyle: "normal", fontSize: 10, textTransform: "uppercase", letterSpacing: ".5px", opacity: 0.8 }}>{t} · </span>
);

/** un bloque suelto: texto, pensamiento, algo que dijo el usuario en el medio, o un subagente */
function oneBlock(b: Block, key: number): ReactNode {
  switch (b.kind) {
    case "text":
      return <ReactMarkdown key={key}>{b.text}</ReactMarkdown>;
    case "thinking":
      return (
        <div key={key} className="think">
          {tag("pensamiento")}
          {b.text}
        </div>
      );
    case "user_text":
      return (
        <div key={key} className="ut">
          {tag("vos")}
          {b.text}
        </div>
      );
    case "subagent":
      return (
        <div key={key} className="sub">
          subagente · {b.n} líneas
        </div>
      );
    case "tool":
      return <ToolBlock key={b.id ?? key} b={b} />;
  }
}

/** es trabajo, no algo que el agente haya dicho: se puede plegar junto con lo que tenga al lado */
const isWork = (b: Block) => b.kind === "tool" || b.kind === "thinking";

/** Los bloques en orden, con las corridas de trabajo plegadas (ver `ToolRun`). Una corrida corta se
 *  deja como esta: plegar dos lineas no le gana a leerlas. */
function renderBlocks(bs: Block[]): ReactNode[] {
  const out: ReactNode[] = [];
  let i = 0;
  while (i < bs.length) {
    if (isWork(bs[i])) {
      let j = i;
      while (j < bs.length && isWork(bs[j])) j++;
      const run = bs.slice(i, j);
      if (run.filter((b) => b.kind === "tool").length >= RUN_FOLD) out.push(<ToolRun key={`run${i}`} run={run} />);
      else for (let k = 0; k < run.length; k++) out.push(oneBlock(run[k], i + k));
      i = j;
    } else {
      out.push(oneBlock(bs[i], i));
      i++;
    }
  }
  return out;
}

export function TurnView({ turn: t }: { turn: Turn }) {
  return (
    <div className="turn">
      <div className="ts">
        {/* venia cruda del server ("2026-09-07T01:15:58.621Z"): en UTC y con los milisegundos */}
        {t.ts_start ? whenLabel(t.ts_start, true) : "sin hora"}
        {t.error && <span className="errtxt"> · {t.error}</span>}
      </div>
      <div className="u">{t.prompt}</div>
      <div className="a md">{renderBlocks(t.blocks)}</div>
      {t.final && (
        <div className="frow">
          <CopyBtn text={t.final} title="copiar la respuesta de este turno" />
        </div>
      )}
    </div>
  );
}
