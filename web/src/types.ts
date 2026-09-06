export type State = "corriendo" | "te_necesita" | "termino" | "muerta";

export interface Needs {
  kind: string;
  tool?: string | null;
  detail?: string;
  tool_use_id?: string | null;
  where?: "lienzo" | "terminal";
}

export interface Session {
  session_id: string;
  agent: "claude" | "codex";
  pid: number | null;
  cwd: string | null;
  repo: string;
  branch: string | null;
  title: string | null;
  transcript_path: string | null;
  state: State;
  state_since: string;
  needs: Needs | null;
  last_prompt: string;
  last_reply: string;
  last_error?: string | null;
  /** aviso de limite de uso con hora de vuelta (ISO): la tarjeta ofrece programar "Continuar" */
  limit_until?: string | null;
  /** aviso de limite ya atendido por el server (regla automatica creada para ese limit_until) */
  continue_scheduled_for?: string | null;
  started: string;
  last_event: string | null;
  alive: boolean;
  source: "hook" | "sweep";
  pending_id: string | null;
  orphan?: boolean;
  no_console?: boolean;
  in_vscode?: boolean;
  suggestion?: string | null;
  /** alguien esta escribiendo en esa terminal (lo detecta screen_loop): lo que se mande se mezcla */
  typing?: boolean;
}

export interface Pending {
  request_id: string;
  session_id: string;
  agent: string;
  tool_name: string;
  tool_input: unknown;
  expires_at: string;
}

export interface ToolResult {
  text: string;
  is_error: boolean;
}

export type Block =
  | { kind: "text"; text: string; phase?: string }
  | { kind: "thinking"; text: string }
  | { kind: "user_text"; text: string }
  | { kind: "subagent"; n: number }
  | { kind: "tool"; id: string; name: string; input: Record<string, unknown>; result: ToolResult | null };

export interface Turn {
  id: string;
  agent: string;
  ts_start: string | null;
  ts_end: string | null;
  prompt: string;
  blocks: Block[];
  final: string;
  ended: boolean;
  error: string | null;
}

export interface DigestTurn {
  id: string;
  ts_start: string | null;
  ended: boolean;
  prompt: string;
  final: string;
  files: string[];
  commands: string[];
  errors: string[];
  questions: string[];
  peers?: string[];
  reads: number;
  subagents: number;
  tools: number;
}

export interface TurnsResponse {
  turns: Turn[];
  has_more: boolean;
  note?: string;
}

export interface DigestResponse {
  turns: DigestTurn[];
  has_more: boolean;
  note?: string;
}

/** Envio hecho entre dos sesiones (flecha del tablero). Los que el usuario manda desde el
 *  SendBox llegan del server con from null y kind "user": App los filtra antes de dar el
 *  tablero, y se ven solo en la pestana Conexiones (ConnectionLink). */
export interface Link {
  id: string;
  from: string;
  to: string;
  ts: string;
  text: string;
  kind?: "send" | "native" | "rule" | "user";
}

/** ~/.lienzo/config.json, la parte que la UI puede leer y escribir (GET/PUT /config). */
export interface Config {
  /** ante un aviso de limite de uso con hora, programar "Continuar" solo */
  auto_continue: boolean;
}

export interface Rule {
  id: string;
  kind: "on_stop" | "at";
  from: string | null;
  to: string;
  text: string;
  at: string | null;
  repeat: boolean;
  max_fires: number;
  fired: number;
  enabled: boolean;
  last_fired?: string;
  last_result?: string;
}

/** GET /sessions/<sid>/connections: lo que esa sesion mando/recibio y las reglas que la tocan.
 *  `other` ya viene armado por el server para no depender del tablero: hoy como objeto
 *  {session_id, name: "repo · titulo"}; un server anterior lo mandaba como string. */
export type OtherSession = string | { session_id: string | null; name: string };

export interface ConnectionLink extends Omit<Link, "from"> {
  /** null en lo que mando el usuario desde el lienzo (kind "user") */
  from: string | null;
  rule_id?: string;
  other: OtherSession;
}

export interface ConnectionRule {
  id: string;
  kind: "on_stop" | "at";
  from: string | null;
  to: string;
  text: string;
  at: string | null;
  enabled: boolean;
  fired: number;
  max_fires: number;
  last_fired?: string | null;
  other: OtherSession;
}

export interface ConnectionsResponse {
  links: ConnectionLink[];
  rules: ConnectionRule[];
}

export type ServerEvent =
  | { type: "snapshot"; sessions: Session[]; pending: Pending[]; links?: Link[]; rules?: Rule[] }
  | { type: "links"; links: Link[] }
  | { type: "rules"; rules: Rule[] }
  | { type: "session"; session: Session }
  | { type: "removed"; session_id: string }
  | { type: "pending"; pending: Pending[] }
  | { type: "transcript"; session_id: string; size: number };
