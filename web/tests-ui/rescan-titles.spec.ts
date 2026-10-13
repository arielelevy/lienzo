import { test, expect } from "@playwright/test";
import { abrirTablero } from "./tablero-fijo";

test("buscar sesiones solicita barrido y actualización de nombres", async ({ page }) => {
  await abrirTablero(page);
  let calls = 0;
  await page.route("**/rescan", async route => {
    expect(route.request().method()).toBe("POST");
    calls++;
    await route.fulfill({ status: 202, contentType: "application/json", body: '{"ok":true}' });
  });
  await page.locator(".board").dispatchEvent("contextmenu", { clientX: 500, clientY: 300 });
  await page.getByRole("menuitem", { name: "Buscar sesiones ahora" }).click();
  await expect(page.getByText("Buscando sesiones y actualizando nombres y etiquetas…")).toBeVisible();
  expect(calls).toBe(1);
});
