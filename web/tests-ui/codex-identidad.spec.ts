import { expect, test } from "@playwright/test";
import { BASE, SID, bloquearEscrituras, instalarTablero, sesiones } from "./tablero-fijo";

for (const state of ["corriendo", "termino"] as const) {
  test(`Codex sin transcripción explica identidad pendiente (${state})`, async ({ page }) => {
    await bloquearEscrituras(page);
    const cards = sesiones();
    Object.assign(cards.find(s => s.session_id === SID.mapas)!, {
      agent: "codex", source: "sweep", state, hooked: false, transcript_path: null, last_prompt: "", last_reply: "",
    });
    await instalarTablero(page, cards);
    await page.route(`**/sessions/${SID.mapas}/digest*`, route => route.fulfill({
      json: { turns: [], has_more: false, note: "sin transcripcion" },
    }));
    await page.goto(BASE);
    await page.locator(`.card[data-sid="${SID.mapas}"] .title`).dblclick();
    const panel = page.locator(".panel");
    await expect(panel.getByRole("status")).toContainText("todavía no identificó su conversación");
    await expect(panel).not.toContainText("Esta sesión todavía no recibió pedidos");
    await page.screenshot({ path: test.info().outputPath(`codex-identidad-${state}.png`) });
  });
}
