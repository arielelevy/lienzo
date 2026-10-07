import { useState } from "react";
import { failMsg, rulesApi, sessionsApi, type Decision } from "../api";
import { hhmm } from "../nl";
import { shortName } from "../names";
import type { Session } from "../types";
import type { ToastFn } from "./useLocalToast";

/** Limite de uso con hora de vuelta (Codex): "Continuar" va un minuto despues de que vuelva el cupo. */
export const continueAt = (s: Session): Date | null =>
  s.limit_until ? new Date(new Date(s.limit_until).getTime() + 60_000) : null;

/** Las acciones de red de una tarjeta y su `busy`: mientras una corre, los botones que la disparan
 *  quedan deshabilitados. Cada una avisa con un toast de exito o de error; el de error lo arma
 *  `failMsg`, que distingue la ruta que falta (reiniciar el server) de cualquier otro 404. */
export function useCardActions(s: Session, toast: ToastFn) {
  const [busy, setBusy] = useState(false);

  /** accion contra el server con los botones deshabilitados mientras dura: `fn` devuelve el texto
   *  del toast de exito, `fail` arma el de error a partir del error */
  const act = async (fn: () => Promise<string>, fail: (e: unknown) => string) => {
    setBusy(true);
    try {
      toast(await fn());
    } catch (e) {
      toast(fail(e), true);
    } finally {
      setBusy(false);
    }
  };

  const limitAt = continueAt(s);
  const scheduleContinue = () =>
    limitAt &&
    act(async () => {
      await rulesApi.create({ kind: "at", from: null, to: s.session_id, text: "Continuar", at: limitAt.toISOString() });
      return `A las ${hhmm(limitAt)} se le escribe "Continuar"`;
    }, failMsg("programar"));

  /** una opción del diálogo de la TUI: se teclea el número en su terminal, sin Enter */
  const pickDialog = (n: number, text: string) =>
    act(async () => {
      await sessionsApi.dialog(s.session_id, n);
      return `Elegido: ${text}`;
    }, failMsg("elegir"));

  /** el permiso que CODA pide en su terminal: Enter (Yes) o Esc, tecleado por el server */
  const codaDecide = (decision: Decision) =>
    act(async () => {
      await sessionsApi.approve(s.session_id, decision);
      return decision === "allow" ? "Permitido en su terminal" : "Denegado en su terminal";
    }, failMsg("contestar"));

  const quickSend = (text: string) =>
    act(async () => {
      const r = await sessionsApi.send(s.session_id, { text, attachments: [] });
      return `Enviado (${r.chars} caracteres)`;
    }, failMsg("enviar"));

  /** le avisa al agente que el humano autoriza lo que se le denego, para que lo reintente */
  const autorizarDenegado = () => {
    const d = s.last_denied;
    if (!d) return;
    // todas las del turno, una por una: con una sola, «lo que se te denego» autorizaba tambien lo que
    // la tarjeta no mostraba (un rm -r detras de una suma inofensiva, 2026-10-04)
    const lista = d.todas && d.todas.length > 1 ? d.todas : [d];
    const que = lista.map((x, i) => `${lista.length > 1 ? `(${i + 1}) ` : ""}${x.detalle ? `${x.tool} ${x.detalle}` : x.tool}`).join("; ");
    void quickSend(`El humano autoriza lo que se te denegó: ${que}. Reintentá sólo eso; si la regla te lo vuelve a frenar, avisame y no insistas.`);
  };

  // estrella de coordinadora: a lo sumo una por repo; recibe los avisos "cuando termine" del
  // SendBox y el "avisame" del parser. Un server anterior a la ruta contesta 404 y la estrella solo avisa
  const toggleCoordinator = () => {
    const on = !s.coordinator;
    return act(async () => {
      await sessionsApi.coordinator(s.session_id, on);
      return on ? `${shortName(s)} es la coordinadora de ${s.repo}` : `${shortName(s)} ya no es la coordinadora`;
    }, failMsg());
  };

  // la llave stopped: prendida no recibe mensajes ni reglas (el server avisa a sus conectadas),
  // apagada vuelve a recibir. La prende el pegado de su trabajo en otra tarjeta, o el menu
  const toggleStopped = () => {
    const on = !s.stopped_by;
    return act(async () => {
      const r = await sessionsApi.stopped(s.session_id, on);
      if (!on) return `${shortName(s)} habilitada: vuelve a recibir`;
      const avisadas = r.notified?.length ? `; avisadas: ${r.notified.join(", ")}` : "; sin conectadas a quien avisar";
      return `${shortName(s)} detenida${r.interrupted ? " (Esc en su terminal)" : ""}${avisadas}`;
    }, failMsg());
  };

  const kill = () => {
    if (!confirm(`¿Cerrar a la fuerza ${shortName(s)} y sus procesos hijos? Se perderá el trabajo que no haya guardado.`)) return;
    return act(async () => {
      await sessionsApi.kill(s.session_id);
      return `${shortName(s)} cerrada`;
    }, failMsg("cerrar el proceso"));
  };

  return {
    busy,
    act,
    scheduleContinue,
    pickDialog,
    codaDecide,
    quickSend,
    autorizarDenegado,
    toggleCoordinator,
    toggleStopped,
    kill,
  };
}

export type CardActions = ReturnType<typeof useCardActions>;
