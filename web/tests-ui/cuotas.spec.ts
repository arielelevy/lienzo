import { expect, test, type Page } from "@playwright/test";
import type { CuotasResponse } from "../src/api";
import { abrirTablero } from "./tablero-fijo";

/** Cuotas de Claude y Codex (ronda 2026-10-17): el indicador abajo a la derecha y el lanzamiento
 *  balanceado, contra GET /cuotas y POST /sessions/launch interceptados. Los números son los medidos
 *  ese día (Claude 11 % en 5 h y 82 % semanal; Codex 51 % semanal, sin ventana de 5 h en su plan). */

const en = (h: number) => new Date(Date.now() + h * 3600_000).toISOString();
const MEDIDO = "2026-10-17T13:52:00.000Z";
const REMEDIDO = "2026-10-17T14:07:00.000Z";
const hora = (iso: string) => new Date(iso).toLocaleString("es-AR", { timeZone: "America/Argentina/Buenos_Aires", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

const lectura = (o: Partial<CuotasResponse> = {}, readAt = MEDIDO): CuotasResponse => ({
  claude: { ok: true, plan: "team", five_hour: { used_pct: 11, resets_at: en(3) }, weekly: { used_pct: 82, resets_at: en(50) }, read_at: readAt, error: null },
  codex: { ok: true, plan: "prolite", five_hour: null, weekly: { used_pct: 51, resets_at: en(70) }, read_at: readAt, error: null },
  sugerido: "codex",
  motivo: "Codex 49 % libre en la semana contra 18 % de Claude",
  ...o,
});

const json = (data: unknown, status = 200) => ({ status, contentType: "application/json", body: JSON.stringify(data) });

/** Antes de abrir el tablero: su `**\/*` cae con fallback a esta ruta. Devuelve las URLs pedidas. */
async function servirCuotas(page: Page, primera: CuotasResponse, remedida?: CuotasResponse) {
  const pedidos: string[] = [];
  await page.route("**/cuotas*", route => {
    const url = new URL(route.request().url());
    pedidos.push(url.pathname + url.search);
    return route.fulfill(json(url.searchParams.get("refrescar") === "1" && remedida ? remedida : primera));
  });
  return pedidos;
}

async function abrirLanzar(page: Page) {
  await page.locator(".board").dispatchEvent("contextmenu", { clientX: 800, clientY: 600 });
  await page.getByRole("menuitem", { name: "Lanzar CLI…" }).click();
  const dialog = page.getByRole("dialog", { name: "Lanzar CLI", exact: true });
  await expect(dialog).toBeVisible();
  return dialog;
}

test("lectura ok: Claude y Codex lado a lado abajo a la derecha, con su medición; un click vuelve a medir", async ({ page }, testInfo) => {
  const pedidos = await servirCuotas(page, lectura(), lectura({}, REMEDIDO));
  await abrirTablero(page);
  const grupo = page.getByRole("group", { name: "Cuotas de Claude y Codex" });
  const claude = grupo.getByRole("button", { name: /^Claude Code:/ });
  const codex = grupo.getByRole("button", { name: /^Codex:/ });
  await expect(claude).toContainText("82 % usado semanal · 11 % usado 5 h");
  await expect(claude).toContainText(hora(MEDIDO));
  await expect(codex).toContainText("51 % usado semanal");
  await expect(codex).not.toContainText("5 h");
  await expect(codex).toHaveAttribute("title", /5 h: el plan no informa 5 h/);
  await expect(codex).toHaveAccessibleName(/el plan no informa 5 h, conviene ahora/);
  await expect(codex.getByText("conviene", { exact: true })).toBeVisible();
  await expect(claude.getByText("conviene", { exact: true })).toHaveCount(0);
  await expect(claude).toHaveAttribute("title", /Semana: 82 % usado, reinicia /);

  // abajo a la derecha, uno al lado del otro (sin la barra de scroll: fixed se mide desde el área visible)
  const vp = await page.evaluate(() => ({ width: document.documentElement.clientWidth, height: document.documentElement.clientHeight }));
  const [bc, bx, bg] = [await claude.boundingBox(), await codex.boundingBox(), await grupo.boundingBox()];
  // pegado a la esquina: 16 px de margen más lo que reserve el contenedor de la app (10 px a la derecha)
  expect(vp.width - (bg!.x + bg!.width)).toBeLessThanOrEqual(32);
  expect(vp.height - (bg!.y + bg!.height)).toBeLessThanOrEqual(32);
  expect(bg!.x).toBeGreaterThan(vp.width / 2);
  expect(bc!.x + bc!.width).toBeLessThanOrEqual(bx!.x);
  expect(Math.round(bc!.y)).toBe(Math.round(bx!.y));
  await page.screenshot({ path: testInfo.outputPath("cuotas-ok.png") });

  expect(pedidos).toEqual(["/cuotas"]);
  await codex.click();
  await expect(codex).toContainText(hora(REMEDIDO));
  await expect(claude).toContainText(hora(REMEDIDO));
  expect(pedidos).toEqual(["/cuotas", "/cuotas?refrescar=1"]);
});

test("una lectura fallida lo dice, sin números", async ({ page }) => {
  const fallida = { ok: false, plan: null, five_hour: null, weekly: null, read_at: MEDIDO, error: "el token de Claude venció" };
  await servirCuotas(page, lectura({ claude: fallida, motivo: "Claude sin lectura; Codex 49 % libre en la semana" }));
  await abrirTablero(page);
  const claude = page.getByRole("button", { name: /^Claude Code:/ });
  await expect(claude).toContainText("sin lectura");
  await expect(claude).not.toContainText("%");
  await expect(claude).toHaveAttribute("title", /No se pudo leer: el token de Claude venció/);
  await expect(claude).not.toHaveAttribute("title", /5 h:/);
  await expect(page.getByRole("button", { name: /^Codex:/ })).toContainText("conviene");
});

test("sin elegible: ninguno conviene y el lanzamiento automático no lanza (409 claro)", async ({ page }) => {
  const llena = (pct5: number, sem: number) => ({ ok: true, plan: "team", five_hour: { used_pct: pct5, resets_at: en(1) }, weekly: { used_pct: sem, resets_at: en(40) }, read_at: MEDIDO, error: null });
  const motivo = "Claude 95 % y Codex 92 % en 5 h";
  await servirCuotas(page, lectura({ claude: llena(95, 70), codex: llena(92, 40), sugerido: null, motivo }));
  await abrirTablero(page);
  const grupo = page.getByRole("group", { name: "Cuotas de Claude y Codex" });
  await expect(grupo.getByText("conviene", { exact: true })).toHaveCount(0);
  await expect(grupo.getByRole("button", { name: /^Codex:/ })).toHaveAttribute("title", new RegExp(`Ninguno con margen: ${motivo}`));
  await expect(grupo.locator(".cuota.alta")).toHaveCount(2);

  const launches: Record<string, unknown>[] = [];
  await page.route("**/sessions/launch", route => {
    launches.push(route.request().postDataJSON());
    return route.fulfill(json({ error: "ningún agente con margen", motivo }, 409));
  });
  const dialog = await abrirLanzar(page);
  await dialog.getByRole("combobox", { name: "Agente", exact: true }).selectOption({ label: "Automático (el de más margen)" });
  await expect(dialog.getByText(`Ninguno con margen ahora: ${motivo}`)).toBeVisible();
  await dialog.getByRole("button", { name: "Lanzar", exact: true }).click();
  await expect(dialog.getByRole("alert")).toHaveText(`No se lanzó: ningún agente con margen. ${motivo}`);
  await expect(dialog).toBeVisible();
  expect(launches).toHaveLength(1);
  expect(launches[0]).toMatchObject({ agent: "auto" });
});

test("lanzamiento automático: manda auto y dice qué eligió el server y por qué, sin volver a pedir cuotas", async ({ page }) => {
  const pedidos = await servirCuotas(page, lectura());
  await abrirTablero(page);
  await expect(page.getByRole("group", { name: "Cuotas de Claude y Codex" })).toBeVisible();
  let payload: Record<string, unknown> | undefined;
  await page.route("**/sessions/launch", route => {
    payload = route.request().postDataJSON();
    return route.fulfill(json({ ok: true, agent: "codex", motivo: "Codex 49 % libre en la semana contra 18 % de Claude." }));
  });
  const dialog = await abrirLanzar(page);
  await dialog.getByRole("combobox", { name: "Agente", exact: true }).selectOption("auto");
  await expect(dialog.getByText("Ahora elegiría Codex: Codex 49 % libre en la semana contra 18 % de Claude")).toBeVisible();
  await dialog.getByRole("button", { name: "Lanzar", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(payload).toMatchObject({ agent: "auto" });
  await expect(page.getByText("CLI lanzada con Codex. Codex 49 % libre en la semana contra 18 % de Claude", { exact: true })).toBeVisible();
  expect(pedidos).toEqual(["/cuotas"]);
});

test("lanzamiento manual con menos margen: avisa antes y después, sin bloquear", async ({ page }) => {
  await servirCuotas(page, lectura());
  await abrirTablero(page);
  let payload: Record<string, unknown> | undefined;
  await page.route("**/sessions/launch", route => {
    payload = route.request().postDataJSON();
    return route.fulfill(json({ ok: true, aviso: "Claude 82 % semanal; Codex tiene más margen" }));
  });
  const dialog = await abrirLanzar(page);
  await dialog.getByRole("combobox", { name: "Agente", exact: true }).selectOption("claude");
  await expect(dialog.getByText("Codex tiene más margen: Codex 49 % libre en la semana contra 18 % de Claude")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Lanzar", exact: true })).toBeEnabled();
  await dialog.getByRole("button", { name: "Lanzar", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(payload).toMatchObject({ agent: "claude" });
  await expect(page.getByText("CLI lanzada. Claude 82 % semanal; Codex tiene más margen", { exact: true })).toBeVisible();
});

test("un server sin /cuotas no muestra el indicador ni pistas en el lanzamiento", async ({ page }) => {
  await page.route("**/cuotas*", route => route.fulfill(json({ error: "ruta desconocida" }, 404)));
  await abrirTablero(page);
  await expect(page.locator(".card").first()).toBeVisible();
  await expect(page.getByRole("group", { name: "Cuotas de Claude y Codex" })).toHaveCount(0);
  const dialog = await abrirLanzar(page);
  await expect(dialog.locator(".cuotas-pista")).toHaveCount(0);
  await dialog.getByRole("combobox", { name: "Agente", exact: true }).selectOption("auto");
  await expect(dialog.getByText("El server elige al lanzar según las cuotas de Claude y Codex.")).toBeVisible();
});

test("refresca solo cada 5 min, no antes", async ({ page }) => {
  await page.clock.install();
  const pedidos = await servirCuotas(page, lectura());
  await abrirTablero(page);
  await expect(page.getByRole("group", { name: "Cuotas de Claude y Codex" })).toBeVisible();
  await page.clock.runFor("04:50");
  expect(pedidos).toHaveLength(1);
  await page.clock.runFor("00:15");
  await expect.poll(() => pedidos.length).toBe(2);
});
