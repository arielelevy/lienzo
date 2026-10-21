import { expect, test, type Page, type Route } from "@playwright/test";
import { BASE, bloquearEscrituras, instalarTablero } from "./tablero-fijo";

// Frente C, lote 8: Buscar pagina sobre la foto fija del servidor. Las páginas siguientes mandan el
// token; 409/410 se muestran como error; sin foto, el motivo se avisa con role=status. Nada escribe.
const node = (texto: string, extra: Record<string, unknown> = {}) => ({ id: "n-" + texto, tipo: "hallazgo", texto, estado: "propuesto",
  autor: "f", datos: {}, origen: {}, fecha: "2026-10-20T00:00:00Z", ronda: null, procedencia: ["tema"], puntaje: null, puesto: null,
  salto: 0, vinculos: [], ...extra });
const page = (offset: number, foto: unknown, candidatos = [node("Página " + offset)], extra: Record<string, unknown> = {}) => ({
  proyecto: "lienzo", consultas: ["alfa"], temas_sin_resolver: [], total: 101, offset, limite: 100,
  siguientes: offset === 0 ? 100 : null, candidatos, foto, ...extra });
const FOTO = { token: "tok-1", hasta_seq: 7, ids: 101, vence_en_s: 600 };
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

async function open(page_: Page, preguntar: (params: URLSearchParams, route: Route) => Promise<void> | void) {
  const seen: URLSearchParams[] = [];
  await bloquearEscrituras(page_);
  await instalarTablero(page_);
  await page_.route("**/conocimiento/**", route => {
    const url = new URL(route.request().url());
    if (route.request().method() !== "GET") return route.fulfill({ status: 403, body: "{}" });
    if (url.pathname === "/conocimiento/proyectos") return json(route, [{ id: "lienzo", nombre: "Lienzo" }, { id: "demo", nombre: "Demo" }]);
    if (url.pathname.endsWith("/temas")) return json(route, { temas: [] });
    if (url.pathname.endsWith("/preguntar")) { seen.push(url.searchParams); return preguntar(url.searchParams, route); }
    return json(route, {});
  });
  await page_.goto(BASE);
  await page_.getByRole("button", { name: "más opciones", exact: true }).click();
  await page_.getByRole("menuitem", { name: /Memoria/ }).click();
  await page_.getByLabel("Proyecto", { exact: true }).selectOption("lienzo");
  await page_.getByRole("button", { name: "Buscar", exact: true }).first().click();
  await page_.getByLabel("Consultas, una por línea").fill("alfa");
  await page_.getByRole("button", { name: "Buscar", exact: true }).last().click();
  return seen;
}
const more = (p: Page) => p.getByRole("button", { name: "Más resultados", exact: true });

test("las páginas siguientes mandan el token de la foto y marcan lo que cambió después", async ({ page: p }) => {
  const seen = await open(p, (params, route) => {
    const offset = Number(params.get("offset"));
    return json(route, page(offset, FOTO, offset ? [node("Página 100", { cambio_despues_de_la_foto: true })] : undefined));
  });
  await expect(p.getByText("Página 0", { exact: true })).toBeVisible();
  expect(seen[0].get("foto")).toBeNull();
  await more(p).click();
  await expect(p.getByText("Página 100", { exact: true })).toBeVisible();
  expect(seen.at(-1)!.get("foto")).toBe("tok-1");
  expect(seen.at(-1)!.get("offset")).toBe("100");
  await expect(p.getByText("Cambió después de la búsqueda", { exact: true })).toBeVisible();
  await p.getByRole("button", { name: "Anterior", exact: true }).click();
  await expect(p.getByText("Página 0", { exact: true })).toBeVisible();
  expect(seen.at(-1)!.get("foto")).toBe("tok-1");
  await expect(p.getByText("Cambió después de la búsqueda", { exact: true })).toHaveCount(0);
});

test("una foto vencida (410) se muestra como error y no como página vacía", async ({ page: p }) => {
  await open(p, (params, route) => Number(params.get("offset"))
    ? json(route, { error: "la foto de la busqueda vencio o no existe; repeti la busqueda" }, 410)
    : json(route, page(0, FOTO)));
  await more(p).click();
  await expect(p.getByRole("alert")).toContainText("la foto de la busqueda vencio");
  await expect(p.getByText("Sin resultados en esta página")).toHaveCount(0);
});

test("sin foto el motivo se avisa con role=status y la página siguiente no inventa un token", async ({ page: p }) => {
  const motivo = "demasiados candidatos para fijar una foto (5000); afina la consulta: las paginas siguientes se recalculan";
  const seen = await open(p, (params, route) => json(route, page(Number(params.get("offset")), null, undefined, { foto_motivo: motivo })));
  await expect(p.getByRole("status").filter({ hasText: "demasiados candidatos" })).toHaveText(motivo);
  await more(p).click();
  await expect(p.getByText("Página 100", { exact: true })).toBeVisible();
  expect(seen.at(-1)!.get("foto")).toBeNull();
});

test("una foto con formato inválido es un error de formato", async ({ page: p }) => {
  await open(p, (_, route) => json(route, page(0, { token: "", hasta_seq: 1, ids: 1, vence_en_s: 1 })));
  await expect(p.getByRole("alert")).toContainText("foto");
  await expect(p.getByText("Página 0", { exact: true })).toHaveCount(0);
});

test("la página tardía se descarta al cancelar y al cambiar de proyecto", async ({ page: p }) => {
  let release!: () => void;
  let delay = true;
  const pending = new Promise<void>(resolve => { release = resolve; });
  const seen = await open(p, async (params, route) => {
    const offset = Number(params.get("offset"));
    if (offset && delay) await pending;
    return json(route, page(offset, FOTO));
  });
  await expect(p.getByText("Página 0", { exact: true })).toBeVisible();
  await more(p).click();
  await expect.poll(() => seen.length).toBe(2);
  await p.getByRole("button", { name: "Cancelar consulta" }).click();
  release();
  await p.waitForTimeout(200);
  await expect(p.getByText("Página 100", { exact: true })).toHaveCount(0);
  delay = false;
  await p.getByRole("button", { name: "Buscar", exact: true }).last().click();
  await expect(p.getByText("Página 0", { exact: true })).toBeVisible();
  let again!: () => void;
  const late = new Promise<void>(resolve => { again = resolve; });
  await p.unroute("**/conocimiento/**");
  await p.route("**/conocimiento/**", async route => {
    const url = new URL(route.request().url());
    if (url.pathname === "/conocimiento/proyectos") return json(route, [{ id: "lienzo", nombre: "Lienzo" }, { id: "demo", nombre: "Demo" }]);
    if (url.pathname.endsWith("/temas")) return json(route, { temas: [] });
    if (url.pathname.endsWith("/preguntar")) { await late; return json(route, page(100, FOTO)); }
    return json(route, {});
  });
  await more(p).click();
  await p.getByLabel("Proyecto", { exact: true }).selectOption("demo");
  again();
  await p.waitForTimeout(200);
  await expect(p.getByText("Página 100", { exact: true })).toHaveCount(0);
});
