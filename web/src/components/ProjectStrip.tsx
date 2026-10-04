import { useEffect, useState } from "react";
import { toggled } from "../names";
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
  selectRepo: (key: string) => void;
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
  // el click elige ese proyecto y nada mas: otro click sobre el elegido no lo suelta (eso es Todos)
  const selectRepo = (key: string) => setSelected(new Set([key]));
  // Ctrl/Cmd + click: suma o saca ese proyecto de los elegidos; si saca el ultimo, vuelve a "todos"
  const toggleRepo = (key: string) => setSelected((cur) => toggled(cur, key));
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
  return { selected, coordOnly, selectRepo, toggleRepo, showAll, toggleCoord };
}

/** ¿Pasa el filtro de proyectos? Sin nada elegido pasa todo, y con algo elegido solo lo elegido.
 *  ★ Coordinadoras se suma a eso: de lo que queda, solo las coordinadoras. */
export function passesProjects(s: Session, selected: Set<string>, coordOnly: boolean): boolean {
  if (coordOnly && !s.coordinator) return false;
  return selected.size === 0 || selected.has(s.repo_key || s.repo);
}

interface RepoGroup {
  key: string;
  label: string;
  count: number;
  /** los `repo_key || repo` de sus sesiones: lo que el filtro compara contra cada tarjeta */
  members: string[];
}

/** Un grupo por proyecto, aunque sus sesiones sean de distintas PCs: se juntan las que comparten
 *  `repo_key` (el remote normalizado, la identidad entre PCs) Y las que comparten el nombre `repo`
 *  sin distinguir mayusculas. Pedido de Ariel (2026-10-04): «chess» salia dos veces, una por PC,
 *  porque en una PC la carpeta tenia remote y en la otra no (repo_key distinto, mismo nombre). La
 *  clave del grupo es el menor de sus miembros, estable mientras no cambien las sesiones; la
 *  etiqueta, el `repo` mas repetido. Orden: el que mas sesiones tiene primero. */
export function repoGroups(sessions: Session[]): RepoGroup[] {
  // union-find sobre «k:<repo_key|repo>» y «n:<nombre en minusculas>»
  const padre = new Map<string, string>();
  const raiz = (x: string): string => {
    let r = x;
    while (padre.get(r) !== r) r = padre.get(r) ?? r;
    padre.set(x, r);
    return r;
  };
  const unir = (a: string, b: string) => {
    for (const x of [a, b]) if (!padre.has(x)) padre.set(x, x);
    const ra = raiz(a);
    const rb = raiz(b);
    if (ra !== rb) padre.set(ra < rb ? rb : ra, ra < rb ? ra : rb);
  };
  for (const s of sessions) unir(`k:${s.repo_key || s.repo}`, `n:${(s.repo || "").toLowerCase()}`);
  const by = new Map<string, { members: Set<string>; labels: Map<string, number>; count: number }>();
  for (const s of sessions) {
    const member = s.repo_key || s.repo;
    const r = raiz(`k:${member}`);
    const g = by.get(r) ?? { members: new Set<string>(), labels: new Map<string, number>(), count: 0 };
    g.members.add(member);
    g.labels.set(s.repo, (g.labels.get(s.repo) ?? 0) + 1);
    g.count++;
    by.set(r, g);
  }
  return [...by.values()]
    .map((g) => {
      const members = [...g.members].sort();
      const label = [...g.labels].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0][0];
      return { key: members[0], label, count: g.count, members };
    })
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}

/** Lo elegido (claves de grupo) expandido a todos los miembros de cada grupo: es lo que va al
 *  filtro de tarjetas (passesProjects compara `repo_key || repo` de cada una). */
export function expandSelected(selected: Set<string>, groups: RepoGroup[]): Set<string> {
  if (selected.size === 0) return selected;
  const out = new Set(selected);
  for (const g of groups) if (selected.has(g.key)) for (const m of g.members) out.add(m);
  return out;
}

interface Props {
  groups: RepoGroup[];
  selected: Set<string>;
  coordOnly: boolean;
  onSelectRepo: (key: string) => void;
  /** Ctrl/Cmd + click: suma o saca el proyecto de los elegidos */
  onToggleRepo: (key: string) => void;
  onShowAll: () => void;
  onToggleCoord: () => void;
}

/** Chips de proyecto en el menu de arriba, al lado del buscador y fuera de su fondo (pedido de
 *  Ariel): uno por repo con sesiones vivas y su conteo, mas ★ Coordinadoras. El click elige y nada
 *  mas: queda solo ese proyecto, otro click sobre el elegido no lo suelta, y Todos vuelve a todo.
 *  Ctrl/Cmd + click suma o saca proyectos de los elegidos (varios a la vez). ★ es
 *  la excepcion, se prende y se apaga. Con
 *  un solo repo en el tablero no aparece: no hay nada que elegir. */
export function ProjectStrip({ groups, selected, coordOnly, onSelectRepo, onToggleRepo, onShowAll, onToggleCoord }: Props) {
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
          title={`ver solo las sesiones de ${g.label} (Ctrl + click suma o saca proyectos)`}
          onClick={(e) => (e.ctrlKey || e.metaKey ? onToggleRepo(g.key) : onSelectRepo(g.key))}
        >
          {g.label}
          <sub className="n">{g.count}</sub>
        </button>
      ))}
      <button
        type="button"
        className={`chip pjchip star ${coordOnly ? "on" : ""}`}
        aria-pressed={coordOnly}
        title="ver solo las coordinadoras de los proyectos elegidos (de todos, sin ninguno elegido)"
        onClick={onToggleCoord}
      >
        ★ Coordinadoras
      </button>
    </div>
  );
}
