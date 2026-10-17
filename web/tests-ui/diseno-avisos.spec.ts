import { expect, test } from "@playwright/test";
import type { Session } from "../src/types";
import { BASE, SID, instalarTablero, sesiones } from "./tablero-fijo";

for (const estado of ["encolado", "sin_confirmacion"] as const) {
  test(`aviso solicitado queda armado con envío ${estado}, sin afirmar entrega`, async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("lienzo.send.notifyme", "1"));
    const lista = sesiones().map((s): Session => s.session_id === SID.capas ? {
      ...s, agent: "codex", no_console: true, pending_id: null, needs: null, stopped_by: null,
      external: { kind: "codex-desktop", via: "rollout", desktop: true },
      envio: { puede: true, motivo: null, transporte: "codex_queue" },
    } : s.session_id === SID.coordinadora ? { ...s, coordinator: true } : s);
    await instalarTablero(page, lista);
    let sends = 0;
    const rules: unknown[] = [];
    await page.route("**/rules", async route => {
      if (route.request().method() === "POST") {
        rules.push(route.request().postDataJSON());
        await route.fulfill({ json: { ok: true } });
      } else {
        await route.fulfill({ json: [] });
      }
    });
    await page.route(`**/sessions/${SID.capas}/send`, async route => {
      sends++;
      await route.fulfill({ json: { ok: true, chars: 4, estado, envio_id: "fixture-id", transporte: "codex_queue" } });
    });
    await page.goto(BASE);
    await page.locator(`.card[data-sid="${SID.capas}"] .title`).dblclick();
    const panel = page.locator(".panel");
    await panel.locator("textarea").last().fill("hola");
    await panel.getByRole("button", { name: "Enviar", exact: true }).click();
    await expect.poll(() => rules.length).toBe(1);
    expect(rules[0]).toMatchObject({ kind: "on_stop", from: SID.capas, repeat: true });
    expect(sends).toBe(1);
    await expect(page.getByText("Entregado", { exact: true })).toHaveCount(0);
  });
}
