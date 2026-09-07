import { defineConfig, devices } from "@playwright/test";
import { BASE } from "./tablero-fijo";

/** Las pruebas de interfaz corren contra el server que ya está levantado en el 7321: no lo
 *  arrancan ni lo reinician (hay sesiones de verdad colgando de él). `global-setup.ts` avisa con
 *  una línea si no contesta. `LIENZO_URL` apunta a otro lado si hace falta. */
export default defineConfig({
  testDir: ".",
  globalSetup: "./global-setup.ts",
  // las trazas de una corrida fallida van adentro de node_modules, que ya está en .gitignore: si
  // fueran a web/test-results, cada corrida dejaría archivos sin seguir en `git status`
  outputDir: "../node_modules/.playwright-artifacts",
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: true,
  workers: process.env.CI ? 2 : 4,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: BASE,
    viewport: { width: 1440, height: 900 },
    // el tablero se mide en píxeles: un factor de escala distinto cambiaría los números
    deviceScaleFactor: 1,
    locale: "es-AR",
    timezoneId: "America/Argentina/Buenos_Aires",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 } }],
});
