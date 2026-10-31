import { expect, test } from "@playwright/test";
import { BASE, aislarCapturas, bloquearEscrituras, esperarQuietud, instalarTablero, sesiones, SID } from "./tablero-fijo";
import type { Link, Peer, Rule, Session } from "../src/types";

/** Las capturas del README (docs/img), sacadas del tablero fijo con datos inventados: nada de las
 *  sesiones reales de quien las corre. No es una prueba: solo corre con CAPTURAS=1.
 *
 *    cd web; npm run build; $env:CAPTURAS=1; npx playwright test --config tests-ui/playwright.config.ts capturas
 */
test.skip(!process.env.CAPTURAS, "solo con CAPTURAS=1: regenera las imagenes del README");
test.use({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, serviceWorkers: "block" });

const DESTINO = "../docs/img";
const ESCRITORIO = "pc-ofi";
const NOTEBOOK = "pc-note";

const ahora = () => new Date().toISOString();

const PEERS: Peer[] = [
  {
    pc_id: ESCRITORIO,
    name: "escritorio",
    color: "#5b9cff",
    alive: true,
    last_seen: ahora(),
    local: true,
    health: { mem_free_gb: 6.2, mem_total_gb: 16, cpu_pct: 18, temp_c: 54, agentes_libres: 6, git_auth: { "https://git.ejemplo.com/curso.git": "ok" } },
  },
  {
    pc_id: NOTEBOOK,
    name: "notebook",
    color: "#82c91e",
    alive: true,
    last_seen: ahora(),
    local: false,
    latencia_ms: 86,
    health: { mem_free_gb: 2.1, mem_total_gb: 16, cpu_pct: 41, temp_c: 71, agentes_libres: 0, git_auth: { "https://git.ejemplo.com/curso.git": "vencida" } },
  },
];

/** El tablero fijo con lo que hoy muestra lienzo: dos PCs, una coda, una Pi y un permiso denegado. */
function tableroDeHoy(): Session[] {
  return sesiones().map((s, i) => {
    const pc = i % 2 === 0 ? ESCRITORIO : NOTEBOOK;
    if (s.session_id === SID.migracion)
      return {
        ...s,
        pc,
        agent: "coda",
        last_denied: { tool: "bash", detalle: "git push --force origin main", motivo: "comando que pide confirmación", fuente: "coda" },
      };
    if (s.session_id === SID.capas) return { ...s, pc, agent: "pi" };
    return { ...s, pc };
  });
}

const haceMin = (m: number) => new Date(Date.now() - m * 60_000).toISOString();

/** Más movimiento que el tablero fijo: la coordinadora reparte (dos envíos cruzan a la notebook) y
 *  le vuelven informes y avisos «cuando termine». */
const EXTRA: { links: Link[]; rules: Rule[] } = {
  links: [
    { id: "x1", from: SID.coordinadora, to: SID.flechas, ts: haceMin(2), text: "medí que ninguna flecha cruce una tarjeta", kind: "send" },
    { id: "x2", from: SID.coordinadora, to: SID.migracion, ts: haceMin(4), text: "pasá las tablas viejas al esquema nuevo", kind: "send" },
    { id: "x3", from: SID.mapas, to: SID.coordinadora, ts: haceMin(1), text: "capa lista", kind: "send" },
    { id: "x4", from: SID.capas, to: SID.mapas, ts: haceMin(3), text: "te dejo las 23 capas", kind: "send" },
  ] as Link[],
  rules: [
    { id: "x5", kind: "on_stop", from: SID.migracion, to: SID.coordinadora, text: "avisame cuando termines", at: null, repeat: true, max_fires: 20, fired: 0, enabled: true },
    { id: "x6", kind: "on_stop", from: SID.capas, to: SID.flechas, text: "avisame cuando termines", at: null, repeat: true, max_fires: 20, fired: 1, enabled: true },
  ] as Rule[],
};

async function abrir(page: import("@playwright/test").Page) {
  await aislarCapturas(page);
  await bloquearEscrituras(page);
  await instalarTablero(page, tableroDeHoy(), PEERS, EXTRA);
  await page.route("**/conocimiento/**", route => {
    const p = new URL(route.request().url()).pathname;
    const creencia = (id: string, estado: string, texto: string, accion: string) => ({
      creencia: id, estado, texto, accion, dimension: "pruebas", motivo: "Comparación del escenario de demostración.",
      evidencia: estado === "sin_veredicto" ? null : "ev-demo", excepciones: "Revisar si cambia el alcance.",
      vigente_hasta: "2027-01-01T00:00:00Z", contexto: { tipo_trabajo: "bugfix" },
      alcance: "proyecto", usos: { sirvio: 2, no_aplico: 0, ya_sabido: 0 }, revisar: false,
    });
    const data = p.endsWith("/proyectos") ? [{ id: "demo", nombre: "Huerta · proyecto de ejemplo" }]
      : p.endsWith("/temas") ? { temas: [{ id: "riego", texto: "Riego por sectores" }] }
      : p.endsWith("/creencias-proyecto") ? { proyecto: { total: 3, items: [
        creencia("c1", "sin_veredicto", "Simular un sensor sin señal antes de cambiar el riego.", "Agregar el caso sin señal al escenario de prueba."),
        creencia("c2", "vigente", "Comparar el caudal esperado con el registrado en cada sector.", "Registrar ambos valores en el informe."),
        creencia("c3", "refutada", "Reintentar siempre recupera la conexión del sensor.", "No usar reintentos ilimitados."),
      ] }, lienzo: { total: 1, items: [creencia("c4", "vigente", "Cada encargo indica qué evidencia debe volver.", "Anotar el criterio de verificación antes de repartir.")] } }
      : p.endsWith("/nodos") ? { total: 1, nodos: [{ id: "ev-demo", texto: "Prueba inventada: cuatro sectores y un sensor sin señal." }] }
      : p.endsWith("/patrones-desarrollo") ? { revisados: 4, sin_clasificar: 0, muestra_parcial: false, patrones: [{ contexto: { tipo_trabajo: "bugfix" }, encargos: 4, fuentes: ["encargo-demo"], controles_declarados: { pruebas: 4 }, controles_evidencia: [{ ejecutados: [{}], verificados: [{}] }] }] }
      : p.endsWith("/contexto-sugerido") ? { contexto: { tipo_trabajo: "bugfix" }, fuente: "Encargo de ejemplo", fuentes: [] }
      : p.endsWith("/briefing") ? {
        vigente: [{ id: "decision-demo", tipo: "decision", estado: "vigente", texto: "**Riego por sectores.** Cada sector conserva su umbral y su horario. Un sensor sin señal detiene sólo su sector.", origen: "Ronda de ejemplo", estado_por: "Lucía (demo)" }],
        abierto: [{ id: "pregunta-demo", tipo: "pregunta", estado: "abierto", texto: "¿Cuánto tiempo esperar una lectura antes de avisar? Falta comparar el caso de batería baja con el de señal intermitente." }],
        otros: [{ id: "informe-demo", tipo: "informe", estado: "observado", texto: "El escenario inventado cubre cuatro sectores: tres reciben lectura y uno queda sin señal. El informe conserva entradas, salida y motivo." }],
      } : [];
    return route.fulfill({ json: data });
  });
  await page.goto(BASE);
  await page.waitForSelector(".card", { state: "visible" });
  await page.waitForFunction(() => document.querySelectorAll(".board .col").length === 3);
  await esperarQuietud(page);
  await expect(page.locator(".pcstrip")).toBeVisible();
}

/** Hasta donde llega el tablero: sin la franja vacía de abajo. */
async function recorte(page: import("@playwright/test").Page) {
  const alto = await page.evaluate(() => Math.max(...[...document.querySelectorAll(".board .col")].map((c) => c.getBoundingClientRect().bottom)));
  return { x: 0, y: 0, width: 1440, height: Math.min(900, Math.ceil(alto) + 1) };
}

test("tablero", async ({ page }) => {
  await abrir(page);
  // Oráculo de aislamiento: ni una lectura nueva ni una escritura sin fixture llegan al server.
  const status = await page.evaluate(async () => Promise.all([
    fetch("/__captura_sin_fixture").then(r => r.status),
    fetch("/__captura_sin_fixture", { method: "POST", body: "demo" }).then(r => r.status),
  ]));
  expect(status).toEqual([404, 403]);
  await page.screenshot({ path: `${DESTINO}/tablero.png`, clip: await recorte(page) });
});

test("tira de PCs", async ({ page }) => {
  await abrir(page);
  await page.locator(".pcstrip").screenshot({ path: `${DESTINO}/tira-pcs.png` });
});

for (const aprendizaje of [false, true]) test(aprendizaje ? "aprendizaje" : "memoria del proyecto", async ({ page }) => {
  if (aprendizaje) await page.setViewportSize({ width: 1440, height: 1400 });
  await abrir(page);
  await page.getByRole("button", { name: "más opciones", exact: true }).click();
  await page.getByRole("menuitem", { name: /Memoria/ }).click();
  await page.getByLabel("Proyecto", { exact: true }).selectOption("demo");
  if (aprendizaje) {
    await page.getByRole("button", { name: "Aprendizaje", exact: true }).click();
    await expect(page.getByRole("region", { name: "De este proyecto", exact: true })).toContainText("Simular un sensor");
  } else {
    await page.getByRole("button", { name: "Leer briefing" }).click();
    await expect(page.getByText("Riego por sectores.", { exact: true })).toBeVisible();
  }
  await page.getByRole("dialog", { name: "Memoria del proyecto" }).screenshot({ path: `${DESTINO}/${aprendizaje ? "aprendizaje" : "memoria-proyecto"}.png` });
});

test("consulta entre investigadores", async ({ page }) => {
  await abrir(page);
  await page.route("**/consultas", route => route.fulfill({ json: [{
    id: "consulta-demo", pregunta: "¿Cómo detectar un sensor sin señal?", estado: "abierta", vuelta: 1, vueltas: 2,
    investigadores: [SID.mapas, SID.capas], revisor: SID.coordinadora, coordinador: SID.coordinadora,
    nombres: { [SID.mapas]: "Modelo de sensores", [SID.capas]: "Pruebas de señal", [SID.coordinadora]: "Revisión" },
    esperando: [SID.capas], pendientes: [], fuera: {}, motivo: null, creada: ahora(), cerrada: null,
  }] }));
  await page.reload();
  await esperarQuietud(page);
  await expect(page.getByText("¿Cómo detectar un sensor sin señal?", { exact: false }).first()).toBeVisible();
  await page.screenshot({ path: `${DESTINO}/consulta-investigadores.png`, clip: await recorte(page) });
});

test("panel", async ({ page }) => {
  await abrir(page);
  // el chat de la coordinadora con dos turnos que parecen de verdad (el del tablero fijo repite un
  // texto largo a proposito, para probar el scroll)
  const turno = (id: string, min: number, prompt: string, says: string[], final: string, extra: object) => ({
    id, ts_start: haceMin(min), ended: true, prompt, says, final, files: [], commands: [], errors: [], questions: [],
    peers: [], reads: 0, subagents: 0, tools: 0, ...extra,
  });
  await page.route("**/sessions/*/digest*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        has_more: false,
        turns: [
          turno("c1", 14, "repartí los encargos y traeme las mediciones de cada sesión",
            ["Reviso qué quedó pendiente de ayer.", "Lanzo los frentes y los cableo para que me avisen al terminar."],
            "Ocho encargos repartidos: flechas y glifos en la notebook, el motor de reglas y la migración acá. Cada frente me avisa cuando termina.",
            { tools: 9, reads: 3, peers: ["→ lienzo · Flechas y glifos: medí que ninguna flecha cruce una tarjeta", "→ teorema · Migración de datos: pasá las tablas viejas"], commands: ["coordinar.lanzar_y_titular(...)"] }),
          turno("c2", 2, "¿cómo vamos?",
            ["Leo los informes que llegaron."],
            "Tres de ocho cerrados y verificados contra el árbol: el ruteo de flechas por carriles, skip_busy en las reglas periódicas y la capa de calor. La migración está frenada por un permiso denegado (git push --force): no lo autorizo, le pido que abra una rama. Falta la batería de pruebas de interfaz.",
            { tools: 4, reads: 6, files: ["Board.tsx", "Card.tsx"], commands: ["npm run build"] }),
        ],
      }),
    }),
  );
  await page.locator(`.card[data-sid="${SID.coordinadora}"]`).dblclick();
  await expect(page.locator(".panel")).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${DESTINO}/panel.png` });
});

async function altArrastre(page: import("@playwright/test").Page, soltar: boolean) {
  const desde = await page.locator(`.card[data-sid="${SID.flechas}"] .title`).boundingBox();
  const hasta = await page.locator(`.card[data-sid="${SID.reglas}"]`).boundingBox();
  await page.keyboard.down("Alt");
  await page.mouse.move(desde!.x + desde!.width / 2, desde!.y + desde!.height / 2);
  await page.mouse.down();
  await page.mouse.move(hasta!.x + hasta!.width / 2, hasta!.y + hasta!.height / 2, { steps: 12 });
  if (soltar) {
    await page.mouse.up();
    await page.keyboard.up("Alt");
  }
}

test("arrastre", async ({ page }) => {
  await abrir(page);
  await altArrastre(page, false);
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${DESTINO}/arrastre.png` });
});

test("conectar", async ({ page }) => {
  await abrir(page);
  await altArrastre(page, true);
  const fwd = page.locator(".fwd");
  await expect(fwd).toBeVisible();
  await fwd.locator("input, textarea").first().fill("cada 30 min continuá hasta 3 veces");
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${DESTINO}/conectar.png` });
});

test("lanzar", async ({ page }) => {
  await abrir(page);
  // clic derecho en el vacío de la columna Trabajo: abre el menú del tablero
  const col = await page.locator(".board .col").first().boundingBox();
  await page.mouse.click(col!.x + col!.width / 2, col!.y + col!.height - 40, { button: "right" });
  await page.getByRole("menuitem", { name: "Lanzar CLI…" }).click();
  await expect(page.getByRole("dialog", { name: "Lanzar CLI" })).toBeVisible();
  await page.getByRole("combobox", { name: "PC" }).selectOption(NOTEBOOK);
  await page.getByRole("combobox", { name: "Agente" }).selectOption("claude");
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${DESTINO}/lanzar.png` });
});

test.describe("celular", () => {
  test.use({ deviceScaleFactor: 3 });
  test("celular", async ({ page }) => {
    // se abre a lo ancho (como pcs.spec.ts: a 390 px las tres columnas son una sola) y se achica
    await abrir(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${DESTINO}/celular.png`, fullPage: true });
  });
});

test("Chrome remoto con página inventada", async ({ page, context }) => {
  // La imagen del remoto también es un fixture: se dibuja en una página sin red.
  const remoto = await context.newPage();
  await remoto.route("**/*", route => route.abort());
  await remoto.setViewportSize({ width: 1280, height: 800 });
  await remoto.setContent(`<html lang="es"><meta charset="utf-8"><style>
    *{box-sizing:border-box}body{margin:0;background:#edf2ed;color:#183d31;font:20px system-ui}
    .tabs{background:#dbe3e9;padding:16px 28px;font-size:16px}.url{background:white;padding:12px 32px;font-size:16px}
    main{padding:50px 64px}small{letter-spacing:2px}h1{font-size:48px;margin:16px 0}p{color:#537266}
    .grid{display:flex;gap:22px;margin-top:42px}.card{background:white;border:1px solid #cadace;border-radius:14px;padding:28px;flex:1}
    strong{display:block;font-size:28px;margin:20px 0}.pill{background:#e1efe7;padding:8px 12px;border-radius:8px;font-size:16px}
    footer{margin-top:45px;font-size:16px;color:#537266}
    </style><div class="tabs">Huerta · demostración\u3000 ×\u3000\u3000 Manual de sensores\u3000 ×\u3000\u3000 +</div>
    <div class="url">←\u3000→\u3000↻\u3000\u3000 huerta.example.test / sectores</div><main><small>PROYECTO DE EJEMPLO</small>
    <h1>Riego por sectores</h1><p>Escenario inventado para mostrar Chrome remoto en Lienzo.</p><div class="grid">
    <div class="card">Sector norte<strong>Lectura recibida</strong><span class="pill">Riego programado</span></div>
    <div class="card">Sector sur<strong>Sin señal</strong><span class="pill">Esperando revisión</span></div>
    <div class="card">Semillero<strong>Lectura recibida</strong><span class="pill">Riego programado</span></div></div>
    <footer>Datos de demostración · Sin conexión a sensores ni servicios externos</footer></main></html>`);
  const png = await remoto.screenshot({ scale: "css" });
  await remoto.close();
  await aislarCapturas(page);
  await bloquearEscrituras(page);
  await page.route("**/auth", r => r.fulfill({ json: { configured: false, authenticated: true, local: true } }));
  await page.route("**/peers", r => r.fulfill({ json: PEERS }));
  await page.route("**/browser", r => r.fulfill({ json: r.request().postDataJSON().action === "windows"
    ? { windows: [{ id: "demo", title: "Huerta · demostración", profile: "Ejemplo" }] }
    : { profiles: [{ id: "Default", name: "Ejemplo" }] } }));
  const header = Buffer.alloc(17);
  header.writeUInt32BE(1); header.writeUInt16BE(1280, 8); header.writeUInt16BE(800, 10);
  header.writeUInt16BE(1280, 12); header.writeUInt16BE(800, 14); header.writeUInt8(1, 16);
  await page.routeWebSocket("**/browser/stream*", ws => ws.onMessage(message => {
    if (JSON.parse(String(message)).t === "open") ws.send(Buffer.concat([header, png]));
  }));
  await page.goto(`${BASE}/chrome?pc=${NOTEBOOK}`);
  await expect(page.getByRole("application", { name: "Página remota: mouse y teclado" })).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${DESTINO}/chrome-remoto.png` });
});
