import { useEffect, useMemo, useState } from "react";
import { ago, api, ApiError } from "../api";
import { toggled } from "../names";
import type { Peer, Session } from "../types";

const POLL_MS = 15000;

/** `GET /peers` (ronda 2): la lista de PCs de la federacion, la propia incluida (`local: true`).
 *  La ruta no existe todavia en el server de esta ronda (404) y un server caido da lo mismo que
 *  uno sin peers emparejados: en los dos casos, el array queda vacio y la tira no aparece. */
export function usePeers(): Peer[] {
  const [peers, setPeers] = useState<Peer[]>([]);
  useEffect(() => {
    let disposed = false;
    const load = () =>
      api
        .get<Peer[]>("/peers")
        .then((ps) => {
          if (!disposed) setPeers(Array.isArray(ps) ? ps : []);
        })
        .catch(() => {
          if (!disposed) setPeers([]);
        });
    load();
    const id = window.setInterval(load, POLL_MS);
    return () => {
      disposed = true;
      window.clearInterval(id);
    };
  }, []);
  return peers;
}

const PC_FILTER_KEY = "lienzo.pcFilters";
/** clave de antes, cuando se elegia una sola PC: un pc_id suelto. Se lee una vez y se migra. */
const PC_FILTER_OLD_KEY = "lienzo.pcFilter";

function loadPcFilter(): Set<string> {
  try {
    const raw = localStorage.getItem(PC_FILTER_KEY);
    if (raw) {
      const arr = JSON.parse(raw) as unknown;
      return new Set(Array.isArray(arr) ? arr.filter((x): x is string => typeof x === "string") : []);
    }
    const viejo = localStorage.getItem(PC_FILTER_OLD_KEY);
    return new Set(viejo ? [viejo] : []);
  } catch {
    return new Set();
  }
}

const NINGUNA: Set<string> = new Set();

/** Las PCs elegidas en la tira (vacio es "Todas"), recordadas en el navegador. Click simple deja
 *  solo esa PC; `togglePc` (Ctrl/Cmd + click) la suma o la saca, asi se miran varias a la vez.
 *  Las que ya no estan emparejadas (las revocaron) se ignoran: no tiene sentido filtrar por una PC
 *  que dejo de existir, y si no queda ninguna vigente vuelve solo a "Todas". */
export function usePcFilter(peers: Peer[]): {
  pcFilter: Set<string>;
  selectPc: (id: string) => void;
  togglePc: (id: string) => void;
  showAllPcs: () => void;
} {
  const [elegidas, setElegidas] = useState<Set<string>>(loadPcFilter);
  const guardar = (next: Set<string>) => {
    setElegidas(next);
    try {
      if (next.size) localStorage.setItem(PC_FILTER_KEY, JSON.stringify([...next]));
      else localStorage.removeItem(PC_FILTER_KEY);
      localStorage.removeItem(PC_FILTER_OLD_KEY);
    } catch {
      /* sin storage, no importa */
    }
  };
  // derivado y no corregido en un effect: sin tira (menos de dos PCs, o /peers caido) no hay filtro
  // posible, y si quedara el guardado el tablero se vaciaria sin ningun chip que lo explique
  const pcFilter = useMemo(() => {
    if (peers.length < 2) return NINGUNA;
    const vigentes = [...elegidas].filter((id) => peers.some((p) => p.pc_id === id));
    return vigentes.length ? new Set(vigentes) : NINGUNA;
  }, [elegidas, peers]);
  return {
    pcFilter,
    selectPc: (id) => guardar(new Set([id])),
    togglePc: (id) => guardar(toggled(pcFilter, id)),
    showAllPcs: () => guardar(new Set()),
  };
}

/** El pc_id dueño de una sesion: el que trae (frente B, ronda 2) o, sin ese campo, la PC local. */
export function pcOf(s: Session, localPcId: string | null): string | null {
  return s.pc ?? localPcId;
}

interface Props {
  peers: Peer[];
  sessions: Record<string, Session>;
  filter: Set<string>;
  /** click simple: solo esa PC */
  onSelect: (pc: string) => void;
  /** Ctrl/Cmd + click: suma o saca la PC de las elegidas */
  onToggle: (pc: string) => void;
  onAll: () => void;
}

/** Tira de PCs arriba del tablero (§3.9 del plan): solo con al menos un peer emparejado (el
 *  arreglo trae la propia PC mas la de al lado). "Todas N" y un chip por PC con conteo, memoria y
 *  temperatura; un peer caido se ve en ○ y su chip ya no dice memoria ni temperatura, que son datos
 *  viejos. Click filtra el tablero a esa PC y nada mas; Ctrl/Cmd + click suma o saca PCs (varias a la vez);
 *  se vuelve con Todas. */
export function PcStrip({ peers, sessions, filter, onSelect, onToggle, onAll }: Props) {
  // el aviso del ultimo click en el violeta, atado al problema que lo genero: cuando el violeta se va
  // (o cambia) el aviso viejo deja de verse; antes «pasada» quedaba pegado para siempre
  const [gitMsg, setGitMsg] = useState<Record<string, { msg: string; git: string | null }>>({});
  if (peers.length < 2) return null;
  const localPcId = peers.find((p) => p.local)?.pc_id ?? null;
  const total = Object.keys(sessions).length;
  const countOf = (pcId: string) => Object.values(sessions).filter((s) => pcOf(s, localPcId) === pcId).length;

  const avisar = (p: Peer, msg: string) =>
    setGitMsg((m) => ({ ...m, [p.pc_id]: { msg, git: p.health ? gitDe(p.health) : null } }));
  /** Click en el violeta (pedido de Ariel, 2026-10-04): si lo que falla es la credencial (vencida o
   *  no verificable), esta PC le pasa la suya, cifrada con la clave del par (POST /secrets con
   *  `desde: "git_local"`, lo mismo que coordinar.pasar_credencial_git). Sin red o timeout no se
   *  arreglan con otra credencial y se dice. La PC de este tablero no se puede pasar a si misma:
   *  hay que hacer click desde el tablero de la PC que la tiene. */
  const pasarGit = async (p: Peer) => {
    const malas = Object.entries(p.health?.git_auth ?? {}).filter(([, v]) => v === "vencida" || v === "no_verificable");
    if (!malas.length) return avisar(p, "es la red o git colgado, no la credencial: pasar otra no lo arregla");
    if (p.local) return avisar(p, "es esta PC: hacé click desde el tablero de la PC que tiene la credencial");
    avisar(p, "pasando la credencial…");
    const res: string[] = [];
    for (const [url] of malas) {
      const host = hostDe(url);
      try {
        await api.post("/secrets", { pc: p.pc_id, nombre: `git ${url}`, destino: "git", git_url: url, desde: "git_local" });
        res.push(`${host}: pasada`);
      } catch (e) {
        // un 503 sin `no_llego` (timeout, corte a mitad) pudo haberse guardado igual: el violeta lo confirma
        const quizas = e instanceof ApiError && e.status === 503 && !e.body.no_llego;
        res.push(`${host}: ${e instanceof Error ? e.message : String(e)}${quizas ? " (pudo haber llegado igual: si el violeta se va, quedó)" : ""}`);
      }
    }
    avisar(p, `${res.join("; ")} (se vuelve a probar sola en unos segundos)`);
  };

  return (
    <div className="pcstrip" role="toolbar" aria-label="filtrar por PC">
      <button type="button" className={`pcchip all ${filter.size === 0 ? "on" : ""}`} onClick={onAll}>
        Todas<sub className="n">{total}</sub>
      </button>
      {peers.map((p) => {
        const down = p.alive === false;
        const alerta = !down && p.health ? alertaDe(p.health) : null;
        const git = !down && p.health ? gitDe(p.health) : null;
        const aviso = gitMsg[p.pc_id];
        return (
          <span key={p.pc_id} className="pcwrap">
          <button
            type="button"
            className={`pcchip ${filter.has(p.pc_id) ? "on" : ""} ${down ? "down" : ""} ${alerta ? "alerta" : ""}`}
            style={{ "--pc-color": p.color } as React.CSSProperties}
            title={
              down
                ? `${p.name}: sin conexión hace ${ago(p.last_seen)}`
                : `${p.name}${alerta ? ` — ${alerta}` : ""}${git ? ` — git: ${git}` : ""} (Ctrl + click suma o saca PCs)`
            }
            aria-pressed={filter.has(p.pc_id)}
            onClick={(e) => (e.ctrlKey || e.metaKey ? onToggle(p.pc_id) : onSelect(p.pc_id))}
          >
            <span className="dot" aria-hidden="true" />
            {p.name}
            <sub className="n">{countOf(p.pc_id)}</sub>
            {!down && p.health && (
              <span className="health">
                {p.health.mem_free_gb != null && ` · ${p.health.mem_free_gb.toFixed(1)} GB`}
                {p.health.cpu_pct != null && ` · CPU ${Math.round(p.health.cpu_pct)}%`}
                {p.health.temp_c != null && ` · ${Math.round(p.health.temp_c)} °C`}
                {p.latencia_ms != null && ` · ${p.latencia_ms} ms`}
              </span>
            )}
          </button>
          {git && (
            <button
              type="button"
              className="pcgit"
              title={p.local ? `git: ${git} (es esta PC: pasale la credencial desde el tablero de otra)` : `git: ${git}. Click: pasarle la credencial de git de esta PC, cifrada`}
              onClick={() => void pasarGit(p)}
            >
              <span aria-hidden="true">⚿</span> git: {git}
            </button>
          )}
          {git && aviso && aviso.git === git && <span className="pcgitmsg">{aviso.msg}</span>}
          </span>
        );
      })}
    </div>
  );
}

/** TEMP_ALERTA_C: desde aca una PC se esta cocinando. Sin memoria para un agente mas (la regla del
 *  server, agentes_libres) tambien es alerta: lanzar ahi pagina y arrastra a todas sus sesiones. */
const TEMP_ALERTA_C = 85;

export function alertaDe(h: {
  temp_c: number | null;
  agentes_libres?: number | null;
  cuotas?: Record<string, string> | null;
}): string | null {
  const motivos: string[] = [];
  const sinCuota = Object.entries(h.cuotas ?? {}).filter(([, v]) => v.startsWith("agotada"));
  if (sinCuota.length) motivos.push(`sin cuota: ${sinCuota.map(([a, v]) => (v === "agotada" ? a : `${a} (${v.replace("agotada ", "")})`)).join(", ")}`);
  if (h.temp_c != null && h.temp_c >= TEMP_ALERTA_C) motivos.push(`a ${Math.round(h.temp_c)} °C`);
  if (h.agentes_libres === 0) motivos.push("sin memoria para otro agente");
  return motivos.length ? motivos.join(" y ") : null;
}

const MOTIVO_GIT: Record<string, string> = {
  vencida: "vencida",
  no_verificable: "no verificable",
  sin_red: "sin red",
  timeout: "timeout",
  error: "error",
};

/** El estado de la credencial de git, aparte de la alerta roja de recursos (pedido de Ariel,
 *  2026-10-04: se confundia con memoria y temperatura). Una linea por url con problema:
 *  «vencida (git.ejemplo.com · curso)», host y repo, porque las urls salen de los repos con sesion
 *  viva y hay que ver cual la trajo (bug 9); null si todas andan. vencida es la credencial (401/403),
 *  sin red y timeout son la red o git colgado: ahi pasar otra credencial no arregla nada. */
function hostDe(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

export function gitDe(h: { git_auth?: Record<string, string> | null }): string | null {
  const porMotivo = new Map<string, string[]>();
  for (const [url, v] of Object.entries(h.git_auth ?? {})) {
    if (v === "ok") continue;
    let host = url;
    try {
      const u = new URL(url);
      const repo = u.pathname.replace(/\/+$/, "").split("/").pop()?.replace(/\.git$/, "");
      host = repo ? `${u.host} · ${repo}` : u.host;
    } catch {
      /* url rara: se muestra entera */
    }
    const m = MOTIVO_GIT[v] ?? v;
    porMotivo.set(m, [...(porMotivo.get(m) ?? []), host]);
  }
  return porMotivo.size ? [...porMotivo].map(([m, hosts]) => `${m} (${hosts.join(", ")})`).join(", ") : null;
}
