import { expect, test } from "@playwright/test";
import { abrirTablero, SID, sesiones } from "./tablero-fijo";

for (const agent of ["codex", "claude"] as const) for (const desktop of [false, true]) {
  test(`${agent} ${desktop ? "Desktop" : "CLI"}: elegir coordinadora y cablear avisos`, async ({ page }) => {
    const lista = sesiones().filter(s => [SID.coordinadora, SID.flechas].includes(s.session_id));
    const coordinadora = lista.find(s => s.session_id === SID.coordinadora)!;
    coordinadora.agent = agent;
    coordinadora.coordinator = false;
    if (desktop) {
      coordinadora.pid = agent === "claude" ? 321 : null;
      coordinadora.no_console = true;
      coordinadora.external = { kind: `${agent}-desktop`, via: agent === "codex" ? "rollout" : "registro", desktop: true };
      coordinadora.envio = { puede: true, motivo: null, transporte: agent === "codex" ? "codex_queue" : "claude_pipe" };
    }
    await abrirTablero(page, lista);
    const cambios: unknown[] = [];
    const reglas: unknown[] = [];
    await page.route(`**/sessions/${SID.coordinadora}/coordinator`, async route => {
      cambios.push(route.request().postDataJSON());
      await route.fulfill({ json: { ok: true, coordinator: true } });
    });
    await page.route(`**/sessions/${SID.flechas}/send`, route => route.fulfill({ json: { ok: true } }));
    await page.route("**/rules", async route => {
      if (route.request().method() === "POST") {
        reglas.push(route.request().postDataJSON());
        await route.fulfill({ json: { ok: true } });
      } else await route.fulfill({ json: [] });
    });
    const card = page.locator(`.card[data-sid="${SID.coordinadora}"]`);
    await card.locator(".kebab").click();
    await card.getByRole("menuitem", { name: /Coordinadora del repo/ }).click();
    await expect.poll(() => cambios).toEqual([{ on: true }]);
    await page.locator(`.card[data-sid="${SID.flechas}"] .title`).dblclick();
    const panel = page.locator(".panel");
    await panel.getByRole("checkbox", { name: /avisarme cuando termine/ }).check();
    await panel.locator("textarea").last().fill("Continuá");
    await panel.getByRole("button", { name: "Enviar", exact: true }).click();
    await expect.poll(() => reglas).toEqual([expect.objectContaining({
      kind: "on_stop", from: SID.flechas, to: SID.coordinadora, repeat: true,
      text: expect.stringContaining("{respuesta}"),
    })]);
  });
}
