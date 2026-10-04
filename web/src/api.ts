const HEADERS = { "X-Lienzo": "1", "Content-Type": "application/json" };

/** Error HTTP con el body JSON del server: un 409 de programadas trae rule_id, at, text y replace. */
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public body: Record<string, unknown>,
  ) {
    super(message);
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
