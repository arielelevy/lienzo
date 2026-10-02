"""Cliente del lienzo para coordinar frentes. Se importa, no se corre solo.

    import sys; sys.path.insert(0, r"<ruta de esta skill>")
    import coordinar as c
    c.YO = "<session_id de la coordinadora>"
    for letra, s in sorted(c.frentes("miapp").items()):
        c.enviar(s, "…")

La idea de fondo: **a un frente se le habla por nombre, nunca por pid**. El lienzo tiene copiar y
pegar trabajo entre tarjetas; al pegar, la destino hereda el título con la marca copycat y la de
origen queda detenida, y una detenida no recibe nada. Así que el tablero resuelve solo la
ambigüedad de títulos repetidos: la que trabaja es la que no está detenida. El pid deja de servir
apenas se mueve un encargo de una tarjeta a otra.
"""

import json
import re
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:7321"
YO = ""  # session_id de la coordinadora; lo fija quien importa este módulo


def pedir(metodo, ruta, cuerpo=None, timeout=20):
    """Un pedido al lienzo. Devuelve (código, cuerpo), y 0 con el motivo si no hubo respuesta.

    El header `X-Lienzo` es obligatorio en las escrituras, y el JSON va en UTF-8 explícito o los
    acentos se rompen del otro lado.
    """
    datos = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8") if cuerpo is not None else None
    req = urllib.request.Request(BASE + ruta, data=datos, method=metodo)
    req.add_header("Content-Type", "application/json; charset=utf-8")
    req.add_header("X-Lienzo", "1")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            c = r.read().decode("utf-8")
            return r.status, (json.loads(c) if c.strip() else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def sesiones():
    s = pedir("GET", "/sessions")[1]
    return s if isinstance(s, list) else (s or {}).get("sessions", [])


def activa(s):
    """Sirve si está viva y nadie la detuvo: una detenida rebota todo lo que se le mande."""
    return bool(s.get("alive")) and not s.get("stopped_by")


def frentes(proyecto, todas=False, pc=None):
    """{letra: tarjeta} buscando por NOMBRE, con el título `<proyecto> - encargo <letra> - <qué>`.

    Acepta la PC en el título (`<proyecto> - encargo A @notebook - <qué>`) y la marca ` · copycat`
    que el tablero agrega al pegar. La coordinadora (`<proyecto> - coordinadora - …`) no entra.

    Si dos tarjetas comparten letra —un copiar y pegar en curso— gana la que no está detenida. Si
    las dos están vivas y ninguna detenida (la casilla Duplicar del tablero), gana la copycat, que
    es la que se puso a trabajar último.

    Con varias PCs emparejadas, `GET /sessions` ya trae las de todas mezcladas; `pc` (el `pc_id` de
    `GET /peers`) filtra a una sola. Sin `pc`, se ven las de cualquier PC, como siempre.
    """
    out = {}
    for s in sesiones():
        m = re.match(rf"{re.escape(proyecto)} - encargo ([A-Z]+)(?: @\S+)? - ", str(s.get("title") or ""))
        if not m or (not todas and not activa(s)):
            continue
        if pc and s.get("pc") != pc:
            continue
        letra = m.group(1)
        previa = out.get(letra)
        if previa is None or (s.get("copycat_of") and not previa.get("copycat_of")):
            out[letra] = s
    return out


def enviar(s, texto, enlazar=True):
    """Escribe en la terminal de esa sesión. Con `enlazar`, el tablero dibuja la flecha."""
    cuerpo = {"text": texto}
    if enlazar and YO:
        cuerpo.update({"from": YO, "link_to": s["session_id"]})
    return pedir("POST", f"/sessions/{s['session_id']}/send", cuerpo)[0]


def enviar_seguro(s, texto, proyecto=None, letra=None, enlazar=True, espera=8, reintentos=2):
    """Como `enviar`, pero no da por hecho que llegó: devuelve {"ok", "code", "motivo", "sid"}.

    Un 200 sólo dice que el server aceptó el pedido. Acá además se verifica que la tarjeta lo tomó
    (pasa a `corriendo`, o `last_prompt` cambia) y se cubren las fallas de otra PC:
    - 404 con `gone` (la tarjeta ya no existe allá): se vuelve a buscar el frente por nombre
      (`proyecto` + `letra`) y se manda al id nuevo, una vez. Sin `proyecto`/`letra` no se adivina.
    - 503 (sin conexión con esa PC): se espera y se reintenta, hasta `reintentos` veces.
    - Detenida (`stopped_by`) o muerta: no se manda, se dice por qué.
    """
    import time

    sid = s["session_id"]
    for intento in range(reintentos + 1):
        if s.get("stopped_by"):
            return {"ok": False, "code": 409, "motivo": f"detenida por {s['stopped_by']}", "sid": sid}
        antes = (s.get("last_prompt"), s.get("prompt_id"))
        cuerpo = {"text": texto}
        if enlazar and YO:
            cuerpo.update({"from": YO, "link_to": sid})
        code, res = pedir("POST", f"/sessions/{sid}/send", cuerpo, timeout=80)
        if code == 200:
            fin = time.time() + espera
            while time.time() < fin:
                time.sleep(1)
                n = next((x for x in sesiones() if x["session_id"] == sid), None)
                if n and (n.get("state") == "corriendo" or (n.get("last_prompt"), n.get("prompt_id")) != antes):
                    return {"ok": True, "code": 200, "motivo": "la tarjeta lo tomó", "sid": sid}
            return {"ok": False, "code": 200, "motivo": f"el server lo aceptó pero la tarjeta no reaccionó en {espera} s (¿consola ocupada o en un diálogo?)", "sid": sid}
        if code == 404 and isinstance(res, str) and "gone" in res and proyecto and letra:
            nuevo = frentes(proyecto).get(letra)
            if nuevo and nuevo["session_id"] != sid:
                s, sid = nuevo, nuevo["session_id"]
                continue
        if code in (0, 503) and intento < reintentos:
            time.sleep(3 * (intento + 1))
            continue
        return {"ok": False, "code": code, "motivo": str(res)[:200], "sid": sid}
    return {"ok": False, "code": 0, "motivo": "sin respuesta", "sid": sid}


def titular(s, titulo):
    return pedir("PUT", f"/sessions/{s['session_id']}/title", {"title": titulo})[0]


def regla_informe(s, texto, max_fires=30):
    """Regla `on_stop` del frente hacia la coordinadora, para que el informe llegue solo.

    `repeat` es obligatorio: sin él dispara una vez y queda apagada, y un frente que cierra dos
    turnos avisa solo el primero.
    """
    return pedir(
        "POST",
        "/rules",
        {"kind": "on_stop", "from": s["session_id"], "to": YO, "text": texto, "repeat": True, "max_fires": max_fires},
    )[0]


def borrar_reglas_hacia_mi():
    """Apaga las reglas que apuntan a la coordinadora: entre rondas, y durante una pausa larga."""
    r = pedir("GET", "/rules")[1]
    r = r if isinstance(r, list) else (r or {}).get("rules", r) or []
    return sum(1 for x in r if x.get("to") == YO and pedir("DELETE", f"/rules/{x['id']}")[0] == 200)


def pendientes():
    return pedir("GET", "/pending")[1] or []


def contestar(pendiente_id, decision):
    return pedir("POST", f"/pending/{pendiente_id}", {"decision": decision})[0]


def modelo_de(s):
    """Con qué modelo respondió último.

    Sale de `model` en `GET /sessions` (ronda multi-PC: el server ya lo lee del transcript). Es
    obligatorio para una sesión de otra PC — su transcript vive en un disco que no es el nuestro,
    así que leerlo a mano no sirve — y para la propia es lo mismo sin abrir el archivo dos veces.
    Sin ese campo (server viejo, sin el campo todavía) cae a leer el transcript local, la única
    forma de verificar que un `/model` entró: el envío devuelve 200 igual, y un comando inyectado
    en una consola ocupada queda encolado y no se ejecuta.
    """
    if s.get("model"):
        return s["model"]
    from pathlib import Path

    p = Path(s.get("transcript_path") or "")
    if not p.exists():
        return "?"
    ult = "?"
    with p.open(encoding="utf-8", errors="replace") as f:
        for linea in f:
            m = re.search(r'"model":"(claude-[a-z0-9.-]+)"', linea)
            if m:
                ult = m.group(1)
    return ult


def tamano_contexto_mb(s):
    """Megas del transcript, proxy para decidir si conviene reusar la sesión o `/clear`.

    Sale de `transcript_bytes` en `GET /sessions` (ronda multi-PC) si está: por la misma razón que
    `modelo_de`, el `stat` de una sesión remota no se puede hacer desde acá. Sin ese campo cae al
    `stat` del transcript local.
    """
    if s.get("transcript_bytes") is not None:
        return round(s["transcript_bytes"] / 1048576, 1)
    from pathlib import Path

    p = Path(s.get("transcript_path") or "")
    return round(p.stat().st_size / 1048576, 1) if p.exists() else 0.0


def tablero(proyecto, pc=None):
    """Una línea por frente: PC, estado, contexto y qué dijo último. Para mirar antes de decidir.

    La columna PC (`pc_id` recortado, o "-" en una sesión sin ese campo) sólo importa con más de
    una PC en el tablero; `pc` filtra a una sola, como en `frentes`.
    """
    for letra, s in sorted(frentes(proyecto, todas=True, pc=pc).items(), key=lambda x: (len(x[0]), x[0])):
        marca = "detenida" if s.get("stopped_by") else ("copycat" if s.get("copycat_of") else "")
        print(
            f"  {letra:>2} {(s.get('pc') or '-')[:8]:8s} {str(s['title'])[:30]:30s} {s.get('state')!s:9s} "
            f"{tamano_contexto_mb(s):5.1f} MB {marca:8s} "
            f"{str(s.get('last_reply') or '')[:65]}"
        )


def lanzar(pc, cwd, titulo, agent="claude"):
    """POST /sessions/launch: lanza una sesión nueva, local si `pc` es None (o la propia), o en la
    PC `pc` (`pc_id` de `GET /peers`) si se da. `cwd` tiene que caer dentro de `launch_roots` de esa
    PC (`config.json`; vacía o ausente ahí es NINGUNA carpeta, no todas). La tarjeta nueva aparece
    después de un barrido: buscarla por `title` (o por `pc` + orden de aparición).
    """
    cuerpo = {"cwd": cwd, "agent": agent, "title": titulo}
    if pc:
        cuerpo["pc"] = pc
    return pedir("POST", "/sessions/launch", cuerpo)


def lan():
    """GET /peers/lan: las PCs de la LAN con el lienzo andando que todavía no están emparejadas
    (`{pc_id, name, ip, port, last_seen}`), por el anuncio sin firma del beacon cada 10 s. Es la
    forma de buscarlas: la pantalla "Varias PCs" las pide una sola vez, al abrirse. Emparejar sigue
    pidiendo la frase de seis palabras (Mostrar frase en una, Unirme en la otra).
    """
    p = pedir("GET", "/peers/lan")[1]
    return p if isinstance(p, list) else []


def salud():
    """GET /peers: memoria libre, CPU y temperatura de cada PC de la federación, la propia primero
    (`local: true`). Una PC caída viene con `alive: false` y sin salud reciente (dato viejo, no se
    muestra). Vacío si el server no tiene la ruta todavía (servidor sin emparejar o muy viejo).
    """
    p = pedir("GET", "/peers")[1]
    return p if isinstance(p, list) else []
