// Lo común a todas las figuras: encuentra el kit de la skill anatomy y escribe las salidas.
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
export const REPO = resolve(HERE, "..", "..");
// Las pruebas los apuntan a una carpeta temporal para no pisar lo versionado.
export const IMG = process.env.LIENZO_INFOGRAFIAS_IMG || join(REPO, "docs", "img", "infografias");
export const PREVIEW = process.env.LIENZO_INFOGRAFIAS_PREVIEW || join(tmpdir(), "lienzo-infografias");

const CANDIDATES = [
  process.env.ANATOMY_DIR,
  join(homedir(), ".claude", "skills", "anatomy"),
  join(homedir(), ".agents", "skills", "anatomy"),
].filter(Boolean);

export const ANATOMY = CANDIDATES.find((dir) => existsSync(join(dir, "kit", "iso-kit.mjs")));
if (!ANATOMY) {
  console.error(`No encuentro la skill anatomy (busqué en ${CANDIDATES.join(", ")}).\nInstalala con git clone https://github.com/wheresryan22/anatomy o fijá ANATOMY_DIR.`);
  process.exit(2);
}

const load = (path) => import(pathToFileURL(join(ANATOMY, path)).href);
export const k = await load("kit/iso-kit.mjs");
export const { tubePieces, tubeSvg } = await load("kit/tube.mjs");

// Escribe el SVG suelto en los dos temas (lo que usa el README) y una página con su tarjeta
// para revisarla en el navegador. Nunca lleva script: las figuras del lienzo son estáticas.
export function write(name, { width, height, label, body, card }) {
  mkdirSync(IMG, { recursive: true });
  mkdirSync(PREVIEW, { recursive: true });
  const written = [];
  for (const theme of ["dark", "light"]) {
    const svg = join(IMG, `${name}-${theme}.svg`);
    writeFileSync(svg, k.figureSvg({ width, height, label, body, standalone: theme }) + "\n");
    const page = join(PREVIEW, `${name}-${theme}.html`);
    const plate = k.plateHtml({ ...card, body: `<div class="iso-stage">${k.figureSvg({ width, height, label, body })}</div>` });
    writeFileSync(page, k.pageHtml({ title: card.title, theme, body: plate, width: width + 80 }));
    written.push(svg, page);
  }
  return written;
}
