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

import hashlib
import json
import re
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:7321"
YO = ""  # session_id de la coordinadora; lo fija quien importa este módulo


def pedir(metodo, ruta, cuerpo=None, timeout=20):
    """Un pedido al lienzo. Devuelve (código, cuerpo), y 0 con el motivo si no hubo respuesta.

    En un error HTTP el cuerpo es el dict del JSON de error (`{"error", "code", "gone"…}`); si no
    es JSON, el texto recortado a 200 caracteres.

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
        texto = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(texto)
        except ValueError:
            return e.code, texto[:200]
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


def _cuerpo_envio(sid, texto, enlazar):
    """El JSON de `POST /sessions/<sid>/send`; con `enlazar` (y `YO`) el tablero dibuja la flecha."""
    cuerpo = {"text": texto}
    if enlazar and YO:
        cuerpo.update({"from": YO, "link_to": sid})
    return cuerpo


def enviar(s, texto, enlazar=True):
    """Escribe en la terminal de esa sesión. Con `enlazar`, el tablero dibuja la flecha."""
    return pedir("POST", f"/sessions/{s['session_id']}/send", _cuerpo_envio(s["session_id"], texto, enlazar))[0]


def enviar_seguro(s, texto, proyecto=None, letra=None, enlazar=True, espera=8, reintentos=2):
    """Como `enviar`, pero no da por hecho que llegó: devuelve {"ok", "code", "motivo", "sid"}.

    Un 200 sólo dice que el server aceptó el pedido. Acá además se verifica que la tarjeta lo tomó
    (pasa a `corriendo`, o `last_prompt` cambia) y se cubren las fallas de otra PC:
    - 404 con `gone` (la tarjeta ya no existe allá): se vuelve a buscar el frente por nombre
      (`proyecto` + `letra`) y se manda al id nuevo, una vez. Sin `proyecto`/`letra` no se adivina.
    - 503 (sin conexión con esa PC): se espera y se reintenta, hasta `reintentos` veces.
    - Detenida (`stopped_by`) o muerta: no se manda, se dice por qué.
    """
    permitidos = "\n\t\r"  # salto de línea, tab y retorno
    raros = sorted({hex(ord(ch)) for ch in texto if ord(ch) < 32 and ch not in permitidos})
    if raros:
        # el server borra los caracteres de control sin avisar (strip_control): una ruta de Windows
        # con una barra invertida sin escapar (la «a» de D:\apps pasa a ser BEL) llega rota y el
        # agente busca archivos que no existen. Se corta acá.
        return {"ok": False, "code": 400, "motivo": f"el texto trae caracteres de control {raros} (¿una ruta de Windows sin escapar?)", "sid": s["session_id"]}
    sid = s["session_id"]
    for intento in range(reintentos + 1):
        if s.get("stopped_by"):
            return {"ok": False, "code": 409, "motivo": f"detenida por {s['stopped_by']}", "sid": sid}
        antes = (s.get("last_prompt"), s.get("prompt_id"))
        code, res = pedir("POST", f"/sessions/{sid}/send", _cuerpo_envio(sid, texto, enlazar), timeout=80)
        if code == 200:
            fin = time.time() + espera
            while time.time() < fin:
                time.sleep(1)
                n = reubicar(s, sesiones())
                if n and (n.get("state") == "corriendo" or (n.get("last_prompt"), n.get("prompt_id")) != antes):
                    return {"ok": True, "code": 200, "motivo": "la tarjeta lo tomó", "sid": n["session_id"]}
            return {"ok": False, "code": 200, "motivo": f"el server lo aceptó pero la tarjeta no reaccionó en {espera} s (¿consola ocupada o en un diálogo?)", "sid": sid}
        if code == 404 and isinstance(res, dict) and res.get("gone") and proyecto and letra:
            nuevo = frentes(proyecto).get(letra)
            if nuevo and nuevo["session_id"] != sid:
                s, sid = nuevo, nuevo["session_id"]
                continue
        if code in (0, 503) and intento < reintentos:
            time.sleep(3 * (intento + 1))
            continue
        motivo = res.get("error") if isinstance(res, dict) and res.get("error") else res
        return {"ok": False, "code": code, "motivo": str(motivo)[:200], "sid": sid}
    return {"ok": False, "code": 0, "motivo": "sin respuesta", "sid": sid}


def reubicar(s, todas):
    """La tarjeta `s` tal como está ahora. Una sesión sin hooks (barrido, coda) nace con id
    `pid-NNNN` y, al engancharse los hooks, pasa a tener su UUID real: el id viejo desaparece pero
    es el mismo proceso. Se busca por id y, si no está, por (pc, pid, cwd)."""
    por_id = next((x for x in todas if x["session_id"] == s["session_id"]), None)
    if por_id:
        return por_id
    return next(
        (
            x
            for x in todas
            if s.get("pid") and x.get("pid") == s.get("pid") and x.get("pc") == s.get("pc") and x.get("cwd") == s.get("cwd")
        ),
        None,
    )


_PANTALLAS = {}  # session_id -> (hash de la pantalla, desde cuándo no cambia)


def estancada(s, minutos=5):
    """True si la tarjeta figura `corriendo` pero su pantalla no cambió en `minutos`: el agente (o el
    modelo detrás, p. ej. el DGX de coda) quedó colgado. Hay que llamarla de a ratos: guarda la
    última pantalla vista. Sirve para decidir interrumpir y reintentar en vez de esperar de más."""
    code, x = pedir("GET", f"/sessions/{s['session_id']}/screen")
    if code != 200 or not isinstance(x, dict):
        return False
    h = hashlib.md5("\n".join(x.get("lines") or []).encode("utf-8")).hexdigest()
    ahora = time.time()
    previo = _PANTALLAS.get(s["session_id"])
    if previo is None or previo[0] != h:
        _PANTALLAS[s["session_id"]] = (h, ahora)
        return False
    return s.get("state") == "corriendo" and ahora - previo[1] >= minutos * 60


def capacidad(pc, n, gb_por_sesion=0.7, reserva_gb=1.5):
    """¿Aguanta esa PC `n` sesiones más? Devuelve {ok, libre_gb, necesita_gb}. Una sesión ocupa unos
    0,7 GB; con menos de `reserva_gb` libres Windows empieza a paginar y arrastra al resto."""
    for p in salud():
        if p.get("pc_id") == pc or (pc is None and p.get("local")):
            libre = (p.get("health") or {}).get("mem_free_gb")
            if libre is None:
                return {"ok": True, "libre_gb": None, "necesita_gb": round(n * gb_por_sesion, 1)}
            return {"ok": libre - n * gb_por_sesion >= reserva_gb, "libre_gb": libre, "necesita_gb": round(n * gb_por_sesion, 1)}
    return {"ok": False, "libre_gb": None, "necesita_gb": round(n * gb_por_sesion, 1)}


def lanzar_y_titular(pc, cwd, titulo, agent="claude", espera=60, model=None):
    """Lanza y devuelve LA tarjeta nueva (ya titulada), no solo el 200 de `lanzar`. Distingue la
    nueva de las que ya había en esa carpeta comparando ids antes y después. None si no apareció."""
    def en_carpeta():
        return {
            x["session_id"]: x
            for x in sesiones()
            if x.get("agent") == agent and (x.get("cwd") or "").lower() == cwd.lower() and (pc is None or x.get("pc") == pc)
        }

    antes = set(en_carpeta())
    code, res = lanzar(pc, cwd, titulo, agent, model)
    if code != 200:
        return None
    fin = time.time() + espera
    while time.time() < fin:
        time.sleep(3)
        nuevas = [x for sid, x in en_carpeta().items() if sid not in antes]
        if nuevas:
            nueva = nuevas[0]
            titular(nueva, titulo)
            return nueva
    return None


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


def cablear(texto=None, pc=None, solo_vivas=True, max_fires=30, filtro=None):
    """Cablea CADA frente vivo hacia la coordinadora (`YO`): una regla `on_stop` por tarjeta, para que
    el informe llegue solo cuando termine. No repite las que ya tienen regla hacia `YO`, no cablea a
    la coordinadora consigo misma. `filtro(s)` (opcional) deja afuera lo que no es de este trabajo: sin
    él se cablea TODO lo vivo, incluidas sesiones de otros proyectos. Devuelve
    {"creadas": [...], "ya_estaban": [...], "fallaron": [{"sid", "code", "error"}]}.

    Una tarjeta de OTRA PC crea su regla en esa PC (ahi ocurre el Stop): si esa PC tiene un lienzo
    viejo, falla con un mensaje que lo dice (hace falta `git pull` y reiniciarlo)."""
    r = pedir("GET", "/rules")[1]
    r = r if isinstance(r, list) else (r or {}).get("rules", []) or []
    ya = {x.get("from") for x in r if x.get("to") == YO and x.get("kind") == "on_stop"}
    out = {"creadas": [], "ya_estaban": [], "fallaron": []}
    for s in sesiones():
        sid = s["session_id"]
        if sid == YO or s.get("coordinator") or (pc and s.get("pc") != pc) or (solo_vivas and not s.get("alive")):
            continue
        if filtro and not filtro(s):
            continue
        if sid in ya:
            out["ya_estaban"].append(sid)
            continue
        nombre = (s.get("title") or s.get("repo") or sid[:8])[:40]
        msg = texto or f"[regla automática] Terminó «{nombre}» ({sid[:8]}). Leé su `last_reply` en GET /sessions (la tarjeta {sid}) y decidí el próximo paso."
        code, res = pedir("POST", "/rules", {"kind": "on_stop", "from": sid, "to": YO, "text": msg, "repeat": True, "max_fires": max_fires})
        if code == 200:
            out["creadas"].append(sid)
        else:
            out["fallaron"].append({"sid": sid, "code": code, "error": (res if isinstance(res, str) else (res or {}).get("error", ""))[:140]})
    return out


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


def lanzar(pc, cwd, titulo, agent="claude", model=None):
    """POST /sessions/launch: lanza una sesión nueva, local si `pc` es None (o la propia), o en la
    PC `pc` (`pc_id` de `GET /peers`) si se da. `cwd` tiene que caer dentro de `launch_roots` de esa
    PC (`config.json`; vacía o ausente ahí es NINGUNA carpeta, no todas). La tarjeta nueva aparece
    después de un barrido: buscarla por `title` (o por `pc` + orden de aparición).

    `model` elige el modelo de la sesión con `--model` (coda, claude y codex), por ejemplo
    `globant_dgx/GLM-5.3-Flash` para coda. La respuesta trae `model_applied`: falso si el agente no
    lo soporta o el id no es válido (solo `[A-Za-z0-9._/:@-]`).
    """
    cuerpo = {"cwd": cwd, "agent": agent, "title": titulo}
    if pc:
        cuerpo["pc"] = pc
    if model:
        cuerpo["model"] = model
    return pedir("POST", "/sessions/launch", cuerpo)


def restaurables(pc=None):
    """GET /restaurables: las sesiones que se pueden relanzar tras un reinicio, de esta PC y de cada
    peer vivo, la más nueva primero, cada una `{session_id, agent, cwd, title, repo, pc, saved_at,
    ended_at}`. Con `pc` (`pc_id` de `GET /peers`) solo las de esa PC.
    """
    r = pedir("GET", "/restaurables")[1]
    r = r if isinstance(r, list) else []
    return [e for e in r if e.get("pc") == pc] if pc else r


def restaurar(session_id=None, pc=None, todas=False, limit_by_memory=False):
    """POST /restaurar: relanza UNA sesión (`session_id`) o `todas` las de la PC `pc` (None = esta),
    de a una con ~2 s entre cada una. Devuelve (código, cuerpo) con `{restored, failed}`. `todas` se
    rechaza (409, con cuántas entran) si falta memoria en esa PC, salvo `limit_by_memory=True`, que
    relanza solo las que entran. Mismo timeout largo que un lanzamiento: son varios en fila.
    """
    if bool(session_id) == bool(todas):
        raise ValueError("pasá session_id, o todas=True (una de las dos)")
    cuerpo = {"all": True} if todas else {"session_id": session_id}
    if pc:
        cuerpo["pc"] = pc
    if limit_by_memory:
        cuerpo["limit_by_memory"] = True
    return pedir("POST", "/restaurar", cuerpo, timeout=120)


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
