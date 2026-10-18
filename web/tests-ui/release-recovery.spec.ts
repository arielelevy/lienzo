import { expect, test } from "@playwright/test";
import { BASE, SID, bloquearEscrituras, instalarTablero, sesiones } from "./tablero-fijo";
import type { Rule } from "../src/types";

test("regla apagada conserva flecha gris y motivo; se puede reactivar", async ({ page }) => {
  await bloquearEscrituras(page);
  const off: Rule = { id: "off-release", kind: "on_stop", from: SID.flechas, to: SID.coordinadora,
    text: "{respuesta}", at: null, enabled: false, repeat: true, fired: 4, limit: "rate",
    disabled_reason: "entrega fallida; revisar conexión" };
  await instalarTablero(page, sesiones(), undefined, { rules: [off] });
  let sent: Record<string, unknown> | null = null;
  await page.route("**/rules/off-release", (route) => {
    sent = route.request().postDataJSON();
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...off, ...sent }) });
  });
  await page.goto(BASE);
  const card = page.locator(`.card[data-sid="${SID.flechas}"]`);
  await expect(card.getByText("sin aviso a coordinadora", { exact: true })).toBeVisible();
  const arrow = page.locator("svg.arrows g.arrow").filter({ has: page.locator("title", { hasText: "Deshabilitada: entrega fallida" }) });
  await expect(arrow).toHaveCount(1);
  await expect(arrow).toHaveCSS("opacity", "0.4");
  await arrow.locator("circle.dot").dblclick({ force: true });
  const editor = page.getByRole("dialog", { name: "editar conexión" });
  await editor.getByRole("checkbox", { name: "Habilitada", exact: true }).check();
  await editor.getByRole("button", { name: "Guardar" }).click();
  await expect(editor).toHaveCount(0);
  expect(sent).toMatchObject({ enabled: true });
  await page.screenshot({ path: "node_modules/.playwright-artifacts/release-recovery.png" });
  await page.reload();
  await expect(card.getByText("sin aviso a coordinadora", { exact: true })).toBeVisible();
});

test("regla activa evita aviso sin cable; otra carpeta no usa esa coordinadora", async ({ page }) => {
  await bloquearEscrituras(page);
  const list = sesiones().map((s) => s.session_id === SID.reglas
    ? { ...s, repo: "lienzo", cwd: "D:\\Apps\\lienzo" } : s);
  await instalarTablero(page, list);
  await page.goto(BASE);
  await expect(page.locator(`.card[data-sid="${SID.reglas}"]`)).toBeVisible();
  await expect(page.locator(`.card[data-sid="${SID.reglas}"]`).getByText("sin aviso a coordinadora")).toHaveCount(0);
  await expect(page.locator(`.card[data-sid="${SID.migracion}"]`).getByText("sin aviso a coordinadora")).toHaveCount(0);
});
