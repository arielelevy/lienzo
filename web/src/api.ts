import type { ConnectionsResponse, DigestResponse, Rule } from "./types";

const HEADERS ={ "X-Lienzo": "1", "Content-Type": "application/json" };

/** Error HTTP con el body JSON del server: un 409 de programadas trae rule_id, at, text y replace. */
export class ApiError extends Error {
  status: number;
  body: Record<string, unknown>;
  constructor(message: string, status: number, body: Record<string, unknown>) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function parse<T>(r: Response): Promise<T> {
  const j = (await r.json().catch(() => {
    if (r.ok) throw new Error("El servidor devolvió una respuesta que no es JSON");
    return {};
  })) as Record<string, unknown>;
  if (!r.ok) throw new ApiError(typeof j.error === "string" ? j.error : String(r.status), r.status, j);
  return j as T;
}

/** El server que corre es anterior a esa ruta: un 404 de la ruta, no de la tarjeta. Antes se
 *  comparaba el mensaje con "404" o "ruta desconocida" en cada componente, y el Panel solo miraba
 *  "404", asi que con un server que contesta JSON ({"error": "ruta desconocida"}) nunca lo detectaba.
 *  Un 404 de tarjeta desconocida trae `code: "unknown_session"` (server.py no_session; mirror.py
 *  depende de ese code) y no es "reiniciá el server": la tarjeta se fue, nada mas. */
export function isMissingRoute(e: unknown): boolean {
  if (!(e instanceof ApiError) || e.status !== 404 || e.body.code === "unknown_session") return false;
  return e.body.error === "ruta desconocida" || !e.body.error;
}

/** Texto del toast de error de una accion: "reiniciá el server" si falta la ruta, si no
 *  "No se pudo <verbo>: <motivo>". Sin verbo queda "No se pudo: <motivo>". */
export const failMsg = (verbo = "") => (e: unknown): string =>
  isMissingRoute(e) ? "El server que corre no tiene esta ruta todavía: reiniciá el server" : `No se pudo${verbo ? ` ${verbo}` : ""}: ${(e as Error).message}`;

const request = <T,>(path: string, options?: RequestInit): Promise<T> => fetch(path, options).then(parse<T>);
const jsonRequest = <T,>(method: string, path: string, body: unknown) =>
  request<T>(path, { method, headers: HEADERS, body: JSON.stringify(body) });

export const api = {
  get: request,
  post: <T,>(path: string, body: unknown) => jsonRequest<T>("POST", path, body),
  put: <T,>(path: string, body: unknown) => jsonRequest<T>("PUT", path, body),
  del: <T,>(path: string) => request<T>(path, { method: "DELETE", headers: { "X-Lienzo": "1" } }),
  upload: (sid: string, file: File) =>
    request<{ path: string; bytes: number }>(`/sessions/${sid}/attach`, {
      method: "POST",
      headers: { "X-Lienzo": "1", "X-Filename": encodeURIComponent(file.name) },
      body: file,
    }),
};

/* Rutas de una tarjeta y de las reglas, una funcion fina por ruta y con el cuerpo tipado: antes
 * cada componente armaba la URL y el cuerpo a mano, y un campo mal escrito (`stop_orgin`) llegaba
 * al server sin que nadie lo viera. Los errores siguen siendo los de `api` (ApiError, failMsg). */

/** Cuerpo de POST /sessions/<sid>/send. */
export interface SendBody {
  text: string;
  /** rutas que ya devolvio `api.upload` */
  attachments: string[];
  /** la sesion que manda: deja la flecha from -> sid (sin esto, lo mando el usuario) */
  from?: string;
  /** canal nativo (con `native: true`): la otra punta del canal que esta sesion va a abrir */
  link_to?: string;
  native?: boolean;
  /** pegar trabajo: la destino hereda el titulo de `from` con la marca copycat */
  copycat?: boolean;
  /** con copycat, `false` deja a `from` trabajando ("Duplicar"); si no, recibe un Esc y queda stopped */
  stop_origin?: boolean;
  /** «Autorizar y que reintente»: la PC dueña anota lo autorizado y deja de mostrar el aviso */
  autoriza_denegado?: boolean;
}

export interface SendResult {
  chars: number;
  estado?: "pendiente" | "encolado" | "entregado" | "sin_confirmacion" | "rechazado";
  motivo?: string | null;
  referencia?: string | null;
  envio_id?: string | null;
  transporte?: string | null;
  /** pegar trabajo: el origen estaba corriendo y recibio el Esc */
  interrupted?: boolean;
  handover_error?: string;
}

/** Aceptación del transporte no es entrega. Legacy conserva su texto sin inventar confirmación. */
export function sendNotice(r: SendResult, target = ""): { text: string; attention: boolean; confirmed: boolean } {
  const to = target ? ` a ${target}` : "";
  const confirmed = r.estado === "entregado" || r.estado === undefined;
  const text = r.estado === "entregado" ? `Entregado${to}`
    : r.estado === "encolado" ? `Encolado${to}; espera confirmación`
    : r.estado === "pendiente" ? `Envío pendiente${to}; no se reenvía`
    : r.estado === "sin_confirmacion" ? `Sin confirmación${to}: ${r.motivo || "resultado incierto; no se reintenta"}`
    : r.estado === "rechazado" ? `Rechazado${to}: ${r.motivo || "no se pudo enviar"}`
    : r.estado === undefined ? `Enviado${to} (${r.chars} caracteres)`
    : `Resultado sin confirmar${to}; no se reintenta`;
  return { text, attention: !confirmed || !!r.handover_error, confirmed };
}

export type Decision = "allow" | "deny";

/** Respuesta de PUT /sessions/<sid>/stopped */
export interface StoppedResult {
  interrupted?: boolean;
  /** las conectadas a las que se les aviso, ya en nombre */
  notified?: string[];
}

/** GET /sessions/<sid>/screen: el buffer de la consola */
export interface ScreenResponse {
  ok: boolean;
  lines?: string[];
  cols?: number;
  error?: string;
}

const ses = (sid: string, rest: string) => `/sessions/${sid}/${rest}`;

/** POST /restaurar: la relanza con el retomar de su agente, en la PC dueña (`pc`; sin ella, esta) */
export interface RestoreResult {
  restored: { session_id: string; agent: string; cwd: string }[];
  failed: { session_id: string; error: string }[];
  /** con limit_by_memory: las que no entraron en la memoria de esa PC */
  skipped?: string[];
}
export const restoreApi = {
  one: (sid: string, pc?: string | null) => api.post<RestoreResult>("/restaurar", pc ? { session_id: sid, pc } : { session_id: sid }),
  /** varias de una PC, de a una con pausa y mientras entren en su memoria (server.restore_local) */
  some: (sids: string[], pc?: string | null) =>
    api.post<RestoreResult>("/restaurar", { session_ids: sids, limit_by_memory: true, ...(pc ? { pc } : {}) }),
};

export const sessionsApi = {
  claudePipe: (sid: string, reconnect = false) => api.post<{ command: string; session_id: string; expires_at: number; connected: boolean }>(ses(sid, "claude-pipe"), { reconnect }),
  send: (sid: string, body: SendBody) => api.post<SendResult>(ses(sid, "send"), body),
  interrupt: (sid: string) => api.post(ses(sid, "interrupt"), {}),
  kill: (sid: string) => api.post(ses(sid, "kill"), { confirm: sid }),
  /** el permiso que CODA pide en su terminal; `expect` es el sha256 del comando que se juzgo */
  approve: (sid: string, decision: Decision, expect?: string) =>
    api.post(ses(sid, "approve"), expect === undefined ? { decision } : { decision, expect }),
  /** una opcion del dialogo de la TUI, por su numero */
  dialog: (sid: string, choice: number) => api.post(ses(sid, "dialog"), { choice }),
  title: (sid: string, title: string) => api.put(ses(sid, "title"), { title }),
  /** la deja en el canal nativo (ListAgents de esta PC y de las otras): /rename + /remote-control */
  native: (sid: string) => api.post<{ ok: boolean; native_name: string }>(ses(sid, "native"), {}),
  stopped: (sid: string, on: boolean) => api.put<StoppedResult>(ses(sid, "stopped"), { on }),
  coordinator: (sid: string, on: boolean) => api.put(ses(sid, "coordinator"), { on }),
  remove: (sid: string) => api.del(`/sessions/${sid}`),
  digest: (sid: string, n: number) => api.get<DigestResponse>(ses(sid, `digest?n=${n}`)),
  screen: (sid: string) => api.get<ScreenResponse>(ses(sid, "screen")),
  connections: (sid: string) => api.get<ConnectionsResponse>(ses(sid, "connections")),
};

/** Cuerpo de POST /rules: "al terminar" (on_stop) o programada (at). */
export type NewRule =
  | { kind: "on_stop"; from: string; to: string; text: string; repeat?: boolean; max_fires?: number; limit?: "rate" | "total" }
  | {
      kind: "at";
      /** quien la programo, para dibujar la flecha; null si es a la misma sesion */
      from: string | null;
      to: string;
      text: string;
      /** ISO */
      at: string;
      /** periodica: cada tantos segundos (>= 60) */
      every_s?: number;
      max_fires?: number;
      skip_busy?: boolean;
      /** con una programada a ±2 min hacia el mismo destino (409), reemplazarla */
      replace?: boolean;
    };

/** Cuerpo de PUT /rules/<id>: solo lo que cambia. `every_s: null` la vuelve de un disparo. */
export interface RuleEdit {
  enabled?: boolean;
  text?: string;
  at?: string;
  every_s?: number | null;
  max_fires?: number;
  skip_busy?: boolean;
  repeat?: boolean;
  /** on_stop: "rate" (sin tope total) o "total" (con max_fires) */
  limit?: "rate" | "total";
}

export const rulesApi = {
  list: () => api.get<Rule[]>("/rules"),
  create: (r: NewRule) => api.post("/rules", r),
  update: (id: string, r: RuleEdit) => api.put(`/rules/${id}`, r),
  remove: (id: string) => api.del(`/rules/${id}`),
  acknowledgeReport: (id: string, report: string, estado: "recibido" | "integrado") =>
    api.post(`/rules/${encodeURIComponent(id)}/informes/${encodeURIComponent(report)}/acuse`, { estado }),
};

/** Contestar un pendiente de hook: permiso, o pregunta con opciones (`answers`). */
export const pendingApi = {
  decide: (requestId: string, decision: Decision) => api.post(`/pending/${requestId}`, { decision }),
  answer: (requestId: string, answers: Record<string, string>) => api.post(`/pending/${requestId}`, { decision: "allow", answers }),
};

/** GET /cuotas (ronda 2026-10-17): lo mismo que `/usage` de Claude y `/status` de Codex. Una lectura
 *  fallida trae `ok: false`, `error` y las ventanas en null: nunca hay números inventados. */
export interface VentanaCuota {
  used_pct: number;
  /** ISO */
  resets_at: string | null;
}

export interface CuotaAgente {
  ok: boolean;
  plan: string | null;
  five_hour: VentanaCuota | null;
  weekly: VentanaCuota | null;
  /** ISO: cuándo se midió */
  read_at: string | null;
  error: string | null;
  credits?: RecursoMensual | null;
  messages?: RecursoMensual | null;
  resets_at?: string | null;
}

export interface RecursoMensual {
  used: number;
  limit: number | null;
  available: number | null;
}

export type AgenteCuota = "claude" | "codex";

export interface CuotasResponse {
  claude: CuotaAgente;
  codex: CuotaAgente;
  kiro?: CuotaAgente;
  /** el de menor uso semanal entre los que tienen lectura y 5 h < 90 %; null si ninguno */
  sugerido: AgenteCuota | null;
  motivo: string;
}

/** Lo leído vale 5 min: el indicador y el diálogo de lanzamiento comparten la lectura, así abrir
 *  «Lanzar CLI» no pide /cuotas otra vez. Sólo un click la fuerza. */
export const CUOTAS_VIGENCIA_MS = 5 * 60_000;
let cuotasCache: { t: number; data: CuotasResponse } | null = null;
let cuotasEnCurso: Promise<CuotasResponse> | null = null;

const esCuota = (c: unknown): c is CuotaAgente => !!c && typeof c === "object" && typeof (c as CuotaAgente).ok === "boolean";

/** La lectura vigente, o una nueva. `forzar` mide de nuevo (`?refrescar=1`) en vez de usar la caché
 *  del server. Pedidos simultáneos sin forzar comparten el mismo fetch. */
export function leerCuotas(forzar = false): Promise<CuotasResponse> {
  // vence 10 s antes: el tick de 5 min del indicador llega apenas antes de cumplirse los 5 min de la lectura
  // y, con el borde exacto, se salteaba un refresco
  if (!forzar && cuotasCache && Date.now() - cuotasCache.t < CUOTAS_VIGENCIA_MS - 10_000) return Promise.resolve(cuotasCache.data);
  if (!forzar && cuotasEnCurso) return cuotasEnCurso;
  const inicio = Date.now();
  const pedido = api.get<CuotasResponse>(forzar ? "/cuotas?refrescar=1" : "/cuotas").then(d => {
    if (!d || !esCuota(d.claude) || !esCuota(d.codex)) throw new Error("respuesta de /cuotas con otra forma");
    // una lectura pedida antes que la que ya está (un click mientras esta volvía) no la pisa
    if (cuotasCache && cuotasCache.t > inicio) return cuotasCache.data;
    cuotasCache = { t: inicio, data: d };
    return d;
  }).finally(() => { if (cuotasEnCurso === pedido) cuotasEnCurso = null; });
  cuotasEnCurso = pedido;
  return pedido;
}

export interface AuthInfo {
  configured: boolean;
  authenticated: boolean;
  local: boolean;
  remote_url: string | null;
  mode: "code" | "full";
}

export function ago(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = (Date.now() - new Date(iso).getTime()) / 1000;
  if (d < 60) return `${Math.round(d)} s`;
  if (d < 3600) return `${Math.round(d / 60)} min`;
  if (d < 86400) return `${Math.round(d / 360) / 10} h`;
  return `${Math.round(d / 86400)} d`;
}

export function detail(inp: unknown): string {
  if (!inp) return "";
  if (typeof inp === "string") return inp;
  const o = inp as Record<string, unknown>;
  for (const k of ["command", "cmd", "file_path", "notebook_path", "url", "pattern", "description"]) {
    if (o[k]) return String(o[k]);
  }
  return JSON.stringify(inp);
}
