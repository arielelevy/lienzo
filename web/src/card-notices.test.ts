import assert from "node:assert/strict";
import { test } from "node:test";
// @ts-ignore TS5097: Node ejecuta TypeScript directamente.
import { freshNotice, NOTICE_MS, showApproval, showSendNotice, showTurnPrompt } from "./card-notices.ts";
import type { Session, Turno } from "./types";

const now = Date.parse("2026-10-22T23:00:00Z");
const iso = (offset = 0) => new Date(now + offset).toISOString();
const session = (fields: Partial<Session> = {}) => ({
  session_id: "Z", agent: "claude", alive: true, state: "corriendo", state_since: iso(-60_000),
  last_prompt: "trabajo", auto_aprobado: { at: iso(-1000), que: "permiso", via: "dialogo" }, ...fields,
}) as Session;

test("los avisos caducan exactamente a tres minutos y rechazan fechas inválidas", () => {
  assert.equal(freshNotice(iso(-NOTICE_MS + 1), now), true);
  assert.equal(freshNotice(iso(-NOTICE_MS), now), false);
  assert.equal(freshNotice(iso(-NOTICE_MS - 1), now), false);
  assert.equal(freshNotice("inválido", now), false);
  assert.equal(freshNotice(undefined, now), false);
  assert.equal(freshNotice(iso(1), now), false);
});

test("auto-aprobado desaparece con pedido nuevo, cierre o proceso muerto", () => {
  assert.equal(showApproval(session(), now), true);
  assert.equal(showApproval(session({ prompt_ts: iso() }), now), false);
  assert.equal(showApproval(session({ state: "termino", state_since: iso() }), now), false);
  assert.equal(showApproval(session({ alive: false }), now), false);
});

test("sin enviar desaparece con confirmación causal o pedido nuevo; un recibo viejo no lo borra", () => {
  const s = session({ needs: { kind: "sin_enviar", since: iso(-1000) } });
  assert.equal(showSendNotice(s, now), true);
  assert.equal(showSendNotice({ ...s, prompt_ts: iso() }, now), false);
  for (const agent of ["claude", "codex"] as const) {
    const field = agent === "claude" ? "envio_claude" : "envio_codex";
    const receipt = { estado: "entregado" as const, at: now / 1000, confirmacion_final: true };
    assert.equal(showSendNotice({ ...s, agent, [field]: receipt }, now), false);
    assert.equal(showSendNotice({ ...s, agent, [field]: { ...receipt, at: (now - 2000) / 1000 } }, now), true);
    assert.equal(showSendNotice({ ...s, agent, [field]: { ...receipt, confirmacion_final: false } }, now), true);
  }
  assert.equal(showSendNotice({ ...s, needs: { kind: "permission", since: iso(-NOTICE_MS) } }, now), true);
});

test("turno sólo se muestra mientras pertenece a la sesión y no venció ni fue liberado", () => {
  const s = session({ last_prompt: "[lienzo] te toca el turno de «motores» (vence a las 23:10)." });
  const dueno = { session_id: "Z", motivo: null, desde: iso(-1000), vence: iso(60_000) };
  const turnos: Record<string, Turno> = { motores: { dueno, cola: [] } };
  assert.equal(showTurnPrompt(s, turnos, now), true);
  assert.equal(showTurnPrompt(s, { motores: { dueno: null, cola: [] } }, now), false);
  assert.equal(showTurnPrompt(s, { motores: { dueno: { ...dueno, session_id: "otra" }, cola: [] } }, now), false);
  assert.equal(showTurnPrompt(s, turnos, now + 60_000), false);
  assert.equal(showTurnPrompt(s, turnos, now + NOTICE_MS), false);
  assert.equal(showTurnPrompt(session(), {}, now), true);
});
