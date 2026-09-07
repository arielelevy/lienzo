import { useEffect, useMemo, useRef, useState } from "react";
import { Arrows } from "./Arrows";
import { Card, freeGroups, shortName } from "./Card";
import type { Link, Pending, Rule, Session, State } from "../types";
import { searchText, stalledReason } from "../names";

/** Columnas del tablero. "Trabajo" junta corriendo y termino (el estado se ve como icono en la
 *  tarjeta); "Te necesita" y "Muerta" siguen aparte porque piden accion. El tipo State es del
 *  server y no cambia: el mapeo estado -> columna vive aca. */
export type ColKey = "trabajo" | "te_necesita" | "muerta";
export const COLS: [ColKey, string][] = [
  ["trabajo", "Trabajo"],
  ["te_necesita", "Te necesita"],
  ["muerta", "Muerta"],
];
export const colOfState = (st: State): ColKey => (st === "corriendo" || st === "termino" ? "trabajo" : st);
/** Columna de una sesion. Una huerfana (proceso vivo pero sin terminal donde escribirle) o una con
 *  el proceso muerto va a "Muerta" aunque su estado diga otra cosa: no se le puede pedir nada. */
export const colOf = (s: Session): ColKey => (s.orphan || s.alive === false ? "muerta" : colOfState(s.state));
/** estado del filtro (State, lo maneja App) que representa a cada columna */
const FILTER_STATE: Record<ColKey, State> = { trabajo: "corriendo", te_necesita: "te_necesita", muerta: "muerta" };

interface Props {
  sessions: Record<string, Session>;
  pending: Record<string, Pending>;
  selected: string | null;
  filter: State;
  onFilter: (s: State) => void;
  onSelect: (sid: string) => void;
  onDecide: (requestId: string, decision: "allow" | "deny") => void;
  onDrop: (sid: string) => void;
  links: Link[];
  rules: Rule[];
  onDeleteLink: (id: string) => void;
  onDeleteRule: (id: string) => void;
  onConnect: (from: string, to: string) => void;
  /** boton del header: con muchas flechas conviene poder apagarlas */
  showArrows: boolean;
  /** filtro del header: texto libre (agente, repo, rama, titulo, ultimo pedido) y agentes visibles */
  query: string;
  agents: Record<Session["agent"], boolean>;
  /** toast global para las acciones de la tarjeta (copiar, botones rapidos, renombrar) */
  toast?: (msg: string, err?: boolean) => void;
}

export type Agent = Session["agent"];

/** Columnas que el usuario colapso a mano teniendo tarjetas: por columna, los ids que tenia en ese
 *  momento. Se respeta mientras la columna solo contenga esas tarjetas; una nueva la abre y borra la
 *  entrada. (El formato viejo, booleanos, se ignora.) */
const COLLAPSE_KEY = "lienzo.collapsed";
type Manual = Partial<Record<ColKey, string[]>>;
function loadManual(): Manual {
  try {
    const raw = localStorage.getItem(COLLAPSE_KEY);
    const j = raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
    const out: Manual = {};
    for (const [k] of COLS) if (Array.isArray(j[k])) out[k] = (j[k] as unknown[]).filter((x): x is string => typeof x === "string");
    return out;
  } catch {
    return {};
  }
}
const EMPTY_COLLAPSE_MS = 5_000;   // pedido de Ariel: 10 s se sentia largo

/** Ancho al que se lee comoda una tarjeta del lienzo: titulo de una linea, dos del pedido, hasta
 *  seis de la respuesta y una del comando. Con 300 px entra todo eso, pero 300 como objetivo dejaba
 *  **3 subcolumnas de 350 px** en una ventana de 1280, que es donde se usa el lienzo: la tarjeta
 *  queda ancha y vacia y se pierde una subcolumna. Con 265 la misma ventana da 4 de 253 px, y el
 *  resto no se mueve (1440: 4 de 294; 1600: 5 de 260; 1920: 6 de 264). Abajo de 1200 sigue en 3,
 *  para no caer a 220. Mas ancho que esto no agrega lineas de texto, solo aire.
 *  El titulo si se corta: el server los recorta a 60 caracteres, que son ~380 px, asi que a este
 *  ancho la mayoria queda con puntos suspensivos. Es a proposito: se prefiere ver mas tarjetas. */
const ANCHO_TARJETA = 265;

/** Cuantas subcolumnas de tarjetas entran en total. No hay tope fijo: se mide el ancho que queda
 *  **para las tarjetas** (la suma de los `.cards` de las columnas abiertas, sin su relleno) y se
 *  elige la cantidad que deje la tarjeta mas cerca de ANCHO_TARJETA, en proporcion (350 y 260 estan
 *  igual de lejos de 300 en pixeles, pero 260 se lee peor). Se mide del DOM y no de la ventana
 *  porque el ancho util no es el de la ventana: las tiras de las columnas colapsadas ocupan lo
 *  suyo, cada columna tiene su relleno y el tablero se puede angostar (el panel de hoy flota por
 *  encima, pero abajo de 900 px le come lugar). Ese ancho no depende de cuantas subcolumnas haya
 *  (medido: 2401, 2400 y 2401 px con 4, 5 y 6), asi que la cuenta no se realimenta.
 *  El ancho de la tarjeta no puede ser estrictamente monotono con subcolumnas enteras --al pasar de
 *  4 a 3 el ancho sube por definicion, porque es el mismo lugar dividido en menos partes--, asi que
 *  ANCHO_TARJETA es tambien un techo: lo que sobra va al canal entre subcolumnas (ver `medir`), y
 *  la tarjeta queda entre 243 y 300 px en todo el rango en vez de 222 a 574. */
const MAX_LANES = 12;

function useLaneBudget(ref: React.RefObject<HTMLElement | null>): number {
  const [budget, setBudget] = useState(2);
  const medir = () => {
    const board = ref.current;
    if (!board) return;
    const gap = parseFloat(getComputedStyle(board).getPropertyValue("--col-gap")) || 35;
    let util = 0;
    const cajas: { el: HTMLElement; u: number; n: number }[] = [];
    for (const el of board.querySelectorAll<HTMLElement>(".col:not(.collapsed) .cards")) {
      const cs = getComputedStyle(el);
      const u = el.clientWidth - parseFloat(cs.paddingLeft || "0") - parseFloat(cs.paddingRight || "0");
      util += u;
      cajas.push({ el, u, n: parseInt(cs.columnCount) || 1 });
    }
    if (util <= 0) return; // todas colapsadas: se queda con el reparto que tenia
    // Techo del ancho de tarjeta: lo que sobra despues de darle ANCHO_TARJETA a cada subcolumna se
    // reparte en el canal que las separa, no en estirar las tarjetas. Se usa el column-count que
    // **aplica** el CSS (en movil lo fuerza a 1, y ahi la tarjeta va a lo ancho de la pantalla), y
    // se toca solo el column-gap: el ancho de `.cards` no cambia, asi que la cuenta de abajo no se
    // realimenta. Con una sola subcolumna no hay canal donde poner el sobrante y no se recorta.
    for (const c of cajas) {
      const sobra = c.n >= 2 ? c.u - (c.n * ANCHO_TARJETA + (c.n - 1) * gap) : 0;
      c.el.style.columnGap = sobra > 1 ? `${gap + sobra / (c.n - 1)}px` : "";
    }
    // cuantas subcolumnas entran con la tarjeta en su ancho objetivo, redondeando. Con el techo
    // puesto, redondear para abajo ("las que entren justas") deja la tarjeta clavada en
    // ANCHO_TARJETA pero junta todo el sobrante en el canal, y cuando falta poco para otra
    // subcolumna eso es casi una tarjeta de aire (medido a 960 px: 2 subcolumnas y un canal de
    // 320 px, un agujero en el medio del tablero). Redondeando, el sobrante nunca pasa de media
    // subcolumna y la tarjeta se queda entre 236 y 265 px, siempre por debajo del techo.
    setBudget(Math.max(1, Math.min(MAX_LANES, Math.round((util + gap) / (ANCHO_TARJETA + gap)))));
  };
  // en cada render (una columna que se abre o se colapsa cambia el ancho util sin que cambie el
  // del tablero) y ademas con cada cambio de tamano del tablero
  useEffect(medir);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const o = new ResizeObserver(medir);
    o.observe(el);
    return () => o.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ref]);
  return budget;
}

/** Reparte `budget` subcolumnas entre las columnas abiertas: una para cada una y el resto en
 *  proporcion a cuantas tarjetas tiene, sin que ninguna se lleve mas subcolumnas que tarjetas. Lo
 *  que sobra por ese tope vuelve a la que mas tarjetas tenga, asi el ancho util no se desperdicia.
 *  Cada columna crece despues en proporcion a sus subcolumnas (flexGrow), y por eso todas las
 *  tarjetas del tablero terminan del mismo ancho. */
export function splitLanes(open: { key: ColKey; n: number }[], budget: number): Record<ColKey, number> {
  const out = { trabajo: 1, te_necesita: 1, muerta: 1 } as Record<ColKey, number>;
  if (!open.length) return out;
  const tope = (o: { n: number }) => Math.max(1, o.n);
  for (const o of open) out[o.key] = 1;
  let resto = budget - open.length;
  const total = open.reduce((a, o) => a + o.n, 0);
  if (resto > 0 && total > 0) {
    for (const o of open) {
      const suma = Math.max(0, Math.min(Math.floor((resto * o.n) / total), tope(o) - out[o.key]));
      out[o.key] += suma;
    }
    resto = budget - open.reduce((a, o) => a + out[o.key], 0);
    // el sobrante (por el redondeo hacia abajo y por el tope) va de a una a las que mas tarjetas
    // tienen, mientras quede lugar
    const orden = [...open].sort((a, b) => b.n - a.n);
    let cambio = true;
    while (resto > 0 && cambio) {
      cambio = false;
      for (const o of orden) {
        if (resto <= 0) break;
        if (out[o.key] < tope(o)) {
          out[o.key]++;
          resto--;
          cambio = true;
        }
      }
    }
  }
  return out;
}

const norm = (s: string) => s.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");

const canReceive = (s: Session | undefined) => !!s && s.alive && !!s.pid && !s.orphan && !s.no_console;
/** Card dibuja el agarre ⇢ si recibe onGrip; el arrastre en si lo maneja el tablero por Pointer Events */
const noGrip = () => undefined;

interface Drag {
  from: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  over: string | null;
}

export function Board({ sessions, pending, selected, filter, onFilter, onSelect, onDecide, onDrop, links, rules, onDeleteLink, onDeleteRule, onConnect, showArrows, query, agents, toast }: Props) {
  const boardRef = useRef<HTMLDivElement | null>(null);
  // el arrastre vive en el ref (los listeners de document lo leen al instante, sin esperar el
  // render) y se copia al estado para dibujar la linea
  const dragRef = useRef<Drag | null>(null);
  const [drag, setDragState] = useState<Drag | null>(null);
  const setDrag = (d: Drag | null) => {
    dragRef.current = d;
    setDragState(d);
  };
  // tarjeta bajo el mouse: Arrows resalta sus flechas y atenua las demas
  const [hover, setHover] = useState<string | null>(null);
  // tarjeta elegida con un click: se resalta, muestra sus conexiones en palabras y sus flechas
  // quedan resaltadas (por el mismo camino que el hover). Es distinto de `selected`, que es la que
  // tiene el panel abierto: se puede tener el panel de una y elegida otra.
  const [picked, setPicked] = useState<string | null>(null);
  useEffect(() => {
    if (picked && !sessions[picked]) setPicked(null); // se fue la sesion elegida
  }, [sessions, picked]);
  // El arrastre va por Pointer Events, asi funciona igual con mouse y con el dedo. Presion sobre el
  // cuerpo de una tarjeta (solo mouse: con el dedo el cuerpo scrollea): es arrastre si se mueve mas
  // de 8 px, si no es click. Desde el agarre ⇢ arrastra de una, con cualquier puntero (.grip lleva
  // touch-action: none para que el scroll no se lo lleve).
  const pressRef = useRef<{ sid: string; x: number; y: number } | null>(null);
  const draggedRef = useRef(false);
  const draggedTimer = useRef<number | undefined>(undefined);

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    const t = e.target as HTMLElement;
    const sid = t.closest<HTMLElement>("[data-sid]")?.dataset.sid;
    // una muerta, huerfana o sin consola no arrastra: no habria a donde escribir ni que programarle
    if (!sid || !canReceive(sessions[sid])) return;
    if (t.closest(".grip")) {
      draggedRef.current = true;
      startDragAt(sid, e.clientX, e.clientY);
      return;
    }
    if (e.pointerType !== "mouse" || t.closest("button, a, input, textarea, .x, code")) return;
    // se arrastra desde la fila de arriba y el titulo; el cuerpo de la tarjeta es texto que se
    // lee y se copia, y arrastrar desde ahi se llevaba puesta la seleccion
    if (!t.closest(".top, .title, .freeline")) return;
    pressRef.current = { sid, x: e.clientX, y: e.clientY };
  };

  // una pasada por render: las sesiones que pasan el filtro del header, agrupadas por columna.
  // En "Trabajo" van primero las que corren (por repo + inicio) y despues las terminadas, la mas
  // reciente arriba. El filtro es solo visual: el server no se entera.
  const byState = useMemo(() => {
    const q = norm(query.trim());
    const g: Record<ColKey, Session[]> = { trabajo: [], te_necesita: [], muerta: [] };
    for (const s of Object.values(sessions)) {
      if (!agents[s.agent]) continue;
      if (q && !norm(searchText(s)).includes(q)) continue;
      g[colOf(s)].push(s);
    }
    // lo que esta trabajando de verdad va primero; lo que termino, despues; lo que figura corriendo
    // pero esta quieto (sin cupo, o sin actividad hace rato), al final. Con las tarjetas repartidas
    // en subcolumnas, "al final" es "a la derecha"
    // el permiso pendiente va primero de todo: vence a los 60 s
    const rank = (s: Session) => (s.pending_id && pending[s.pending_id] ? -1 : stalledReason(s) ? 2 : s.state === "termino" ? 1 : 0);
    for (const k of COLS.map(([k]) => k)) {
      g[k].sort((a, b) => {
        if (rank(a) !== rank(b)) return rank(a) - rank(b);
        if (rank(a) > 0) return b.state_since.localeCompare(a.state_since);
        return (a.repo + a.started).localeCompare(b.repo + b.started);
      });
    }
    return g;
  }, [sessions, pending, query, agents]);

  // Una tarjeta con permiso pendiente va antes que las demas en el recorrido de Tab: el orden del
  // Tab es el del DOM, asi que su columna se dibuja primero y el orden visual se repone con `order`
  // (el tablero es flex). El canal de 30 px entre columnas sale de `.col + .col`, que es adyacencia
  // del DOM: mientras dura el adelanto lo pone card.css por `.board.reordered`.
  const urgent = useMemo(() => COLS.map(([k]) => k).find((k) => byState[k].some((s) => s.pending_id && pending[s.pending_id])) ?? null, [byState, pending]);
  const domCols = useMemo(() => {
    const cols = COLS.map(([k, label], visual) => ({ k, label, visual }));
    return urgent ? [...cols.filter((c) => c.k === urgent), ...cols.filter((c) => c.k !== urgent)] : cols;
  }, [urgent]);

  // columnas colapsadas a la tira vertical. Regla: abierta si tiene tarjetas, colapsada si no, las
  // tres por igual. Encima de eso, dos excepciones:
  //  - `manual` (localStorage lienzo.collapsed): el usuario colapso a mano una columna con tarjetas.
  //    Se guarda con los ids que tenia y se respeta mientras solo contenga esas; una tarjeta nueva la
  //    vuelve a abrir y borra la eleccion.
  //  - `openEmpty` (solo en memoria): una columna vacia que esta abierta (el usuario la abrio, o se
  //    vacio estando abierta) se cierra sola a los 5 s.
  // Mientras el filtro del header (texto o agentes) matchea tarjetas de una columna colapsada, esa
  // columna se muestra abierta sin tocar nada de lo anterior.
  const [manual, setManual] = useState<Manual>(loadManual);
  const [openEmpty, setOpenEmpty] = useState<Partial<Record<ColKey, boolean>>>({});
  const emptyTimers = useRef<Partial<Record<ColKey, number>>>({});
  const filtering = query.trim() !== "" || Object.values(agents).some((v) => !v);
  const saveManual = (next: Manual) => {
    setManual(next);
    try {
      localStorage.setItem(COLLAPSE_KEY, JSON.stringify(next));
    } catch {
      /* sin storage, no importa */
    }
  };
  const stopEmptyTimer = (k: ColKey) => {
    window.clearTimeout(emptyTimers.current[k]);
    emptyTimers.current[k] = undefined;
  };
  // columna vacia abierta: 5 s y se cierra sola
  const holdOpenEmpty = (k: ColKey) => {
    stopEmptyTimer(k);
    setOpenEmpty((o) => ({ ...o, [k]: true }));
    emptyTimers.current[k] = window.setTimeout(() => {
      emptyTimers.current[k] = undefined;
      setOpenEmpty((o) => ({ ...o, [k]: false }));
    }, EMPTY_COLLAPSE_MS);
  };
  const setCol = (k: ColKey, collapse: boolean) => {
    const ids = byState[k].map((s) => s.session_id);
    if (collapse) {
      stopEmptyTimer(k);
      setOpenEmpty((o) => ({ ...o, [k]: false }));
      if (ids.length) saveManual({ ...manual, [k]: ids });
    } else if (ids.length) {
      const { [k]: _drop, ...rest } = manual;
      saveManual(rest);
    } else {
      holdOpenEmpty(k);
    }
  };
  // con cada cambio de tarjetas: una nueva en una columna colapsada a mano la abre (y borra la
  // eleccion); una columna abierta que se vacia arranca sus 5 s; una que recibe tarjetas deja de
  // depender del timer
  const prevCount = useRef<Record<ColKey, number>>(Object.fromEntries(COLS.map(([k]) => [k, byState[k].length])) as Record<ColKey, number>);
  useEffect(() => {
    let next = manual;
    let changed = false;
    for (const [k] of COLS) {
      const ids = byState[k].map((s) => s.session_id);
      const kept = next[k];
      if (kept && ids.some((id) => !kept.includes(id))) {
        const { [k]: _drop, ...rest } = next;
        next = rest;
        changed = true;
      }
      const n = ids.length;
      if (n === 0 && prevCount.current[k] > 0) holdOpenEmpty(k);
      if (n > 0 && emptyTimers.current[k] !== undefined) stopEmptyTimer(k);
      prevCount.current[k] = n;
    }
    if (changed) saveManual(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [byState]);
  useEffect(() => () => [...Object.values(emptyTimers.current), draggedTimer.current].forEach((t) => window.clearTimeout(t)), []);

  // la columna Muerta arranca colapsada aunque tenga tarjetas: lo que esta ahi ya no se puede
  // tocar. El usuario la abre con un click y la eleccion queda en el navegador
  const [openDead, setOpenDead] = useState(() => {
    try {
      return localStorage.getItem("lienzo.openDead") === "1";
    } catch {
      return false;
    }
  });

  const setDead = (open: boolean) => {
    setOpenDead(open);
    try {
      localStorage.setItem("lienzo.openDead", open ? "1" : "0");
    } catch {
      /* sin storage, no importa */
    }
  };

  const isCollapsed = (k: ColKey, n: number) => {
    if (filtering && n > 0) return false;
    // "Muerta" arranca colapsada aunque tenga tarjetas: una sesion muerta no se puede hacer nada
    // con ella, es historial. Se abre con un click en la tira y esa eleccion se recuerda.
    // Va ANTES del caso de la columna vacia: al reves, una Muerta sin tarjetas se decidia por
    // `openEmpty`, que el click en su tira no toca (llama a `setDead`), y no se abria nunca.
    // Medido: la tira quedaba en 20 px por mas clicks que recibiera.
    if (k === "muerta") return !openDead;
    if (n === 0) return !openEmpty[k];
    return !!manual[k];
  };

  // aprovechar el ancho: hasta 4 subcolumnas de tarjetas en total (2 en pantallas angostas),
  // repartidas entre las columnas abiertas. Cada columna crece en proporcion a sus subcolumnas,
  // asi todas las tarjetas del tablero quedan del mismo ancho
  const laneBudget = useLaneBudget(boardRef);
  const lanes = useMemo(() => {
    const open = COLS.map(([k]) => k)
      .filter((k) => !isCollapsed(k, byState[k].length))
      .map((k) => ({ key: k, n: byState[k].length }));
    return splitLanes(open, laneBudget);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [manual, openEmpty, byState, filtering, laneBudget]);

  // colapso por columna, para que el canal entre columnas mire al vecino *visual* y no al del DOM
  // (mientras una columna se adelanta por un permiso pendiente no son el mismo)
  const collapsedOf = Object.fromEntries(COLS.map(([k]) => [k, isCollapsed(k, byState[k].length)])) as Record<ColKey, boolean>;

  // el server no conoce ninguna sesión (no: "el filtro no dejó ninguna"): recién instalado, o
  // arrancado antes que los agentes. Es el único caso que se explica; si lo que vacía el tablero
  // es el filtro del header, el que lo escribió ya sabe por qué no ve nada
  const sinTarjetas = Object.keys(sessions).length === 0;

  // las flechas se recalculan cuando algo pudo mover una tarjeta
  const versionRef = useRef(0);
  // al elegir una tarjeta se explican sus conexiones, y tambien las de la del otro extremo: una
  // conexion tiene dos puntas y se entiende mirando las dos. La del otro extremo muestra *solo* lo
  // que comparte con la elegida (si ademas tiene reglas con otras tres sesiones, esas no vienen al
  // caso, y escribirlas le cambiaba el alto a media pantalla): lo que le llego de ella --lo que la
  // elegida recibio se lee en la elegida-- y las reglas que las unen, en cualquier direccion.
  const related = useMemo(() => {
    const out = new Map<string, { links: Link[]; rules: Rule[] }>();
    if (!picked) return out;
    const at = (sid: string) => {
      let e = out.get(sid);
      if (!e) out.set(sid, (e = { links: [], rules: [] }));
      return e;
    };
    for (const l of links) if (l.from === picked && l.to && l.to !== picked) at(l.to).links.push(l);
    for (const r of rules) {
      if (!r.enabled) continue;
      if (r.from === picked && r.to && r.to !== picked) at(r.to).rules.push(r);
      else if (r.to === picked && r.from && r.from !== picked) at(r.from).rules.push(r);
    }
    return out;
  }, [picked, links, rules]);

  const arrowsVersion = useMemo(() => ++versionRef.current, [sessions, filter, selected, picked, manual, openEmpty, query, agents, laneBudget]);

  // arrastre de una tarjeta a otra: linea provisoria que sigue al mouse, al soltar sobre otra
  // tarjeta se abre el reenvio con ese destino
  const startDragAt = (sid: string, cx: number, cy: number) => {
    const board = boardRef.current;
    if (!board) return;
    const b = board.getBoundingClientRect();
    // la linea sale del agarre ⇢ (fila de arriba de la tarjeta); sin agarre, del mouse
    const card = board.querySelector<HTMLElement>(`[data-sid="${sid}"]`);
    const r = card?.querySelector<HTMLElement>(".grip")?.getBoundingClientRect();
    const x1 = r ? (r.left + r.right) / 2 - b.left : cx - b.left;
    const y1 = r ? (r.top + r.bottom) / 2 - b.top : cy - b.top;
    setDrag({ from: sid, x1, y1, x2: cx - b.left, y2: cy - b.top, over: null });
  };
  // un solo juego de listeners en document, suscrito una vez: sin arrastre siguen la presion
  // (arranca a los 8 px); con arrastre mueven la linea y resuelven el destino al soltar
  useEffect(() => {
    // tarjeta con consola bajo el puntero (la propia tambien: la flecha que vuelve al mismo bloque
    // es un bucle, "programale un mensaje a esta misma sesion")
    const cardAt = (e: PointerEvent) => {
      const sid = document.elementFromPoint(e.clientX, e.clientY)?.closest<HTMLElement>("[data-sid]")?.dataset.sid;
      return sid && canReceive(sessions[sid]) ? sid : null;
    };
    const move = (e: PointerEvent) => {
      const board = boardRef.current;
      if (!board) return;
      const d = dragRef.current;
      if (d) {
        const b = board.getBoundingClientRect();
        setDrag({ ...d, x2: e.clientX - b.left, y2: e.clientY - b.top, over: cardAt(e) });
        return;
      }
      const pr = pressRef.current;
      if (pr && Math.hypot(e.clientX - pr.x, e.clientY - pr.y) > 8) {
        pressRef.current = null;
        draggedRef.current = true;
        startDragAt(pr.sid, e.clientX, e.clientY);
      }
    };
    const up = (e: PointerEvent) => {
      pressRef.current = null;
      // el click (si lo hay) llega despues del pointerup, y la tarjeta lo demora PICK_MS para
      // distinguirlo del doble click: la marca tiene que sobrevivir a esa demora (y a un arrastre
      // anterior muy reciente, cuyo timer no debe borrarla antes de tiempo)
      window.clearTimeout(draggedTimer.current);
      draggedTimer.current = window.setTimeout(() => {
        draggedRef.current = false;
      }, 400);
      const d = dragRef.current;
      if (!d) return;
      // soltar sobre una muerta, huerfana o sin consola no conecta: no habria a donde escribir.
      // Sobre si misma (solo si el arrastre ya arranco: un click sin mover nunca llega aca) abre el
      // dialogo con from === to, que Forward toma como "programar para esta sesion"
      const to = cardAt(e);
      setDrag(null);
      if (to) onConnect(d.from, to);
    };
    const key = (e: KeyboardEvent) => {
      // Esc durante un arrastre lo cancela (soltar en cualquier lado, tambien); si no, deselecciona
      if (e.key !== "Escape") return;
      if (dragRef.current) setDrag(null);
      // Esc pela una capa por vez: con el panel abierto lo cierra App y la eleccion queda; el
      // siguiente Esc la suelta. Sin este guard, un solo Esc hacia las dos cosas.
      else if (!selected) setPicked(null);
    };
    const cancel = () => {
      pressRef.current = null;
      setDrag(null); // el navegador se quedo el puntero (scroll, gesto del sistema)
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
    document.addEventListener("pointercancel", cancel);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      document.removeEventListener("pointercancel", cancel);
      document.removeEventListener("keydown", key);
    };
  }, [sessions, onConnect, selected]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      {/* selector de columna, solo abajo de 900 px (una columna por vez). Un permiso pendiente en
          otra columna se marca con un punto: ahi no se ven las tarjetas, y sin la marca el pedido
          pasaba desapercibido hasta que vencia */}
      <div className="filters">
        {COLS.map(([k, label]) => {
          const pide = byState[k].some((x) => x.pending_id && pending[x.pending_id]);
          const aca = colOfState(filter) === k;
          return (
            <button
              key={k}
              className={`${aca ? "on" : ""} ${pide && !aca ? "pide" : ""}`}
              title={pide ? "una sesión de esta columna está esperando un permiso" : undefined}
              onClick={() => onFilter(FILTER_STATE[k])}
            >
              {label} {byState[k].length}
              {pide && !aca && <span className="pin" aria-label="hay un permiso esperando" />}
            </button>
          );
        })}
      </div>
      <div
        className={`board ${drag ? "dragging" : ""} ${urgent ? "reordered" : ""}`}
        ref={boardRef}
        onPointerDown={onPointerDown}
        onClick={(e) => {
          // click en el vacio del tablero: deselecciona (como Esc)
          if (!(e.target as HTMLElement).closest("[data-sid]")) setPicked(null);
        }}
        onMouseOver={(e) => {
          const sid = (e.target as HTMLElement).closest<HTMLElement>("[data-sid]")?.dataset.sid ?? null;
          setHover((h) => (h === sid ? h : sid));
        }}
        onMouseLeave={() => setHover(null)}
      >
        {/* sin nada bajo el mouse, las flechas resaltadas son las de la tarjeta elegida */}
        {showArrows && <Arrows links={links} rules={rules} sessions={sessions} boardRef={boardRef} version={arrowsVersion} hover={hover ?? picked} onDelete={onDeleteLink} onDeleteRule={onDeleteRule} toast={toast} />}
        {drag && (
          <>
            <svg className="arrows draglink">
              <line x1={drag.x1} y1={drag.y1} x2={drag.x2} y2={drag.y2} />
            </svg>
            <div className="draghint">
              {drag.over === drag.from
                ? "Soltá acá para programarle un mensaje a esta sesión (a una hora o cada tanto)"
                : drag.over
                  ? `Soltá para conectar con ${shortName(sessions[drag.over])}`
                  : "Soltá sobre otra tarjeta para conectar, o sobre la misma para programarle un mensaje · Esc cancela"}
            </div>
          </>
        )}
        {domCols.map(({ k, label, visual }) => {
          const list = byState[k];
          // las libres de un mismo repo y agente se leen como un dato solo ("4 sesiones libres
          // en lienzo"), no como cuatro tarjetas que dicen exactamente lo mismo. La elegida y la
          // que tiene el panel abierto quedan afuera del grupo, asi siguen enteras
          const grupos = freeGroups(list, [selected, picked]);
          const col = collapsedOf[k];
          // canal a la izquierda, mirando al vecino *visual*: 8 px si alguno de los dos es una tira
          // colapsada, 30 si no (es lo mismo que dice styles.css, pero ahi sale de la adyacencia del
          // DOM, que con el adelanto por permiso pendiente ya no es la que se ve)
          const gap = visual === 0 ? "first" : collapsedOf[COLS[visual - 1][0]] || col ? "gapthin" : "gapwide";
          const wide = lanes[k] > 1;
          // la columna lleva ademas las clases de los estados que contiene: Arrows ubica la tira de
          // una columna colapsada por `.col.<estado>.collapsed`, con el estado de la sesion
          const stateClasses = k === "trabajo" ? "corriendo termino" : k;
          return (
            <div
              key={k}
              className={`col ${k} ${stateClasses} ${col ? "collapsed" : ""} ${wide ? "wide" : ""} ${gap} ${colOfState(filter) === k ? "show" : ""}`}
              style={{ order: visual, ...(col ? {} : { flexGrow: lanes[k], "--lanes": lanes[k] }) } as React.CSSProperties}
            >
              {col ? (
                <>
                  <div
                    className="vlabel"
                    role="button"
                    tabIndex={0}
                    title={`${label}: ${list.length} · click para expandir`}
                    onClick={() => (k === "muerta" ? setDead(true) : setCol(k, false))}
                    onKeyDown={(e) => e.key === "Enter" && (k === "muerta" ? setDead(true) : setCol(k, false))}
                  >
                    <span>{label}</span>
                    <span className="n">{list.length}</span>
                  </div>
                  {/* con el tablero entero vacío no se repite "nada acá" por columna: eso ya lo
                      dice, y mejor, el cartel de primera vez */}
                  {!sinTarjetas && <div className="empty">{list.length ? `${list.length} ocultas` : "nada acá"}</div>}
                </>
              ) : (
                <>
                  {/* Trabajo con tarjetas no se colapsa a mano: es el contenido del tablero y
                      colapsarla deja la pantalla vacia. Vacia si se colapsa sola, como las demas */}
                  <h2
                    className={k === "trabajo" && list.length > 0 ? "fixed" : ""}
                    title={k === "trabajo" && list.length > 0 ? "la columna del trabajo no se colapsa: es lo que estás mirando" : "click para colapsar la columna"}
                    onClick={() => {
                      if (k === "trabajo" && list.length > 0) return;
                      if (k === "muerta") return setDead(false);
                      setCol(k, true);
                    }}
                  >
                    <span>{label}</span>
                    <span className="n">{list.length}</span>
                  </h2>
                  {list.length === 0 && !sinTarjetas && <div className="empty">nada acá</div>}
                  <div className="cards">
                  {/* columna ancha: subcolumnas por CSS (column-count: var(--lanes) en .col.wide .cards),
                      no por padres distintos: si una tarjeta cambiara de subcolumna React la remontaria
                      y perderia su estado (pedido expandido, input de renombrar, toast) */}
                  {list.map((s) => (
                    <div key={s.session_id} className={drag?.over === s.session_id ? "droptarget" : ""}>
                      <Card
                        session={s}
                        pending={s.pending_id ? pending[s.pending_id] : undefined}
                        rules={rules.filter((r) => r.enabled && (r.to === s.session_id || r.from === s.session_id))}
                        links={links.filter((l) => l.to === s.session_id)}
                        sessions={sessions}
                        onDeleteRule={onDeleteRule}
                        toast={toast}
                        selected={selected === s.session_id}
                        picked={picked === s.session_id}
                        related={related.get(s.session_id)}
                        freeGroup={grupos.get(s.session_id)}
                        onPick={() => {
                          // el click que cierra un arrastre tampoco elige la tarjeta
                          if (draggedRef.current) return;
                          // el segundo click sobre la misma la deselecciona: es el mismo gesto de
                          // ida y vuelta, sin tener que buscar el vacio ni acordarse de Escape
                          setPicked((prev) => (prev === s.session_id ? null : s.session_id));
                        }}
                        onSelect={() => {
                          // el click que cierra un arrastre no abre el panel
                          if (draggedRef.current) {
                            draggedRef.current = false;
                            return;
                          }
                          onSelect(s.session_id);
                        }}
                        onDecide={onDecide}
                        onDrop={() => onDrop(s.session_id)}
                        onGrip={noGrip}
                      />
                    </div>
                  ))}
                  </div>
                </>
              )}
            </div>
          );
        })}
        {/* Tablero sin una sola tarjeta (recién instalado, o el server arrancado antes que los
            agentes): las tres columnas colapsan a sus tiras y la pantalla queda en negro sin decir
            nada. Las columnas siguen colapsadas —esa regla no cambia—, el cartel va al lado. */}
        {sinTarjetas && (
          <div className="empty primeravez">
            <b>Todavía no hay ninguna sesión.</b>
            <span>Abrí Claude Code o Codex en un repo y la tarjeta aparece sola.</span>
            <span>
              Si no aparece, corré <code>python install.py</code> en la carpeta del lienzo: registra los hooks.
            </span>
          </div>
        )}
      </div>
    </>
  );
}
