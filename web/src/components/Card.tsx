import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { ago, api, detail } from "../api";
import { hhmm } from "../nl";
import { canWrite, foldPrompt, foldSentence, isFree, linkSentences, needsLabel, periodLabel, plainText, ruleSentence, shortName, titleIsPrompt, whenLabel, stalledReason } from "../names";
import { Ask, askQuestions } from "./Ask";
import type { Link, Pending, Rule, Session } from "../types";
import "../card.css";

/** Los nombres y textos viven en names.ts; App, Board, Forward, SendBox, Arrows y Panel los
 *  siguen importando de aca. */
export { shortName, plainText, whenLabel, periodLabel };

export type ToastFn = (msg: string, err?: boolean) => void;

/** Toast: si el componente recibe el global por props lo usa; si no, muestra uno chico propio
 *  (posicionado dentro del contenedor, que tiene que ser position: relative). */
export function useLocalToast(external?: ToastFn) {
  const [msg, setMsg] = useState<{ text: string; err: boolean } | null>(null);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const toast = useCallback<ToastFn>(
    (text, err = false) => {
      if (external) {
        external(text, err);
        return;
      }
      setMsg({ text, err });
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setMsg(null), 2500);
    },
    [external],
  );
  const node =
    msg && !external ? (
      <div className={`ctoast ${msg.err ? "err" : ""}`} role="status">
        {msg.text}
      </div>
    ) : null;
  return { toast, node };
}

export async function copyText(text: string, toast: ToastFn) {
  try {
    await navigator.clipboard.writeText(text);
    toast("copiado");
  } catch (e) {
    toast(`no se pudo copiar: ${(e as Error).message}`, true);
  }
}

/** el server que corre es anterior a esa ruta (404 crudo, o su JSON "ruta desconocida") */
const noRoute = (m: string) => m === "404" || m === "ruta desconocida";

/** Renombrar en el lugar: `start` abre un input con el titulo actual (seleccionado); Enter guarda
 *  por PUT /sessions/<sid>/title, Escape o blur cancelan. Devuelve el input listo para poner donde
 *  iba el titulo. */
function useRename(s: Session, toast: ToastFn) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);
  const start = () => {
    setDraft(s.title || "");
    setEditing(true);
  };
  const save = async () => {
    const title = draft.trim();
    setEditing(false);
    if (!title || title === (s.title || "")) return;
    try {
      await api.put(`/sessions/${s.session_id}/title`, { title });
      toast("título guardado");
    } catch (e) {
      const m = (e as Error).message;
      toast(noRoute(m) ? "reiniciá el server" : `No se pudo renombrar: ${m}`, true);
    }
  };
  const input = editing ? (
    <input
      ref={inputRef}
      value={draft}
      aria-label="nuevo título"
      onChange={(e) => setDraft(e.target.value)}
      onClick={(e) => e.stopPropagation()}
      onBlur={() => setEditing(false)}
      onKeyDown={(e) => {
        e.stopPropagation();
        if (e.key === "Enter") {
          e.preventDefault();
          save();
        } else if (e.key === "Escape") {
          e.preventDefault();
          setEditing(false);
        }
      }}
    />
  ) : null;
  return { editing, start, input };
}

/** Las conexiones de la tarjeta elegida, en palabras: una frase por linea, con su ✕ las reglas (lo
 *  ya recibido no se puede quitar). Como mucho dos, y el resto contado en "+N mas", como hacian los
 *  chips: la coordinadora tiene 20 reglas activas y las escribia todas (medido: la tarjeta pasaba
 *  de 205 a 559 px). El bloque se dibuja por encima, colgado del borde de abajo (card.css), asi
 *  elegir una tarjeta no cambia ningun alto ni mueve a las demas de subcolumna. */
const MAX_WORDS = 2;

function CardWords({ sid, rules, links, sessions, onDelete }: { sid: string; rules: Rule[]; links: Link[]; sessions: Record<string, Session>; onDelete?: (id: string) => void }) {
  const items = [
    ...linkSentences(links, sid, sessions).map((t) => ({ key: t, text: t, id: null as string | null })),
    ...rules.map((r) => ({ key: r.id, text: ruleSentence(r, sid, sessions), id: r.id })),
  ];
  if (!items.length) return null;
  const rest = items.slice(MAX_WORDS);
  return (
    <div className="words">
      {items.slice(0, MAX_WORDS).map((it) => (
        <div key={it.key} className={`w ${it.id ? "" : "done"}`}>
          <span>{it.text}</span>
          {it.id && (
            <button
              type="button"
              className="del"
              title="quitar"
              aria-label="quitar conexión"
              onClick={(e) => {
                e.stopPropagation();
                if (confirm("Quitar esta conexión?")) onDelete?.(it.id!);
              }}
            >
              ✕
            </button>
          )}
        </div>
      ))}
      {!!rest.length && (
        <div className="w more" title={rest.map((r) => r.text).join("\n") + "\n\nEstán todas en la pestaña Conexiones del panel."}>
          +{rest.length} más
        </div>
      )}
    </div>
  );
}

/** Cuatro sesiones recien abiertas del mismo repo dicen exactamente lo mismo ("Libre · sin pedidos
 *  todavía · desde hace 1 min") y ocupan una fila entera del tablero para no decir nada: para el que
 *  mira, "hay cuatro libres" es **un solo dato**. Se juntan entonces en una tarjeta sola, que se
 *  despliega cuando hace falta elegir a cual. La primera de la lista la encabeza (el orden lo fijo
 *  el tablero); en cuanto una recibe un pedido deja de ser libre, sale del grupo y vuelve a ser su
 *  tarjeta, sin que nadie tenga que acordarse de sacarla. */
export type FreeGroup = { lead: true; mates: Session[] } | { lead: false };

/** Las libres de un mismo repo y agente, de a dos o mas, forman grupo. Mismo agente porque la
 *  tarjeta lleva un solo badge y "4 libres en lienzo" con dos agentes adentro seria mentira a
 *  medias. `keep` son las que quedan afuera pase lo que pase: la elegida y la que tiene el panel
 *  abierto se siguen viendo enteras, y asi el numero del grupo tampoco miente. */
export function freeGroups(list: Session[], keep: (string | null | undefined)[] = []): Map<string, FreeGroup> {
  const skip = new Set(keep.filter(Boolean) as string[]);
  const by = new Map<string, Session[]>();
  for (const s of list) {
    if (!isFree(s) || skip.has(s.session_id)) continue;
    const k = `${s.repo}|${s.agent}`;
    const arr = by.get(k);
    if (arr) arr.push(s);
    else by.set(k, [s]);
  }
  const out = new Map<string, FreeGroup>();
  for (const mates of by.values()) {
    if (mates.length < 2) continue;
    out.set(mates[0].session_id, { lead: true, mates });
    for (const m of mates.slice(1)) out.set(m.session_id, { lead: false });
  }
  return out;
}

/** Que grupos estan desplegados. Vive afuera de los componentes porque al grupo lo dibuja la
 *  primera tarjeta y lo obedecen las demas, que son hermanas: no hay un padre comun donde poner el
 *  estado sin subirlo al tablero, que es de otro archivo. Es el mismo recurso que usa Arrows con
 *  `data-lanes`, pero en React en vez de en el DOM. */
const openGroups = new Set<string>();
const groupWatchers = new Set<() => void>();
function useGroupOpen(key: string) {
  const open = useSyncExternalStore(
    (cb) => {
      groupWatchers.add(cb);
      return () => groupWatchers.delete(cb);
    },
    () => openGroups.has(key),
  );
  const toggle = () => {
    if (openGroups.has(key)) openGroups.delete(key);
    else openGroups.add(key);
    for (const cb of [...groupWatchers]) cb();
  };
  return { open, toggle };
}

/** La tarjeta del grupo plegado: un dato en vez de cuatro iguales. "Darle trabajo" abre el panel de
 *  la primera (que es la que viene esperando hace mas), y "ver las N" despliega para elegir a cual;
 *  desplegado, cada una vuelve a ser su tarjeta entera, con su arrastre, su estrella y su menu. */
function FreeGroupCard({ mates, onOpen, onExpand }: { mates: Session[]; onOpen: () => void; onExpand: () => void }) {
  const first = mates[0];
  const oldest = mates.reduce((a, b) => (a.started <= b.started ? a : b));
  return (
    <div
      className="card free freegroup"
      data-sid={first.session_id}
      role="group"
      aria-label={`${mates.length} sesiones libres en ${first.repo}`}
      onDoubleClick={onOpen}
    >
      <div className="top">
        <span className={`badge ${first.agent}`}>{first.agent}</span>
        <span className="repo">{first.repo}</span>
        <span className="right">{ago(oldest.started)}</span>
      </div>
      <div className="title">
        {mates.length} sesiones libres en {first.repo}
      </div>
      <div className="freeline" title={mates.map((m) => `${shortName(m)} · abierta hace ${ago(m.started)}`).join("\n")}>
        sin pedidos todavía · la más vieja, hace {ago(oldest.started)}
      </div>
      <div className="quickact freeact">
        <button type="button" title={`abre el panel de ${shortName(first)}, la que viene esperando hace más`} onClick={onOpen}>
          Darle trabajo
        </button>
        <button type="button" className="expand" title="verlas una por una para elegir a cual" onClick={onExpand}>
          ver las {mates.length}
        </button>
      </div>
    </div>
  );
}

/** Envoltorio con que el lienzo manda un texto largo: la sugerencia que arranca asi es nuestra. */
const ATTACH_WRAPPER = "Leé el archivo adjunto y respondé";
/** "usando Bash": la transcripcion dice que herramienta corre; es actividad, no una respuesta */
const WORKING_RE = /^usando \S+/;

const QUICK = ["Continuá", "sí", "no"];

const RECENT_MS = 30 * 60 * 1000;

/** Espera del click simple antes de elegir la tarjeta. Si en ese rato llega el segundo click, se
 *  cancela y el doble click abre el panel sin elegir nada: elegir agrega las conexiones en palabras
 *  y **cambia el alto de la tarjeta**, asi que el segundo click del doble caia en otro elemento (se
 *  medio en la tarjeta de Codex, la mas baja del tablero: el doble click no abria el panel). */
const PICK_MS = 240;

/** Tab recorre las tarjetas, no sus botones. Todo lo que la tarjeta contiene sale del orden de
 *  tabulacion (tabIndex -1) mientras el foco no este ya en uno de sus controles: asi Tab va de
 *  tarjeta en tarjeta y no cae en la ✕ ("quitar tarjeta") ni en la estrella, dos acciones con
 *  consecuencia, antes que en el elemento que las contiene. Con la tarjeta enfocada, las flechas
 *  entran a sus botones (y ahi Tab los recorre); Escape vuelve a la tarjeta.
 *  La excepcion son Permitir y Denegar (`data-always-tab`): un permiso vence a los 60 s y es la
 *  unica accion del tablero que no puede esperar a que el usuario descubra la flecha.
 *  Se hace por efecto y no boton por boton porque la tarjeta arma su contenido segun el estado
 *  (pedido plegado, permiso pendiente, sugerencia, botones rapidos): un control nuevo queda
 *  cubierto solo. */
const FOCUSABLE = "button, a[href], input, textarea, select";

function controlsOf(el: HTMLElement | null): HTMLElement[] {
  return el ? [...el.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((n) => n.offsetParent !== null) : [];
}

function useRovingTab(ref: React.RefObject<HTMLElement | null>, inside: boolean) {
  useEffect(() => {
    for (const n of ref.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []) n.tabIndex = inside || n.dataset.alwaysTab !== undefined ? 0 : -1;
  });
}

interface Props {
  session: Session;
  pending?: Pending;
  rules?: Rule[];
  /** reenvios que tocan a esta sesion (llegan por SSE); alimentan el chip "informe de" */
  links?: Link[];
  sessions?: Record<string, Session>;
  onDeleteRule?: (id: string) => void;
  /** su panel esta abierto */
  selected: boolean;
  /** elegida con un click en el tablero: se resalta y muestra sus conexiones en palabras */
  picked?: boolean;
  /** esta en el otro extremo de una conexion de la elegida: muestra en palabras **solo** eso que
   *  comparte con ella (lo arma Board), no todas las conexiones que tenga */
  related?: { links: Link[]; rules: Rule[] };
  /** agrupada con las otras libres de su repo: la encabeza (`lead`) o se pliega adentro. Lo calcula
   *  el tablero con `freeGroups`; sin esto la tarjeta se dibuja como siempre */
  freeGroup?: FreeGroup;
  /** un click: elegir la tarjeta, sin abrir nada */
  onPick?: () => void;
  /** doble click (o Enter): abrir el panel */
  onSelect: () => void;
  onDecide: (requestId: string, decision: "allow" | "deny") => void;
  onAnswer: (requestId: string, answers: Record<string, string>) => Promise<void>;
  onDrop: () => void;
  onGrip?: (e: React.MouseEvent) => void;
  onPress?: (e: React.MouseEvent) => void;
  /** toast global; si no viene, la tarjeta muestra uno propio */
  toast?: ToastFn;
}

export function Card({ session: s, pending: p, rules = [], links = [], sessions = {}, onDeleteRule, selected, picked = false, related, freeGroup, onPick, onSelect, onDecide, onAnswer, onDrop, onGrip, onPress, toast: extToast }: Props) {
  const { toast, node: toastNode } = useLocalToast(extToast);
  const [promptOpen, setPromptOpen] = useState(false);
  const [errorOpen, setErrorOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const rename = useRename(s, toast);
  // el grupo de libres se abre y se cierra para todas sus tarjetas a la vez (ver `useGroupOpen`)
  const group = useGroupOpen(`${s.repo}|${s.agent}`);
  const rootRef = useRef<HTMLDivElement>(null);
  // el foco esta en un control de la tarjeta (no en la tarjeta misma): recien ahi sus botones
  // entran en el orden de tabulacion. El CSS ya usa :focus-within para mostrarlos
  const [inside, setInside] = useState(false);
  useRovingTab(rootRef, inside);
  // click simple demorado (PICK_MS): se limpia al desmontar y si la tarjeta cambia de sesion, para
  // que no quede uno vivo que elija una tarjeta que ya no esta
  const pickTimer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(pickTimer.current), [s.session_id]);
  // Menu ⋯ de la tarjeta: renombrar, coordinadora y quitar. Los tres son de mantenimiento y no
  // tienen que ver con lo que uno esta haciendo, asi que no ocupan la fila de arriba, donde quedan
  // solo el agarre y este ⋯ (en tactil no hay hover: escondidos "hasta pasar el mouse" se veian
  // siempre, justo donde mas molestan). Se abre con click o con Enter desde el teclado, el foco va
  // al primer item, y se cierra con Escape, al elegir algo o al tocar afuera.
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const kebabRef = useRef<HTMLButtonElement>(null);
  const closeMenu = () => {
    setMenuOpen(false);
    kebabRef.current?.focus();
  };
  useEffect(() => {
    if (!menuOpen) return;
    menuRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const afuera = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!menuRef.current?.contains(t) && !kebabRef.current?.contains(t)) setMenuOpen(false);
    };
    document.addEventListener("pointerdown", afuera);
    return () => document.removeEventListener("pointerdown", afuera);
  }, [menuOpen]);
  // ultimo reenvio recibido en la ultima media hora: "ya te llego el informe de X"
  const recent = links
    .filter((l) => l.to === s.session_id && l.kind !== "native" && Date.now() - new Date(l.ts).getTime() < RECENT_MS)
    .sort((a, b) => b.ts.localeCompare(a.ts))[0];
  // remitente como "repo · título" (varias sesiones comparten repo); título largo cortado a 24
  const recentFrom = recent ? shortName(sessions[recent.from]) : "";

  // la tarjeta muestra texto plano: sin asteriscos ni almohadillas del markdown de la respuesta
  const promptText = plainText(s.last_prompt);
  const replyText = plainText(s.last_reply);
  const { head, cut } = foldPrompt(promptText);
  const dupPrompt = titleIsPrompt(s);
  const err = foldSentence(s.last_error || "");
  const working = WORKING_RE.test(s.last_reply || "");
  const suggestion = s.suggestion && !s.suggestion.trim().startsWith(ATTACH_WRAPPER) ? s.suggestion : null;
  const writable = canWrite(s);
  // pregunta abierta: la ultima respuesta termina en "?" (la linea de actividad "usando X" no cuenta)
  const asks = !working && /\?\s*$/.test((s.last_reply || "").trim());
  // botones rapidos: solo si la sesion espera input de verdad o pregunto algo. Una que entrego un
  // informe y no pregunto nada no tiene nada que continuar ni que contestar: alcanza la caja del panel
  const quick = writable && !s.pending_id && !p && (s.needs?.kind === "idle" || asks);
  // pendiente que en realidad es una pregunta con opciones: se contesta eligiendo (Ask.tsx)
  const preguntas = askQuestions(p);
  // libre: viva, con consola y sin ningun pedido todavia (sesion recien abierta). No hay nada que
  // continuar ni que contestar: en vez de los botones rapidos, un solo "Darle trabajo" que abre el
  // panel con el cursor en la caja
  const free = !p && isFree(s);
  const freeTitle = `abierta hace ${ago(s.started)}, sin ningún pedido todavía`;
  const freeText = `Libre · sin pedidos todavía · desde hace ${ago(s.started)}`;
  // elegida con un click: las conexiones en palabras, una por linea. La elegida escribe las suyas;
  // la del otro extremo, solo las del par
  const words = picked || !!related;
  const wordRules = picked ? rules : related?.rules ?? [];
  const wordLinks = picked ? links : related?.links ?? [];

  // limite de uso con hora de vuelta (Codex): un click deja programado "Continuar" un minuto
  // despues; si ya hay una regla a esa hora (manual o automatica) el chip de abajo la muestra
  const limitAt = s.limit_until ? new Date(new Date(s.limit_until).getTime() + 60_000) : null;
  const stalledWhy = stalledReason(s);
  const stalled = stalledWhy === "sin actividad" ? `sin actividad desde hace ${ago(s.state_since)}` : stalledWhy;
  // 30 s de margen: si la regla ya disparo y el navegador va unos segundos adelantado, no se ofrece
  // programar otra; y si el server ya la creo solo, tampoco
  const limitPending = !!limitAt && limitAt.getTime() > Date.now() + 30_000 && s.continue_scheduled_for !== s.limit_until;
  const hasContinue =
    !!limitAt && rules.some((r) => r.kind === "at" && r.to === s.session_id && !!r.at && Math.abs(new Date(r.at).getTime() - limitAt.getTime()) < 5 * 60_000);

  /** accion contra el server con los botones deshabilitados mientras dura: `fn` devuelve el texto
   *  del toast de exito, `fail` arma el de error a partir del mensaje */
  const act = async (fn: () => Promise<string>, fail: (m: string) => string) => {
    setBusy(true);
    try {
      toast(await fn());
    } catch (e) {
      toast(fail((e as Error).message), true);
    } finally {
      setBusy(false);
    }
  };
  const scheduleContinue = () =>
    limitAt &&
    act(async () => {
      await api.post("/rules", { kind: "at", from: null, to: s.session_id, text: "Continuar", at: limitAt.toISOString() });
      return `A las ${hhmm(limitAt)} se le escribe "Continuar"`;
    }, (m) => `No se pudo programar: ${m}`);
  const quickSend = (text: string) =>
    act(async () => {
      const r = await api.post<{ chars: number }>(`/sessions/${s.session_id}/send`, { text, attachments: [] });
      return `Enviado (${r.chars} caracteres)`;
    }, (m) => `No se pudo enviar: ${m}`);
  // estrella de coordinadora: a lo sumo una por repo; recibe los avisos "cuando termine" del
  // SendBox y el "avisame" del parser. Un server anterior a la ruta contesta 404 y la estrella solo avisa
  const toggleCoordinator = () => {
    const on = !s.coordinator;
    return act(async () => {
      await api.put(`/sessions/${s.session_id}/coordinator`, { on });
      return on ? `${shortName(s)} es la coordinadora de ${s.repo}` : `${shortName(s)} ya no es la coordinadora`;
    }, (m) => (noRoute(m) ? "El server que corre no tiene esta ruta todavía: reiniciá el server" : `No se pudo: ${m}`));
  };

  // Plegada adentro de un grupo de libres: no se dibuja, la representa la tarjeta del grupo. Va
  // despues de todos los hooks a proposito: el orden de los hooks no puede depender de esto.
  if (freeGroup && !freeGroup.lead && !group.open) return null;
  if (freeGroup?.lead && !group.open) return <FreeGroupCard mates={freeGroup.mates} onOpen={onSelect} onExpand={group.toggle} />;

  return (
    <>
      {/* desplegado: una tira arriba de la primera dice de que grupo son y permite volver a plegarlo */}
      {freeGroup?.lead && group.open && (
        <div className="freegrouphead">
          <span>
            {freeGroup.mates.length} sesiones libres en {s.repo}
          </span>
          <button type="button" onClick={group.toggle} title="volver a juntarlas en una sola tarjeta">
            ocultar
          </button>
        </div>
      )}
    <div
      ref={rootRef}
      className={`card ${selected ? "sel" : ""} ${picked ? "picked" : ""} ${free ? "free" : ""} ${menuOpen ? "menuopen" : ""} ${words ? "haswords" : ""}`}
      role="button"
      tabIndex={0}
      aria-label={`${s.repo}: ${s.title || s.last_prompt || (free ? "libre, sin pedidos todavía" : "sin título")}`}
      aria-pressed={picked || selected}
      /* un click elige la tarjeta, pero recién a los PICK_MS: si llega el segundo click no se elige
         nada y el doble click abre el panel, sin el parpadeo ni el cambio de alto del medio */
      onClick={(e) => {
        if (e.detail > 1) return; // el segundo click de un doble: lo atiende onDoubleClick
        window.clearTimeout(pickTimer.current);
        pickTimer.current = window.setTimeout(() => onPick?.(), PICK_MS);
      }}
      onDoubleClick={(e) => {
        window.clearTimeout(pickTimer.current); // el click simple ya no elige
        /* doble click sobre un control (✕, estrella, lápiz, chips) no abre el panel */
        if ((e.target as HTMLElement).closest("button, a, input, textarea, code")) return;
        onSelect();
      }}
      onKeyDown={(e) => {
        const onCard = e.target === e.currentTarget;
        // con el menú abierto, Escape lo cierra y vuelve al ⋯ (y no le llega al tablero)
        if (e.key === "Escape" && menuOpen) {
          e.stopPropagation();
          closeMenu();
          return;
        }
        // Enter sobre la tarjeta misma abre el panel; los botones de adentro manejan su propio Enter
        if (e.key === "Enter" && onCard) {
          e.preventDefault();
          onSelect();
          return;
        }
        // con la tarjeta enfocada, las flechas entran a sus controles (↓ → al primero, ↑ ← al
        // último): son los que Tab ya no pisa
        if (onCard && ["ArrowDown", "ArrowRight", "ArrowUp", "ArrowLeft"].includes(e.key)) {
          const cs = controlsOf(rootRef.current);
          if (!cs.length) return;
          e.preventDefault();
          (e.key === "ArrowUp" || e.key === "ArrowLeft" ? cs[cs.length - 1] : cs[0]).focus();
          return;
        }
        // Escape desde un control vuelve a la tarjeta (y no le llega al tablero, que con Esc
        // deselecciona: Esc pela una capa por vez)
        if (e.key === "Escape" && !onCard) {
          e.stopPropagation();
          e.currentTarget.focus();
        }
      }}
      data-sid={s.session_id}
      /* el foco en un control (por las flechas o por un click) mete a los demás en el orden de
         tabulación; en la tarjeta misma, o afuera, vuelven a quedar fuera */
      onFocus={(e) => setInside(e.target !== e.currentTarget)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setInside(false);
      }}
      onMouseDown={(e) => {
        // el arrastre arranca sólo desde la fila de arriba y el título: el resto de la tarjeta es
        // texto que se lee y se copia, y arrastrar desde ahí se llevaba puesta la selección
        const t = e.target as HTMLElement;
        if (e.button !== 0 || t.closest("button, a, input, textarea, .x, .grip, code")) return;
        if (!t.closest(".top, .title, .freeline")) return;
        onPress?.(e);
      }}
    >
      <div className="top">
        <span className={`badge ${s.agent}`}>{s.agent}</span>
        <span className="repo" title={s.repo}>
          {s.repo}
        </span>
        {s.branch && (
          <span className="branch" title={`rama ${s.branch}`}>
            ⎇ {s.branch}
          </span>
        )}
        <span className="right">
          {/* estado como icono: corriendo y termino comparten la columna "Trabajo"; la huerfana va a
              "Muerta" con esta etiqueta, para distinguirla de un proceso muerto de verdad */}
          {s.orphan ? (
            <span className="st orphan" title="el proceso sigue, pero su terminal de VS Code se cerró: no hay dónde escribirle">
              sin terminal
            </span>
          ) : s.alive === false ? null : s.state === "corriendo" ? (
            /* verde sólo si de verdad está haciendo algo: sin cupo, o quieta hace rato, el punto se
               apaga. Una sesión que llegó al límite de uso nunca cierra el turno, así que sin esto
               se queda en verde para siempre (medido en Codex: 1,2 h "corriendo" sin cupo) */
            stalled ? (
              <span className="st idle" role="img" aria-label={stalled} title={stalled} />
            ) : (
              <span className="st run" role="img" aria-label="corriendo" title="corriendo" />
            )
          ) : s.state === "termino" ? (
            <span className="st done" role="img" aria-label="terminó" title="terminó">
              ✓
            </span>
          ) : null}
          {/* la coordinadora se sigue viendo, pero como indicador: la acción vive en el menú ⋯ */}
          {s.coordinator && (
            <span className="star on" role="img" aria-label="coordinadora del repo" title="coordinadora del repo: recibe los avisos 'cuando termine' y 'avisame'">
              ★
            </span>
          )}
          {ago(s.state_since)}
          {onGrip && writable && (
            <button
              type="button"
              className="grip"
              title="arrastrá hasta otra tarjeta para reenviarle la última respuesta"
              aria-label="arrastrar para conectar con otra tarjeta"
              onClick={(e) => e.stopPropagation()}
              onMouseDown={(e) => {
                e.stopPropagation();
                e.preventDefault();
                onGrip(e);
              }}
            >
              ⇢
            </button>
          )}
          <button
            type="button"
            className="kebab"
            ref={kebabRef}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            title="más acciones: renombrar, coordinadora, quitar la tarjeta"
            aria-label="más acciones de la tarjeta"
            onClick={(e) => {
              e.stopPropagation();
              setMenuOpen((o) => !o);
            }}
            onDoubleClick={(e) => e.stopPropagation()}
          >
            ⋯
          </button>
        </span>
      </div>
      {menuOpen && (
        <div className="cardmenu" role="menu" ref={menuRef} onClick={(e) => e.stopPropagation()}>
          {writable && (
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                closeMenu();
                rename.start();
              }}
            >
              ✎ Renombrar
            </button>
          )}
          {s.agent === "claude" && writable && (
            <button
              type="button"
              role="menuitem"
              disabled={busy}
              aria-pressed={!!s.coordinator}
              title="la coordinadora del repo recibe los avisos 'cuando termine' y 'avisame'"
              onClick={() => {
                closeMenu();
                toggleCoordinator();
              }}
            >
              {s.coordinator ? "★ Quitarle el rol de coordinadora" : "☆ Coordinadora del repo"}
            </button>
          )}
          <button
            type="button"
            role="menuitem"
            className="danger"
            onClick={() => {
              closeMenu();
              onDrop();
            }}
          >
            ✕ Quitar la tarjeta
          </button>
        </div>
      )}
      <div className={`title ${dupPrompt ? "plain" : ""}`}>
        {rename.input ??
          (free && !s.title ? (
            <span className="freeline" title={freeTitle}>
              {freeText}
            </span>
          ) : (
            s.title || s.last_prompt || "(sin título)"
          ))}
      </div>
      {free && s.title && (
        <div className="freeline" title={freeTitle}>
          {freeText}
        </div>
      )}
      {/* el pedido no se repite si el titulo ya es su primera linea; si hay mas texto queda el "…más" */}
      {s.title && s.last_prompt && (!dupPrompt || cut) && (
        <div className={`prompt ${promptOpen ? "open" : ""}`}>
          {(!dupPrompt || promptOpen) && <span className="ptext">› {promptOpen ? promptText : head}</span>}
          {cut && (
            <button
              type="button"
              className="more"
              aria-expanded={promptOpen}
              onClick={(e) => {
                e.stopPropagation();
                setPromptOpen((o) => !o);
              }}
            >
              {promptOpen ? "menos" : dupPrompt ? "…ver el pedido" : "…más"}
            </button>
          )}
        </div>
      )}
      {recent && (
        <div className="chip recent" title={`informe de ${recentFrom}: ${plainText(recent.text)}`}>
          ✓ {recentFrom} · hace {ago(recent.ts)}
        </div>
      )}
      {/* lo que pide la sesion va antes que la respuesta: Permitir/Denegar es lo primero visible.
          Si lo que espera es una pregunta con opciones, van las opciones: no hay nada que permitir */}
      {p && preguntas.length > 0 ? (
        <Ask pending={p} questions={preguntas} onAnswer={onAnswer} onDecide={onDecide} />
      ) : p ? (
        // no se frena la propagacion del bloque entero: es la mitad de la tarjeta y frenarlo dejaba
        // el doble click sin abrir el panel. Los dos botones la frenan por su cuenta
        <div className="needs">
          <b>Pide permiso: {p.tool_name}</b>
          <code>{detail(p.tool_input)}</code>
          <div className="btns">
            {/* los unicos dos botones que quedan siempre en el orden de tabulacion: el permiso vence */}
            <button className="allow" data-always-tab="" onClick={(e) => { e.stopPropagation(); onDecide(p.request_id, "allow"); }}>Permitir</button>
            <button className="deny" data-always-tab="" onClick={(e) => { e.stopPropagation(); onDecide(p.request_id, "deny"); }}>Denegar</button>
            <span className="dim small">vence {hhmm(new Date(p.expires_at))}</span>
          </div>
        </div>
      ) : s.state === "te_necesita" && s.needs && !(quick && s.needs.kind === "idle") ? (
        /* ociosa con botones rapidos: el aviso va en una linea con los botones, mas abajo */
        <div className="needs terminal">
          <b>{needsLabel(s.needs)}</b>
          {s.needs.detail && <code>{s.needs.detail}</code>}
          <div className="dim small">
            {s.needs.kind === "idle" ? "podés escribirle desde acá" : s.needs.where === "terminal" ? "contestar en VS Code" : "esperando al lienzo"}
          </div>
        </div>
      ) : null}
      {s.last_error ? (
        <div className={`error ${errorOpen ? "open" : ""}`}>
          <span className="etext">⚠ {errorOpen ? s.last_error : err.head}</span>
          {err.cut && (
            <button
              type="button"
              className="more"
              aria-expanded={errorOpen}
              onClick={(e) => {
                e.stopPropagation();
                setErrorOpen((o) => !o);
              }}
            >
              {errorOpen ? "menos" : "…más"}
            </button>
          )}
        </div>
      ) : working ? (
        <div className="reply working" title="lo que está haciendo ahora, según la transcripción">
          <span className="wdot" aria-hidden="true" />
          {s.last_reply}
        </div>
      ) : free ? null : (
        <div className="replyrow">
          <div className="reply">{replyText}</div>
          {s.last_reply && (
            <button
              type="button"
              className="copy"
              title="copiar la última respuesta"
              aria-label="copiar la última respuesta"
              onClick={(e) => {
                e.stopPropagation();
                copyText(s.last_reply, toast);
              }}
            >
              📋
            </button>
          )}
        </div>
      )}
      {limitPending && !hasContinue && writable && limitAt && (
        <div className="limitrow" onClick={(e) => e.stopPropagation()}>
          <button
            type="button"
            disabled={busy}
            title={`a las ${hhmm(limitAt)} se escribe "Continuar" en su terminal (un minuto después de que vuelva el cupo)`}
            onClick={scheduleContinue}
          >
            ⏰ Continuar a las {hhmm(limitAt)}
          </button>
        </div>
      )}
      {/* qué viene haciendo adentro: cuántas herramientas lleva el turno y sobre qué archivos.
          Una sesión sin pedidos todavía no tiene nada que contar */}
      {!free && !!s.tool_count && (
        <div className="activity" title="actividad del turno que corre (o del último)">
          <span className="n">{s.tool_count} {s.tool_count === 1 ? "paso" : "pasos"}</span>
          {!!s.tool_errors && (
            <span className="e" title={`${s.tool_errors} de esos pasos volvieron con error`}>
              {s.tool_errors} ⚠
            </span>
          )}
          {!!s.last_files?.length && <span className="f">{s.last_files.join(" · ")}</span>}
        </div>
      )}
      {!free && s.last_cmd && (
        <div className="lastcmd" title={s.last_cmd}>
          <span className="p">$</span> {s.last_cmd}
        </div>
      )}
      {/* la sugerencia que la terminal tiene tipeada: un click la manda, que es lo que uno iba a
          hacer igual. Sin consola no es un botón, sólo texto */}
      {suggestion &&
        (writable && !s.pending_id ? (
          <button
            type="button"
            className="sugg act"
            disabled={busy}
            title="lo que está tipeado en esa terminal · click para mandarlo"
            onClick={(e) => {
              e.stopPropagation();
              quickSend(suggestion);
            }}
          >
            💡 {suggestion}
            <span className="go">enviar</span>
          </button>
        ) : (
          <div className="sugg" title="leído de la caja de entrada de la terminal">💡 {suggestion}</div>
        ))}
      {/* las conexiones no compiten con lo que pasa adentro: viven en las flechas, y al elegir la
          tarjeta se leen en palabras. El contador queda para saber que hay algo */}
      {words && <CardWords sid={s.session_id} rules={wordRules} links={wordLinks} sessions={sessions} onDelete={onDeleteRule} />}
      {free ? (
        <div className="quickact freeact" onClick={(e) => e.stopPropagation()}>
          <button type="button" title="abre el panel con el cursor en la caja de envío" onClick={onSelect}>
            Darle trabajo
          </button>
        </div>
      ) : quick && (
        <div className="quickact" onClick={(e) => e.stopPropagation()}>
          {s.state === "te_necesita" && <span className="dim small">Espera que le escribas</span>}
          {QUICK.map((q) => (
            <button key={q} type="button" disabled={busy} title="se escribe en su terminal" onClick={() => quickSend(q)}>
              {q}
            </button>
          ))}
        </div>
      )}

      <div className="meta">
        <span>PID {s.pid ?? "?"}</span>
        <span>{s.source === "sweep" ? "barrido" : "hooks"}</span>
        {s.alive === false && <span>proceso muerto</span>}
        {s.no_console && !s.orphan && <span className="warn" title="panel de Claude Code de VS Code o app de escritorio: se ve, no se le escribe">sin consola</span>}
        <span>{s.session_id.slice(0, 8)}</span>
      </div>
      {toastNode}
    </div>
    </>
  );
}
