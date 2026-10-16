import { expect, test } from "@playwright/test";
import { SID, abrirTablero } from "./tablero-fijo";

const settings = { preferences: { brief: false, rtk: false }, tools: [
  { id: "breve", nombre: "Respuestas breves", tipo: "mejora", origen: "https://github.com/JuliusBrussee/caveman", descripcion: "Sin proxy ni compresión de archivos", version: null, costo: "gratis", modos: ["general", "ingenieria-reversa"], preferencia: "brief", instalar: null, estado: { disponible: true } },
  { id: "rtk", nombre: "RTK", tipo: "mejora", origen: "https://github.com/rtk-ai/rtk", descripcion: "Salidas de comandos", version: "0.51.0", costo: "gratis", modos: ["general", "ingenieria-reversa"], preferencia: "rtk", instalar: null, estado: { disponible: true } },
  { id: "rea", nombre: "REA", tipo: "trabajo", origen: "https://github.com/morluto/rea", descripcion: "Ingeniería reversa", version: null, costo: "gratis", modos: ["ingenieria-reversa"], preferencia: null, instalar: "rea setup", estado: { disponible: false, detalle: "no instalada" } },
], scope: "esta PC; nuevas sesiones" };
const report = (sid: string) => ({ session_id: sid, snapshot: "reviewed", agent: "codex", model: null, quality: "no evaluada", note: null,
  jev_available: true, jev_max_cost_usd: .001, evidence: { scope: "ultimos 10 turnos", counts: { turns: 2, closed: 1, tools: 3, errors: 1, known_results: 2, missing_results: 1 } }, suggestions: [] });
const json = (data: unknown) => ({ status: 200, contentType: "application/json", body: JSON.stringify(data) });

test("piloto distingue habilitado de apto y pausa llamadas automáticas", async ({ page }) => {
  await abrirTablero(page);
  await page.route("**/agent-improvements", route => route.fulfill(json(settings)));
  let enabled = true;
  await page.route("**/agent-improvements/scheduler", route => {
    if (route.request().method() === "PUT") {
      const action = route.request().postDataJSON();
      if (action.action === "configure") enabled = action.enabled;
    }
    return route.fulfill(json({ enabled, pilot_enabled: true, paid_enabled: false,
      reason: enabled ? "cooldown" : "pausado por el usuario", projects: [], jobs: [],
      budget: { limit_usd: "2", spent_usd: ".00002268", reserved_usd: ".037418892", available_usd: "1.962558428", unknown_charges: 1, blocked: false,
        pilot: { deadline: 1791993600, attempts: 1, maximum_calls: 24, cooldown_seconds: 3600, within_window: true } } }));
  });
  await page.locator(".board").dispatchEvent("contextmenu", { clientX: 800, clientY: 600 });
  await page.getByRole("menuitem", { name: "Mejoras de agentes…" }).click();
  const section = page.getByRole("region", { name: "Aprendizaje en segundo plano" });
  await expect(section.getByText(/llamadas pagas acotadas/)).toBeVisible();
  await expect(section.getByText(/intentos 1\/24/)).toBeVisible();
  await expect(section.getByText(/cooldown 60 min/)).toBeVisible();
  await expect(section.getByText(/cota permanece reservada/)).toBeVisible();
  await expect(section.getByText(/Sin envío automático ahora/)).toBeVisible();
  await section.getByRole("button", { name: "Pausar aprendizaje" }).click();
  await expect(section.getByText("pausado por el usuario", { exact: true })).toBeVisible();
  await expect(section.getByRole("button", { name: "Habilitar aprendizaje" })).toBeVisible();
});

test("scheduler informa bloqueo y encola solo análisis local", async ({ page }) => {
  await abrirTablero(page);
  await page.route("**/agent-improvements", route => route.fulfill(json(settings)));
  let status = { enabled: true, reason: "actividad del usuario", projects: [{ id: "lienzo", name: "Lienzo" }], jobs: [] as object[], paid_enabled: false, new_agents_enabled: false, budget: { limit_usd: "2", spent_usd: "0.00002268", reserved_usd: "0", available_usd: "0", unknown_charges: 1, blocked: true } };
  const writes: unknown[] = [];
  await page.route("**/agent-improvements/scheduler", route => {
    if (route.request().method() !== "GET") {
      const data = route.request().postDataJSON();
      if (data.action === "enqueue") { writes.push(data); status = { ...status, jobs: [{ id: "job", project: "lienzo", state: "queued", cursor: 0, results: [] }] }; }
      else if (data.action === "configure") { writes.push(data); status = { ...status, enabled: data.enabled }; }
    }
    return route.fulfill(json(status));
  });
  await page.locator(".board").dispatchEvent("contextmenu", { clientX: 800, clientY: 600 });
  await page.getByRole("menuitem", { name: "Mejoras de agentes…" }).click();
  const section = page.getByRole("region", { name: "Aprendizaje en segundo plano" });
  await expect(section.getByText("actividad del usuario", { exact: true })).toBeVisible();
  await expect(section.getByText(/Presupuesto total USD 2/)).toBeVisible();
  await expect(section.getByText(/Cargos previos sin conciliar/)).toBeVisible();
  await expect(section.getByRole("button", { name: "Encolar análisis local" })).toBeDisabled();
  await section.getByRole("combobox").selectOption("lienzo");
  await section.getByRole("button", { name: "Encolar análisis local" }).click();
  await expect(section.getByText("lienzo · queued")).toBeVisible();
  await section.getByRole("button", { name: "Pausar aprendizaje" }).click();
  await expect(section.getByRole("button", { name: "Habilitar aprendizaje" })).toBeVisible();
  expect(writes).toEqual([{ action: "enqueue", project: "lienzo" }, { action: "configure", enabled: false }]);
});

test("menú contextual ofrece preferencias y conserva estado ante error", async ({ page }) => {
  await abrirTablero(page);
  await page.route("**/agent-improvements/scheduler", route => route.fulfill(json({ enabled: true, reason: "actividad del usuario", projects: [], jobs: [] })));
  let writes = 0;
  await page.route("**/agent-improvements", async route => {
    if (route.request().method() === "GET") return route.fulfill(json(settings));
    writes++;
    return route.fulfill(writes === 1 ? { status: 500, contentType: "application/json", body: '{"error":"no se pudo guardar"}' } : json({ ...settings, preferences: { brief: true, rtk: false } }));
  });
  await page.locator(".board").evaluate(el => el.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 1435, clientY: 895 })));
  const menu = page.getByRole("menu", { name: "Área libre" });
  await expect(menu.getByRole("menuitem", { name: "Mejoras de agentes…", exact: true })).toBeVisible();
  const bounds = await menu.boundingBox();
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(900);
  await menu.getByRole("menuitem", { name: "Mejoras de agentes…" }).click();
  const dialog = page.getByRole("dialog", { name: "Mejoras de agentes", exact: true });
  const brief = dialog.getByRole("switch", { name: "Respuestas breves" });
  // la casilla nativa está oculta: se toca el interruptor, como lo haría una persona
  const toggle = dialog.locator("label.tool-switch").filter({ hasText: "Respuestas breves" });
  await expect(dialog.getByRole("list", { name: "Catálogo de tools" }).getByRole("listitem")).toHaveCount(3);
  await expect(dialog.getByText(/no instalada/)).toBeVisible();
  await toggle.click();
  await expect(dialog.getByRole("alert")).toHaveText("no se pudo guardar");
  await expect(brief).not.toBeChecked();
  await toggle.click();
  await expect(brief).toBeChecked();
  expect(writes).toBe(2);
  await dialog.getByRole("button", { name: "Cerrar", exact: true }).click();
  await expect(dialog).toHaveCount(0);
});

test("Jev exige autorizar costo y una falla no queda como éxito", async ({ page }) => {
  await abrirTablero(page);
  let paid = 0;
  await page.route("**/sessions/*/improvements", route => route.fulfill(json(report(SID.migracion))));
  await page.route("**/sessions/*/improvements/jev", async route => {
    paid++;
    expect(route.request().postDataJSON()).toEqual({ snapshot: "reviewed", allow_cost: true });
    await route.fulfill({ status: 409, contentType: "application/json", body: '{"error":"la muestra cambio"}' });
  });
  await page.locator(`.card[data-sid="${SID.migracion}"] .title`).dblclick();
  const panel = page.locator(".panel");
  await panel.getByRole("button", { name: "Mejoras", exact: true }).click();
  await expect(panel.getByRole("button", { name: "Consultar Jev" })).toBeDisabled();
  await panel.getByRole("checkbox", { name: /Autorizar una consulta/ }).check();
  await panel.getByRole("button", { name: "Consultar Jev" }).click();
  await expect(panel.getByRole("alert")).toHaveText("la muestra cambio");
  await expect(panel.getByRole("checkbox", { name: /Autorizar una consulta/ })).not.toBeChecked();
  expect(paid).toBe(1);
});

test("una consulta tardía no aparece en otra sesión", async ({ page }) => {
  await abrirTablero(page);
  await page.route("**/sessions/*/improvements", route => {
    const sid = route.request().url().split("/").at(-2)!;
    return route.fulfill(json(report(sid)));
  });
  let release: (() => void) | undefined;
  const held = new Promise<void>(resolve => { release = resolve; });
  let pending = false;
  await page.route("**/sessions/*/improvements/jev", async route => {
    pending = true;
    await held;
    await route.fulfill(json({ session_id: SID.migracion, decision: { choice: "rtk", note: "resultado anterior", model: "test", usage: { cost: .00001 } } }));
  });
  await page.locator(`.card[data-sid="${SID.migracion}"] .title`).dblclick();
  await page.locator(".panel").getByRole("button", { name: "Mejoras", exact: true }).click();
  await page.locator(".panel").getByRole("checkbox", { name: /Autorizar una consulta/ }).check();
  await page.locator(".panel").getByRole("button", { name: "Consultar Jev" }).click();
  await expect.poll(() => pending).toBe(true);
  await page.getByRole("button", { name: "cerrar panel" }).click();
  await page.locator(`.card[data-sid="${SID.mapas}"] .title`).dblclick();
  await page.locator(".panel").getByRole("button", { name: "Mejoras", exact: true }).click();
  release!();
  await expect(page.locator(".panel").getByText("2 turnos · 3 herramientas")).toBeVisible();
  await expect(page.getByText("resultado anterior")).toHaveCount(0);
});

test("un lanzamiento muestra el aviso de mejoras no disponibles", async ({ page }) => {
  await abrirTablero(page);
  await page.route("**/sessions/launch", route => route.fulfill(json({ ok: true, aviso: "RTK no esta instalado en el entorno elegido" })));
  await page.locator(".board").dispatchEvent("contextmenu", { clientX: 800, clientY: 600 });
  await page.getByRole("menuitem", { name: "Lanzar CLI…" }).click();
  const dialog = page.getByRole("dialog", { name: "Lanzar CLI", exact: true });
  await dialog.getByRole("combobox", { name: "Proyecto", exact: true }).selectOption("");
  await dialog.getByRole("textbox", { name: "Carpeta", exact: true }).fill("D:/Apps/lienzo");
  await dialog.getByRole("button", { name: "Lanzar", exact: true }).click();
  await expect(page.getByText("CLI lanzada. RTK no esta instalado en el entorno elegido", { exact: true })).toBeVisible();
});
