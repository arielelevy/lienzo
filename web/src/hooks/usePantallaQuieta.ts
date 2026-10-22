import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { sessionsApi } from "../api";
import { hasConsole } from "../names";
import type { Session } from "../types";

/** Aviso de tarjeta estancada: figura `corriendo` y su pantalla no cambió en N minutos. Parte de
 *  `coordinar.estancada()` de la skill lienzo, pero sin contar el reloj del spinner (ver
 *  huellaPantalla): estancada sí lo cuenta y no ve a un agente colgado. El server no guarda cuándo cambió la
 *  pantalla, así que el tablero la mira cada MIRAR_MS, sólo con la pestaña a la vista y sólo de las
 *  tarjetas que corren: cada lectura en Windows es un subproceso screen.py. */
export const QUIETA_KEY = "lienzo.pantallaQuietaMin";
export const QUIETA_MIN_DEFECTO = 5;
/** lo que ofrece el menú ⋯ de la tarjeta, en orden; 0 apaga el aviso */
export const QUIETA_OPCIONES = [3, 5, 10, 15, 30, 0];
export const MIRAR_MS = 60_000;

const oyentes = new Set<() => void>();

function leerMinutos(): number {
  try {
    const raw = localStorage.getItem(QUIETA_KEY);
    const n = raw === null ? QUIETA_MIN_DEFECTO : Number(raw);
    return QUIETA_OPCIONES.includes(n) ? n : QUIETA_MIN_DEFECTO;
  } catch {
    return QUIETA_MIN_DEFECTO;
  }
}

let minutos = leerMinutos();

/** Minutos de pantalla quieta antes del aviso (0 = apagado), uno solo para todas las tarjetas. */
export function useMinutosQuieta(): [number, (n: number) => void] {
  const valor = useSyncExternalStore(
    (cb) => {
      oyentes.add(cb);
      // otra pestaña del tablero lo cambió
      const otra = (e: StorageEvent) => {
        if (e.key !== QUIETA_KEY) return;
        minutos = leerMinutos();
        cb();
      };
      window.addEventListener("storage", otra);
      return () => {
        oyentes.delete(cb);
        window.removeEventListener("storage", otra);
      };
    },
    () => minutos,
  );
  const cambiar = (n: number) => {
    minutos = n;
    try {
      localStorage.setItem(QUIETA_KEY, String(n));
    } catch {
      /* sin almacenamiento dura lo que la pestaña */
    }
    oyentes.forEach((cb) => cb());
  };
  return [valor, cambiar];
}

const SPINNER = /^[\s⠀-⣿✻✶✳✢✽✺*·•◐◓◑◒⏺●○◯|/\\-]+/;
const DURACION = /\b\d+(?:[.,]\d+)?\s*(?:ms|s|m|min|h)\b/g;
const RELOJ = /\b\d{1,2}:\d{2}(?::\d{2})?\b/g;

/** La pantalla sin lo que cambia sólo con el reloj: el spinner del principio de la línea, los
 *  segundos («(34s · esc to interrupt)») y las horas. Un agente colgado esperando al modelo sigue
 *  moviendo eso; los tokens y el texto nuevo sí cuentan como cambio. */
export function huellaPantalla(lines: string[]): string {
  return lines.map((l) => l.replace(SPINNER, "").replace(DURACION, "#").replace(RELOJ, "#").trimEnd()).join("\n");
}

/** Desde cuándo (ms) la pantalla de una tarjeta que corre no cambia, o null si no corre, no se
 *  puede leer o el aviso está apagado. Arranca a contar en la primera lectura: lo de antes no se vio. */
export function usePantallaQuieta(s: Session, apagado: boolean): number | null {
  const corre = !apagado && s.state === "corriendo" && s.state_source !== "unverified" && hasConsole(s);
  // cada turno (state_since) cuenta de cero: la marca de otro turno no vale
  const clave = `${s.session_id}|${s.state_since}`;
  const [visto, setVisto] = useState<{ clave: string; desde: number } | null>(null);
  const ultima = useRef<{ clave: string; huella: string } | null>(null);
  useEffect(() => {
    if (!corre) return;
    let vivo = true;
    const mirar = () => {
      if (document.hidden) return;
      sessionsApi
        .screen(s.session_id)
        .then((r) => {
          if (!vivo || !r.ok || !r.lines) return; // sin lectura no se sabe: no se avisa ni se reinicia
          const huella = huellaPantalla(r.lines);
          if (ultima.current?.clave !== clave || ultima.current.huella !== huella) {
            ultima.current = { clave, huella };
            setVisto({ clave, desde: Date.now() });
          }
        })
        .catch(() => {
          /* server reiniciándose o PC caída: se mira de nuevo en la próxima vuelta */
        });
    };
    mirar();
    const timer = window.setInterval(mirar, MIRAR_MS);
    document.addEventListener("visibilitychange", mirar);
    return () => {
      vivo = false;
      // lo que pase mientras no se mira (aviso apagado, PC caída) no cuenta como pantalla quieta
      ultima.current = null;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", mirar);
    };
  }, [corre, s.session_id, clave]);
  return corre && visto?.clave === clave ? visto.desde : null;
}
