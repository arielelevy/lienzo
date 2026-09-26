import { useEffect, useState } from "react";
import type { Session } from "../types";

const HIDDEN_KEY = "lienzo.hiddenRepos";
const COORD_KEY = "lienzo.coordOnly";

function loadHidden(): Set<string> {
  try {
    const raw = localStorage.getItem(HIDDEN_KEY);
    const arr = raw ? (JSON.parse(raw) as unknown) : [];
    return new Set(Array.isArray(arr) ? arr.filter((x): x is string => typeof x === "string") : []);
  } catch {
    return new Set();
  }
}

function saveHidden(h: Set<string>) {
  try {
    localStorage.setItem(HIDDEN_KEY, JSON.stringify([...h]));
  } catch {
    /* sin storage, no importa */
  }
}

/** Repos ocultos (por su `repo_key`, o `repo` sin ese campo) y el chip ★ Coordinadoras, recordados
 *  en el navegador. Un repo que ya no tiene ninguna sesion se saca solo de la selección: si vuelve
 *  a aparecer despues (otra sesion del mismo repo), no sigue oculto por una eleccion vieja. */
export function useProjectFilter(groups: { key: string }[]): {
  hidden: Set<string>;
  coordOnly: boolean;
  toggleRepo: (key: string) => void;
  showAll: () => void;
  toggleCoord: () => void;
} {
  const [hidden, setHidden] = useState<Set<string>>(loadHidden);
  const [coordOnly, setCoordOnly] = useState<boolean>(() => {
    try {
      return localStorage.getItem(COORD_KEY) === "1";
    } catch {
      return false;
    }
  });
  // la poda se hace durante el render cuando cambia el conjunto de repos (el patron de React para
  // ajustar estado a una prop, sin effect). Con cero grupos no se poda: es el tablero cargando, y
  // podar ahi borraria toda la eleccion guardada antes de que lleguen las sesiones
  const firma = groups
    .map((g) => g.key)
    .sort()
    .join("\n");
  const [firmaVista, setFirmaVista] = useState(firma);
  if (firma !== firmaVista) {
    setFirmaVista(firma);
    if (groups.length > 0) {
      const keys = new Set(groups.map((g) => g.key));
      const next = new Set([...hidden].filter((k) => keys.has(k)));
      if (next.size !== hidden.size) setHidden(next);
    }
  }
  useEffect(() => saveHidden(hidden), [hidden]);
  const toggleRepo = (key: string) =>
    setHidden((h) => {
      const next = new Set(h);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const showAll = () => setHidden(new Set());
  const toggleCoord = () =>
    setCoordOnly((v) => {
      const next = !v;
      try {
        localStorage.setItem(COORD_KEY, next ? "1" : "0");
      } catch {
        /* sin storage, no importa */
      }
      return next;
    });
  return { hidden, coordOnly, toggleRepo, showAll, toggleCoord };
}

interface RepoGroup {
  key: string;
  label: string;
  count: number;
}

/** Un grupo por repo (frente B agrega `repo_key`: agrupa por eso si viene, y si no por `repo`), la
 *  etiqueta siempre es `repo`. Orden: el que mas sesiones tiene primero. */
export function repoGroups(sessions: Session[]): RepoGroup[] {
  const by = new Map<string, RepoGroup>();
  for (const s of sessions) {
    const key = s.repo_key || s.repo;
    const g = by.get(key);
    if (g) g.count++;
    else by.set(key, { key, label: s.repo, count: 1 });
  }
  return [...by.values()].sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}

interface Props {
  groups: RepoGroup[];
  hidden: Set<string>;
  coordOnly: boolean;
  onToggleRepo: (key: string) => void;
  onShowAll: () => void;
  onToggleCoord: () => void;
}

/** Chips de proyecto en el menu de arriba, despues de los de agente y separados por una raya
 *  (pedido de Ariel): uno por repo con sesiones vivas y su conteo, mas ★ Coordinadoras. Seleccion
 *  multiple (ocultar/mostrar, no exclusiva), todos prendidos por defecto; con un solo repo en el
 *  tablero no aparece: no hay nada que elegir. */
export function ProjectStrip({ groups, hidden, coordOnly, onToggleRepo, onShowAll, onToggleCoord }: Props) {
  if (groups.length < 2) return null;
  return (
    <span className="pjstrip" role="group" aria-label="filtrar por proyecto">
      <span className="sep" aria-hidden="true" />
      <button type="button" className={`chip pjchip all ${hidden.size === 0 ? "on" : ""}`} onClick={onShowAll}>
        Todos
      </button>
      {groups.map((g) => (
        <button
          key={g.key}
          type="button"
          className={`chip pjchip ${hidden.has(g.key) ? "" : "on"}`}
          aria-pressed={!hidden.has(g.key)}
          title={hidden.has(g.key) ? `mostrar sesiones de ${g.label}` : `ocultar sesiones de ${g.label}`}
          onClick={() => onToggleRepo(g.key)}
        >
          {g.label} {g.count}
        </button>
      ))}
      <button
        type="button"
        className={`chip pjchip star ${coordOnly ? "on" : ""}`}
        aria-pressed={coordOnly}
        title="mostrar solo las coordinadoras, de todos los proyectos"
        onClick={onToggleCoord}
      >
        ★ Coordinadoras
      </button>
    </span>
  );
}
