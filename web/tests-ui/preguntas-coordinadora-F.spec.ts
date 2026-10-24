import { expect, test } from "@playwright/test";
import { BASE, SID, bloquearEscrituras, esperarQuietud, instalarTablero, sesiones } from "./tablero-fijo";

test("la tarjeta muestra coordinadora consultada y respuesta", async ({ page }) => {
  await bloquearEscrituras(page);
  const cards = sesiones().map((s) => s.session_id === SID.pregunta ? {
    ...s,
    consulta_coordinadora: { titulo: "★ prueba F", a: "coord-F" },
    respuesta_coordinadora: { por: "★ prueba F", texto: "VERDE", at: new Date().toISOString() },
  } : s);
  await instalarTablero(page, cards);
  await page.goto(BASE);
  await esperarQuietud(page);
  const card = page.locator(`.card[data-sid="${SID.pregunta}"]`);
  await expect(card.getByRole("status").filter({ hasText: "consultada a la coordinadora «★ prueba F»" })).toBeVisible();
  await expect(card.getByRole("status").filter({ hasText: "★ prueba F eligió: VERDE" })).toBeVisible();
});
