/** Las opciones del selector «Proyecto» de Lanzar CLI (Launch.tsx), para la PC elegida: arriba las
 *  carpetas abiertas ahora (con una sesión viva) y las permitidas (`launch_roots` que publica cada
 *  PC en su salud); abajo y grisadas las usadas estos días que recuerda `GET /recientes` y no están
 *  arriba; al final los proyectos que solo conocen otras PCs, a los que hay que indicarles la
 *  carpeta. Puro, sin React, para probarlo con node --test. */
import type { Peer, Reciente, Session } from "./types";

/** `cwd` null: proyecto conocido por otra PC; la carpeta en esta se escribe a mano. */
export interface OpcionProyecto {
  key: string;
  label: string;
  cwd: string | null;
  /** título que viaja en el lanzamiento (el nombre del repo o de la carpeta) */
  title: string;
}

export interface GruposProyecto {
  /** abiertas ahora primero, después las carpetas permitidas; sin repetir */
  carpetas: OpcionProyecto[];
  /** usadas estos días que no están en `carpetas`, de la más nueva a la más vieja */
  usadas: OpcionProyecto[];
  otras: OpcionProyecto[];
}

export const nombreCarpeta = (cwd: string) => cwd.replace(/[\\/]+$/, "").split(/[\\/]/).pop() || cwd;

/** Misma carpeta escrita con / o \, con o sin barra final, en cualquier caja (Windows). */
export const claveCarpeta = (cwd: string) => cwd.replace(/\//g, "\\").replace(/\\+$/, "").toLowerCase();

const inicioDia = (t: number) => new Date(t).setHours(0, 0, 0, 0);

/** «hoy», «ayer» o «hace N días», por día calendario local, no por bloques de 24 h. */
export function hace(last: string, ahora = Date.now()): string {
  const t = Date.parse(last);
  if (Number.isNaN(t)) return "";
  const dias = Math.round((inicioDia(ahora) - inicioDia(t)) / 86_400_000);
  if (dias <= 0) return "hoy";
  if (dias === 1) return "ayer";
  return `hace ${dias} días`;
}

export function opcionesProyecto(pc: string, peers: Peer[], sessions: Session[], recientes: Reciente[], ahora = Date.now()): GruposProyecto {
  const localPc = peers.find(p => p.local)?.pc_id ?? "";
  const pcKey = pc || localPc;
  const dePc = (s: Session) => (s.pc || localPc) === pcKey;
  const active = sessions.filter(s => s.alive && !s.stopped_by && s.cwd);
  const roots = peers.find(p => p.pc_id === pcKey)?.health?.launch_roots ?? [];

  // la misma regla que launch._cwd_allowed: la carpeta o algo adentro de una permitida. Sin la lista
  // (server viejo o salud sin llegar) no se filtra: el server dirá que no
  const rootKeys = roots.map(claveCarpeta);
  const permitida = (k: string) => !rootKeys.length || rootKeys.some(r => k === r || k.startsWith(r + "\\"));

  const vistas = new Set<string>();
  const carpetas: OpcionProyecto[] = [];
  const agregar = (cwd: string, title: string, label = title) => {
    const k = claveCarpeta(cwd);
    if (vistas.has(k) || !permitida(k)) return false;
    vistas.add(k);
    carpetas.push({ key: `dir:${k}`, label, cwd, title });
    return true;
  };
  for (const s of active.filter(dePc)) agregar(s.cwd!, s.repo || nombreCarpeta(s.cwd!));
  for (const r of roots) agregar(r, nombreCarpeta(r));

  // el server ya las manda de la más nueva a la más vieja; sin PC conocida (server viejo, sin
  // GET /peers) se muestran todas
  const usadas: OpcionProyecto[] = [];
  for (const r of recientes) {
    if (pcKey && r.pc !== pcKey) continue;
    const k = claveCarpeta(r.cwd);
    if (vistas.has(k) || !permitida(k)) continue;
    vistas.add(k);
    const title = r.repo || nombreCarpeta(r.cwd);
    usadas.push({ key: `dir:${k}`, label: `${title} · ${hace(r.last, ahora)}`, cwd: r.cwd, title });
  }

  const conocidos = new Set([...carpetas, ...usadas].map(o => o.title.toLowerCase()));
  const otras: OpcionProyecto[] = [];
  const vistasRepo = new Set<string>();
  for (const s of active) {
    if (dePc(s)) continue;
    const repoKey = s.repo_key || s.repo || s.cwd!;
    const title = s.repo || nombreCarpeta(s.cwd!);
    if (vistasRepo.has(repoKey) || conocidos.has(title.toLowerCase())) continue;
    vistasRepo.add(repoKey);
    otras.push({ key: `repo:${repoKey}`, label: title, cwd: null, title });
  }
  return { carpetas, usadas, otras };
}
