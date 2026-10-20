import { expect, test } from "@playwright/test";
import { BASE, bloquearEscrituras, instalarTablero } from "./tablero-fijo";

const status = { phase: "available", available: true, busy: false, running: "1234567890", target: "abcdef1234", version: "0.4.1", checked_at: 1792450000, changes: ["abcdef1 Esperar la consulta Git antes de actualizar"], blocked: "" };
const peers = [
  { pc_id: "local", name: "Escritorio", local: true, alive: true, color: "green", last_seen: "", health: null },
  { pc_id: "notebook", name: "Notebook", local: false, alive: true, color: "blue", last_seen: "", health: null },
];

test("Actualizar inicia una sola vez y muestra progreso y resultado sin otra confirmación", async ({ page }) => {
  await bloquearEscrituras(page); await instalarTablero(page);
  let state = { ...status };
  const sent: unknown[] = [];
  await page.route("**/updates", route => route.fulfill({ json: state }));
  await page.route("**/updates/apply", route => {
    sent.push(route.request().postDataJSON()); state = { ...status, phase: "building", busy: true };
    return route.fulfill({ status: 202, json: state });
  });
  await page.goto(BASE);
  await page.getByRole("button", { name: "más opciones" }).click();
  await page.getByRole("menuitem", { name: "Actualizar", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Actualizaciones", exact: true });
  await expect(dialog.getByText("Compilando la interfaz…")).toBeVisible();
  expect(sent).toEqual([{ target: status.target }]);
  await expect(dialog.getByRole("progressbar")).toBeVisible();
  await expect(dialog.getByRole("heading", { name: "Qué cambió" })).toBeVisible();
  await expect(dialog.getByText(status.changes[0], { exact: true })).toBeVisible();
  await expect(dialog.getByText("En ejecución", { exact: true })).toBeVisible();
  await expect(dialog.getByText("v0.4.1 abcdef12", { exact: true })).toBeVisible();
  await page.screenshot({ path: "node_modules/.playwright-artifacts/update-detail-progress.png" });
  await expect(dialog.getByRole("button", { name: /Actualizar/ })).toHaveCount(0);
  state = { ...status, phase: "current", available: false, running: status.target };
  await expect(dialog.getByText("Actualización aplicada", { exact: true })).toBeVisible();
  await expect(dialog.getByRole("progressbar")).toHaveCount(0);
  await expect(dialog.getByText(/al día/i)).toHaveCount(0);
  await page.screenshot({ path: "node_modules/.playwright-artifacts/update-simple.png" });
});

test("sin novedades no hay Actualizar ni Al día en menú, PC ni versión", async ({ page }) => {
  await bloquearEscrituras(page); await instalarTablero(page, [], peers);
  let reads = 0;
  await page.route("**/updates*", route => { reads++; return route.fulfill({ json: { ...status, phase: "current", available: false } }); });
  await page.goto(BASE);
  await expect.poll(() => reads).toBeGreaterThan(0);
  const badge = page.getByRole("complementary", { name: "Versión de Lienzo" });
  await expect(badge).toBeVisible();
  await expect(badge.getByRole("button")).toHaveCount(0);
  await expect(badge).not.toContainText(/al día|disponible/i);
  await page.getByRole("button", { name: "más opciones" }).click();
  await expect(page.getByRole("menuitem", { name: /Actualizar|Al día|Actualizaciones/ })).toHaveCount(0);
  await page.keyboard.press("Escape");
  await page.locator('.pcchip[data-pc="local"]').click({ button: "right" });
  await expect(page.getByRole("menu", { name: "Acciones de Escritorio" })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: /Actualizar|Al día|Consultar actualizaciones/ })).toHaveCount(0);
  await expect(page.getByText(/al día/i)).toHaveCount(0);
});

test("Actualizar de otra PC inicia sólo el target de esa máquina", async ({ page }) => {
  await bloquearEscrituras(page); await instalarTablero(page, [], peers);
  await page.route("**/updates*", route => route.fulfill({ json: new URL(route.request().url()).searchParams.get("pc") === "notebook" ? status : { ...status, available: false } }));
  let sent: unknown;
  await page.route("**/updates/apply", route => { sent = route.request().postDataJSON(); return route.fulfill({ status: 202, json: status }); });
  await page.goto(BASE);
  await page.locator('.pcchip[data-pc="notebook"]').click({ button: "right" });
  await page.getByRole("menuitem", { name: "Actualizar", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Actualizaciones" }).getByText("Notebook", { exact: true })).toBeVisible();
  await expect.poll(() => sent).toEqual({ pc: "notebook", target: status.target });
  await expect(page.getByRole("combobox", { name: "PC a actualizar" })).toHaveCount(0);
});

test("cambio local concurrente aparece como error sin forzar la actualización", async ({ page }) => {
  await bloquearEscrituras(page); await instalarTablero(page);
  await page.route("**/updates", route => route.fulfill({ json: status }));
  await page.route("**/updates/apply", route => route.fulfill({ status: 409, json: { error: "Hay cambios locales" } }));
  await page.goto(BASE);
  await page.getByRole("button", { name: "Abrir actualizaciones" }).click();
  await expect(page.getByRole("dialog", { name: "Actualizaciones" }).getByRole("alert")).toContainText("Hay cambios locales");
});

test("el error de un intento anterior no se muestra como fallo del nuevo", async ({ page }) => {
  await bloquearEscrituras(page); await instalarTablero(page);
  let state = { ...status, phase: "error", error: "La compilación anterior falló" };
  let applied = false;
  await page.route("**/updates", async route => {
    // tras aceptar, la próxima lectura tarda: en ese lapso sólo hay estado viejo en pantalla
    if (applied) await new Promise(resolve => setTimeout(resolve, 1500));
    return route.fulfill({ json: state });
  });
  await page.route("**/updates/apply", route => {
    applied = true; state = { ...status, phase: "building", busy: true };
    return route.fulfill({ status: 202, json: state });
  });
  await page.goto(BASE);
  await page.getByRole("button", { name: "Abrir actualizaciones" }).click();
  const dialog = page.getByRole("dialog", { name: "Actualizaciones" });
  await expect.poll(() => applied).toBe(true);
  await expect(dialog.getByText("Iniciando actualización…")).toBeVisible();
  await expect(dialog.getByRole("alert")).toHaveCount(0);
  await expect(dialog.getByText("Compilando la interfaz…")).toBeVisible();
  await expect(dialog.getByRole("alert")).toHaveCount(0);
});

test("volver a abrir durante la compilación retoma el progreso sin otro apply", async ({ page }) => {
  await bloquearEscrituras(page); await instalarTablero(page);
  let state = { ...status };
  let applies = 0;
  await page.route("**/updates", route => route.fulfill({ json: state }));
  await page.route("**/updates/apply", route => {
    applies++; state = { ...status, phase: "building", busy: true };
    return route.fulfill({ status: 202, json: state });
  });
  await page.goto(BASE);
  await page.getByRole("button", { name: "Abrir actualizaciones" }).click();
  await expect(page.getByText("Compilando la interfaz…")).toBeVisible();
  await page.getByRole("button", { name: "Cerrar actualizaciones" }).click();
  await page.getByRole("button", { name: "Abrir actualizaciones" }).click();
  await expect(page.getByText("Compilando la interfaz…")).toBeVisible();
  expect(applies).toBe(1);
});

test("Actualizar espera la consulta Git y después inicia una sola actualización", async ({ page }) => {
  await bloquearEscrituras(page); await instalarTablero(page);
  let state = { ...status };
  let applies = 0;
  await page.route("**/updates", route => route.fulfill({ json: state }));
  await page.route("**/updates/apply", route => {
    applies++; state = { ...status, phase: "building", busy: true };
    return route.fulfill({ status: 202, json: state });
  });
  await page.goto(BASE);
  const open = page.getByRole("button", { name: "Abrir actualizaciones" });
  await expect(open).toBeVisible();
  state = { ...status, phase: "checking", busy: true };
  await open.click();
  const dialog = page.getByRole("dialog", { name: "Actualizaciones" });
  await expect(dialog.getByText("Terminando consulta de novedades…")).toBeVisible();
  expect(applies).toBe(0);
  state = { ...status };
  await expect(dialog.getByText("Compilando la interfaz…")).toBeVisible();
  expect(applies).toBe(1);
});

test("una consulta Git fallida se informa sin aplicar ni simular éxito", async ({ page }) => {
  await bloquearEscrituras(page); await instalarTablero(page);
  let state = { ...status, error: "" };
  let applies = 0;
  await page.route("**/updates", route => route.fulfill({ json: state }));
  await page.route("**/updates/apply", route => { applies++; return route.fulfill({ status: 202, json: status }); });
  await page.goto(BASE);
  const open = page.getByRole("button", { name: "Abrir actualizaciones" });
  await expect(open).toBeVisible();
  state = { ...status, phase: "checking", busy: true, error: "" };
  await open.click();
  const dialog = page.getByRole("dialog", { name: "Actualizaciones" });
  await expect(dialog.getByText("Terminando consulta de novedades…")).toBeVisible();
  state = { ...status, phase: "error", error: "No se pudo consultar Git" };
  await expect(dialog.getByRole("alert")).toHaveText("No se pudo consultar Git");
  await expect(dialog.getByRole("progressbar")).toHaveCount(0);
  expect(applies).toBe(0);
});

test("una consulta Git que no termina vence con error visible", async ({ page }) => {
  await page.clock.install();
  await bloquearEscrituras(page); await instalarTablero(page);
  let state = { ...status };
  let applies = 0;
  await page.route("**/updates", route => route.fulfill({ json: state }));
  await page.route("**/updates/apply", route => { applies++; return route.fulfill({ status: 202, json: status }); });
  await page.goto(BASE);
  const open = page.getByRole("button", { name: "Abrir actualizaciones" });
  await expect(open).toBeVisible();
  state = { ...status, phase: "checking", busy: true };
  await open.click();
  const dialog = page.getByRole("dialog", { name: "Actualizaciones" });
  await expect(dialog.getByText("Terminando consulta de novedades…")).toBeVisible();
  await page.clock.fastForward(91000);
  await expect(dialog.getByRole("alert")).toContainText("La consulta de novedades no terminó");
  expect(applies).toBe(0);
});

test("las novedades y el avance caben en el celular sin otro botón Actualizar", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await bloquearEscrituras(page); await instalarTablero(page);
  await page.route("**/updates", route => route.fulfill({ json: status }));
  await page.route("**/updates/apply", route => route.fulfill({ status: 202, json: status }));
  await page.goto(BASE);
  await page.getByRole("button", { name: "Abrir actualizaciones" }).click();
  const dialog = page.getByRole("dialog", { name: "Actualizaciones" });
  await expect(dialog.getByText(status.changes[0], { exact: true })).toBeVisible();
  await expect(dialog.getByRole("button", { name: /Actualizar/ })).toHaveCount(0);
  expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
  await page.screenshot({ path: "node_modules/.playwright-artifacts/update-detail-mobile.png" });
});
