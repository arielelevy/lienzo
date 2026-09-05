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
  started: string;
  last_event: string | null;
  alive: boolean;
  source: "hook" | "sweep";
  pending_id: string | null;
  orphan?: boolean;
  no_console?: boolean;
  in_vscode?: boolean;
  suggestion?: string | null;
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

export interface Link {
  id: string;
  from: string;
  to: string;
  ts: string;
  text: string;
  kind?: "send" | "native";
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
 *  `other` ya viene armado por el server ("repo · titulo") para no depender del tablero. */
export interface ConnectionLink extends Link {
  rule_id?: string;
  other: string;
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
  other: string;
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
