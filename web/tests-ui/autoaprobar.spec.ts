import { expect, test } from "@playwright/test";
import { abrirTablero, BASE, bloquearEscrituras, instalarTablero, sesiones } from "./tablero-fijo";

/** Auto-aprobar TODO (peligroso) y los permisos denegados: lo que tiene que verse sí o sí. */

test("con auto-aprobar prendido hay una barra negra arriba y su switch del menú va en rojo", async ({ page }) => {
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

test("«Autorizar y que reintente» le avisa a la PC dueña que lo autorizó, para que deje de mostrarlo", async ({ page }) => {
  const lista = sesiones();
  lista[0] = { ...lista[0], last_denied: { tool: "Bash", detalle: "node cdp.mjs click", motivo: "auto mode", fuente: "transcript" } };
  await abrirTablero(page, lista);
  let cuerpo: Record<string, unknown> | undefined;
  await page.route(`**/sessions/${lista[0].session_id}/send`, async route => {
    cuerpo = route.request().postDataJSON();
    await route.fulfill({ status: 200, contentType: "application/json", body: '{"chars":10}' });
  });
  await page.locator(`.card[data-sid="${lista[0].session_id}"] .needs.denied`).getByRole("button", { name: "Autorizar y que reintente" }).click();
  await expect.poll(() => cuerpo).toBeTruthy();
  expect(cuerpo).toMatchObject({ autoriza_denegado: true, attachments: [] });
  expect(String(cuerpo!.text)).toContain("node cdp.mjs click");
});

test("si el auto-aprobar vio el diálogo y no lo contesta, la tarjeta dice por qué", async ({ page }) => {
  const lista = sesiones();
  lista[0] = {
    ...lista[0],
    state: "te_necesita",
    needs: { kind: "dialog", detail: "Switch model?", where: "terminal", since: "2026-10-08T12:00:00-03:00" },
    dialog: { question: "Switch model?", detail: "", options: [{ n: 1, text: "Default" }, { n: 2, text: "Opus" }], selected: 1 },
    auto_aprobar_omitido: "el cambio de modelo lo decide el humano",
  };
  await abrirTablero(page, lista);
  const bloque = page.locator(".card .needs.tui").first();
  await expect(bloque).toContainText("Espera que elijas en la terminal");
  await expect(bloque.locator(".auto-omitido")).toContainText("auto-aprobar no lo contesta: el cambio de modelo lo decide el humano");
});

test("sin motivo, la tarjeta del diálogo no inventa ningún aviso", async ({ page }) => {
  const lista = sesiones();
  lista[0] = {
    ...lista[0],
    state: "te_necesita",
    needs: { kind: "dialog", detail: "Switch model?", where: "terminal", since: "2026-10-08T12:00:00-03:00" },
    dialog: { question: "Switch model?", detail: "", options: [{ n: 1, text: "Default" }, { n: 2, text: "Opus" }], selected: 1 },
  };
  await abrirTablero(page, lista);
  await expect(page.locator(".card .needs.tui").first()).toContainText("Espera que elijas en la terminal");
  await expect(page.locator(".auto-omitido")).toHaveCount(0);
});

