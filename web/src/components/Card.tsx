import { ago, detail } from "../api";
import type { Pending, Session } from "../types";

interface Props {
  session: Session;
  pending?: Pending;
  selected: boolean;
  onSelect: () => void;
  onDecide: (requestId: string, decision: "allow" | "deny") => void;
  onDrop: () => void;
  onGrip?: (e: React.MouseEvent) => void;
}

export function Card({ session: s, pending: p, selected, onSelect, onDecide, onDrop, onGrip }: Props) {
  return (
    <div className={`card ${selected ? "sel" : ""}`} onClick={onSelect} data-sid={s.session_id}>
      <span
        className="x"
        title="quitar tarjeta"
        onClick={(e) => {
          e.stopPropagation();
          onDrop();
        }}
      >
        ✕
      </span>
      <div className="top">
        <span className={`badge ${s.agent}`}>{s.agent}</span>
        <span className="repo">{s.repo}</span>
        {s.branch && <span>⎇ {s.branch}</span>}
        <span className="right">{ago(s.state_since)}</span>
      </div>
      <div className="title">{s.title || s.last_prompt || "(sin título)"}</div>
      <div className="prompt">› {s.last_prompt}</div>
      {s.last_error ? <div className="error">⚠ {s.last_error}</div> : <div className="reply">{s.last_reply}</div>}
      {s.suggestion && <div className="sugg" title="leído de la caja de entrada de la terminal">💡 {s.suggestion}</div>}

      {p ? (
        <div className="needs" onClick={(e) => e.stopPropagation()}>
          <b>Pide permiso: {p.tool_name}</b>
          <code>{detail(p.tool_input)}</code>
          <div className="btns">
            <button className="allow" onClick={() => onDecide(p.request_id, "allow")}>Permitir</button>
            <button className="deny" onClick={() => onDecide(p.request_id, "deny")}>Denegar</button>
            <span className="dim small">vence {new Date(p.expires_at).toLocaleTimeString()}</span>
          </div>
        </div>
      ) : s.state === "te_necesita" && s.needs ? (
        <div className="needs terminal">
          <b>
            {s.needs.kind === "idle"
              ? "Espera tu input"
              : s.needs.kind === "permission"
                ? `Pide permiso: ${s.needs.tool ?? ""}`
                : s.needs.kind}
          </b>
          {s.needs.detail && <code>{s.needs.detail}</code>}
          <div className="dim small">
            {s.needs.kind === "idle" ? "podés escribirle desde acá" : s.needs.where === "terminal" ? "contestar en VS Code" : "esperando al lienzo"}
          </div>
        </div>
      ) : null}

      <div className="meta">
        <span>PID {s.pid ?? "?"}</span>
        <span>{s.source === "sweep" ? "barrido" : "hooks"}</span>
        {s.alive === false && <span>proceso muerto</span>}
        {s.orphan && <span className="warn" title="su terminal de VS Code se cerró; el proceso sigue pero no hay dónde escribirle">sin terminal</span>}
        <span>{s.session_id.slice(0, 8)}</span>
      </div>
      {onGrip && s.alive && !s.orphan && (
        <span
          className="grip"
          title="arrastrá hasta otra tarjeta para reenviarle la última respuesta"
          onMouseDown={(e) => {
            e.stopPropagation();
            e.preventDefault();
            onGrip(e);
          }}
        >
          ⇢
        </span>
      )}
    </div>
  );
}
