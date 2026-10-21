import { expect, test } from "@playwright/test";
import { abrirTablero } from "./tablero-fijo";

const json = (data: unknown) => ({ status: 200, contentType: "application/json", body: JSON.stringify(data) });
const settings = { preferences: { brief: false, rtk: false }, tools: [], scope: "esta PC; nuevas sesiones" };

test("investigación en revisión: revisar, reencolar si quedan inicios y descartar sólo con confirmación", async ({ page }) => {
  await abrirTablero(page);
  await page.route("**/agent-improvements", route => route.fulfill(json(settings)));
  const base = { project: "lienzo", cursor: 0, results: [], kind: "research", runs: [1792540000] };
  const conInicios = { ...base, id: "r1", state: "review", attempts: 1, reason: "ejecución interrumpida", case: { case_key: "c-1", area: "esperas" },
    last_run: { code: 1, stopped: "agentes trabajando o permisos pendientes" } };
  const agotada = { ...base, id: "r2", state: "review", attempts: 2, runs: [1792540000, 1792541000], reason: "intentos agotados; sin reintento automático",
    case: { case_key: "c-2", area: "retrabajo" }, last_run: { code: 1, stopped: "recursos insuficientes o memoria desconocida" } };
  let jobs: object[] = [conInicios, agotada];
  const writes: unknown[] = [];
  await page.route("**/agent-improvements/scheduler", route => {
    if (route.request().method() === "PUT") {
      const data = route.request().postDataJSON();
      if (data.action !== "activity") writes.push(data);
      if (data.action === "requeue_research") jobs = jobs.map(j => (j as { id: string }).id === data.job
        ? { ...j, state: "queued", reason: "reencolado por el usuario; conserva intentos 1 de 2", history: [{ at: 1792542000, from: "review", to: "queued", reason: "ejecución interrumpida" }] } : j);
      if (data.action === "dismiss_research") jobs = jobs.map(j => (j as { id: string }).id === data.job
        ? { ...j, state: "cancelled", reason: "descartado por el usuario tras revisión" } : j);
    }
    return route.fulfill(json({ enabled: true, reason: "quieto", projects: [{ id: "lienzo", name: "Lienzo" }], jobs,
      research: { last_evaluation: null, scope: "sólo lectura", note: "sin evaluar en este proceso", ceilings: { max_starts_per_case: 2 } } }));
  });
  await page.locator(".board").dispatchEvent("contextmenu", { clientX: 800, clientY: 600 });
  await page.getByRole("menuitem", { name: "Mejoras de agentes…" }).click();
  const trabajos = page.getByRole("list", { name: "Trabajos" });
  const item = (key: string) => trabajos.getByRole("listitem").filter({ hasText: key });

  await item("c-1").getByText("Revisar", { exact: true }).click();
  await expect(item("c-1").getByText(/Intentos 1 de 2 · corridas 1 · último corte: agentes trabajando/)).toBeVisible();
  await item("c-2").getByText("Revisar", { exact: true }).click();
  await expect(item("c-2").getByText(/Intentos agotados: el caso no se puede reencolar/)).toBeVisible();
  await expect(item("c-2").getByRole("button", { name: "Reencolar investigación" })).toBeDisabled();

  await item("c-1").getByRole("button", { name: "Reencolar investigación" }).click();
  await expect(item("c-1").getByText("lienzo · queued")).toBeVisible();
  await expect(item("c-1").getByText(/conserva intentos 1 de 2/)).toBeVisible();

  page.once("dialog", dialog => void dialog.dismiss());
  await item("c-2").getByRole("button", { name: "Descartar" }).click();
  await expect(item("c-2").getByText("lienzo · review")).toBeVisible();
  page.once("dialog", dialog => void dialog.accept());
  await item("c-2").getByRole("button", { name: "Descartar" }).click();
  await expect(item("c-2").getByText("lienzo · cancelled")).toBeVisible();
  await expect(item("c-2").getByRole("button", { name: "Descartar" })).toHaveCount(0);

  expect(writes).toEqual([{ action: "requeue_research", job: "r1" }, { action: "dismiss_research", job: "r2" }]);
});
