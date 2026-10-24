import { expect, test } from "@playwright/test";
import { abrirTablero, reglas, SID } from "./tablero-fijo";

test("informe inactivo conserva evidencia y requiere dos acuses explícitos", async ({ page }) => {
  await abrirTablero(page);
  const rule = { ...reglas()[0], id: "r-backlog", from: SID.mapas, to: SID.coordinadora, enabled: false,
    other: { session_id: SID.coordinadora, name: "Coordinadora" },
    informes: [{ id: "informe-1", estado: "entregado", created: "2026-10-17T22:00:00Z", respuesta: "Evidencia conservada" }] };
  await page.route(`**/sessions/${SID.mapas}/connections`, (route) => route.fulfill({ json: { links: [], rules: [rule] } }));
  const acknowledgements: string[] = [];
  await page.route("**/rules/r-backlog/informes/informe-1/acuse", async (route) => {
    acknowledgements.push(route.request().postDataJSON().estado);
    await route.fulfill({ json: { ok: true } });
  });
  await page.locator(`.card[data-sid="${SID.mapas}"] .title`).dblclick();
  await page.locator(".panel .tabs button", { hasText: "Conexiones" }).click();
  await page.getByText("Informe informe- · entregado", { exact: true }).click();
  await expect(page.getByText("Evidencia conservada", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Confirmar integración verificada" })).toHaveCount(0);
  expect(acknowledgements).toEqual([]);
  await page.getByRole("button", { name: "Confirmar recepción" }).click();
  await expect(page.getByText("Informe informe- · recibido", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Confirmar integración verificada" }).click();
  await expect(page.getByText("Informe informe- · integrado", { exact: true })).toBeVisible();
  expect(acknowledgements).toEqual(["recibido", "integrado"]);
});
