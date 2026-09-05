import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { detail } from "../api";
import type { Block, Turn } from "../types";

function ToolBlock({ b }: { b: Extract<Block, { kind: "tool" }> }) {
  const [open, setOpen] = useState(false);
  const err = b.result?.is_error;
  const line = (detail(b.input) || "").split("\n")[0].slice(0, 160);
  return (
    <div className={`tool ${err ? "err" : ""} ${open ? "open" : ""}`} onClick={() => setOpen(!open)}>
      <b>{b.name}</b>: {line}
      {open && (
        <pre>
          {JSON.stringify(b.input, null, 1)}
          {"\n\n--- resultado ---\n"}
          {b.result ? b.result.text.split("\n").slice(0, 40).join("\n") : "(sin resultado todavía)"}
        </pre>
      )}
    </div>
  );
}

export function TurnView({ turn: t }: { turn: Turn }) {
  return (
    <div className="turn">
      <div className="ts">
        {t.ts_start}
        {t.error && <span className="errtxt"> · {t.error}</span>}
      </div>
      <div className="u">{t.prompt}</div>
      <div className="a md">
        {t.blocks.map((b, i) => {
          switch (b.kind) {
            case "text":
              return <ReactMarkdown key={i}>{b.text}</ReactMarkdown>;
            case "thinking":
              return <div key={i} className="think">{b.text}</div>;
            case "user_text":
              return <div key={i} className="ut">{b.text}</div>;
            case "subagent":
              return <div key={i} className="sub">subagente · {b.n} líneas</div>;
            case "tool":
              return <ToolBlock key={b.id ?? i} b={b} />;
          }
        })}
      </div>
    </div>
  );
}
