import { expect, test } from "@playwright/test";
import { SID, abrirTablero, sesiones } from "./tablero-fijo";

test("área libre permite lanzar CLI y conserva el formulario si falla", async ({ page }) => {
  await abrirTablero(page);
  const launches: Record<string, unknown>[] = [];
  await page.route("**/sessions/launch", async route => {
    launches.push(route.request().postDataJSON());
    await route.fulfill({ status: launches.length === 1 ? 400 : 200, contentType: "application/json",
      body: JSON.stringify(launches.length === 1 ? { error: "carpeta inexistente" } : { ok: true }) });
  });
  await page.locator(".board").dispatchEvent("contextmenu", { clientX: 800, clientY: 600 });
  await page.getByRole("menuitem", { name: "Lanzar CLI…" }).click();
  const dialog = page.getByRole("dialog", { name: "Lanzar CLI", exact: true });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Proyecto", { exact: true }).selectOption("");
  await expect(dialog.getByRole("button", { name: "Lanzar", exact: true })).toBeDisabled();
  await dialog.getByRole("textbox", { name: "Carpeta", exact: true }).fill("D:/Apps/lienzo");
  await dialog.getByRole("combobox", { name: "Agente", exact: true }).selectOption("codex");
  await dialog.getByRole("button", { name: "Lanzar", exact: true }).click();
  await expect(dialog.getByRole("alert")).toHaveText("carpeta inexistente");
  await expect(dialog.getByRole("textbox", { name: "Carpeta", exact: true })).toHaveValue("D:/Apps/lienzo");
  await dialog.getByRole("button", { name: "Lanzar", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(launches).toHaveLength(2);
  expect(launches[1]).toMatchObject({ cwd: "D:/Apps/lienzo", agent: "codex", title: "" });
});

test("clic derecho en tarjeta no abre lanzamiento y Escape cierra el menú libre", async ({ page }) => {
  await abrirTablero(page);
  await page.locator(`.card[data-sid="${SID.mapas}"]`).click({ button: "right" });
  await expect(page.getByRole("menu", { name: "Área libre" })).toHaveCount(0);
  await page.locator(".board").dispatchEvent("contextmenu", { clientX: 800, clientY: 600 });
  await expect(page.getByRole("menu", { name: "Área libre" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("menu", { name: "Área libre" })).toHaveCount(0);
});

test("lanzamiento elige proyecto activo y conserva su carpeta en la PC elegida", async ({ page }) => {
  await abrirTablero(page);
  let payload: Record<string, unknown> | undefined;
  await page.route("**/sessions/launch", async route => {
    payload = route.request().postDataJSON();
    await route.fulfill({ status: 200, contentType: "application/json", body: '{"ok":true}' });
  });
  await page.locator(".board").dispatchEvent("contextmenu", { clientX: 800, clientY: 600 });
  await page.getByRole("menuitem", { name: "Lanzar CLI…" }).click();
  const dialog = page.getByRole("dialog", { name: "Lanzar CLI", exact: true });
  await dialog.getByLabel("Proyecto", { exact: true }).selectOption({ label: "lienzo" });
  await expect(dialog.getByLabel("Carpeta", { exact: true })).toHaveCount(0);
  await expect(dialog.getByLabel("Título", { exact: true })).toHaveCount(0);
  await dialog.getByRole("button", { name: "Lanzar", exact: true }).click();
  expect(payload).toMatchObject({ cwd: "D:\\Apps\\lienzo", title: "lienzo", agent: "codex" });
});

test("lanzamiento lista arriba las abiertas y permitidas de la PC y, grisadas abajo, las usadas estos días", async ({ page }) => {
  const hoy = new Date();
  const hace = (dias: number) => new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate() - dias, 10).toISOString();
  // solo las tarjetas de lienzo: las demás carpetas del tablero fijo también saldrían como «ahora»
  await abrirTablero(page, sesiones().filter(s => s.repo === "lienzo"), [
    { pc_id: "pcA", name: "Local", color: "#12B886", alive: true, last_seen: hoy.toISOString(), local: true,
      health: { launch_roots: ["D:\\Apps\\chess", "D:\\Apps\\lienzo"], mem_free_gb: null, cpu_pct: null, temp_c: null } },
    { pc_id: "pcB", name: "Remota", color: "#82C91E", alive: true, last_seen: hoy.toISOString(), local: false,
      health: { launch_roots: ["E:\\Repos"], mem_free_gb: null, cpu_pct: null, temp_c: null } },
  ]);
  await page.route("**/recientes*", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([
    { cwd: "D:/Apps/lienzo", repo: "lienzo", pc: "pcA", last: hace(0) }, // ya está arriba: no se repite
    { cwd: "D:\\Apps\\chess\\motor", repo: "motor", pc: "pcA", last: hace(3) },
    { cwd: "C:\\Users\\x\\scratch", repo: "scratch", pc: "pcA", last: hace(1) }, // fuera de las permitidas: no se ofrece
    { cwd: "E:\\Repos\\demo", repo: "demo", pc: "pcB", last: hace(0) },
  ]) }));
  let payload: Record<string, unknown> | undefined;
  await page.route("**/sessions/launch", async route => {
    payload = route.request().postDataJSON();
    await route.fulfill({ status: 200, contentType: "application/json", body: '{"ok":true}' });
  });
  await page.locator(".board").dispatchEvent("contextmenu", { clientX: 800, clientY: 600 });
  await page.getByRole("menuitem", { name: "Lanzar CLI…" }).click();
  const dialog = page.getByRole("dialog", { name: "Lanzar CLI", exact: true });
  const proyecto = dialog.getByLabel("Proyecto", { exact: true });
  // arriba la abierta ahora y después las permitidas, sin repetir lienzo
  await expect(proyecto.locator("optgroup[label='Carpetas'] option")).toHaveText(["lienzo", "chess"]);
  const usadas = proyecto.locator("optgroup.launch-recientes");
  await expect(usadas).toHaveAttribute("label", "Usadas estos días");
  await expect(usadas.locator("option")).toHaveText(["motor · hace 3 días"]);
  // grisadas: el color del grupo es el apagado de la tarjeta, no el del texto normal
  const colores = await usadas.evaluate(g => [getComputedStyle(g).color, getComputedStyle(g.closest("select")!).color]);
  expect(colores[0]).not.toBe(colores[1]);
  await proyecto.selectOption({ label: "motor · hace 3 días" });
  await expect(dialog.getByLabel("Carpeta", { exact: true })).toHaveCount(0);
  await dialog.getByRole("button", { name: "Lanzar", exact: true }).click();
  expect(payload).toMatchObject({ pc: "pcA", cwd: "D:\\Apps\\chess\\motor", title: "motor", agent: "codex" });
});

test("lanzamiento en otra PC muestra sus carpetas y sus recientes, no los de acá", async ({ page }) => {
  const hoy = new Date().toISOString();
  await abrirTablero(page, sesiones().filter(s => s.repo === "lienzo"), [
    { pc_id: "pcA", name: "Local", color: "#12B886", alive: true, last_seen: hoy, local: true,
      health: { launch_roots: ["D:\\Apps\\lienzo"], mem_free_gb: null, cpu_pct: null, temp_c: null } },
    { pc_id: "pcB", name: "Remota", color: "#82C91E", alive: true, last_seen: hoy, local: false,
      health: { launch_roots: ["E:\\Repos"], mem_free_gb: null, cpu_pct: null, temp_c: null } },
  ]);
  await page.route("**/recientes*", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([
    { cwd: "D:\\Apps\\lienzo\\web", repo: "web", pc: "pcA", last: hoy },
    { cwd: "E:\\Repos\\demo", repo: "demo", pc: "pcB", last: hoy },
  ]) }));
  await page.locator(".board").dispatchEvent("contextmenu", { clientX: 800, clientY: 600 });
  await page.getByRole("menuitem", { name: "Lanzar CLI…" }).click();
  const dialog = page.getByRole("dialog", { name: "Lanzar CLI", exact: true });
  const proyecto = dialog.getByLabel("Proyecto", { exact: true });
  await expect(proyecto.locator("optgroup[label='Carpetas'] option")).toHaveText(["lienzo"]);
  await expect(proyecto.locator("optgroup.launch-recientes option")).toHaveText(["web · hoy"]);
  await dialog.getByLabel("PC", { exact: true }).selectOption("pcB");
  await expect(proyecto.locator("optgroup[label='Carpetas'] option")).toHaveText(["Repos"]);
  await expect(proyecto.locator("optgroup.launch-recientes option")).toHaveText(["demo · hoy"]);
  // los proyectos activos acá que esa PC no conoce siguen al final, con carpeta a mano
  await expect(proyecto.locator("optgroup[label='En otras PCs'] option").first()).toHaveText("lienzo");
  // esa PC no tiene lienzo: queda elegida su primera carpeta, sin pedir la ruta a mano
  await expect(proyecto.locator("option:checked")).toHaveText("Repos");
  await expect(dialog.getByLabel("Carpeta", { exact: true })).toHaveCount(0);
});

test("otra PC permite lanzar sin sesión activa y nunca reutiliza la carpeta local", async ({ page }) => {
  await abrirTablero(page, sesiones(), [
    { pc_id: "pcA", name: "Local", color: "#12B886", alive: true, last_seen: new Date().toISOString(), local: true, health: null },
    { pc_id: "pcB", name: "Remota", color: "#82C91E", alive: true, last_seen: new Date().toISOString(), local: false, health: null },
  ]);
  let payload: Record<string, unknown> | undefined;
  await page.route("**/sessions/launch", async route => {
    payload = route.request().postDataJSON();
    await route.fulfill({ status: 200, contentType: "application/json", body: '{"ok":true}' });
  });
  await page.locator(".board").dispatchEvent("contextmenu", { clientX: 800, clientY: 600 });
  await page.getByRole("menuitem", { name: "Lanzar CLI…" }).click();
  const dialog = page.getByRole("dialog", { name: "Lanzar CLI", exact: true });
  await dialog.getByLabel("PC", { exact: true }).selectOption("pcB");
  await expect(dialog.getByLabel("Carpeta", { exact: true })).toHaveValue("");
  await expect(dialog.getByRole("button", { name: "Lanzar", exact: true })).toBeDisabled();
  await dialog.getByLabel("Proyecto", { exact: true }).selectOption({ label: "demo" });
  await expect(dialog.getByLabel("PC", { exact: true })).toHaveValue("pcB");
  await dialog.getByLabel("Carpeta", { exact: true }).fill("E:/Repos/demo");
  await dialog.getByRole("button", { name: "Lanzar", exact: true }).click();
  expect(payload).toMatchObject({ pc: "pcB", cwd: "E:/Repos/demo", title: "demo", agent: "codex" });
});

test("copiar trabajo, editarlo y reintentar un envío fallido", async ({ page }) => {
  await abrirTablero(page);
  const source = page.locator(`.card[data-sid="${SID.mapas}"]`);
  const target = page.locator(`.card[data-sid="${SID.coordinadora}"]`);
  const sends: Record<string, unknown>[] = [];
  await page.route(`**/sessions/${SID.coordinadora}/send`, async (route) => {
    sends.push(route.request().postDataJSON());
    await route.fulfill({ status: sends.length === 1 ? 409 : 200, contentType: "application/json",
      body: JSON.stringify(sends.length === 1 ? { error: "ocupada" } : { chars: 20, interrupted: true }) });
  });
  await source.focus();
  await page.keyboard.press("Control+c");
  await expect(page.getByText(/Trabajo copiado\./)).toBeVisible();
  await target.focus();
  await page.keyboard.press("Control+v");
  const dialog = page.getByRole("dialog", { name: "Pegar trabajo", exact: true });
  await expect(dialog).toBeVisible();
  const text = dialog.getByRole("textbox", { name: "Trabajo a enviar" });
  await expect(text).toHaveValue(/Último pedido:/);
  await expect(text).toHaveValue(/gold.viajes/);
  expect(sends).toHaveLength(0);
  await text.fill("Continuá con el trabajo revisado");
  const enviar = dialog.getByRole("button", { name: "Enviar y detener origen" });
  await enviar.click();
  await expect(page.getByText(/No se pudo pegar el trabajo: ocupada/)).toBeVisible();
  await expect(text).toHaveValue("Continuá con el trabajo revisado");
  await enviar.click();
  await expect(dialog).toHaveCount(0);
  expect(sends).toHaveLength(2);
  // por defecto la copia es copycat y la de origen se detiene (el Esc lo manda el server)
  expect(sends[1]).toEqual({
    from: SID.mapas, text: "Continuá con el trabajo revisado", attachments: [], copycat: true, stop_origin: true,
  });
  await expect(page.getByText(/Trabajo enviado a .*; .* detenida/)).toBeVisible();
});

test("duplicar: la de origen sigue y la copia le manda su informe al terminar, una vez", async ({ page }) => {
  await abrirTablero(page);
  const source = page.locator(`.card[data-sid="${SID.mapas}"]`);
  const target = page.locator(`.card[data-sid="${SID.coordinadora}"]`);
  const sends: Record<string, unknown>[] = [];
  const rules: Record<string, unknown>[] = [];
  await page.route(`**/sessions/${SID.coordinadora}/send`, async (route) => {
    sends.push(route.request().postDataJSON());
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ chars: 20, interrupted: false }) });
  });
  await page.route("**/rules", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    rules.push(route.request().postDataJSON());
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: "r-dup" }) });
  });
  await source.focus();
  await page.keyboard.press("Control+c");
  await expect(page.getByText(/Trabajo copiado\./)).toBeVisible();
  await target.focus();
  await page.keyboard.press("Control+v");
  const dialog = page.getByRole("dialog", { name: "Pegar trabajo", exact: true });
  await dialog.getByRole("checkbox", { name: /Duplicar/ }).check();
  await dialog.getByRole("button", { name: "Duplicar trabajo" }).click();
  await expect(dialog).toHaveCount(0);
  expect(sends).toHaveLength(1);
  expect(sends[0]).toMatchObject({ from: SID.mapas, copycat: true, stop_origin: false });
  // un solo sentido y con tope: la conexion de vuelta la rechaza el server (bucle A<->B)
  expect(rules).toEqual([{
    kind: "on_stop", from: SID.coordinadora, to: SID.mapas, max_fires: 1,
    text: expect.stringContaining("trabajó en paralelo"),
  }]);
  await expect(page.getByText(/su informe va a /)).toBeVisible();
});

test("menú copiar/pegar permite cancelar sin enviar", async ({ page }) => {
  await abrirTablero(page);
  const source = page.locator(`.card[data-sid="${SID.mapas}"]`);
  const target = page.locator(`.card[data-sid="${SID.coordinadora}"]`);
  let sends = 0;
  await page.route("**/sessions/*/send", async (route) => {
    sends++;
    await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });
  await source.locator(".kebab").click();
  await source.getByRole("menuitem", { name: /Copiar trabajo/ }).click();
  await expect(page.getByText(/Trabajo copiado\./)).toBeVisible();
  await target.locator(".kebab").click();
  await target.getByRole("menuitem", { name: /Pegar trabajo/ }).click();
  await page.getByRole("button", { name: "Cancelar", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Pegar trabajo", exact: true })).toHaveCount(0);
  expect(sends).toBe(0);
  await source.locator(".title").dblclick();
  await expect(page.locator(".panel")).toBeVisible();
  await expect(page.locator(".panel").getByRole("button", { name: /^Conversaci[oó]n$/ })).toHaveCount(0);
});
