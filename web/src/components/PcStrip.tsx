import { useEffect, useState } from "react";
import { ago, api } from "../api";
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

const PC_FILTER_KEY = "lienzo.pcFilter";

/** El pc_id elegido en la tira ("Todas" es null), recordado en el navegador. Si el peer elegido
 *  ya no esta emparejado (lo revocaron), vuelve solo a "Todas": no tiene sentido seguir filtrando
 *  por una PC que dejo de existir. */
export function usePcFilter(peers: Peer[]): [string | null, (v: string | null) => void] {
  const [pcFilter, setPcFilterState] = useState<string | null>(() => {
    try {
      return localStorage.getItem(PC_FILTER_KEY);
    } catch {
      return null;
    }
  });
  const setPcFilter = (v: string | null) => {
    setPcFilterState(v);
    try {
      if (v) localStorage.setItem(PC_FILTER_KEY, v);
      else localStorage.removeItem(PC_FILTER_KEY);
    } catch {
      /* sin storage, no importa */
    }
  };
  // derivado y no corregido en un effect: sin tira (menos de dos PCs, o /peers caido) no hay filtro
  // posible, y si quedara el guardado el tablero se vaciaria sin ningun chip que lo explique
  const vigente = pcFilter && peers.length >= 2 && peers.some((p) => p.pc_id === pcFilter) ? pcFilter : null;
  return [vigente, setPcFilter];
}

/** El pc_id dueño de una sesion: el que trae (frente B, ronda 2) o, sin ese campo, la PC local. */
export function pcOf(s: Session, localPcId: string | null): string | null {
  return s.pc ?? localPcId;
}

interface Props {
  peers: Peer[];
  sessions: Record<string, Session>;
  filter: string | null;
  onFilter: (pc: string | null) => void;
}

/** Tira de PCs arriba del tablero (§3.9 del plan): solo con al menos un peer emparejado (el
 *  arreglo trae la propia PC mas la de al lado). "Todas N" y un chip por PC con conteo, memoria y
 *  temperatura; un peer caido se ve en ○ y su chip ya no dice memoria ni temperatura, que son datos
 *  viejos. Click filtra el tablero a esa PC; click en el activo vuelve a Todas. */
export function PcStrip({ peers, sessions, filter, onFilter }: Props) {
  if (peers.length < 2) return null;
  const localPcId = peers.find((p) => p.local)?.pc_id ?? null;
  const total = Object.keys(sessions).length;
  const countOf = (pcId: string) => Object.values(sessions).filter((s) => pcOf(s, localPcId) === pcId).length;

  return (
    <div className="pcstrip" role="toolbar" aria-label="filtrar por PC">
      <button type="button" className={`pcchip all ${filter === null ? "on" : ""}`} onClick={() => onFilter(null)}>
        Todas {total}
      </button>
      {peers.map((p) => {
        const down = p.alive === false;
        return (
          <button
            key={p.pc_id}
            type="button"
            className={`pcchip ${filter === p.pc_id ? "on" : ""} ${down ? "down" : ""}`}
            style={{ "--pc-color": p.color } as React.CSSProperties}
            title={down ? `${p.name}: sin conexión hace ${ago(p.last_seen)}` : p.name}
            aria-pressed={filter === p.pc_id}
            onClick={() => onFilter(filter === p.pc_id ? null : p.pc_id)}
          >
            <span className="dot" aria-hidden="true" />
            {p.name} {countOf(p.pc_id)}
            {!down && p.health && (
              <span className="health">
                {p.health.mem_free_gb != null && ` · ${p.health.mem_free_gb.toFixed(1)} GB`}
                {p.health.temp_c != null && ` · ${Math.round(p.health.temp_c)} °C`}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
