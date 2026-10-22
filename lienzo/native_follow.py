"""Publicación diferida del nombre de Claude; un intento por nombre y proceso."""

import launch


def schedule(ses, card: dict) -> None:
    with ses.lock:
        if (
            card.get("agent") != "claude"
            or card.get("title_source") != "user"
            or not card.get("alive")
            or card.get("state") != "termino"
            or card.get("stopped_by")
            or card.get("typing")
            or card.get("dialog")
            or card.get("external")
            or card.get("native_sync_busy")
            or card.get("_native_queued")
        ):
            return
        name = launch.nombre_corto(card.get("title") or "")
        key = (name, card.get("pid"), card.get("started"))
        if not name or card.get("native_name") == name or card.get("_native_attempt") == key:
            return
        card["_native_attempt"] = key
        card["_native_queued"] = True
    ses.en_hilo(_apply, ses, card, name, key)


def _apply(ses, card: dict, name: str, key: tuple) -> None:
    try:
        with ses.lock:
            if (
                ses.sessions.get(card["session_id"]) is not card
                or card.get("state") != "termino"
                or card.get("typing")
                or (launch.nombre_corto(card.get("title") or ""), card.get("pid"), card.get("started")) != key
            ):
                card.pop("_native_attempt", None)  # no se escribió; se difiere hasta la próxima pasada
                return
        code, result = ses.nombrar_nativo(card, name)
        deferred = code == 409 and result.get("code") == "native_deferred"
        with ses.lock:
            if deferred:
                card.pop("_native_attempt", None)  # un aplazamiento conserva el cambio pendiente
            card["native_sync_error"] = None if code == 200 or deferred else result.get("error", "no se pudo nombrar")
            ses.touch(card)
        if code != 200 and not deferred:
            ses.state.log(f"nombre nativo {card['session_id'][:8]}: fallo {code}")
    except Exception as error:
        with ses.lock:
            card["native_sync_error"] = f"nombre nativo: {type(error).__name__}"
            ses.touch(card)
        ses.state.log(f"nombre nativo {card['session_id'][:8]}: {type(error).__name__}")
    finally:
        with ses.lock:
            card["_native_queued"] = False
            ses.touch(card)
