import assert from "node:assert/strict";
import { mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import lienzo from "./pi-lienzo.ts";

test("Pi emits ordered local events, only for TUI and only settles once idle", () => {
  const home = mkdtempSync(join(tmpdir(), "lienzo-pi-test-"));
  const previous = process.env.USERPROFILE;
  process.env.USERPROFILE = home;
  try {
    const handlers = new Map();
    lienzo({ on: (name, fn) => handlers.set(name, fn), getSessionName: () => "Revisión" });
    let idle = true;
    let file;
    let sid = "first";
    const ctx = {
      mode: "tui", cwd: "D:/Apps/lienzo", isIdle: () => idle,
      ui: { notify: (message) => assert.fail(message) },
      sessionManager: {
        getSessionId: () => sid, getSessionFile: () => file, getLeafId: () => "leaf",
        getBranch: () => [{ type: "message", message: { role: "assistant", content: [{ type: "text", text: "Listo ✓" }] } }],
      },
    };
    const emit = (name, event = {}) => handlers.get(name)(event, ctx);
    emit("session_start");
    idle = false;
    emit("agent_start");
    emit("message_start", { message: { role: "user", content: [{ type: "text", text: "Hola ñ" }] } });
    file = "D:/sesión.jsonl";
    emit("tool_call");
    emit("agent_settled"); // not idle: must not announce Stop
    emit("ui_prompt_start", { title: "Confirmar", kind: "confirm" });
    emit("ui_prompt_end");
    idle = true;
    emit("agent_settled");
    emit("session_tree");
    emit("session_shutdown");
    sid = "second";
    emit("session_start");
    for (const mode of ["rpc", "print", "json"]) {
      ctx.mode = mode;
      emit("session_start");
      emit("agent_settled");
    }
    const events = readdirSync(join(home, ".lienzo", "events")).sort()
      .map((name) => JSON.parse(readFileSync(join(home, ".lienzo", "events", name), "utf8")));
    assert.deepEqual(events.map((e) => e.hook_event_name), [
      "SessionStart", "PiBusy", "UserPromptSubmit", "PiProgress", "PiPromptStart", "PiPromptEnd", "Stop", "PiTree", "SessionEnd", "SessionStart",
    ]);
    assert.equal(events[0].transcript_path, null);
    assert.equal(events[2].prompt, "Hola ñ");
    assert.equal(events[2].pi_leaf_id, null);
    assert.equal(events[3].transcript_path, file);
    assert.equal(events[6].last_assistant_message, "Listo ✓");
    assert.equal(events[7].pi_leaf_id, "leaf");
    assert.equal(events.at(-1).session_id, "second");
    assert.ok(events.every((e) => e.pid === process.pid && e.agent === "pi"));
    assert.equal(handlers.has("agent_end"), false);
    assert.equal(handlers.has("turn_end"), false);
  } finally {
    if (previous === undefined) delete process.env.USERPROFILE;
    else process.env.USERPROFILE = previous;
    rmSync(home, { recursive: true, force: true });
  }
});
