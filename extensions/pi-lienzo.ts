/** Pi -> Lienzo. Local, atomic event files; no server dependency or permission changes. */
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { mkdirSync, renameSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { randomUUID } from "node:crypto";

export default function (pi: ExtensionAPI) {
  const events = join(process.env.USERPROFILE || homedir(), ".lienzo", "events");
  let sequence = 0;
  let warned = false;

  function emit(ctx: ExtensionContext, name: string, extra: Record<string, unknown> = {}) {
    // RPC has hasUI=true too, but no terminal to inject into. Never advertise it as a TUI.
    if (ctx.mode !== "tui") return;
    try {
      mkdirSync(events, { recursive: true });
      const id = `${Date.now()}-${process.pid}-${String(sequence++).padStart(8, "0")}-${randomUUID()}`;
      const target = join(events, `${id}.json`);
      const event = {
        agent: "pi", hook_event_name: name,
        session_id: ctx.sessionManager.getSessionId(),
        transcript_path: ctx.sessionManager.getSessionFile() ?? null,
        pid: process.pid, agent_exe: process.execPath, cwd: ctx.cwd,
        host_ts: new Date().toISOString(),
        // While running, infer from disk so newly appended entries are not hidden by an old leaf.
        pi_leaf_id: ctx.isIdle() ? (ctx.sessionManager.getLeafId() ?? "") : null,
        pi_title: pi.getSessionName() ?? null,
        ...extra,
      };
      writeFileSync(`${target}.tmp`, JSON.stringify(event), "utf8");
      renameSync(`${target}.tmp`, target);
    } catch (error) {
      // An unavailable dashboard must never break tools or block a turn.
      if (!warned) {
        warned = true;
        ctx.ui.notify(`Lienzo: no se pudo publicar el estado: ${String(error)}`, "warning");
      }
    }
  }

  pi.on("session_start", (_event, ctx) => emit(ctx, "SessionStart", { pi_idle: ctx.isIdle() }));
  pi.on("session_shutdown", (_event, ctx) => emit(ctx, "SessionEnd"));
  pi.on("session_info_changed", (_event, ctx) => emit(ctx, "PiMetadata"));
  pi.on("session_tree", (_event, ctx) => emit(ctx, "PiTree"));
  pi.on("agent_start", (_event, ctx) => emit(ctx, "PiBusy", { pi_leaf_id: null }));
  // A new session file may not exist at startup; tool_call runs after it is persisted.
  pi.on("tool_call", (_event, ctx) => emit(ctx, "PiProgress", { pi_leaf_id: null }));
  // Observe delivered user messages, not input: input may be queued, transformed or handled.
  pi.on("message_start", (event, ctx) => {
    if (event.message.role !== "user") return;
    const content = event.message.content;
    const prompt = typeof content === "string" ? content : content
      .filter((b) => b.type === "text").map((b) => b.text).join("\n");
    emit(ctx, "UserPromptSubmit", { prompt: prompt || "(imagen)", pi_leaf_id: null });
  });
  // agent_end is too early: retries, compaction and follow-ups can still be pending.
  pi.on("agent_settled", (_event, ctx) => {
    if (!ctx.isIdle()) return;
    const last = [...ctx.sessionManager.getBranch()].reverse().find(
      (entry) => entry.type === "message" && entry.message.role === "assistant",
    );
    const message = last?.type === "message" ? last.message : undefined;
    const text = message && Array.isArray(message.content) ? message.content
      .filter((b) => b.type === "text").map((b) => b.text).join("\n") : "";
    emit(ctx, "Stop", { last_assistant_message: text });
  });
  // Inform only: Pi extension dialogs are answered in the terminal, not permission approvals.
  pi.on("ui_prompt_start", (event, ctx) => emit(ctx, "PiPromptStart", { message: event.title || event.kind }));
  pi.on("ui_prompt_end", (_event, ctx) => emit(ctx, "PiPromptEnd", { pi_idle: ctx.isIdle() }));
}
