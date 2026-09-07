/** Tablero fijo para las pruebas de interfaz.
 *
 *  Las sesiones de verdad cambian todo el tiempo (nacen, mueren, cambian de estado): medir contra
 *  el tablero del momento da pruebas que pasan o fallan segun la hora. Aca se arma un tablero
 *  inventado y se interceptan las rutas que lo alimentan (`/sessions`, `/pending`, `/links`,
 *  `/rules`, mas `/auth`, `/config` y lo que pide el panel), asi la prueba mide siempre lo mismo.
 *
 *  El stream SSE no se puede servir con `route.fulfill` (fulfill cierra la respuesta y el
 *  EventSource se reconecta cada 3 s, con re-renders en el medio): se reemplaza `window.EventSource`
 *  por un doble que entrega el snapshot fijo una vez y se queda abierto.
 *
 *  Los tipos salen de `src/types.ts` a proposito: si el server cambia la forma de una sesion, esto
 *  deja de compilar en vez de mentir. */
import type { Page } from "@playwright/test";
import type { Link, Pending, Rule, Session } from "../src/types";

/** El server real corre en el 7321 y estas pruebas no lo levantan ni lo reinician. */
export const BASE = process.env.LIENZO_URL ?? "http://127.0.0.1:7321";

const iso = (minAgo: number) => new Date(Date.now() - minAgo * 60_000).toISOString();
const enMin = (min: number) => new Date(Date.now() + min * 60_000).toISOString();

type Semilla = Partial<Session> & Pick<Session, "session_id" | "repo" | "state">;

const S = (o: Semilla): Session => ({
  agent: "claude",
  pid: 1000,
  cwd: `D:\\Apps\\${o.repo}`,
  branch: "main",
  title: null,
  transcript_path: `C:\\t\\${o.session_id}.jsonl`,
  state_since: iso(3),
  needs: null,
  last_prompt: "",
  last_reply: "",
  last_error: null,
  limit_until: null,
  continue_scheduled_for: null,
  started: iso(90),
  last_event: "Stop",
  alive: true,
  source: "hook",
  pending_id: null,
  orphan: false,
  no_console: false,
  in_vscode: true,
  suggestion: null,
  typing: false,
  tool_count: 0,
  last_files: [],
  last_cmd: null,
  tool_errors: 0,
  title_source: "user",
  coordinator: false,
  ...o,
});

/** ids legibles: aparecen en los selectores de las pruebas (`.card[data-sid="t1"]`) */
export const SID = {
  coordinadora: "t1",
  flechas: "t2",
  mapas: "t3",
  capas: "t4",
  reglas: "t5",
  migracion: "t6",
  permiso: "n1",
  pregunta: "n2",
  muerta: "m1",
  huerfana: "m2",
} as const;

/** Seis en Trabajo, dos en Te necesita (una pidiendo permiso, que adelanta su columna en el DOM),
 *  dos en Muerta (una con el proceso muerto y una huerfana). Diez tarjetas es lo que tenia el
 *  tablero el dia que aparecieron los problemas que estas pruebas miden. */
export function sesiones(): Session[] {
  return [
    S({
      session_id: SID.coordinadora,
      repo: "lienzo",
      state: "corriendo",
      title: "Coordinadora del lienzo",
      coordinator: true,
      last_prompt: "repartí los encargos y traeme las mediciones de cada sesión",
      last_reply: "Ocho encargos repartidos. Falta la batería de pruebas de interfaz.",
      tool_count: 3,
      last_files: ["Board.tsx", "Card.tsx"],
      last_cmd: "npm run build",
      state_since: iso(2),
    }),
    S({
      session_id: SID.flechas,
      repo: "lienzo",
      agent: "codex",
      state: "corriendo",
      title: "Flechas y glifos",
      last_prompt: "que ninguna flecha cruce una tarjeta",
      last_reply: "Voy por el ruteo por carriles.",
      tool_count: 7,
      last_files: ["arrows-geometry.ts"],
      state_since: iso(1),
    }),
    S({
      session_id: SID.mapas,
      repo: "mapo",
      state: "termino",
      title: "Tablero de mapas",
      last_prompt: "armá la capa de calor",
      last_reply: "Listo: la capa de calor sale de la vista `gold.viajes` y se dibuja con 12 cortes.",
      state_since: iso(11),
    }),
    S({
      session_id: SID.capas,
      repo: "mapo",
      agent: "codex",
      state: "termino",
      title: "Importador de capas",
      last_prompt: "importá los shapefiles de la provincia",
      last_reply: "23 capas importadas, 2 con geometrías inválidas que dejé anotadas.",
      state_since: iso(24),
    }),
    S({
      session_id: SID.reglas,
      repo: "teorema",
      state: "corriendo",
      title: "Motor de reglas",
      last_prompt: "las reglas periódicas tienen que saltear el disparo si el destino está corriendo",
      last_reply: "Agregué skip_busy y su prueba.",
      tool_count: 2,
      state_since: iso(4),
    }),
    S({
      session_id: SID.migracion,
      repo: "teorema",
      agent: "codex",
      state: "termino",
      title: "Migración de datos",
      last_prompt: "pasá las tablas viejas al esquema nuevo",
      last_reply: "Migradas 14 tablas. La de auditoría quedó afuera: no tiene clave.",
      state_since: iso(38),
    }),
    S({
      session_id: SID.permiso,
      repo: "lienzo",
      state: "te_necesita",
      title: "Pruebas de interfaz",
      pending_id: "p1",
      needs: { kind: "permission", tool: "Bash", detail: "npm run test:ui", where: "lienzo" },
      last_prompt: "corré la batería",
      last_reply: "Necesito permiso para correr npm.",
      state_since: iso(1),
    }),
    S({
      session_id: SID.pregunta,
      repo: "mapo",
      agent: "codex",
      state: "te_necesita",
      title: "Estilos del mapa",
      needs: { kind: "question", detail: "¿la leyenda va arriba o abajo?", where: "terminal" },
      last_prompt: "elegí la paleta",
      last_reply: "¿La leyenda va arriba o abajo?",
      state_since: iso(6),
    }),
    S({
      session_id: SID.muerta,
      repo: "viejo",
      state: "muerta",
      title: "Limpieza del repo viejo",
      alive: false,
      pid: null,
      last_prompt: "borrá los temporales",
      last_reply: "Borrados 340 archivos.",
      state_since: iso(200),
    }),
    S({
      session_id: SID.huerfana,
      repo: "viejo",
      agent: "codex",
      state: "corriendo",
      title: "Sin terminal",
      orphan: true,
      last_prompt: "seguí con el informe",
      last_reply: "",
      state_since: iso(150),
    }),
  ];
}

export function pendientes(): Pending[] {
  return [
    {
      request_id: "p1",
      session_id: SID.permiso,
      agent: "claude",
      tool_name: "Bash",
      tool_input: { command: "npm run test:ui" },
      expires_at: enMin(1),
    },
  ];
}

/** Envios ya hechos: los dibuja el tablero como flechas. `from` siempre presente (los que manda el
 *  usuario desde el lienzo llegan con from null y App los filtra antes del tablero). */
export function vinculos(): Link[] {
  return [
    { id: "l1", from: SID.coordinadora, to: SID.mapas, ts: iso(20), text: "seguí con la capa de calor", kind: "send" },
    { id: "l2", from: SID.flechas, to: SID.permiso, ts: iso(9), text: "pasame la medición del glifo", kind: "send" },
    { id: "l3", from: SID.coordinadora, to: SID.reglas, ts: iso(35), text: "Continuar", kind: "rule", rule_id: "r2" } as Link,
    { id: "l4", from: SID.mapas, to: SID.coordinadora, ts: iso(15), text: "capa lista", kind: "native" },
  ];
}

export function reglas(): Rule[] {
  return [
    {
      id: "r1",
      kind: "at",
      from: SID.coordinadora,
      to: SID.capas,
      text: "Continuar",
      at: enMin(30),
      repeat: false,
      max_fires: 1,
      fired: 0,
      enabled: true,
    },
    {
      id: "r2",
      kind: "on_stop",
      from: SID.reglas,
      to: SID.coordinadora,
      text: "avisame cuando termines",
      at: null,
      repeat: true,
      max_fires: 20,
      fired: 2,
      enabled: true,
      last_fired: iso(35),
      last_result: "ok",
    },
    {
      id: "r3",
      kind: "at",
      from: SID.flechas,
      to: SID.migracion,
      text: "Continuar",
      at: enMin(45),
      repeat: true,
      every_s: 1800,
      max_fires: 5,
      skip_busy: true,
      fired: 1,
      enabled: true,
      last_fired: iso(15),
      last_result: "ok",
    },
  ];
}

const AUTH = { configured: true, authenticated: true, local: true, remote_url: null, mode: "code" };

/** Respuestas del panel: sin esto la pestaña Destacados pide la transcripción real de una sesión
 *  que no existe y muestra un error (que ademas ensucia la prueba de consola limpia). */
function respuestaDePanel(pathname: string): unknown | null {
  if (/^\/sessions\/[^/]+\/digest$/.test(pathname)) {
    return {
      turns: [
        {
          id: "d1",
          ts_start: iso(12),
          ended: true,
          prompt: "armá la capa de calor",
          final: "Listo: la capa de calor sale de la vista gold.viajes.",
          files: ["capa.py"],
          commands: ["python capa.py"],
          errors: [],
          questions: [],
          peers: [],
          reads: 4,
          subagents: 0,
          tools: 6,
        },
      ],
      has_more: false,
    };
  }
  if (/^\/sessions\/[^/]+\/turns$/.test(pathname)) {
    return {
      turns: [
        {
          id: "u1",
          agent: "claude",
          ts_start: iso(12),
          ts_end: iso(11),
          prompt: "armá la capa de calor",
          blocks: [{ kind: "text", text: "Leí la vista y armé los cortes." }],
          final: "Listo: la capa de calor sale de la vista gold.viajes.",
          ended: true,
          error: null,
        },
      ],
      has_more: false,
    };
  }
  if (/^\/sessions\/[^/]+\/connections$/.test(pathname)) return { links: [], rules: [] };
  if (/^\/sessions\/[^/]+\/screen$/.test(pathname)) {
    return { ok: true, cols: 120, lines: ["> npm run build", "vite v6.0.5 building for production...", "✓ built in 1.20s"] };
  }
  return null;
}

const json = (body: unknown) => ({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

/** Ninguna prueba escribe. El server del 7321 es el de verdad, con sesiones de verdad detrás: un
 *  POST perdido le escribe en la terminal a alguien. Todo lo que no sea GET se corta acá. */
export async function bloquearEscrituras(page: Page) {
  await page.route("**/*", async (route) => {
    if (route.request().method() === "GET") return route.fallback();
    return route.fulfill({ status: 403, contentType: "application/json", body: JSON.stringify({ error: "las pruebas de interfaz no escriben" }) });
  });
}

/** Interceptar las rutas de datos y sembrar el SSE. Devuelve el tablero servido, por si la prueba
 *  necesita contar contra el (cuántas tarjetas van en cada columna, por ejemplo). */
export async function instalarTablero(page: Page) {
  const board = { sessions: sesiones(), pending: pendientes(), links: vinculos(), rules: reglas() };
  const snapshot = { type: "snapshot", sessions: board.sessions, pending: board.pending, links: board.links, rules: board.rules };

  // el EventSource del navegador, reemplazado por un doble que entrega el snapshot y se queda
  // abierto: `route.fulfill` cierra la respuesta y la reconexion cada 3 s vuelve a renderizar todo
  await page.addInitScript((snap) => {
    class SseFalso extends EventTarget {
      readyState = 1;
      onopen: ((e: Event) => void) | null = null;
      onmessage: ((e: MessageEvent) => void) | null = null;
      onerror: ((e: Event) => void) | null = null;
      constructor(public url: string) {
        super();
        setTimeout(() => {
          this.onopen?.(new Event("open"));
          this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(snap) }));
        }, 0);
      }
      close() {
        this.readyState = 2;
      }
    }
    (window as unknown as { EventSource: unknown }).EventSource = SseFalso;
  }, snapshot);

  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    const p = url.pathname;
    if (p === "/auth") return route.fulfill(json(AUTH));
    if (p === "/config") return route.fulfill(json({ auto_continue: false }));
    if (p === "/sessions") return route.fulfill(json(board.sessions));
    if (p === "/pending") return route.fulfill(json(board.pending));
    if (p === "/links") return route.fulfill(json(board.links));
    if (p === "/rules") return route.fulfill(json(board.rules));
    if (p === "/events") return route.fulfill({ status: 200, contentType: "text/event-stream", body: `retry: 86400000\n\ndata: ${JSON.stringify(snapshot)}\n\n` });
    const panel = respuestaDePanel(p);
    if (panel) return route.fulfill(json(panel));
    return route.fallback();
  });
  return board;
}

/** Abre el tablero fijo y espera a que las diez tarjetas estén pintadas. */
export async function abrirTablero(page: Page) {
  await bloquearEscrituras(page);
  const board = await instalarTablero(page);
  await page.goto(BASE);
  await page.waitForSelector(".card", { state: "visible" });
  // el reparto en subcolumnas y las flechas se calculan despues del primer layout
  await page.waitForFunction(() => document.querySelectorAll(".board .col").length === 3);
  await esperarQuietud(page);
  return board;
}

/** Dos pasadas seguidas sin que se mueva ninguna tarjeta ni ninguna flecha: las flechas se dibujan
 *  en un efecto posterior al render (y se recalculan cuando el tablero cambia de ancho), así que
 *  medir antes de que se asienten da posiciones de mentira. */
export async function esperarQuietud(page: Page) {
  await page.waitForFunction(
    () => {
      const clave = () => [
        ...[...document.querySelectorAll<HTMLElement>(".card")].map((c) => { const r = c.getBoundingClientRect(); return `${Math.round(r.x)},${Math.round(r.y)},${Math.round(r.width)},${Math.round(r.height)}`; }),
        ...[...document.querySelectorAll<SVGPathElement>("svg.arrows path.line")].map((p) => p.getAttribute("d") ?? ""),
        ...[...document.querySelectorAll<SVGCircleElement>("svg.arrows circle.dot")].map((c) => `${c.getAttribute("cx")},${c.getAttribute("cy")}`),
      ].join("|");
      const w = window as unknown as { __quieto?: string };
      const k = clave();
      const igual = w.__quieto === k;
      w.__quieto = k;
      return igual;
    },
    undefined,
    { polling: 120, timeout: 5000 },
  );
  await page.evaluate(() => delete (window as unknown as { __quieto?: string }).__quieto);
}
