import { useEffect, useState } from "react";
import type { Session } from "../types";

const SELECTED_KEY = "lienzo.selectedRepos";
const COORD_KEY = "lienzo.coordOnly";

function loadSelected(): Set<string> {
  try {
    const raw = localStorage.getItem(SELECTED_KEY);
    const arr = raw ? (JSON.parse(raw) as unknown) : [];
    return new Set(Array.isArray(arr) ? arr.filter((x): x is string => typeof x === "string") : []);
  } catch {
    return new Set();
  }
}

function saveSelected(s: Set<string>) {
  try {
    localStorage.setItem(SELECTED_KEY, JSON.stringify([...s]));
  } catch {
    /* sin storage, no importa */
  }
}

/** Proyectos elegidos (por su `repo_key`, o `repo` sin ese campo) y el chip ★ Coordinadoras,
 *  recordados en el navegador. Ninguno elegido es "todos": el click elige, nunca oculta. Un repo que
 *  ya no tiene sesiones se saca solo de la eleccion, para que no quede un filtro invisible. */
export function useProjectFilter(groups: { key: string }[]): {
  selected: Set<string>;
  coordOnly: boolean;
  toggleRepo: (key: string) => void;
  showAll: () => void;
  toggleCoord: () => void;
} {
  const [selected, setSelected] = useState<Set<string>>(loadSelected);
  const [coordOnly, setCoordOnly] = useState<boolean>(() => {
    try {
      return localStorage.getItem(COORD_KEY) === "1";
    } catch {
      return false;
    }
  });
  // la poda se hace durante el render cuando cambia el conjunto de repos (el patron de React para
  // ajustar estado a una prop, sin effect). Con cero grupos no se poda: es el tablero cargando, y
  // podar ahi borraria la eleccion guardada antes de que lleguen las sesiones
  const firma = groups
    .map((g) => g.key)
    .sort()
    .join("\n");
  const [firmaVista, setFirmaVista] = useState(firma);
  if (firma !== firmaVista) {
    setFirmaVista(firma);
    if (groups.length > 0) {
      const keys = new Set(groups.map((g) => g.key));
      const next = new Set([...selected].filter((k) => keys.has(k)));
      if (next.size !== selected.size) setSelected(next);
    }
  }
  useEffect(() => saveSelected(selected), [selected]);
  const toggleRepo = (key: string) =>
    setSelected((cur) => {
      const next = new Set(cur);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const showAll = () => setSelected(new Set());
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
  return { selected, coordOnly, toggleRepo, showAll, toggleCoord };
}

/** ¿Pasa el filtro de proyectos? ★ Coordinadoras muestra todas, elegido o no su proyecto: es la
 *  vista de "quien reparte". Si no, sin nada elegido pasa todo, y con algo elegido solo lo elegido. */
export function passesProjects(s: Session, selected: Set<string>, coordOnly: boolean): boolean {
  if (coordOnly) return !!s.coordinator;
  return selected.size === 0 || selected.has(s.repo_key || s.repo);
}

interface RepoGroup {
  key: string;
  label: string;
  count: number;
}

/** Un grupo por repo (agrupa por `repo_key` si viene, y si no por `repo`); la etiqueta siempre es
 *  `repo`. Orden: el que mas sesiones tiene primero. */
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
  selected: Set<string>;
  coordOnly: boolean;
  onToggleRepo: (key: string) => void;
  onShowAll: () => void;
  onToggleCoord: () => void;
}

/** Chips de proyecto en el menu de arriba, al lado del buscador y fuera de su fondo (pedido de
 *  Ariel): uno por repo con sesiones vivas y su conteo, mas ★ Coordinadoras. Un solo estado, el
 *  elegido: click elige (se pueden elegir varios), otro click lo suelta, y Todos suelta todo. Con
 *  un solo repo en el tablero no aparece: no hay nada que elegir. */
export function ProjectStrip({ groups, selected, coordOnly, onToggleRepo, onShowAll, onToggleCoord }: Props) {
  if (groups.length < 2) return null;
  return (
    <div className="pjstrip" role="group" aria-label="filtrar por proyecto">
      <button type="button" className={`chip pjchip all ${selected.size === 0 && !coordOnly ? "on" : ""}`} onClick={onShowAll}>
        Todos
      </button>
      {groups.map((g) => (
        <button
          key={g.key}
          type="button"
          className={`chip pjchip ${selected.has(g.key) ? "on" : ""}`}
          aria-pressed={selected.has(g.key)}
          title={selected.has(g.key) ? `dejar de filtrar por ${g.label}` : `ver las sesiones de ${g.label}`}
          onClick={() => onToggleRepo(g.key)}
        >
          {g.label} {g.count}
        </button>
      ))}
      <button
        type="button"
        className={`chip pjchip star ${coordOnly ? "on" : ""}`}
        aria-pressed={coordOnly}
        title="ver solo las coordinadoras, de todos los proyectos"
        onClick={onToggleCoord}
      >
        ★ Coordinadoras
      </button>
    </div>
  );
}
