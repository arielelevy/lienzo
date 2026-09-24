/** Catalogo de CLI: los filtros, tipos y textos salen de la misma lista. */
export const AGENTS = {
  claude: { label: "Claude Code", resume: "claude --resume" },
  codex: { label: "Codex", resume: "codex resume" },
  pi: { label: "Pi", resume: "pi --resume" },
  coda: { label: "CODA", resume: "coda --lastsession" },
} as const;
export type Agent = keyof typeof AGENTS;
export const agentIds = Object.keys(AGENTS) as Agent[];
export const allAgents = Object.fromEntries(agentIds.map((id) => [id, true])) as Record<Agent, boolean>;
