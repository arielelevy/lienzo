import { expect, test } from "@playwright/test";
import { abrirTablero, BASE, bloquearEscrituras, instalarTablero, sesiones } from "./tablero-fijo";

/** Auto-aprobar TODO (peligroso) y los permisos denegados: lo que tiene que verse sí o sí. */

test("con auto-aprobar prendido hay una barra negra arriba y el check del menú se ve en negro", async ({ page }) => {
  await bloquearEscrituras(page);
  await instalarTablero(page);
  // registrada DESPUES del tablero fijo, asi que gana (Playwright prueba de la ultima a la primera)
  await page.route("**/config", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ auto_continue: false, auto_retry: false, auto_aprobar: true }) }),
  );
  await page.goto(BASE);
  await expect(page.locator(".auto-aprobar-aviso")).toContainText("AUTO-APROBAR TODO prendido");
  await page.getByRole("button", { name: "más opciones" }).click();
  const check = page.getByRole("menuitemcheckbox", { name: /Auto-aprobar TODO/ });
  await expect(check).toHaveClass(/danger/);
  await expect(check).toHaveAttribute("aria-checked", "true");
});

test("apagado no hay barra", async ({ page }) => {
  await abrirTablero(page);
  await expect(page.locator(".auto-aprobar-aviso")).toHaveCount(0);
});

test("un permiso denegado por una regla se ve en la tarjeta con su comando", async ({ page }) => {
  const lista = sesiones();
  lista[0] = { ...lista[0], last_denied: { tool: "Bash", detalle: "git push --force", motivo: "comando que pide confirmación", fuente: "coda" } };
  await abrirTablero(page, lista);
  const bloque = page.locator(".card .needs.denied").first();
  await expect(bloque).toContainText("Denegado: Bash");
  await expect(bloque).toContainText("git push --force");
});
