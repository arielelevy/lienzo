import { expect, test } from "@playwright/test";
import { abrirTablero, esperarQuietud, sesiones } from "./tablero-fijo";
import { crucesDeFlechas } from "./medidas";

for (const width of [1440, 390]) {
  test(`grupos por proyecto, persistencia y vuelta al orden habitual a ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const seeds = sesiones().filter(s => ["t1", "t2", "t3", "t4", "t5", "t6"].includes(s.session_id));
    seeds.find(s => s.session_id === "t3")!.coordinator = true;
    seeds.find(s => s.session_id === "t5")!.repo = "lienzo";
    await abrirTablero(page, seeds);
    await expect(page.locator(".project-cluster")).toHaveCount(0);
    await page.getByRole("button", { name: "Por proyecto", exact: true }).click();
    await expect(page.locator(".project-cluster")).toHaveCount(3);
    await esperarQuietud(page);
    const groups = await page.locator(".project-cluster").evaluateAll(nodes => nodes.map(node => {
      const r = node.getBoundingClientRect();
      const cards = [...node.querySelectorAll<HTMLElement>(".card")].map(c => {
        const b = c.getBoundingClientRect();
        return { sid: c.dataset.sid, x: b.x, y: b.y, right: b.right, bottom: b.bottom, width: b.width };
      });
      return { name: node.getAttribute("aria-label"), x: r.x, y: r.y, right: r.right, bottom: r.bottom, cards };
    }));
    for (const [name, coord] of [["lienzo", "t1"], ["demo", "t3"]]) {
      const group = groups.find(g => g.name === name)!;
      expect(group).toBeTruthy();
      expect(group.cards.map(c => c.sid).sort()).toEqual((name === "lienzo" ? [coord, "t2", "t5"] : [coord, "t4"]).sort());
      const c = group.cards.find(c => c.sid === coord)!;
      for (const card of group.cards.filter(card => card.sid !== coord)) expect(c.y - card.bottom).toBeGreaterThanOrEqual(40);
      expect(c.x).toBeGreaterThan(group.x);
      expect(c.right).toBeLessThan(group.right);
      expect(c.bottom).toBeLessThanOrEqual(group.bottom);
    }
    if (width === 1440) {
      expect(Math.abs(groups[0].y - groups[1].y)).toBeLessThan(2);
      expect(groups[1].x).toBeGreaterThan(groups[0].right);
    } else {
      for (let i = 1; i < groups.length; i++) expect(groups[i].y).toBeGreaterThan(groups[i - 1].bottom);
    }
    expect(groups.find(g => g.name === "teorema")!.cards.map(c => c.sid)).toEqual(["t6"]);
    expect(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - innerWidth))).toBe(0);
    // El tablero actual oculta las flechas debajo de 900 px (Arrows.tsx).
    if (width >= 900) {
      const arrows = await crucesDeFlechas(page);
      expect(arrows.flechas).toBeGreaterThan(2);
      expect(arrows.cruces).toEqual([]);
    }
    await page.screenshot({ path: testInfo.outputPath(`cluster-${width}.png`), fullPage: true });
    await page.reload();
    await expect(page.getByRole("button", { name: "Por proyecto", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator(".project-cluster")).toHaveCount(3);
    await page.getByRole("button", { name: "Orden habitual", exact: true }).click();
    await expect(page.locator(".project-cluster")).toHaveCount(0);
    await expect(page.locator(".board .col")).toHaveCount(3);
    await page.reload();
    await expect(page.getByRole("button", { name: "Orden habitual", exact: true })).toHaveAttribute("aria-pressed", "true");
    expect(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - innerWidth))).toBe(0);
  });
}

test("sin coordinadora no inventa una estrella y el filtro no deja grupos vacíos", async ({ page }) => {
  await abrirTablero(page, sesiones().filter(s => ["t2", "t4"].includes(s.session_id)));
  await page.getByRole("button", { name: "Por proyecto", exact: true }).click();
  await expect(page.locator(".project-cluster")).toHaveCount(2);
  await expect(page.getByRole("img", { name: "coordinadora del repo", exact: true })).toHaveCount(0);
  await page.getByRole("searchbox").fill("proyecto-inexistente-W");
  await expect(page.locator(".project-cluster")).toHaveCount(0);
  await page.getByRole("searchbox").fill("");
  await expect(page.locator(".project-cluster")).toHaveCount(2);
});
