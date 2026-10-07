import { expect, test } from "@playwright/test";
import { BASE, bloquearEscrituras, esperarQuietud, instalarTablero, sesiones, SID } from "./tablero-fijo";
import type { Link, Peer, Rule, Session } from "../src/types";

/** Las capturas del README (docs/img), sacadas del tablero fijo con datos inventados: nada de las
 *  sesiones reales de quien las corre. No es una prueba: solo corre con CAPTURAS=1.
 *
 *    cd web; npm run build; $env:CAPTURAS=1; npx playwright test --config tests-ui/playwright.config.ts capturas
 */
test.skip(!process.env.CAPTURAS, "solo con CAPTURAS=1: regenera las imagenes del README");
test.use({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });

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
    // La coordinadora pertenece al repo, aunque corra en la notebook.
    if (s.session_id === SID.flechas) return { ...s, pc, coordinator: true };
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
  await bloquearEscrituras(page);
  await instalarTablero(page, tableroDeHoy(), PEERS, EXTRA);
  await page.goto(BASE);
  await page.waitForSelector(".card", { state: "visible" });
  await page.waitForFunction(() => document.querySelectorAll(".board .col").length === 3);
  await esperarQuietud(page);
  await expect(page.locator(".pcstrip")).toBeVisible();
}

/** Hasta donde llega el tablero: sin la franja vacía de abajo. */
async function recorte(page: import("@playwright/test").Page) {
  const alto = await page.evaluate(() => Math.max(...[...document.querySelectorAll(".board .col")].map((c) => c.getBoundingClientRect().bottom)));
  return { x: 0, y: 0, width: 1440, height: Math.min(900, Math.ceil(alto) + 16) };
}

test("tablero", async ({ page }) => {
  await abrir(page);
  await page.screenshot({ path: `${DESTINO}/tablero.png`, clip: await recorte(page) });
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
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${DESTINO}/conectar.png` });
});

test.describe("celular", () => {
  test.use({ deviceScaleFactor: 3 });
  test("celular", async ({ page }) => {
    // se abre a lo ancho (como pcs.spec.ts: a 390 px las tres columnas son una sola) y se achica
    await abrir(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${DESTINO}/celular.png` });
  });
});
