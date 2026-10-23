import { expect, test } from "@playwright/test";
import { abrirTablero, esperarQuietud, sesiones } from "./tablero-fijo";
import { crucesDeFlechas } from "./medidas";

for (const width of [1440, 390]) {
  test(`columnas con proyectos y orden recordado a ${width}px`, async ({ page }, testInfo) => {
    const seeds = sesiones().filter(s => ["t1", "t2", "t3", "t4", "n1", "n2"].includes(s.session_id));
    seeds.find(s => s.session_id === "t3")!.coordinator = true;
    await abrirTablero(page, seeds);
    await page.setViewportSize({ width, height: 900 });
    await page.getByRole("button", { name: "Por proyecto", exact: true }).click();
    await expect(page.locator(".board > .col")).toHaveCount(3);
    await expect(page.locator(".board-layout")).toHaveCount(0);
    await expect(page.locator(".project-cluster")).toHaveCount(4);
    await esperarQuietud(page);
    for (const [column, ids] of [["trabajo", ["t1", "t2", "t3", "t4"]], ["te_necesita", ["n1", "n2"]]] as const) {
      const col = page.locator(`.board > .col.${column}`);
      expect(await col.locator(".card").evaluateAll(cards => cards.map(c => (c as HTMLElement).dataset.sid).sort())).toEqual([...ids].sort());
      await expect(col.locator(".project-cluster")).toHaveCount(2);
    }
    const groups = await page.locator(".trabajo .project-cluster").evaluateAll(nodes => nodes.map(node => {
      const cards: { sid: string | undefined; y: number; bottom: number }[] = [];
      for (let sibling = node.nextElementSibling; sibling && !sibling.matches(".project-cluster"); sibling = sibling.nextElementSibling) {
        const c = sibling.querySelector<HTMLElement>(".card");
        if (c) cards.push({ sid: c.dataset.sid, y: c.getBoundingClientRect().y, bottom: c.getBoundingClientRect().bottom });
      }
      return cards;
    }));
    for (const coord of ["t3", "t1"]) {
      const group = groups.find(g => g.some(c => c.sid === coord))!;
      expect(group.at(-1)?.sid).toBe(coord);
      if (width >= 900) expect(group.at(-1)!.y - group[0].bottom).toBeGreaterThanOrEqual(26);
    }
    if (width >= 900) {
      const arrows = await crucesDeFlechas(page);
      expect(arrows.flechas).toBeGreaterThan(0);
      expect(arrows.cruces).toEqual([]);
    } else {
      await page.locator(".filters").getByRole("button", { name: /Te necesita/ }).click();
      await expect(page.locator(".te_necesita .card").first()).toBeVisible();
    }
    expect(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - innerWidth))).toBe(0);
    await page.screenshot({ path: testInfo.outputPath(`cluster-${width}.png`), fullPage: true });
    await page.reload();
    await expect(page.getByRole("button", { name: "Por proyecto", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator(".board > .col")).toHaveCount(3);
    await page.getByRole("button", { name: "Orden habitual", exact: true }).click();
    await expect(page.locator(".project-cluster")).toHaveCount(0);
    await page.reload();
    await expect(page.getByRole("button", { name: "Orden habitual", exact: true })).toHaveAttribute("aria-pressed", "true");
    expect(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - innerWidth))).toBe(0);
  });
}

test("grupos sin coordinadora y filtro sin grupos vacíos", async ({ page }) => {
  await abrirTablero(page, sesiones().filter(s => ["t2", "t4"].includes(s.session_id)));
  await page.getByRole("button", { name: "Por proyecto", exact: true }).click();
  await expect(page.locator(".project-cluster")).toHaveCount(2);
  await expect(page.getByRole("img", { name: "coordinadora del repo", exact: true })).toHaveCount(0);
  await page.getByRole("searchbox").fill("inexistente-Z");
  await expect(page.locator(".project-cluster")).toHaveCount(0);
});

for (const notice of ["auto", "envío", "turno"]) test(`aviso ${notice} vencido desaparece de la tarjeta`, async ({ page }) => {
  const seeds = sesiones().filter(s => ["t1", "t2", "t3"].includes(s.session_id));
  const old = new Date(Date.now() - 30 * 60_000).toISOString();
  seeds[0].auto_aprobado = { at: old, que: "permiso-viejo-Z", via: "dialogo" };
  seeds[1].state = "te_necesita";
  seeds[1].needs = { kind: "sin_enviar", since: old, detail: "envío-viejo-Z" };
  seeds[2].last_prompt = "[lienzo] te toca el turno de «motores» (vence a las 10:00). Al terminar, soltalo: DELETE /turnos/motores";
  await abrirTablero(page, seeds);
  if (notice === "auto") await expect(page.getByText("permiso-viejo-Z")).toHaveCount(0);
  if (notice === "envío") await expect(page.getByText("El encargo quedó sin enviar", { exact: false })).toHaveCount(0);
  if (notice === "turno") await expect(page.locator('.card[data-sid="t3"] .prompt')).toHaveCount(0);
});

test("avisos vigentes se ven y caducan sin otro evento del servidor", async ({ page }) => {
  await page.clock.install();
  const seeds = sesiones().filter(s => ["t1", "t2"].includes(s.session_id));
  const recent = new Date().toISOString();
  seeds[0].auto_aprobado = { at: recent, que: "permiso-reciente-Z", via: "dialogo" };
  seeds[1].state = "te_necesita";
  seeds[1].needs = { kind: "sin_enviar", since: recent, detail: "envío-reciente-Z" };
  await abrirTablero(page, seeds);
  await expect(page.getByText("permiso-reciente-Z")).toBeVisible();
  await expect(page.getByText("El encargo quedó sin enviar", { exact: false })).toBeVisible();
  await page.clock.fastForward(190_000);
  await expect(page.getByText("permiso-reciente-Z")).toHaveCount(0);
  await expect(page.getByText("El encargo quedó sin enviar", { exact: false })).toHaveCount(0);
});
