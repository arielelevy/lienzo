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
  const j = (await r.json().catch(() => ({}))) as Record<string, unknown>;
  if (!r.ok) throw new ApiError(typeof j.error === "string" ? j.error : String(r.status), r.status, j);
  return j as T;
}

export const api = {
  get: <T,>(path: string) => fetch(path).then((r) => parse<T>(r)),
  post: <T,>(path: string, body: unknown) =>
    fetch(path, { method: "POST", headers: HEADERS, body: JSON.stringify(body) }).then((r) => parse<T>(r)),
  put: <T,>(path: string, body: unknown) =>
    fetch(path, { method: "PUT", headers: HEADERS, body: JSON.stringify(body) }).then((r) => parse<T>(r)),
  del: <T,>(path: string) => fetch(path, { method: "DELETE", headers: { "X-Lienzo": "1" } }).then((r) => parse<T>(r)),
  upload: (sid: string, file: File) =>
    fetch(`/sessions/${sid}/attach`, {
      method: "POST",
      headers: { "X-Lienzo": "1", "X-Filename": encodeURIComponent(file.name) },
      body: file,
    }).then((r) => parse<{ path: string; bytes: number }>(r)),
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
