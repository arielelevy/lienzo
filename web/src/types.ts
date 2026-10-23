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
  /** el proceso nació con `--chrome`: maneja el Chrome real por la extensión */
  chrome?: boolean;
  /** El estado operativo de una CLI sin lector de turnos no confirma actividad real. */
  state_source?: "unverified";
  /** Lectura parcial de pantalla; model_label es visible, no un ID canónico ni respuesta. */
  screen_observation?: {
    source: "screen";
    observed_at: string;
    available: boolean;
    model_label: string | null;
    activity: "unverified";
  } | null;
  cwd: string | null;
  repo: string;
  branch: string | null;
  title: string | null;
  transcript_path: string | null;
  state: State;
  state_since: string;
  needs: Needs | null;
  last_prompt: string;
  /** Hora del último pedido real; permite retirar avisos del turno anterior. */
  prompt_ts?: string | null;
  last_reply: string;
  last_error?: string | null;
  /** el ultimo permiso que una regla, una politica o un clasificador DENEGO (no el humano) */
  last_denied?: {
    tool: string;
    motivo?: string;
    detalle?: string;
    fuente?: string;
    visto?: string;
    /** borra o pisa algo (por el motivo del clasificador o por el comando) */
    grave?: boolean;
    /** cuantas se denegaron en el turno, y cuales (hasta 8): la principal es la grave, si hay */
    n?: number;
    todas?: { tool: string; motivo?: string; detalle?: string; grave?: boolean }[];
  } | null;
  /** aviso de limite de uso con hora de vuelta (ISO): la tarjeta ofrece programar "Continuar" */
  limit_until?: string | null;
  /** aviso de limite ya atendido por el server (regla automatica creada para ese limit_until) */
  continue_scheduled_for?: string | null;
  /** el turno murio con un error de API que se arregla reintentando (no es limite de uso) */
  retryable?: boolean;
  /** dialogo de opciones de la TUI leido de la pantalla ("Switch model?"): no dispara ningun hook,
   *  asi que sin el lienzo se queda esperando una tecla que nadie aprieta */
  dialog?: TuiDialog | null;
  /** con auto-aprobar prendido: por que vio este dialogo y NO lo contesto (no es un permiso) */
  auto_aprobar_omitido?: string | null;
  /** lo ultimo que el auto-aprobar contesto por esta sesion: que, cuando (ISO) y por donde */
  auto_aprobado?: { que: string; at: string; via: string } | null;
  started: string;
  last_event: string | null;
  alive: boolean;
  /** "desktop": hilo de la app de Codex, leido de su rollout (sin proceso) */
  source: "hook" | "sweep" | "desktop";
  /** La extension/hook ya publico la identidad exacta de esta sesion. */
  hooked?: boolean;
  pending_id: string | null;
  /** el nombre con que la ven ListAgents y SendMessage (lo pone el lienzo al lanzar o al renombrar) */
  native_name?: string | null;
  orphan?: boolean;
  no_console?: boolean;
  /** ejecucion externa (un orquestador, `claude -p`): solo lectura; null en una sesion personal */
  external?: ExternalRun | null;
  /** si se le puede escribir y por donde (puede_enviar del server); ausente en un server anterior */
  envio?: EnvioEstado | null;
  /** Resultado del último envío; la capacidad `envio` no confirma su entrega. */
  envio_codex?: {
    estado: "pendiente" | "encolado" | "entregado" | "sin_confirmacion" | "rechazado";
    motivo?: string | null;
    referencia?: string | null;
    envio_id?: string | null;
    transporte?: string | null;
    at?: number;
    confirmacion_final?: boolean;
  } | null;
  envio_claude?: Session["envio_codex"];
  /** que fuente maneja la tarjeta: "win32" (Windows) o "tmux" (Mac/Linux/WSL). Ausente = primario. */
  backend?: string;
  /** distro de WSL dueña del tmux de esta tarjeta (solo si corre en WSL). Ausente = no WSL. */
  distro?: string;
  in_vscode?: boolean;
  suggestion?: string | null;
  /** alguien esta escribiendo en esa terminal (lo detecta screen_loop): lo que se mande se mezcla */
  typing?: boolean;
  /** un envio del lienzo que el agente todavia no confirmo con su UserPromptSubmit (a los 25 s libre, «sin enviar») */
  envio_pendiente?: { at: number; sin_consumo?: boolean } | null;
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
  /** le pegaron el trabajo de esa sesion (Ctrl+V): heredo su titulo con la marca copycat */
  copycat_of?: string | null;
  /** la llave stopped: session_id de la copia que se llevo su trabajo, o "user" si la detuvieron desde
   *  el tablero. Prendida no recibe mensajes ni reglas; se apaga desde la etiqueta o con su proximo pedido */
  stopped_by?: string | null;
  /** un envío con sin_aviso: el próximo cierre de turno no le avisa a esa sesión (lienzo/rules.py) */
  sin_aviso?: { a: string; desde: number } | null;
  /** pc_id de la PC dueña de esta sesion (frente B, ronda multi-PC). Ausente: PC local de siempre,
   *  o un server que todavia no lo publica. */
  pc?: string | null;
  /** remote origin normalizado (identidad de repo entre PCs, frente A). Ausente: usar `repo`. */
  repo_key?: string | null;
}

/** `GET /recientes`: una carpeta donde el tablero vio una sesión viva estos días (recientes.py), con
 *  la PC dueña y la última vez. «Lanzar CLI» las lista grisadas debajo de las carpetas permitidas. */
export interface Reciente {
  cwd: string;
  repo: string;
  pc: string;
  last: string;
}

/** Salud de una PC, tal como la mide `lienzo/health.py` (memoria, CPU y temperatura de Windows). */
export interface PeerHealth {
  protocol_version?: number;
  capabilities?: string[];
  launch_roots?: string[];
  /** los proyectos que existen en disco dentro de launch_roots (protocol.carpetas_de_proyecto) */
  carpetas?: string[];
  mem_free_gb: number | null;
  mem_total_gb?: number | null;
  cpu_pct: number | null;
  temp_c: number | null;
  /** cuantos agentes mas entran sin bajar de la reserva de memoria (health.agentes_que_entran) */
  agentes_libres?: number | null;
  /** por url configurada en "git_check" (health.py prueba git ls-remote): ok, vencida (la credencial,
   *  401/403), no_verificable (no habia credencial que mandar sin abrir un login: no prueba que venza),
   *  sin_red (no llega al host), timeout (git no termino) o error (otra cosa) */
  git_auth?: Record<string, "ok" | "vencida" | "no_verificable" | "sin_red" | "timeout" | "error"> | null;
  /** distros de WSL instaladas en esa PC (solo Windows con WSL; vacía o ausente = ninguna) */
  distros_wsl?: string[];
  /** perfiles de Chrome de esa PC con la extensión Claude in Chrome instalada (chrome_claude.py) */
  chrome_claude?: { id: string; name: string; cuenta: string }[];
  /** las extensiones de Claude y Codex conectadas ahora en el Chrome de esa PC, una por agente y por
   *  donde se conecta, con sus hosts nativos vivos (chrome_claude.conexiones) */
  chrome_conexiones?: { agent: "claude" | "codex"; host: "desktop" | "code" | "codex"; pids: number[]; desde: string | null }[];
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
  /** por que no llega (sin ARP, puerto cerrado, otra red, Tailscale), solo si no esta viva */
  diagnostico?: string | null;
  /** el canal de emergencia que queda si no esta viva (emergencia.canal, decision 24): Tailscale o
   *  Tailchrome; `url` solo si la accion es en esta PC */
  emergencia?: { canal: "tailscale" | "tailchrome" | null; url: string | null; texto: string } | null;
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
  history_only?: boolean;
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
  kind?: "send" | "native" | "rule" | "user" | "consulta";
  /** id de la consulta entre investigadores, si la flecha es una de sus vueltas */
  consulta?: string;
}

/** Una consulta entre investigadores (lienzo/consulta.py), como la ve el tablero. */
export interface ConsultaResumen {
  id: string;
  pregunta: string;
  estado: "abierta" | "sintetizando" | "revisando" | "cerrada" | "cancelada";
  vuelta: number;
  vueltas: number;
  investigadores: string[];
  revisor: string;
  coordinador: string | null;
  nombres: Record<string, string>;
  esperando: string[];
  pendientes: string[];
  fuera: Record<string, string>;
  motivo: string | null;
  creada: string;
  cerrada: string | null;
}

/** La consulta entera (GET /consultas/<id>), con las respuestas por vuelta. */
export interface ConsultaEntera extends Omit<ConsultaResumen, "esperando" | "pendientes"> {
  pendientes: Record<string, { marca: string; enviado: string }>;
  respuestas: Record<string, Record<string, { texto: string; ts: string; agente?: string; modelo?: string }>>;
  /** las réplicas mandadas: a quién, de quién y de qué vuelta (consultas viejas de disco: puede no estar) */
  replicas?: { para: string; de: string; vuelta: number; ts: string }[];
  sintesis: string | null;
  objeciones: Record<string, string>;
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
  parked_since?: string;
  disabled_reason?: string;
  archived_at?: string;
  id: string;
  kind: "on_stop" | "at";
  from: string | null;
  to: string;
  text: string;
  at: string | null;
  repeat: boolean;
  /** tope total: en una "at", o en una on_stop con limit "total". En una on_stop por frecuencia, null */
  max_fires: number | null;
  /** on_stop repetida: "rate" (por defecto: sin tope total, a lo sumo rate_max cada rate_window_s;
   *  lo que excede se demora y se agrupa) o "total" (se apaga a los max_fires: solo si se pidio) */
  limit?: "rate" | "total";
  rate_max?: number | null;
  rate_window_s?: number | null;
  /** avisos de una on_stop limitada que esperan salir agrupados */
  deferred?: { since: string; count: number; until: string } | null;
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
  informes?: {
    id: string;
    respuesta: string;
    created: string;
    estado: "pendiente" | "entregado" | "recibido" | "integrado";
    entregado_at?: string;
    recibido_at?: string;
    integrado_at?: string;
    transporte?: { estado?: string; motivo?: string; envio_id?: string };
  }[];
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
  | { type: "transcript"; session_id: string; size: number }
  | { type: "consulta"; consulta: ConsultaResumen }
  | ({ type: "rondas" } & RondasEstado);

/** Aviso coordinado (lienzo/rondas.py): el mismo texto a varios frentes con su confirmación. */
export interface AvisoDestino {
  estado: "enviando" | "enviado" | "fallo" | "confirmado";
  ts: string;
  nota: string | null;
}
export interface Aviso {
  id: string;
  texto: string;
  de: string | null;
  creado: string;
  vence: string;
  cerrado?: string;
  estado: "abierto" | "completo" | "vencido";
  destinos: Record<string, AvisoDestino>;
}
/** Turno de un recurso pesado: un dueño con vencimiento y una cola. */
export interface Turno {
  dueno: { session_id: string; motivo: string | null; desde: string; vence: string } | null;
  cola: { session_id: string; ttl_min: number; motivo: string | null; pedido: string }[];
}
export interface RondasEstado {
  avisos: Aviso[];
  turnos: Record<string, Turno>;
  politicas: Record<string, { ttl_max_min: number; mem_min_gb: number }>;
}
/** GET /memoria: memoria libre de esta PC y qué sesión quieta conviene cerrar. */
export interface PresionMemoria {
  mem_free_gb: number | null;
  umbral_gb: number;
  bajo: boolean;
  cerrar: { session_id: string; title: string | null; repo: string | null; quieta_desde: string | null }[];
  max_sesiones_por_repo: number;
}

/** Ejecucion externa a la que pertenece una tarjeta de agente (un orquestador o `claude -p`): se ve
 *  y se lee, pero no se le escribe, ni se la mata, ni la mueven reglas. `kind` es "batch" (un
 *  `claude -p` suelto), el tipo de orquestador que registro un plugin local, o una app de escritorio
 *  ("claude-desktop" / "codex-desktop", con `desktop: true`). */
/** Resultado de puede_enviar para una tarjeta (contrato de D, 2026-10-17): `motivo` siempre que
 *  `puede` sea false. */
export interface EnvioEstado {
  puede: boolean;
  motivo: string | null;
  /** claude_pipe reservado: no habilita escritura sin adaptador vivo registrado. */
  transporte: "tecleo" | "codex_queue" | "canal_nativo" | "claude_pipe" | null;
}

export interface ExternalRun {
  kind: string;
  /** como se supo: el arbol de procesos, la linea de comando, un plugin por session_id; en las apps,
   *  el registro de Claude Code, la ruta del ejecutable o el rollout del hilo de Codex */
  via: "proceso" | "comando" | "session_id" | "registro" | "ruta" | "rollout";
  /** sesion de una app de escritorio */
  desktop?: boolean;
  /** Claude Desktop: el nombre con que figura en ListAgents (registro de Claude Code) */
  canal?: string | null;
  runner_pid?: number | null;
  run_key?: string;
  run_id?: string;
  capability?: string;
  session?: string;
  step?: string;
  instance?: string;
}
