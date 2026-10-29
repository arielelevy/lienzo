import { expect, test, type Page } from "@playwright/test";
import type { CuotasResponse } from "../src/api";
import { abrirTablero, SID } from "./tablero-fijo";

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

test("Claude Enterprise muestra créditos sin cuota semanal y permite actualizar", async ({ page }) => {
  const claude = { ok: true, plan: "enterprise", five_hour: null, weekly: null, spend: { used: 1.19, limit: 200, currency: "USD" as const }, read_at: MEDIDO, error: null };
  const pedidos = await servirCuotas(page, lectura({ claude }), lectura({ claude: { ...claude, spend: { ...claude.spend, used: 2 } } }, REMEDIDO));
  await abrirTablero(page);
  const boton = page.getByRole("button", { name: /^Claude Code:/ });
  await expect(boton).toContainText("Créditos: USD 1.19 usados de USD 200.00");
  await expect(boton.locator(".cuota-uso")).toHaveCount(2);
  const [usado, limite] = await boton.locator(".cuota-uso").all();
  expect((await usado.boundingBox())!.y).toBeLessThan((await limite.boundingBox())!.y);
  await expect(boton).not.toContainText("sin lectura");
  await expect(boton).not.toHaveAttribute("title", /Semana:|5 h:/);
  await boton.click();
  await expect(boton).toContainText("USD 2.00 usados");
  expect(pedidos).toEqual(["/cuotas", "/cuotas?refrescar=1"]);
});

test("muestra cuotas de Globant y SmartBI por separado", async ({ page }) => {
  const claude = { ...lectura().claude, organization: "Globant" };
  const claude_smartbi = { ...lectura().claude, weekly: { used_pct: 23, resets_at: null }, spend: { used: 0, limit: 0, currency: "USD" as const } };
  await servirCuotas(page, lectura({ claude, claude_smartbi }));
  await abrirTablero(page);
  const botones = page.getByRole("button", { name: /^Claude Code:/ });
  await expect(botones).toHaveCount(2);
  await expect(botones.first()).toContainText("82 % usado semanal");
  const smartbi = botones.nth(1);
  await expect(smartbi).toContainText("23 % usado semanal");
  await expect(smartbi).not.toContainText("Créditos");
  await expect(smartbi).not.toHaveAttribute("title", /Créditos/);
  await expect(smartbi).not.toHaveAccessibleName(/Créditos/);
});

test("avisa si SmartBI todavía no inició sesión", async ({ page }) => {
  const claude_smartbi = { ok: false, plan: null, five_hour: null, weekly: null, read_at: MEDIDO, error: "SmartBI sin iniciar sesión en Claude Code; configurar CLAUDE_CONFIG_DIR para esa cuenta" };
  await servirCuotas(page, lectura({ claude_smartbi }));
  await abrirTablero(page);
  await expect(page.getByRole("button", { name: /^Claude Code: sin iniciar sesión/ })).toBeVisible();
});

/** Antes de abrir el tablero: su `**\/*` cae con fallback a esta ruta. Devuelve las URLs pedidas. */
async function servirCuotas(page: Page, primera: CuotasResponse, remedida?: CuotasResponse) {
  const pedidos: string[] = [];
  await page.route(url => url.pathname === "/cuotas", route => {
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
  const grupo = page.getByRole("group", { name: "Cuotas de Claude, Codex y Kiro" });
  const claude = grupo.getByRole("button", { name: /^Claude Code:/ });
  const codex = grupo.getByRole("button", { name: /^Codex:/ });
  const lineas = claude.locator(".cuota-uso");
  await expect(lineas).toHaveCount(2);
  await expect(lineas.nth(0)).toHaveText("82 % usado semanal");
  await expect(lineas.nth(1)).toHaveText("11 % usado 5 h");
  expect((await lineas.nth(0).boundingBox())!.y).toBeLessThan((await lineas.nth(1).boundingBox())!.y);
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

test("conserva la última lectura y su fecha si falla la actualización", async ({ page }) => {
  const fallida = { ok: false, plan: null, five_hour: null, weekly: null, read_at: REMEDIDO, error: "sin respuesta" };
  await servirCuotas(page, lectura(), lectura({ codex: fallida, sugerido: "claude" }));
  await abrirTablero(page);
  const codex = page.getByRole("button", { name: /^Codex:/ });
  await expect(codex).toContainText("51 % usado semanal");
  await codex.click();
  await expect(codex).toContainText("Última lectura · actualización fallida");
  await expect(codex).toContainText("51 % usado semanal");
  await expect(codex).toContainText(hora(MEDIDO));
  await expect(codex).not.toContainText(hora(REMEDIDO));
  await expect(codex).not.toContainText("conviene");
  await expect(codex).toHaveAttribute("title", /No se pudo leer: sin respuesta/);
  await codex.click();
  await expect(codex).toContainText("51 % usado semanal");
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
  const grupo = page.getByRole("group", { name: "Cuotas de Claude, Codex y Kiro" });
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
  await expect(page.getByRole("group", { name: "Cuotas de Claude, Codex y Kiro" })).toBeVisible();
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
  await page.route(url => url.pathname === "/cuotas", route => route.fulfill(json({ error: "ruta desconocida" }, 404)));
  await abrirTablero(page);
  await expect(page.locator(".card").first()).toBeVisible();
  await expect(page.getByRole("group", { name: "Cuotas de Claude, Codex y Kiro" })).toHaveCount(0);
  const dialog = await abrirLanzar(page);
  await expect(dialog.locator(".cuotas-pista")).toHaveCount(0);
  await dialog.getByRole("combobox", { name: "Agente", exact: true }).selectOption("auto");
  await expect(dialog.getByText("El server elige al lanzar según las cuotas de Claude y Codex.")).toBeVisible();
});

test("refresca solo cada 5 min, no antes", async ({ page }) => {
  await page.clock.install();
  const pedidos = await servirCuotas(page, lectura());
  await abrirTablero(page);
  await expect(page.getByRole("group", { name: "Cuotas de Claude, Codex y Kiro" })).toBeVisible();
  await page.clock.runFor("04:50");
  expect(pedidos).toHaveLength(1);
  await page.clock.runFor("00:15");
  await expect.poll(() => pedidos.length).toBe(2);
});

test("Kiro muestra créditos mensuales, mensajes desconocidos y renovación; refresca sin inventar cuota semanal", async ({ page }, testInfo) => {
  const kiro = { ok: true, plan: "KIRO PRO", five_hour: null, weekly: null,
    credits: { used: 130.37, limit: 1000, available: 869.63 }, messages: null,
    resets_at: "2026-11-01", read_at: MEDIDO, error: null };
  const pedidos = await servirCuotas(page, lectura({ kiro }), lectura({ kiro: { ...kiro, read_at: REMEDIDO } }));
  await abrirTablero(page);
  const boton = page.getByRole("button", { name: /^Kiro/ });
  await expect(boton).toContainText("130.37 usados · 869.63 disponibles de 1000");
  // sin rótulos en la tarjeta: «Créditos por mes» sólo en el aria-label y sin línea de mensajes no informados
  await expect(boton).not.toContainText("Créditos por mes");
  await expect(boton).not.toContainText("Mensajes por mes");
  await expect(boton).toHaveAttribute("aria-label", /Créditos por mes: 130\.37 usados/);
  await expect(boton).toContainText("Renueva 2026-11-01");
  await expect(boton).not.toHaveAttribute("title", /5 h:|Semana:/);
  await boton.click();
  await expect(boton).toContainText(hora(REMEDIDO));
  expect(pedidos).toEqual(["/cuotas", "/cuotas?refrescar=1"]);
  await page.screenshot({ path: testInfo.outputPath("cuotas-kiro-1440.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(boton).toBeVisible();
  const box = await page.getByRole("group", { name: "Cuotas de Claude, Codex y Kiro" }).boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  await page.screenshot({ path: testInfo.outputPath("cuotas-kiro-390.png") });
});

test("renombrar una Claude quieta guarda el título sin duplicar el /native del servidor", async ({ page }) => {
  const titulos: unknown[] = [];
  const nativos: string[] = [];
  await servirCuotas(page, lectura());
  await abrirTablero(page);
  await page.route("**/sessions/*/title", route => {
    titulos.push(route.request().postDataJSON());
    return route.fulfill(json({ ok: true }));
  });
  await page.route("**/sessions/*/native", route => {
    nativos.push(route.request().url());
    return route.fulfill(json({ ok: true, native_name: "demo-Y" }));
  });
  const titulo = page.locator(`.card[data-sid="${SID.mapas}"] .title`);
  await titulo.dblclick();
  await expect(page.locator(".panel")).toBeVisible();
  await titulo.dblclick();
  await page.getByRole("textbox", { name: "nuevo título", exact: true }).fill("demo - encargo Y - nombre");
  await page.getByRole("textbox", { name: "nuevo título", exact: true }).press("Enter");
  await expect(page.getByText("título guardado", { exact: true })).toBeVisible();
  await page.waitForTimeout(300); // deja que salgan las solicitudes encadenadas al PUT, si las hubiera
  expect(titulos).toEqual([{ title: "demo - encargo Y - nombre" }]);
  expect(nativos).toEqual([]);
});
