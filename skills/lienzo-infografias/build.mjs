// Arma las infografías del lienzo. Uso:
//   node skills/lienzo-infografias/build.mjs [nombre ...] [--check]
// Sin nombres arma todas las de figuras/. Con --check saca capturas en los dos temas y corre el
// chequeo de terminaciones de línea del kit; las capturas quedan en la carpeta de vista previa.
import { spawnSync } from "node:child_process";
import { readdirSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { ANATOMY, PREVIEW } from "./kit.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const check = args.includes("--check");
const flags = args.filter((arg) => arg.startsWith("--") && arg !== "--check");
if (flags.length) {
  console.error(`No conozco ${flags.join(", ")}. La única opción es --check.`);
  process.exit(2);
}
const all = readdirSync(join(HERE, "figuras")).filter((file) => file.endsWith(".mjs")).map((file) => basename(file, ".mjs"));
const names = args.filter((arg) => !arg.startsWith("--"));
const unknown = names.filter((name) => !all.includes(name));
if (unknown.length) {
  console.error(`No existe la figura ${unknown.join(", ")}. Hay: ${all.join(", ")}`);
  process.exit(2);
}

let failed = false;
for (const name of names.length ? names : all) {
  const figure = await import(pathToFileURL(join(HERE, "figuras", `${name}.mjs`)).href);
  for (const path of figure.build()) console.log("escribí", path);
  if (!check) continue;
  for (const theme of ["dark", "light"]) {
    const page = join(PREVIEW, `${name}-${theme}.html`);
    const run = (script, extra) => spawnSync(process.execPath, [join(ANATOMY, "scripts", script), page, ...extra], { encoding: "utf8" });
    const shot = run("capture.mjs", ["--width", "1200", "--out", join(PREVIEW, `${name}-${theme}.png`)]);
    const lines = run("lines.mjs", ["--out", join(PREVIEW, `${name}-${theme}-lines.png`)]);
    const said = (result, pattern) => (result.stdout + result.stderr).split("\n").find((line) => pattern.test(line))?.trim() ?? `salió con ${result.status}`;
    console.log(`${name} ${theme}: ${said(shot, /^console:/)} · ${said(lines, /^line ends:/)}`);
    const shotText = shot.stdout + shot.stderr;
    const clean = /^console: clean$/m.test(shotText) && /scrolls sideways: no/.test(shotText);
    if (!clean) console.log(shotText.trim());
    failed ||= shot.status !== 0 || !clean || lines.status !== 0;
  }
}
process.exit(failed ? 1 : 0);
