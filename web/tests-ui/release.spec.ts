import { expect, test } from "@playwright/test";
import { BASE, bloquearEscrituras, instalarTablero } from "./tablero-fijo";

for (const width of [1440, 320]) {
  test(`la versión queda abajo a la izquierda sin tapar las cuotas (${width}px)`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route("**/cuotas*", route => route.fulfill({ json: {
      claude: { ok: true, five_hour: null, weekly: { used_pct: 20 }, read_at: "2026-10-17T15:00:00Z" },
      codex: { ok: true, five_hour: null, weekly: { used_pct: 30 }, read_at: "2026-10-17T15:00:00Z" },
      sugerido: "claude", motivo: "fixture de disposición",
    } }));
    await bloquearEscrituras(page);
    await instalarTablero(page);
    await page.goto(BASE);
    const version = page.getByRole("complementary", { name: "Versión de Lienzo" });
    await expect(version).toHaveText(/^v\d+\.\d+\.\d+(?:[-+][\w.-]+)?$/);
    await expect(page.getByRole("group", { name: "Cuotas de Claude, Codex y Kiro" })).toBeVisible();
    const badge = await version.boundingBox();
    const quotas = await page.locator(".cuotas").boundingBox();
    expect(badge).not.toBeNull();
    expect(quotas).not.toBeNull();
    expect(badge!.x).toBeLessThan(width / 4);
    expect(badge!.y).toBeGreaterThan(450);
    const overlap = badge!.x < quotas!.x + quotas!.width && badge!.x + badge!.width > quotas!.x
      && badge!.y < quotas!.y + quotas!.height && badge!.y + badge!.height > quotas!.y;
    expect(overlap).toBe(false);
    await page.screenshot({ path: testInfo.outputPath("release.png") });
  });
}
