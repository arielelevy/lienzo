import type { Agent } from "./agents";

export type State = "corriendo" | "te_necesita" | "termino" | "muerta";

export interface Needs {
  kind: string;
  tool?: string | null;
  detail?: string;
  tool_use_id?: string | null;
  /** "enviado": la respuesta a un permiso de CODA ya se tecleo en su terminal */
  where?: "lienzo" | "terminal" | "enviado";
  /** hora del aviso (ISO): el server mide contra esto si la transcripcion siguio despues */
  since?: string;
  /** permiso de CODA leido de su log: la hora de esa linea, que lo identifica */
  coda_at?: string;
}

export interface Session {
  session_id: string;
  agent: Agent;
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
  /** el ultimo permiso que una regla, una politica o un clasificador DENEGO (no el humano) */
  last_denied?: { tool: string; motivo?: string; detalle?: string; fuente?: string; visto?: string } | null;
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
  /** La extension/hook ya publico la identidad exacta de esta sesion. */
  hooked?: boolean;
  pending_id: string | null;
  orphan?: boolean;
  no_console?: boolean;
  /** que fuente maneja la tarjeta: "win32" (Windows) o "tmux" (Mac/Linux/WSL). Ausente = primario. */
  backend?: string;
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
  /** "pc": esta coordinadora vale solo para esta PC (menu ⋯ → "Coordinadora solo de esta PC", plan
   *  §3.6) y no apaga ni la reemplaza la coordinadora federada de otra PC. null/ausente: federada. */
  coordinator_scope?: "pc" | null;
  /** le pegaron el trabajo de esa sesion (Ctrl+V): heredo su titulo con la marca copycat */
  copycat_of?: string | null;
  /** la llave stopped: session_id de la copia que se llevo su trabajo, o "user" si la detuvieron desde
   *  el tablero. Prendida no recibe mensajes ni reglas; se apaga desde la etiqueta o con su proximo pedido */
  stopped_by?: string | null;
  /** pc_id de la PC dueña de esta sesion (frente B, ronda multi-PC). Ausente: PC local de siempre,
   *  o un server que todavia no lo publica. */
  pc?: string | null;
  /** remote origin normalizado (identidad de repo entre PCs, frente A). Ausente: usar `repo`. */
  repo_key?: string | null;
}

/** Salud de una PC, tal como la mide `lienzo/health.py` (memoria, CPU y temperatura de Windows). */
export interface PeerHealth {
  mem_free_gb: number | null;
  mem_total_gb?: number | null;
  cpu_pct: number | null;
  temp_c: number | null;
  /** cuantos agentes mas entran sin bajar de la reserva de memoria (health.agentes_que_entran) */
  agentes_libres?: number | null;
  /** por url configurada en "git_check" (health.py prueba git ls-remote): ok, vencida (la credencial,
   *  401/403), sin_red (no llega al host), timeout (git no termino) o error (otra cosa) */
  git_auth?: Record<string, "ok" | "vencida" | "sin_red" | "timeout" | "error"> | null;
  /** cuota por agente en esa PC: "ok", "agotada", "agotada hasta HH:MM" o "desconocida" */
  cuotas?: Record<string, string> | null;
}

/** `GET /peers` (ronda 2): una fila por PC de la federacion, la propia incluida (`local: true`).
 *  Sin peers emparejados la ruta no existe (404) o devuelve un array de un solo elemento: en los
 *  dos casos la tira de PCs no aparece. */
/** `GET /peers/lan`: una PC de la LAN con el lienzo corriendo, todavia sin emparejar (anuncio sin
 *  firma del beacon). Solo para mostrarla y precargar la IP al emparejar. */
export interface LanPc {
  pc_id: string;
  name: string;
  ip: string;
  port: number;
  last_seen: string;
}

export interface Peer {
  pc_id: string;
  name: string;
  color: string;
  alive: boolean;
  last_seen: string;
  local: boolean;
  health: PeerHealth | null;
  /** mediana de los ultimos reenvios a esa PC, en ms (solo las otras PCs) */
  latencia_ms?: number | null;
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
  /** PELIGROSO: aprobar solo, sin mirar, todo permiso que pida cualquier agente de cualquier PC */
  auto_aprobar?: boolean;
}

/** Respuesta de PUT /config. Con auto_aprobar el server lo reenvia a cada PC emparejada y dice
 *  como le fue a cada una: "ok" o el error. Un server anterior no manda `peers`. */
export interface ConfigPut extends Config {
  peers?: Record<string, string>;
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
