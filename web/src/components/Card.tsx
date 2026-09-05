import { ago, detail } from "../api";
import type { Pending, Rule, Session } from "../types";

function ruleLabel(r: Rule, sid: string, sessions: Record<string, Session>): string {
  // nombre corto de la otra sesion: el titulo si lo hay (dos sesiones del mismo repo se confunden)
  const other = (id: string | null) => {
    const o = id ? sessions[id] : undefined;
    if (!o) return "?";
    return o.title ? `${o.repo} · ${o.title.slice(0, 28)}` : `${o.repo} · ${o.session_id.slice(0, 8)}`;
  };
  if (r.kind === "at") {
    const t = r.at ? new Date(r.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false }) : "?";
    if (r.to === sid) return r.from && r.from !== sid ? `⏰ ${t} → "${r.text}" (desde ${other(r.from)})` : `⏰ ${t} → "${r.text}"`;
    return `⏰ ${t} → "${r.text}" a ${other(r.to)}`;
  }
  const count = r.repeat ? ` (${r.fired}/${r.max_fires})` : "";
  return r.from === sid ? `⏹ al terminar → ${other(r.to)}${count}` : `⏹ recibe de ${other(r.from)} al terminar${count}`;
}

interface Props {
  session: Session;
  pending?: Pending;
  rules?: Rule[];
  sessions?: Record<string, Session>;
  onDeleteRule?: (id: string) => void;
  selected: boolean;
  onSelect: () => void;
  onDecide: (requestId: string, decision: "allow" | "deny") => void;
  onDrop: () => void;
  onGrip?: (e: React.MouseEvent) => void;
  onPress?: (e: React.MouseEvent) => void;
}

export function Card({ session: s, pending: p, rules = [], sessions = {}, onDeleteRule, selected, onSelect, onDecide, onDrop, onGrip, onPress }: Props) {
  return (
    <div
      className={`card ${selected ? "sel" : ""}`}
      onClick={onSelect}
      data-sid={s.session_id}
      onMouseDown={(e) => {
        // arrastre desde cualquier parte de la tarjeta, salvo controles y el agarre (que ya arrastra)
        const t = e.target as HTMLElement;
        if (e.button !== 0 || t.closest("button, a, input, textarea, .x, .grip, code")) return;
        onPress?.(e);
      }}
    >
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
      {rules.map((r) => (
        <div key={r.id} className="rule" title={r.kind === "at" ? "programado" : "cuando termine el turno"}>
          <span>{ruleLabel(r, s.session_id, sessions)}</span>
          <span
            className="del"
            title="quitar"
            onClick={(e) => {
              e.stopPropagation();
              if (confirm("Quitar esta conexión?")) onDeleteRule?.(r.id);
            }}
          >
            ✕
          </span>
        </div>
      ))}

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
        {s.no_console && !s.orphan && <span className="warn" title="panel de Claude Code de VS Code o app de escritorio: se ve, no se le escribe">sin consola</span>}
        <span>{s.session_id.slice(0, 8)}</span>
      </div>
      {onGrip && s.alive && !s.orphan && !s.no_console && (
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
