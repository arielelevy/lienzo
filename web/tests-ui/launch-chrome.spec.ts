import { expect, test } from "@playwright/test";
import type { Peer } from "../src/types";
import { BASE, instalarTablero } from "./tablero-fijo";

const pc = (chrome_claude?: { id: string; name: string; cuenta: string }[]): Peer => ({
  pc_id: "pcA", name: "Esta PC", color: "#4a8", alive: true, last_seen: new Date().toISOString(), local: true,
  health: { mem_free_gb: 8, mem_total_gb: 16, cpu_pct: 10, temp_c: 50, ...(chrome_claude ? { chrome_claude } : {}) },
});

async function abrirLanzar(page: import("@playwright/test").Page, peers: Peer[]) {
  await instalarTablero(page, undefined, peers);
  let body: Record<string, unknown> | undefined;
  await page.route("**/sessions/launch", async route => {
    body = route.request().postDataJSON();
    await route.fulfill({ json: { ok: true } });
  });
  await page.goto(BASE);
  await page.locator(".board").dispatchEvent("contextmenu", { clientX: 800, clientY: 600 });
  await page.getByRole("menuitem", { name: "Lanzar CLI…" }).click();
  const dialog = page.getByRole("dialog", { name: "Lanzar CLI", exact: true });
  return { dialog, body: () => body };
}

test("Chrome va sólo tildado, en Claude, y dice en qué perfil está la extensión", async ({ page }) => {
  const { dialog, body } = await abrirLanzar(page, [pc([{ id: "Profile 2", name: "Globant", cuenta: "ariel@example.com" }])]);
  const tilde = dialog.getByRole("checkbox", { name: /Darle Chrome a esta sesión/ });
  await expect(tilde).toHaveCount(0);
  await dialog.getByRole("combobox", { name: "Agente", exact: true }).selectOption("claude");
  await expect(tilde).not.toBeChecked();
  await tilde.check();
  await expect(dialog.getByText("Perfil: Globant (ariel@example.com).", { exact: false })).toBeVisible();
  await dialog.getByRole("button", { name: "Lanzar", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(body()).toMatchObject({ agent: "claude", chrome: true });
});

test("sin tildar no manda chrome, y sin extensión lo avisa", async ({ page }) => {
  const { dialog, body } = await abrirLanzar(page, [pc([])]);
  await dialog.getByRole("combobox", { name: "Agente", exact: true }).selectOption("claude");
  const tilde = dialog.getByRole("checkbox", { name: /Darle Chrome a esta sesión/ });
  await tilde.check();
  await expect(dialog.getByText(/No encuentro la extensión Claude in Chrome/)).toBeVisible();
  await tilde.uncheck();
  await dialog.getByRole("button", { name: "Lanzar", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(body()).not.toHaveProperty("chrome");
});

test("la tarjeta de una sesión con --chrome lleva el subíndice de Chrome; las otras no", async ({ page }) => {
  const { sesiones, SID } = await import("./tablero-fijo");
  const lista = sesiones().map(s => s.session_id === SID.mapas ? { ...s, agent: "claude" as const, chrome: true } : s);
  await instalarTablero(page, lista);
  await page.goto(BASE);
  const marca = page.locator(".card .badge-chrome");
  await expect(marca).toHaveCount(1);
  await expect(page.locator(`.card[data-sid="${SID.mapas}"] .badge`).getByRole("img", { name: "con Chrome" })).toBeVisible();
});
