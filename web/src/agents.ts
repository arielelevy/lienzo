/** Lo que el lienzo sabe hacer con cada CLI, como dato: antes eran `s.agent === "claude"` sueltos
 *  en Card, Panel y Forward, y sumar un agente era buscarlos a todos.
 *  - coordinable: puede ser la coordinadora del repo (estrella del menu ⋯; la que se elige sola si
 *    ninguna tiene estrella)
 *  - nativeChannel: abre el canal nativo con otra sesion (SendMessage, que se apoya en ListAgents)
 *  - screen: la pestana Pantalla del panel lee el buffer de su consola
 *  El permiso que CODA pide en su terminal no esta aca: lo decide un dato de la sesion
 *  (`needs.coda_at`), no el agente. */
interface Caps {
  label: string;
  resume: string;
  coordinable: boolean;
  nativeChannel: boolean;
  screen: boolean;
}

/** Catalogo de CLI: los filtros, tipos, textos y capacidades salen de la misma lista. */
export const AGENTS = {
  claude: { label: "Claude Code", resume: "claude --resume", coordinable: true, nativeChannel: true, screen: true },
  codex: { label: "Codex", resume: "codex resume", coordinable: false, nativeChannel: false, screen: false },
  pi: { label: "Pi", resume: "pi --resume", coordinable: false, nativeChannel: false, screen: false },
  coda: { label: "CODA", resume: "coda --lastsession", coordinable: false, nativeChannel: false, screen: false },
} as const satisfies Record<string, Caps>;
export type Agent = keyof typeof AGENTS;
export type Capability = "coordinable" | "nativeChannel" | "screen";

/** ¿Este agente puede esto? Un agente que el front todavia no conoce (server mas nuevo) no puede nada. */
export const can = (agent: string, cap: Capability): boolean => !!(AGENTS as Record<string, Caps | undefined>)[agent]?.[cap];
export const agentIds = Object.keys(AGENTS) as Agent[];
export const allAgents = Object.fromEntries(agentIds.map((id) => [id, true])) as Record<Agent, boolean>;
