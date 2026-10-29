import assert from "node:assert/strict";
// @ts-ignore TS5097: extension .ts en el import, necesaria para que Node lo resuelva
import { lanzadoPor } from "./lanzado-por.ts";
import type { Session } from "./types";

const titulo = (s: Session) => s.title ?? "?";
const launcher = { tool: "graphify", pid: 16148, agent: "claude", cuenta: "SmartBI" };
const batch = { session_id: "b", pid: 18640, pc: "pc1", transcript_path: null, external: { kind: "batch", via: "comando", launcher } } as unknown as Session;
const madre = { session_id: "m", pid: 16148, pc: "pc1", title: "grafos de Teorema" } as unknown as Session;

// con la tarjeta del agente de arriba: su título
assert.equal(lanzadoPor(batch, { m: madre }, titulo), " (graphify · lanzado por claude SmartBI «grafos de Teorema»)");
// sin tarjeta, o en otra PC: el PID
assert.equal(lanzadoPor(batch, {}, titulo), " (graphify · lanzado por claude SmartBI PID 16148)");
assert.equal(lanzadoPor(batch, { m: { ...madre, pc: "pc2" } }, titulo), " (graphify · lanzado por claude SmartBI PID 16148)");
// sin agente arriba: la herramienta sola
assert.equal(lanzadoPor({ ...batch, external: { ...batch.external!, launcher: { tool: "graphify", pid: null, agent: null, cuenta: null } } }, {}, titulo), " (graphify)");
// con transcripción ya hay conversación: nada
assert.equal(lanzadoPor({ ...batch, transcript_path: "x.jsonl" }, { m: madre }, titulo), "");
// una sesión que no es claude -p, o un server anterior sin launcher: nada
assert.equal(lanzadoPor({ ...batch, external: { kind: "orq", via: "proceso", launcher } }, {}, titulo), "");
assert.equal(lanzadoPor({ ...batch, external: { kind: "batch", via: "comando" } }, {}, titulo), "");
