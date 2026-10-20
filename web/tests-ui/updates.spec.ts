import { expect, test } from "@playwright/test";
import { BASE, bloquearEscrituras, instalarTablero } from "./tablero-fijo";

const status = { phase: "available", available: true, busy: false, running: "1234567890", target: "abcdef1234", version: "0.4.1", checked_at: 1792450000, changes: ["abcdef1 Corregir detección de sesiones"], blocked: "" };

test("Actualizaciones muestra novedades y aplica exactamente la versión consultada", async ({ page }) => {
  await bloquearEscrituras(page);
  await instalarTablero(page);
  let state = { ...status };
  let sent: unknown;
  await page.route("**/updates", route => route.fulfill({ json: state }));
  await page.route("**/updates/apply", route => {
    sent = route.request().postDataJSON();
    state = { ...status, phase: "building", busy: true };
    return route.fulfill({ status: 202, json: state });
  });
  await page.goto(BASE);
  await expect(page.getByText("· Actualización disponible", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "más opciones" }).click();
  await page.getByRole("menuitem", { name: "Actualizaciones", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Actualizaciones", exact: true });
  await expect(dialog.getByText("abcdef1 Corregir detección de sesiones")).toBeVisible();
  await dialog.getByRole("button", { name: "Actualizar esta PC" }).click();
  expect(sent).toEqual({ target: status.target });
  await expect(dialog.getByText("Compilando la interfaz…")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Actualizar esta PC" })).toBeDisabled();
  await page.screenshot({ path: "node_modules/.playwright-artifacts/updates-building.png" });
});

test("cambios locales bloquean actualizar y errores de consulta quedan visibles", async ({ page }) => {
  await bloquearEscrituras(page);
  await instalarTablero(page);
  await page.route("**/updates", route => route.fulfill({ json: { ...status, blocked: "Hay cambios locales; guardalos en Git antes de actualizar" } }));
  await page.route("**/updates/check", route => route.fulfill({ status: 503, json: { error: "Git no está disponible" } }));
  await page.goto(BASE);
  await page.getByRole("button", { name: "Abrir actualizaciones" }).click();
  const dialog = page.getByRole("dialog", { name: "Actualizaciones", exact: true });
  await expect(dialog.getByText("Hay cambios locales; guardalos en Git antes de actualizar")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Actualizar esta PC" })).toBeDisabled();
  await dialog.getByRole("button", { name: "Buscar novedades" }).click();
  await expect(dialog.getByRole("alert")).toContainText("Git no está disponible");
  await dialog.getByRole("button", { name: "Cerrar actualizaciones" }).click();
  await expect(dialog).toHaveCount(0);
});

test("una PC anterior informa que necesita la primera actualización", async ({ page }) => {
  await bloquearEscrituras(page);
  await instalarTablero(page);
  await page.route("**/updates", route => route.fulfill({ status: 404, json: { error: "ruta desconocida" } }));
  await page.goto(BASE);
  await page.getByRole("button", { name: "Abrir actualizaciones" }).click();
  await expect(page.getByRole("dialog", { name: "Actualizaciones", exact: true }).getByRole("alert")).toContainText("primera actualización desde su terminal");
});

test("actualizar otra PC manda su identidad y no la confunde con esta PC", async ({ page }) => {
  await bloquearEscrituras(page);
  await instalarTablero(page, [], [
    { pc_id: "local", name: "Escritorio", local: true, alive: true, color: "green", last_seen: "", health: null },
    { pc_id: "notebook", name: "Notebook", local: false, alive: true, color: "blue", last_seen: "", health: null },
  ]);
  await page.route("**/updates*", route => {
    const pc = new URL(route.request().url()).searchParams.get("pc");
    return route.fulfill({ json: { ...status, running: pc ? "remote123456" : "local123456" } });
  });
  let sent: unknown;
  await page.route("**/updates/apply", route => {
    sent = route.request().postDataJSON();
    return route.fulfill({ status: 202, json: status });
  });
  await page.goto(BASE);
  await page.getByRole("button", { name: "Abrir actualizaciones" }).click();
  const dialog = page.getByRole("dialog", { name: "Actualizaciones", exact: true });
  await dialog.getByRole("combobox", { name: "PC a actualizar" }).selectOption("notebook");
  await expect(dialog.getByText("remote12", { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "Actualizar PC elegida" }).click();
  expect(sent).toEqual({ pc: "notebook", target: status.target });
  await dialog.getByRole("button", { name: "Cerrar actualizaciones" }).click();
  await page.getByRole("button", { name: "Abrir actualizaciones" }).click();
  await expect(dialog.getByRole("combobox", { name: "PC a actualizar" })).toHaveValue("");
  await expect(dialog.getByText("local123", { exact: true })).toBeVisible();
});

test("botón derecho en la PC abre sus actualizaciones; al día no ejecuta nada", async ({ page }) => {
  await bloquearEscrituras(page);
  await instalarTablero(page, [], [
    { pc_id: "local", name: "Escritorio", local: true, alive: true, color: "green", last_seen: "", health: null },
    { pc_id: "notebook", name: "Notebook", local: false, alive: true, color: "blue", last_seen: "", health: null },
  ]);
  await page.route("**/updates*", route => {
    const remote = new URL(route.request().url()).searchParams.get("pc") === "notebook";
    return route.fulfill({ json: remote ? status : { ...status, phase: "current", available: false } });
  });
  await page.goto(BASE);
  await page.locator('.pcchip[data-pc="notebook"]').click({ button: "right" });
  await page.getByRole("menuitem", { name: "Actualizar…", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Actualizaciones", exact: true });
  await expect(dialog.getByRole("combobox", { name: "PC a actualizar" })).toHaveValue("notebook");
  await dialog.getByRole("button", { name: "Cerrar actualizaciones" }).click();
  await page.locator('.pcchip[data-pc="local"]').click({ button: "right" });
  await expect(page.getByRole("menuitem", { name: "Al día", exact: true })).toBeDisabled();
  await expect(page.getByRole("menuitem", { name: "Actualizar…", exact: true })).toHaveCount(0);
  await page.screenshot({ path: "node_modules/.playwright-artifacts/updates-pc-context.png" });
});
