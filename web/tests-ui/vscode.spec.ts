import { test, expect } from "@playwright/test";
import { abrirTablero } from "./tablero-fijo";

test("menú derecho abre VS Code en el proyecto y muestra errores", async ({ page }) => {
  await abrirTablero(page);
  const board = page.locator(".board");
  await board.dispatchEvent("contextmenu", { clientX: 500, clientY: 300 });
  await page.getByRole("menuitem", { name: "Abrir en VS Code…" }).click();
  const dialog = page.getByRole("dialog", { name: "Abrir en VS Code" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("Agente")).toHaveCount(0);
  await dialog.getByLabel("Proyecto", { exact: true }).selectOption("");
  await dialog.getByLabel("Carpeta", { exact: true }).fill("D:/Apps/project & space");
  const posts: Record<string, unknown>[] = [];
  await page.route("**/sessions/launch", async route => {
    posts.push(route.request().postDataJSON());
    await route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({ error: "No encuentro VS Code en esta PC" }) });
  });
  await dialog.getByRole("button", { name: "Abrir", exact: true }).click();
  await expect(dialog.getByRole("alert")).toHaveText("No encuentro VS Code en esta PC");
  expect(posts).toHaveLength(1);
  expect(posts[0]).toMatchObject({ agent: "vscode", cwd: "D:/Apps/project & space" });
  expect(posts[0]).not.toHaveProperty("distro");
});
