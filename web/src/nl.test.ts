/** Tests del parser de frases. Sin runner: desde web/,
 *    node --experimental-strip-types src/nl.test.ts
 */
import assert from "node:assert/strict";
// @ts-ignore TS5097: extension .ts en el import, necesaria para que Node lo resuelva
import { parseConnection, hhmm, firesUntil } from "./nl.ts";

const S = (repo: string, id: string, title = ""): any => ({ session_id: id, repo, title, agent: "claude", alive: true, pid: 1, state: "termino" });
const from = S("lienzo", "f64c2a31aaaa");
const mapo = S("mapo", "bbbbbbbbbbbb", "Tablero");
const others = [mapo, S("lienzo", "cccccccccccc", "coordinadora")];

const P = (s: string) => parseConnection(s, from, others);
const at = (s: string) => { const p = P(s); assert.equal(p.kind, "at", `${s} -> ${p.kind} (${p.summary})`); return p as Extract<ReturnType<typeof P>, { kind: "at" }>; };
const near = (d: Date, ms: number, tol = 5000) => Math.abs(d.getTime() - Date.now() - ms) < tol;

let p = at("cada 30 min continuá");
assert.equal(p.every, 1800); assert.equal(p.text, "continuá"); assert.equal(p.maxFires, 5); assert.ok(near(p.at, 1800e3));
assert.match(p.summary, /^Cada 30 min desde las \d\d:\d\d → "continuá" al destino elegido \(hasta 5 veces\)$/);

p = at("cada 2 horas decile continuá hasta 6 veces");
assert.equal(p.every, 7200); assert.equal(p.text, "continuá"); assert.equal(p.maxFires, 6); assert.ok(near(p.at, 7200e3));

p = at("todos los días a las 9 continuá");
assert.equal(p.every, 86400); assert.equal(p.text, "continuá"); assert.equal(hhmm(p.at), "09:00");
assert.match(p.summary, /^Cada día desde las 09:00/);

p = at("cada día seguí");
assert.equal(p.every, 86400); assert.equal(p.text, "seguí");

p = at("cada hora continuá");
assert.equal(p.every, 3600);
p = at("cada media hora continuá a esta sesión");
assert.equal(p.every, 1800); assert.equal(p.toSelf, true); assert.match(p.summary, /a esta sesión/);

p = at("en 10 min cada 30 min seguí");
assert.equal(p.every, 1800); assert.ok(near(p.at, 600e3)); assert.equal(p.text, "seguí");

p = at("en 2 horas seguí");
assert.equal(p.every, null); assert.equal(p.maxFires, 1); assert.match(p.summary, /"seguí" al destino elegido$/);

p = at("cada 30 min continuá hasta 2 veces");
assert.equal(p.maxFires, 2); assert.equal(p.text, "continuá");

// hasta las HH:MM: cuantos entran
const n = firesUntil(new Date(2026, 8, 6, 9, 0), 1800, 12, 0);
assert.equal(n, 7); // 9:00, 9:30, ..., 12:00
p = at("a las 9 cada 30 min continuá hasta las 12:00");
assert.equal(p.every, 1800); assert.equal(hhmm(p.at), "09:00"); assert.equal(p.maxFires, 7); assert.equal(p.text, "continuá");

p = at("cada 1 min continuá hasta 500 veces");
assert.equal(p.every, 60); assert.equal(p.maxFires, 50);

p = at("a las 16:00 mandale \"revisá el PR 42\" a mapo");
assert.equal(p.text, "revisá el PR 42"); assert.equal(p.to?.repo, "mapo"); assert.equal(p.every, null);

p = at("a las 9 avisame");
assert.equal(p.toMe, true); assert.match(p.summary, /a la coordinadora/);

// on_stop con avisame -> coordinadora
let q = P("cuando termine avisame");
assert.equal(q.kind, "on_stop"); assert.equal((q as any).toMe, true); assert.match(q.summary, /a la coordinadora/);
q = P("cada vez que termine pasale a mapo hasta 5 veces");
assert.equal(q.kind, "on_stop"); assert.equal((q as any).repeat, true); assert.equal((q as any).to.repo, "mapo");
q = P("cuando termine");
assert.equal(q.kind, "on_stop"); assert.equal((q as any).to, null); assert.match(q.summary, /qué sesión/);

q = P("ahora a mapo");
assert.equal(q.kind, "now");
q = P("qué onda");
assert.equal(q.kind, "none"); assert.match(q.summary, /quedan como estaban/);

console.log("nl.test.ts OK");
