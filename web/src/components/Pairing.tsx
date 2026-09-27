import { useEffect, useState } from "react";
import { ago, api } from "../api";
import type { Peer } from "../types";

interface Offer {
  phrase: string;
  expires: number;
}

interface Props {
  /** de usePeers (App): [] si el server que corre no tiene /peers todavía, o [la propia] sin nada
   *  emparejado; con el resto de la federación, la propia siempre primero (local: true). */
  peers: Peer[];
  toast: (msg: string, err?: boolean) => void;
  onClose: () => void;
}

/** Pantalla "Varias PCs" (menú ⋯ del header, plan §3.1 y §3.9): el nombre de esta PC, la lista de
 *  PCs emparejadas con su estado y Quitar, y las dos acciones para emparejar una nueva: mostrar una
 *  frase de seis palabras u ofrecerse a pegar la que muestra la otra. Sin `/peers` (server viejo) o
 *  sin nada emparejado, explica en dos líneas qué hace falta en vez de una lista vacía sin contexto. */
export function Pairing({ peers, toast, onClose }: Props) {
  const local = peers.find((p) => p.local) ?? null;
  const others = peers.filter((p) => !p.local);
  const sinRuta = peers.length === 0;

  // renombrar esta PC (PUT /peers/self): optimista sobre `local.name` mientras el 15 s de
  // usePeers no trae el nombre nuevo, asi la pantalla no muestra el viejo un rato despues de guardar
  const [nameOverride, setNameOverride] = useState<string | null>(null);
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [nameErr, setNameErr] = useState<string | null>(null);
  const [nameBusy, setNameBusy] = useState(false);
  const shownName = nameOverride ?? local?.name ?? "";
  const startRename = () => {
    setNameDraft(shownName);
    setNameErr(null);
    setEditingName(true);
  };
  const saveName = async () => {
    const name = nameDraft.trim();
    if (!name || name === shownName) {
      setEditingName(false);
      return;
    }
    setNameBusy(true);
    setNameErr(null);
    try {
      await api.put<{ name: string }>("/peers/self", { name });
      setNameOverride(name);
      setEditingName(false);
      toast(`Esta PC pasa a llamarse ${name}`);
    } catch (e) {
      setNameErr((e as Error).message);
    } finally {
      setNameBusy(false);
    }
  };

  const [offer, setOffer] = useState<Offer | null>(null);
  const [offerErr, setOfferErr] = useState<string | null>(null);
  const [offerBusy, setOfferBusy] = useState(false);
  // cuenta atras de la vigencia: sin esto el numero queda congelado en el que trajo la respuesta
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (!offer) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [offer]);
  const offerLeft = offer ? Math.max(0, Math.round(offer.expires - now / 1000)) : 0;

  const showOffer = async () => {
    setOfferBusy(true);
    setOfferErr(null);
    try {
      setOffer(await api.post<Offer>("/peers/offer", {}));
    } catch (e) {
      setOfferErr((e as Error).message);
    } finally {
      setOfferBusy(false);
    }
  };

  const [showJoin, setShowJoin] = useState(false);
  const [host, setHost] = useState("");
  const [port, setPort] = useState("7322");
  const [phrase, setPhrase] = useState("");
  const [joinErr, setJoinErr] = useState<string | null>(null);
  const [joinBusy, setJoinBusy] = useState(false);

  const join = async () => {
    const p = Number(port);
    if (!host.trim() || !phrase.trim() || !Number.isFinite(p)) return;
    setJoinBusy(true);
    setJoinErr(null);
    try {
      const peer = await api.post<{ name: string }>("/peers/join", { phrase: phrase.trim(), host: host.trim(), port: p });
      toast(`Emparejada con ${peer.name}`);
      setShowJoin(false);
      setHost("");
      setPhrase("");
      setPort("7322");
    } catch (e) {
      setJoinErr((e as Error).message);
    } finally {
      setJoinBusy(false);
    }
  };

  const quitar = async (peer: Peer) => {
    if (!confirm(`Quitar a ${peer.name}? Deja de verse su tablero desde acá (y el de acá, desde la de ella).`)) return;
    try {
      await api.del(`/peers/${peer.pc_id}`);
      toast(`${peer.name} desemparejada`);
    } catch (e) {
      toast((e as Error).message, true);
    }
  };

  return (
    <div className="gate" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="gate-box wide pairing" role="dialog" aria-label="Varias PCs">
        <h1>Varias PCs</h1>
        {sinRuta ? (
          <p className="small dim">El server que corre no tiene /peers todavía: reiniciá el server.</p>
        ) : (
          <>
            {local && (
              <div className="row">
                <span className="k">Esta PC</span>
                <span className="pcdot" style={{ "--pc-color": local.color } as React.CSSProperties} />
                {editingName ? (
                  <>
                    <input
                      autoFocus
                      aria-label="nuevo nombre de esta PC"
                      value={nameDraft}
                      disabled={nameBusy}
                      onChange={(e) => setNameDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          saveName();
                        } else if (e.key === "Escape") {
                          e.preventDefault();
                          setEditingName(false);
                        }
                      }}
                    />
                    <button type="button" className="primary" disabled={nameBusy} onClick={saveName}>
                      Guardar
                    </button>
                    <button type="button" disabled={nameBusy} onClick={() => setEditingName(false)}>
                      Cancelar
                    </button>
                  </>
                ) : (
                  <>
                    <b>{shownName}</b>
                    <button type="button" title="renombrar esta PC" aria-label="renombrar esta PC" onClick={startRename}>
                      ✎
                    </button>
                  </>
                )}
              </div>
            )}
            {nameErr && <div className="gate-err">{nameErr}</div>}

            {others.length === 0 ? (
              <p className="small dim">
                Sin ninguna PC emparejada todavía: esto junta el tablero de dos a cuatro PCs de la misma red
                local. Hace falta correr <code>install.py --peer</code> en cada una y emparejarlas con una frase.
              </p>
            ) : (
              <div className="pairing-list">
                {others.map((p) => (
                  <div key={p.pc_id} className="row pairing-peer">
                    <span className={`pcdot ${p.alive ? "" : "down"}`} style={{ "--pc-color": p.color } as React.CSSProperties} />
                    <b>{p.name}</b>
                    <span className="small dim">{p.alive ? "conectada" : `sin conexión hace ${ago(p.last_seen)}`}</span>
                    <span className="sp" />
                    <button type="button" onClick={() => quitar(p)}>
                      Quitar
                    </button>
                  </div>
                ))}
              </div>
            )}

            <hr />

            <div className="row">
              <button type="button" disabled={offerBusy} onClick={showOffer}>
                Mostrar frase
              </button>
              <button type="button" onClick={() => setShowJoin((v) => !v)}>
                Unirme a otra PC
              </button>
            </div>

            {offerErr && <div className="gate-err">{offerErr}</div>}
            {offer && (
              <div>
                <div className="k">{offerLeft > 0 ? `vale ${offerLeft} s más` : "vencida"}</div>
                <pre className="pass pairing-phrase">{offer.phrase}</pre>
                <p className="small dim">Pegala en "Unirme a otra PC" de la otra máquina, con esta IP y el puerto 7322.</p>
              </div>
            )}

            {showJoin && (
              <div className="pairing-join">
                <label>
                  Host o IP
                  <input value={host} onChange={(e) => setHost(e.target.value)} placeholder="192.168.1.10" />
                </label>
                <label>
                  Puerto
                  <input value={port} onChange={(e) => setPort(e.target.value)} />
                </label>
                <label>
                  Frase (seis palabras)
                  <input value={phrase} onChange={(e) => setPhrase(e.target.value)} placeholder="palabra palabra palabra…" />
                </label>
                {joinErr && <div className="gate-err">{joinErr}</div>}
                <div className="row">
                  <span className="sp" />
                  <button type="button" className="primary" disabled={joinBusy || !host.trim() || !phrase.trim() || !port.trim()} onClick={join}>
                    Unirme
                  </button>
                </div>
              </div>
            )}
          </>
        )}
        <div className="row">
          <span className="sp" />
          <button type="button" onClick={onClose}>
            Cerrar
          </button>
        </div>
      </div>
    </div>
  );
}
