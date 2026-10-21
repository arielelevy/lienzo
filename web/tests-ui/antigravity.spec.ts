import { test, expect } from "@playwright/test";
import { abrirTablero, sesiones, SID } from "./tablero-fijo";
import type { Peer } from "../src/types";
import { contrasteMalo } from "./medidas";

test("Antigravity se elige al lanzar y explica el alcance de terminal", async ({ page }) => {
  await abrirTablero(page);
  await page.locator(".board").dispatchEvent("contextmenu", { clientX: 500, clientY: 300 });
  await page.getByRole("menuitem", { name: "Lanzar CLI…" }).click();
  const dialog = page.getByRole("dialog", { name: "Lanzar CLI" });
  await dialog.getByLabel("Agente", { exact: true }).selectOption("antigravity");
  await expect(dialog.getByText(/Sin conversación estructurada/)).toBeVisible();
  await dialog.getByLabel("Proyecto", { exact: true }).selectOption("");
  await dialog.getByLabel("Carpeta", { exact: true }).fill("D:/Apps/lienzo");
  const posts: Record<string, unknown>[] = [];
  await page.route("**/sessions/launch", async route => {
    posts.push(route.request().postDataJSON());
    await route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({ error: "no encuentro agy.exe en esta PC" }) });
  });
  await dialog.getByRole("button", { name: "Lanzar", exact: true }).click();
  await expect(dialog.getByRole("alert")).toHaveText("no encuentro agy.exe en esta PC");
  expect(posts).toHaveLength(1);
  expect(posts[0]).toMatchObject({ agent: "antigravity", cwd: "D:/Apps/lienzo" });
  await dialog.getByLabel("Agente", { exact: true }).selectOption("codex");
  await expect(dialog.getByText(/Sin conversación estructurada/)).toHaveCount(0);
});

test("Antigravity descarta WSL al cambiar de agente y conserva la elección para Codex", async ({ page }) => {
  const peer: Peer = {
    pc_id: "pruebaB", name: "PC prueba", local: true, alive: true, color: "#4285f4", last_seen: new Date().toISOString(),
    health: { mem_free_gb: 8, cpu_pct: 0, temp_c: null, distros_wsl: ["Ubuntu"], launch_roots: ["D:/Apps/lienzo"] },
  };
  await abrirTablero(page, undefined, [peer]);
  await page.locator(".board").dispatchEvent("contextmenu", { clientX: 500, clientY: 300 });
  await page.getByRole("menuitem", { name: "Lanzar CLI…" }).click();
  const dialog = page.getByRole("dialog", { name: "Lanzar CLI", exact: true });
  await dialog.getByLabel("Distro de WSL").selectOption("Ubuntu");
  await dialog.getByLabel("Agente", { exact: true }).selectOption("antigravity");
  await expect(dialog.getByLabel("Distro de WSL")).toHaveCount(0);
  await dialog.getByLabel("Agente", { exact: true }).selectOption("codex");
  await expect(dialog.getByLabel("Distro de WSL")).toHaveValue("Ubuntu");
  await dialog.getByLabel("Agente", { exact: true }).selectOption("antigravity");
  await dialog.getByLabel("Proyecto", { exact: true }).selectOption("");
  await dialog.getByLabel("Carpeta", { exact: true }).fill("D:/Apps/lienzo");
  let post: Record<string, unknown> | undefined;
  await page.route("**/sessions/launch", async route => {
    post = route.request().postDataJSON();
    await route.fulfill({ json: { ok: true } });
  });
  await dialog.getByRole("button", { name: "Lanzar", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(post).toMatchObject({ agent: "antigravity" });
  expect(post).not.toHaveProperty("distro");
});

test("la tarjeta declara observación parcial, evita fin de turno y cumple contraste AA", async ({ page }) => {
  const lista = sesiones().map(s => s.session_id === SID.mapas ? {
    ...s, agent: "antigravity" as const, state_source: "unverified" as const, state: "corriendo" as const,
    screen_observation: { source: "screen" as const, observed_at: new Date().toISOString(), available: true, model_label: "Gemini 3.8 Flash · high", activity: "unverified" as const },
  } : s);
  await abrirTablero(page, lista);
  const card = page.locator(`.card[data-sid="${SID.mapas}"]`);
  await expect(card.getByText("actividad sin confirmar", { exact: true })).toBeVisible();
  await expect(card.getByText("Pantalla: Gemini 3.8 Flash · high", { exact: false })).toBeVisible();
  await expect(card.getByText(/Observación parcial; sin respuesta estructurada/)).toBeVisible();
  await expect(card.getByRole("img", { name: /^(corriendo|terminó)$/ })).toHaveCount(0);
  const chip = page.locator("button.chip.antigravity.on");
  await expect(chip).toBeVisible();
  const ratio = await chip.evaluate(el => {
    const css = getComputedStyle(el);
    const lum = (color: string) => {
      const rgb = color.match(/[\d.]+/g)!.slice(0, 3).map(Number).map(v => v / 255);
      const [r, g, b] = rgb.map(v => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const a = lum(css.color), b = lum(css.backgroundColor);
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  });
  console.log(`Antigravity chip activo contraste: ${ratio.toFixed(2)}:1`);
  expect(ratio).toBeGreaterThanOrEqual(4.5);
  const contrast = await contrasteMalo(page);
  expect(contrast.medidos).toBeGreaterThan(30);
  expect(contrast.fallos.filter(f => f.sel.includes("antigravity") || f.sel.includes("terminal-observation"))).toEqual([]);
  await page.screenshot({ path: "../.temp/coordinacion/2026-10-20/B-antigravity/ui-parcial.png" });
  await card.locator(".title").dblclick();
  await expect(page.locator(".panel").getByText(/avisarme cuando termine/)).toHaveCount(0);
});

test("sin lectura de pantalla no inventa modelo; la huérfana sugiere agy sin ID inexistente", async ({ page }) => {
  const lista = sesiones().map(s => s.session_id === SID.mapas ? {
    ...s, agent: "antigravity" as const, screen_observation: null, state: "termino" as const,
  } : s.session_id === SID.huerfana ? { ...s, agent: "antigravity" as const } : s);
  await abrirTablero(page, lista);
  const card = page.locator(`.card[data-sid="${SID.mapas}"]`);
  await expect(card.getByText("Modelo sin observar en pantalla")).toBeVisible();
  await expect(card.getByRole("img", { name: "terminó", exact: true })).toHaveCount(0);
  await page.locator(".col.muerta .vlabel").click();
  await page.locator(`.card[data-sid="${SID.huerfana}"] .title`).dblclick();
  const notice = page.locator(".panel .send");
  await expect(notice.getByText(/Reabrila con/)).toBeVisible();
  await expect(notice.locator("code")).toHaveText("agy");
  await expect(notice).not.toContainText("--conversation");
});
