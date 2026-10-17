import { expect, test } from "@playwright/test";
import type { Session } from "../src/types";
import { abrirTablero, SID, sesiones } from "./tablero-fijo";

function disconnected(): Session[] {
  return sesiones().map(s => s.session_id === SID.mapas ? {
    ...s, agent: "claude", no_console: true, pid: 321, pending_id: null, needs: null,
    external: { kind: "claude-desktop", via: "registro", desktop: true },
    envio: { puede: false, motivo: "adaptador desconectado", transporte: "claude_pipe" },
  } : s);
}

test("reconexión explícita y caducidad: oculta el comando viejo y permite generar otro", async ({ page }) => {
  await page.clock.install();
  await abrirTablero(page, disconnected());
  let calls = 0;
  await page.route(`**/sessions/${SID.mapas}/claude-pipe`, async route => {
    expect(route.request().postDataJSON()).toEqual({ reconnect: true });
    calls++;
    await route.fulfill({ json: { session_id: SID.mapas, command: `public-${calls}`,
      expires_at: (await page.evaluate(() => Date.now())) / 1000 + 5, connected: false } });
  });
  await page.locator(`.card[data-sid="${SID.mapas}"] .title`).dblclick();
  const panel = page.locator(".panel");
  await panel.getByRole("button", { name: "Conectar esta sesión Claude" }).click();
  await expect(panel.getByLabel("Comando público para conectar Claude")).toHaveValue("public-1");
  await page.clock.fastForward(6000);
  await expect(panel.getByText("El comando venció. Generá otro antes de ejecutarlo.")).toBeVisible();
  await expect(panel.getByLabel("Comando público para conectar Claude")).toHaveCount(0);
  await panel.getByRole("button", { name: "Generar otro comando" }).click();
  await expect(panel.getByLabel("Comando público para conectar Claude")).toHaveValue("public-2");
  expect(calls).toBe(2);
});

test("respuesta de conexión tardía no se muestra en otra sesión", async ({ page }) => {
  const lista = disconnected().map(s => s.session_id === SID.capas ? {
    ...s, agent: "claude" as const, no_console: true, pid: 654, pending_id: null, needs: null,
    external: { kind: "claude-desktop", via: "registro", desktop: true },
    envio: { puede: false, motivo: "falta adaptador", transporte: "claude_pipe" as const },
  } : s);
  await abrirTablero(page, lista);
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route(`**/sessions/${SID.mapas}/claude-pipe`, async route => {
    await gate;
    await route.fulfill({ json: { session_id: SID.mapas, command: "old-session-command", expires_at: Date.now() / 1000 + 120, connected: false } });
  });
  await page.locator(`.card[data-sid="${SID.mapas}"] .title`).dblclick();
  await page.getByRole("button", { name: "Conectar esta sesión Claude" }).click();
  await page.getByRole("button", { name: "cerrar panel" }).click();
  await page.locator(`.card[data-sid="${SID.capas}"] .title`).dblclick();
  release();
  await expect(page.getByRole("button", { name: "Conectar esta sesión Claude" })).toBeEnabled();
  await expect(page.getByLabel("Comando público para conectar Claude")).toHaveCount(0);
});

for (const agent of ["claude", "codex"] as const) {
  test(`${agent} Desktop puede dejar de coordinar aunque pierda su canal`, async ({ page }) => {
    const lista = sesiones().map(s => s.session_id === SID.coordinadora ? {
      ...s, agent, no_console: true, pid: agent === "claude" ? 321 : null,
      external: { kind: `${agent}-desktop`, via: agent === "claude" ? "registro" : "rollout", desktop: true },
      envio: { puede: false, motivo: "desconectado", transporte: null },
    } : s);
    await abrirTablero(page, lista);
    let body: unknown;
    await page.route(`**/sessions/${SID.coordinadora}/coordinator`, async route => {
      body = route.request().postDataJSON();
      await route.fulfill({ json: { ok: true, coordinator: false } });
    });
    const card = page.locator(`.card[data-sid="${SID.coordinadora}"]`);
    await card.locator(".kebab").click();
    await card.getByRole("menuitem", { name: /Quitarle el rol de coordinadora/ }).click();
    await expect.poll(() => body).toEqual({ on: false });
  });
}
