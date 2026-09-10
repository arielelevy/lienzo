import { expect, test } from "@playwright/test";
import { SID, abrirTablero } from "./tablero-fijo";

test("copiar trabajo, editarlo y reintentar un envío fallido", async ({ page }) => {
  await abrirTablero(page);
  const source = page.locator(`.card[data-sid="${SID.mapas}"]`);
  const target = page.locator(`.card[data-sid="${SID.coordinadora}"]`);
  const sends: Record<string, unknown>[] = [];
  await page.route(`**/sessions/${SID.coordinadora}/send`, async (route) => {
    sends.push(route.request().postDataJSON());
    await route.fulfill({ status: sends.length === 1 ? 409 : 200, contentType: "application/json",
      body: JSON.stringify(sends.length === 1 ? { error: "ocupada" } : { chars: 20 }) });
  });
  await source.focus();
  await page.keyboard.press("Control+c");
  await expect(page.getByText(/Trabajo copiado\./)).toBeVisible();
  await target.focus();
  await page.keyboard.press("Control+v");
  const dialog = page.getByRole("dialog", { name: "Pegar trabajo", exact: true });
  await expect(dialog).toBeVisible();
  const text = dialog.getByRole("textbox", { name: "Trabajo a enviar" });
  await expect(text).toHaveValue(/Último pedido:/);
  await expect(text).toHaveValue(/gold.viajes/);
  expect(sends).toHaveLength(0);
  await text.fill("Continuá con el trabajo revisado");
  await dialog.getByRole("button", { name: "Enviar trabajo" }).click();
  await expect(page.getByText(/No se pudo pegar el trabajo: ocupada/)).toBeVisible();
  await expect(text).toHaveValue("Continuá con el trabajo revisado");
  await dialog.getByRole("button", { name: "Enviar trabajo" }).click();
  await expect(dialog).toHaveCount(0);
  expect(sends).toHaveLength(2);
  expect(sends[1]).toEqual({ from: SID.mapas, text: "Continuá con el trabajo revisado", attachments: [] });
});

test("menú copiar/pegar permite cancelar sin enviar", async ({ page }) => {
  await abrirTablero(page);
  const source = page.locator(`.card[data-sid="${SID.mapas}"]`);
  const target = page.locator(`.card[data-sid="${SID.coordinadora}"]`);
  let sends = 0;
  await page.route("**/sessions/*/send", async (route) => {
    sends++;
    await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });
  await source.locator(".kebab").click();
  await source.getByRole("menuitem", { name: /Copiar trabajo/ }).click();
  await expect(page.getByText(/Trabajo copiado\./)).toBeVisible();
  await target.locator(".kebab").click();
  await target.getByRole("menuitem", { name: /Pegar trabajo/ }).click();
  await page.getByRole("button", { name: "Cancelar", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Pegar trabajo", exact: true })).toHaveCount(0);
  expect(sends).toBe(0);
  await source.locator(".title").dblclick();
  await expect(page.locator(".panel")).toBeVisible();
  await expect(page.locator(".panel").getByRole("button", { name: /^Conversaci[oó]n$/ })).toHaveCount(0);
});
