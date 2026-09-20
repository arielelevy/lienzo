import { expect, test } from "@playwright/test";
import type { Session } from "../src/types";
import { BASE, SID, bloquearEscrituras, instalarTablero, sesiones } from "./tablero-fijo";

test("Pi sin extension activa explica como vincular el log", async ({ page }) => {
  await bloquearEscrituras(page);
  const cards = sesiones();
  Object.assign(cards.find((s) => s.session_id === SID.mapas)!, {
    agent: "pi", source: "sweep", hooked: false, transcript_path: null, last_prompt: "", last_reply: "",
  });
  await instalarTablero(page, cards);
  await page.route(`**/sessions/${SID.mapas}/digest*`, (route) => route.fulfill({
    contentType: "application/json", body: JSON.stringify({ turns: [], has_more: false, note: "sin transcripcion" }),
  }));
  await page.goto(BASE);
  await page.locator(`.card[data-sid="${SID.mapas}"] .title`).dblclick();
  const panel = page.locator(".panel");
  await expect(panel.getByRole("status")).toContainText("Pi detectado");
  await expect(panel.getByRole("status")).toContainText("/reload");
  await expect(panel.getByRole("status")).toContainText("--pi-only");
  await expect(panel).not.toContainText("Esta sesión todavía no recibió pedidos");
  await expect(panel.locator(".send .quick button")).toHaveCount(0);
});

const pairs: [Session["agent"], Session["agent"]][] = [["pi", "claude"], ["pi", "codex"], ["claude", "pi"], ["codex", "pi"]];
for (const [origin, destination] of pairs) {
  test(`copiar y pegar trabajo ${origin} → ${destination}`, async ({ page }) => {
    await bloquearEscrituras(page);
    const cards = sesiones();
    cards.find((s) => s.session_id === SID.mapas)!.agent = origin;
    cards.find((s) => s.session_id === SID.coordinadora)!.agent = destination;
    await instalarTablero(page, cards);
    const sends: Record<string, unknown>[] = [];
    await page.route(`**/sessions/${SID.coordinadora}/send`, async (route) => {
      sends.push(route.request().postDataJSON());
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ chars: 100, interrupted: false }) });
    });
    await page.goto(BASE);
    await page.locator(`.card[data-sid="${SID.mapas}"]`).focus();
    await page.keyboard.press("Control+c");
    await expect(page.getByText(/Trabajo copiado\./)).toBeVisible();
    await page.locator(`.card[data-sid="${SID.coordinadora}"]`).focus();
    await page.keyboard.press("Control+v");
    const dialog = page.getByRole("dialog", { name: "Pegar trabajo", exact: true });
    await expect(dialog.getByRole("textbox", { name: "Trabajo a enviar" })).toHaveValue(/gold.viajes/);
    await dialog.getByRole("button", { name: "Enviar y detener origen" }).click();
    await expect(dialog).toHaveCount(0);
    expect(sends).toHaveLength(1);
    expect(sends[0]).toMatchObject({ from: SID.mapas, copycat: true, stop_origin: true, text: expect.stringContaining("gold.viajes") });
  });
}
