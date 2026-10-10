import assert from "node:assert/strict";
import { test } from "node:test";
// @ts-ignore TS5097: extension .ts en el import, necesaria para que Node lo resuelva
import { claveCarpeta, hace, nombreCarpeta, opcionesProyecto } from "./recientes.ts";
import type { Peer, Reciente, Session } from "./types";

const AHORA = new Date(2026, 9, 9, 15, 0, 0).getTime(); // 2026-10-09 15:00 local

const iso = (diasAtras: number, hora = 10) => new Date(2026, 9, 9 - diasAtras, hora).toISOString();

const sesion = (o: Partial<Session> & { cwd: string }): Session =>
  ({ session_id: o.cwd, agent: "claude", pid: 1, repo: nombreCarpeta(o.cwd), branch: null, title: null, transcript_path: null,
    state: "termino", state_since: "", needs: null, last_prompt: "", last_reply: "", started: "", last_event: null,
    alive: true, source: "hook", pending_id: null, ...o }) as Session;

const peer = (pc_id: string, local: boolean, roots?: string[]): Peer =>
  ({ pc_id, name: pc_id, color: "#000", alive: true, last_seen: "", local, health: roots ? { launch_roots: roots, mem_free_gb: null, cpu_pct: null, temp_c: null } : null });

test("hace: hoy, ayer y hace N días por día calendario", () => {
  assert.equal(hace(iso(0, 1), AHORA), "hoy"); // 01:00 de hoy: 14 h atrás, sigue siendo hoy
  assert.equal(hace(iso(1, 23), AHORA), "ayer"); // 23:00 de ayer: 16 h atrás, ya es ayer
  assert.equal(hace(iso(3), AHORA), "hace 3 días");
  assert.equal(hace("basura", AHORA), "");
});

test("nombreCarpeta y claveCarpeta normalizan barras, barra final y caja", () => {
  assert.equal(nombreCarpeta("D:\\Apps\\lienzo\\"), "lienzo");
  assert.equal(nombreCarpeta("/home/ariel/chess"), "chess");
  assert.equal(claveCarpeta("D:/Apps/Lienzo/"), claveCarpeta("d:\\apps\\lienzo"));
});

test("opciones: abiertas y permitidas arriba sin «ahora», usadas estos días abajo sin repetir, otras PCs al final", () => {
  const peers = [peer("pcA", true, ["D:\\Apps\\chess", "D:\\Apps\\lienzo", "d:/apps/lienzo/", "D:\\Apps\\Teorema"]), peer("pcB", false, ["E:\\Repos"])];
  const sessions = [
    sesion({ cwd: "D:\\Apps\\Teorema" }), // abierta ahora: primera, aunque también sea permitida
    sesion({ cwd: "D:\\Apps\\lienzo" }),
    sesion({ cwd: "D:\\Apps\\lienzo", session_id: "otra" }), // misma carpeta: una sola opción
    sesion({ cwd: "C:\\tmp\\suelta" }), // abierta, pero fuera de las permitidas: el server la rechazaría
    sesion({ cwd: "E:\\Repos\\demo", pc: "pcB", repo_key: "gh/demo" }), // de la otra PC
    sesion({ cwd: "D:\\Apps\\muerta", alive: false }),
  ];
  const recientes: Reciente[] = [
    { cwd: "D:/Apps/lienzo", repo: "lienzo", pc: "pcA", last: iso(0) }, // ya está arriba: no se repite
    { cwd: "d:\\apps\\teorema", repo: "Teorema", pc: "pcA", last: iso(3) }, // idem, con otra caja
    { cwd: "D:\\Apps\\chess\\motor", repo: "motor", pc: "pcA", last: iso(3) }, // adentro de una permitida
    { cwd: "C:\\Users\\x\\scratch", repo: "scratch", pc: "pcA", last: iso(1) }, // fuera: no se ofrece
    { cwd: "E:\\Repos\\demo", repo: "demo", pc: "pcB", last: iso(1) },
  ];
  const a = opcionesProyecto("pcA", peers, sessions, recientes, AHORA);
  assert.deepEqual(a.carpetas.map(o => o.label), ["Teorema", "lienzo", "chess"]);
  assert.equal(a.carpetas[1].cwd, "D:\\Apps\\lienzo");
  assert.deepEqual(a.usadas.map(o => [o.label, o.cwd]), [["motor · hace 3 días", "D:\\Apps\\chess\\motor"]]);
  assert.deepEqual(a.otras.map(o => [o.label, o.cwd]), [["demo", null]]);

  const b = opcionesProyecto("pcB", peers, sessions, recientes, AHORA);
  assert.deepEqual(b.carpetas.map(o => o.label), ["demo", "Repos"]);
  assert.deepEqual(b.usadas, []);
  assert.deepEqual(b.otras.map(o => o.label), ["Teorema", "lienzo", "suelta"]);
});

test("opciones sin PCs (server viejo): las abiertas como locales, sin permitidas, todas las usadas", () => {
  const sessions = [sesion({ cwd: "D:\\Apps\\lienzo" })];
  const recientes: Reciente[] = [{ cwd: "D:\\Apps\\chess", repo: "chess", pc: "pcA", last: iso(1) }];
  const g = opcionesProyecto("", [], sessions, recientes, AHORA);
  assert.deepEqual(g.carpetas.map(o => o.label), ["lienzo"]);
  assert.deepEqual(g.usadas.map(o => o.label), ["chess · ayer"]);
  assert.deepEqual(g.otras, []);
});

test("opciones: los proyectos en disco de la PC elegida aparecen aunque no tengan sesiones", () => {
  // pedido de Ariel (2026-10-10): mientras la carpeta exista en esa PC, el proyecto se ofrece
  const conCarpetas = (pc_id: string, local: boolean, roots: string[], carpetas: string[]): Peer =>
    ({ ...peer(pc_id, local, roots), health: { launch_roots: roots, carpetas, mem_free_gb: null, cpu_pct: null, temp_c: null } });
  const peers = [conCarpetas("pcA", true, ["D:/Apps"], ["D:/Apps/chess", "D:/Apps/lienzo", "D:/Apps/Teorema"]), conCarpetas("pcB", false, ["D:/apps"], ["D:/apps/lienzo"])];
  const a = opcionesProyecto("pcA", peers, [], [], AHORA);
  assert.deepEqual(a.carpetas.map(o => o.label), ["chess", "lienzo", "Teorema"]);
  // en la otra PC solo lo que existe ahí; la raíz contenedora no se ofrece sola
  const b = opcionesProyecto("pcB", peers, [], [], AHORA);
  assert.deepEqual(b.carpetas.map(o => o.label), ["lienzo"]);
});
