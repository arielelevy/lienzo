import { expect, test, type Page, type Route } from "@playwright/test";
import { BASE, bloquearEscrituras, instalarTablero } from "./tablero-fijo";

// Frente C, lote 7: Buscar muestra cuántas semillas por palabras usó el servidor (encontradas, usadas,
// máximo) y avisa el corte con role=status. Sólo la API de conocimiento usa fixtures; nada escribe.
const node = { id: "h1", tipo: "hallazgo", texto: "Candidato visible", estado: "propuesto", autor: "f", datos: {},
  origen: {}, fecha: "2026-10-20T00:00:00Z", ronda: null, procedencia: ["bm25:alfa"], puntaje: -1, salto: 0, puesto: 1, vinculos: [] };
const answer = (semillas?: unknown) => ({ proyecto: "lienzo", consultas: ["alfa"], temas_sin_resolver: [], total: 1, offset: 0,
  limite: 100, siguientes: null, candidatos: [node], ...(semillas === undefined ? {} : { semillas_lexicas: semillas }) });
const json = (route: Route, body: unknown) => route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });

async function open(page: Page, preguntar: (route: Route) => Promise<void> | void) {
  await bloquearEscrituras(page);
  await instalarTablero(page);
  await page.route("**/conocimiento/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() !== "GET") return route.fulfill({ status: 403, body: "{}" });
    if (path === "/conocimiento/proyectos") return json(route, [{ id: "lienzo", nombre: "Lienzo" }, { id: "demo", nombre: "Demo" }]);
    if (path.endsWith("/temas")) return json(route, { temas: [] });
    if (path.endsWith("/preguntar")) return preguntar(route);
    return json(route, {});
  });
  await page.goto(BASE);
  await page.getByRole("button", { name: "más opciones", exact: true }).click();
  await page.getByRole("menuitem", { name: /Memoria/ }).click();
  await page.getByLabel("Proyecto", { exact: true }).selectOption("lienzo");
  await page.getByRole("button", { name: "Buscar", exact: true }).first().click();
  await page.getByLabel("Consultas, una por línea").fill("alfa");
}
const search = (page: Page) => page.getByRole("button", { name: "Buscar", exact: true }).last().click();

test("el corte de semillas se avisa con role=status y los números del servidor", async ({ page }) => {
  await open(page, route => json(route, answer({ encontradas: 60, usadas: 30, maximo: 30 })));
  await search(page);
  await expect(page.getByText("Candidato visible", { exact: true })).toBeVisible();
  const aviso = page.getByRole("status").filter({ hasText: "Corte de semillas" });
  await expect(aviso).toHaveText("Corte de semillas: se usaron 30 de 60 coincidencias por palabras (máximo 30). Las que quedaron afuera no se descartan: afiná las consultas o sumá temas o archivos.");
});

test("sin corte se informa el conteo sin aviso; sin el dato no se inventa nada", async ({ page }) => {
  let semillas: unknown = { encontradas: 5, usadas: 5, maximo: 30 };
  await open(page, route => json(route, answer(semillas)));
  await search(page);
  await expect(page.getByText("Semillas por palabras: 5 de 5 (máximo 30).", { exact: true })).toBeVisible();
  await expect(page.getByText(/Corte de semillas/)).toHaveCount(0);
  semillas = undefined;  // un server anterior no manda el campo
  await search(page);
  await expect(page.getByText("Candidato visible", { exact: true })).toBeVisible();
  await expect(page.getByText(/Semillas por palabras|Corte de semillas/)).toHaveCount(0);
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("un conteo de semillas inválido es un error de formato, no un aviso", async ({ page }) => {
  await open(page, route => json(route, answer({ encontradas: 3, usadas: 30, maximo: 30 })));
  await search(page);
  await expect(page.getByRole("alert")).toContainText("semillas");
  await expect(page.getByText(/Corte de semillas|Candidato visible/)).toHaveCount(0);
});

test("una respuesta tardía con corte se descarta al cancelar", async ({ page }) => {
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  let count = 0;
  await open(page, async route => {
    count++;
    if (count === 1) { await pending; return json(route, answer({ encontradas: 90, usadas: 30, maximo: 30 })); }
    return json(route, answer({ encontradas: 2, usadas: 2, maximo: 30 }));
  });
  await search(page);
  await expect.poll(() => count).toBe(1);
  await page.getByRole("button", { name: "Cancelar consulta" }).click();
  release();
  await search(page);
  await expect(page.getByText("Semillas por palabras: 2 de 2 (máximo 30).", { exact: true })).toBeVisible();
  await expect(page.getByText(/Corte de semillas/)).toHaveCount(0);
});
