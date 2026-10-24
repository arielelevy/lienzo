// Corre cada web/src/*.test.ts con node --experimental-strip-types, uno por uno.
// Imprime ok o FALLA por archivo y sale con código 1 si alguno falla.
import { spawnSync } from "node:child_process";
import { readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const srcDir = fileURLToPath(new URL("../src", import.meta.url));
const tests = readdirSync(srcDir).filter((f) => f.endsWith(".test.ts")).sort();

let failed = 0;
for (const file of tests) {
  const r = spawnSync(process.execPath, ["--experimental-strip-types", join(srcDir, file)], {
    cwd: srcDir,
    encoding: "utf8",
  });
  if (r.status === 0) {
    console.log(`ok ${file}`);
  } else {
    failed++;
    console.log(`FALLA ${file}`);
    const out = `${r.stdout || ""}${r.stderr || ""}`.trim();
    if (out) console.log(out);
  }
}
console.log(`${tests.length - failed}/${tests.length} archivos en ok`);
process.exit(failed ? 1 : 0);
