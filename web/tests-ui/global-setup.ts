import { BASE } from "./tablero-fijo";

/** El server del 7321 lo levanta el usuario (`lienzo-server.cmd`) y estas pruebas no lo arrancan ni
 *  lo reinician. Si no contesta fallarían las treinta con "net::ERR_CONNECTION_REFUSED": mejor una
 *  línea sola y clara. Se pide la página, no `/auth`: las pruebas con tablero fijo interceptan todo
 *  y sirven igual contra un `vite preview` apuntado con LIENZO_URL. */
export default async function () {
  try {
    const r = await fetch(`${BASE}/`, { signal: AbortSignal.timeout(4000) });
    if (!r.ok) throw new Error(`devolvió ${r.status}`);
  } catch (e) {
    throw new Error(`No hay lienzo escuchando en ${BASE}: arrancá el server (lienzo-server.cmd) y volvé a correr.\n  ${(e as Error).message}`, { cause: e });
  }
}
