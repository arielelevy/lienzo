import { test, expect } from "@playwright/test";
import { abrirTablero, sesiones, SID } from "./tablero-fijo";

test("historial parcial expone límites y nunca dice en curso", async ({ page }) => {
  const lista = sesiones().map(s => s.session_id === SID.mapas ? {
    ...s, agent: "antigravity" as const, source: "sweep" as const, transcript_path: null,
  } : s);
  await abrirTablero(page, lista);
  await page.route(`**/sessions/${SID.mapas}/digest*`, route => route.fulfill({ json: {
    meta: { history_only: true }, has_more: false,
    note: "Historial parcial de SQLite. Fin de turno sin confirmar.",
    turns: [{ id: "synthetic", ended: false, history_only: true, prompt: "Pedido sintético",
      final: "Respuesta sintética", says: [], files: [], commands: [], errors: [], questions: [], tools: 0, reads: 0 }],
  } }));
  await page.locator(`.card[data-sid="${SID.mapas}"] .title`).dblclick();
  const panel = page.locator(".panel");
  await expect(panel.getByText("Respuesta sintética", { exact: true })).toBeVisible();
  await expect(panel.getByText(/Historial parcial de SQLite/)).toBeVisible();
  await expect(panel.locator(".ts")).toContainText("fin sin confirmar");
  await expect(panel.locator(".ts")).not.toContainText("en curso");
  await expect(panel.getByText(/avisarme cuando termine/)).toHaveCount(0);
});

test("identidad ambigua muestra motivo y no promete historial", async ({ page }) => {
  const lista = sesiones().map(s => s.session_id === SID.mapas ? {
    ...s, agent: "antigravity" as const, source: "sweep" as const, transcript_path: null,
  } : s);
  await abrirTablero(page, lista);
  await page.route(`**/sessions/${SID.mapas}/digest*`, route => route.fulfill({ json: {
    meta: { error: "ambiguous_conversation" }, turns: [], has_more: false,
    note: "Historial no disponible: ambiguous_conversation. Fin de turno sin confirmar.",
  } }));
  await page.locator(`.card[data-sid="${SID.mapas}"] .title`).dblclick();
  await expect(page.locator(".panel .empty")).toContainText("ambiguous_conversation");
  await expect(page.locator(".panel .dg")).toHaveCount(0);
});
