export type State = "corriendo" | "te_necesita" | "termino" | "muerta";

export interface Needs {
  kind: string;
  tool?: string | null;
  detail?: string;
  tool_use_id?: string | null;
  where?: "lienzo" | "terminal";
  /** hora del aviso (ISO): el server mide contra esto si la transcripcion siguio despues */
  since?: string;
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
  /** el turno murio con un error de API que se arregla reintentando (no es limite de uso) */
  retryable?: boolean;
  /** dialogo de opciones de la TUI leido de la pantalla ("Switch model?"): no dispara ningun hook,
   *  asi que sin el lienzo se queda esperando una tecla que nadie aprieta */
  dialog?: TuiDialog | null;
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
  /** herramientas usadas en el turno que corre (o en el ultimo): lo que pasa adentro */
  tool_count?: number;
  /** ultimos archivos que toco en ese turno, del mas nuevo al mas viejo, solo el nombre */
  last_files?: string[];
  /** ultimo comando que corrio en ese turno, recortado */
  last_cmd?: string | null;
  /** herramientas del turno que volvieron con error */
  tool_errors?: number;
  /** de donde salio el titulo automatico: "transcript" (ai-title), "prompt" (primera linea del pedido
   *  o encabezado del adjunto) o "user" (renombrado a mano, no se recalcula) */
  title_source?: "transcript" | "prompt" | "user" | null;
  /** coordinadora del repo (estrella en la tarjeta): recibe los avisos "cuando termine" y "avisame". A lo sumo una por repo */
  coordinator?: boolean;
}

export interface Pending {
  request_id: string;
  session_id: string;
  agent: string;
  tool_name: string;
  tool_input: unknown;
  expires_at: string;
}

/** Una opción de una pregunta con opciones (AskUserQuestion), tal como la escribió el agente. */
export interface AskOption {
  label: string;
  description?: string;
}

/** Pregunta con opciones. Llega adentro del `tool_input` de un pendiente de AskUserQuestion, que
 *  no es un permiso: se contesta eligiendo, no permitiendo (ver Ask.tsx). */
export interface AskQuestion {
  question: string;
  header?: string;
  multiSelect?: boolean;
  options?: AskOption[];
}

export interface DigestTurn {
  id: string;
  ts_start: string | null;
  ended: boolean;
  prompt: string;
  /** lo que el agente dijo antes del `final`, en orden y entero: nada se recorta, el panel scrollea */
  says?: string[];
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

/** Dialogo de opciones numeradas de la TUI de Claude, leido del buffer de la consola. */
export interface TuiDialog {
  question: string;
  detail?: string;
  options: { n: number; text: string }[];
  /** la opcion que tiene el cursor: la que se elige con Enter en la terminal */
  selected: number;
}

/** ~/.lienzo/config.json, la parte que la UI puede leer y escribir (GET/PUT /config). */
export interface Config {
  /** ante un aviso de limite de uso con hora, programar "Continuar" solo */
  auto_continue: boolean;
  /** turno muerto por un error de API ("stopped arriving"): reintentar solo, una vez por error */
  auto_retry: boolean;
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
  /** regla "at" periodica: se repite cada tantos segundos (>= 60) hasta max_fires; null o ausente = una vez */
  every_s?: number | null;
  /** periodica: si el destino esta corriendo, saltear ese disparo sin contarlo (por defecto true) */
  skip_busy?: boolean;
  /** la creo el server por un limite de uso con hora (auto_continue), no el usuario */
  auto?: boolean;
  fired: number;
  enabled: boolean;
  last_fired?: string;
  last_result?: string;
}

/** GET /sessions/<sid>/connections: lo que esa sesion mando/recibio y las reglas que la tocan.
 *  `other` ya viene armado por el server para no depender del tablero: {session_id, name: "repo · titulo"}. */
export interface OtherSession {
  session_id: string | null;
  name: string;
}

export interface ConnectionLink extends Omit<Link, "from"> {
  /** null en lo que mando el usuario desde el lienzo (kind "user") */
  from: string | null;
  rule_id?: string;
  other: OtherSession;
}

/** Una regla como la devuelve `GET /sessions/<sid>/connections`: la misma que `Rule`, con la otra
 *  punta ya resuelta a nombre por el server. `last_fired` puede venir en null ahi. */
export interface ConnectionRule extends Omit<Rule, "last_fired"> {
  last_fired?: string | null;
  other: OtherSession;
}

export interface ConnectionsResponse {
  links: ConnectionLink[];
  rules: ConnectionRule[];
}

export type ServerEvent =
  | { type: "snapshot"; sessions: Session[]; pending: Pending[]; links?: Link[]; rules?: Rule[]; build?: string }
  /** latido cada 15 s; `build` es el sello del bundle servido (ver `build_id` en server.py) */
  | { type: "ping"; build?: string }
  | { type: "links"; links: Link[] }
  | { type: "rules"; rules: Rule[] }
  | { type: "session"; session: Session }
  | { type: "removed"; session_id: string }
  | { type: "pending"; pending: Pending[] }
  | { type: "transcript"; session_id: string; size: number };
