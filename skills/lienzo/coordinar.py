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
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("LIENZO_URL") or "http://127.0.0.1:7321"  # otra instancia (pruebas): LIENZO_URL
YO = ""  # session_id de la coordinadora; lo fija quien importa este módulo

# El texto de la regla de vuelta. Los marcadores los llena el server al disparar: sin `{respuesta}` llega
# solo el encabezado y la coordinadora tiene que ir a buscar el informe (medido el 2026-10-09); y el
# título va por `{titulo}` porque el id del lanzamiento (pid-N) cambia con el primer hook.
INFORME = "[regla automática] Terminó «{titulo}». Su informe:\n\n{respuesta}"


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
        if previa is not None and not pc and previa.get("pc") != s.get("pc"):
            # dos «encargo A» en PCs distintas (medido en la revision del 2026-10-04: una pisaba a la
            # otra y enviar_seguro podia mandar a la PC equivocada): las dos quedan, con la PC en la clave
            out.pop(letra)
            out[f"{letra}@{previa.get('pc')}"] = previa
            out[f"{letra}@{s.get('pc')}"] = s
            continue
        if f"{letra}@{s.get('pc')}" in out:
            continue
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
    y se cubren las fallas de otra PC:
    - La tarjeta se relee antes de mandar (la `s` que se pasa puede ser vieja). Cuenta como tomado
      que cambie `last_prompt`/`prompt_id`, o que pase a `corriendo` si antes no lo estaba.
    - Un comando con barra (`/clear`, `/model`) a una tarjeta `corriendo` no se manda: en una
      consola ocupada queda encolado y se pierde. Si se sabe que está quieta, usar `enviar`.
    - 404 con `gone` (la tarjeta ya no existe allá): se vuelve a buscar el frente por nombre
      (`proyecto` + `letra`) en la misma PC y se manda al id nuevo, una vez. Sin `proyecto`/`letra`
      no se adivina.
    - 503 con `no_llego` (el pedido no salió: PC desconocida o conexión rechazada) o el lienzo local
      que rechaza la conexión: se espera y se reintenta, hasta `reintentos` veces. Un timeout o un
      503 sin esa marca (corte a mitad) pudo haberse tecleado del otro lado: NO se reintenta.
    - Detenida (`stopped_by`) o muerta: no se manda, se dice por qué.
    """
    permitidos = "\n\t\r"  # salto de línea, tab y retorno
    raros = sorted({hex(ord(ch)) for ch in texto if ord(ch) < 32 and ch not in permitidos})
    if raros:
        # el server borra los caracteres de control sin avisar (strip_control): una ruta de Windows
        # con una barra invertida sin escapar (la «a» de D:\apps pasa a ser BEL) llega rota y el
        # agente busca archivos que no existen. Se corta acá.
        return {
            "ok": False,
            "code": 400,
            "motivo": f"el texto trae caracteres de control {raros} (¿una ruta de Windows sin escapar?)",
            "sid": s["session_id"],
        }
    for intento in range(reintentos + 1):
        s = reubicar(s, sesiones()) or s
        sid = s["session_id"]
        if s.get("stopped_by"):
            return {"ok": False, "code": 409, "motivo": f"detenida por {s['stopped_by']}", "sid": sid}
        antes = (s.get("last_prompt"), s.get("prompt_id"))
        ya_corria = s.get("state") == "corriendo"
        if ya_corria and texto.lstrip().startswith("/"):
            return {
                "ok": False,
                "code": 409,
                "motivo": "comando con barra a una tarjeta corriendo: quedaría encolado y se pierde",
                "sid": sid,
            }
        code, res = pedir("POST", f"/sessions/{sid}/send", _cuerpo_envio(sid, texto, enlazar), timeout=80)
        if code == 200:
            fin = time.time() + espera
            while time.time() < fin:
                time.sleep(1)
                n = reubicar(s, sesiones())
                # «corriendo» solo prueba algo si antes no corria: a una sesion ocupada (o pegada en
                # corriendo despues de un /compact) se le mira que cambie el pedido
                tomo = (n.get("last_prompt"), n.get("prompt_id")) != antes if n else False
                if n and (tomo or (not ya_corria and n.get("state") == "corriendo")):
                    return {"ok": True, "code": 200, "motivo": "la tarjeta lo tomó", "sid": n["session_id"]}
            motivo = (
                f"ya estaba corriendo: el server lo aceptó pero en {espera} s no cambió su prompt, así que no hay "
                "prueba de que lo tomó (mirar su pantalla o transcript antes de reenviar)"
                if ya_corria
                else f"el server lo aceptó pero la tarjeta no reaccionó en {espera} s (¿consola ocupada o en un diálogo?)"
            )
            return {"ok": False, "code": 200, "motivo": motivo, "sid": sid}
        if code == 404 and isinstance(res, dict) and res.get("gone") and proyecto and letra:
            nuevo = frentes(proyecto, pc=s.get("pc")).get(letra)
            if nuevo and nuevo["session_id"] != sid:
                s = nuevo
                continue
        # solo se reintenta lo que no salio: un 503 con `no_llego` o el lienzo local rechazando la
        # conexion. Un timeout (0) o un 503 sin la marca (corte a mitad) pudo haberse tecleado del
        # otro lado y reintentarlo lo duplicaria
        no_salio = (code == 503 and isinstance(res, dict) and res.get("no_llego")) or (
            code == 0 and "refused" in str(res).lower()
        )
        if no_salio and intento < reintentos:
            time.sleep(3 * (intento + 1))
            continue
        motivo = str(res.get("error") if isinstance(res, dict) and res.get("error") else res)[:200]
        if code in (0, 503) and not no_salio:
            motivo += " — pudo haberse tecleado igual: mirar la tarjeta antes de reenviar"
        return {"ok": False, "code": code, "motivo": motivo, "sid": sid}
    return {"ok": False, "code": 0, "motivo": "sin respuesta", "sid": s["session_id"]}


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
            if s.get("pid")
            and x.get("pid") == s.get("pid")
            and x.get("pc") == s.get("pc")
            and x.get("cwd") == s.get("cwd")
        ),
        None,
    )


_PANTALLAS = {}  # session_id -> (hash de la pantalla, desde cuándo no cambia)


def informe(s):
    """El `last_reply` de la tarjeta SOLO si es un informe: None mientras trabaja o si es el estado de
    una herramienta («usando bash», «usando read»), que el lienzo deja ahi mientras corre una coda y
    no es una respuesta (medido el 2026-10-03: se confundia con el informe final)."""
    r = (s.get("last_reply") or "").strip()
    if not r or s.get("state") == "corriendo" or re.fullmatch(r"usando [\w.\-]+( \(subagente\))?", r):
        return None
    return r


def pasar_credencial_git(pc, git_url, usuario=None):
    """Copia a la PC `pc` la credencial de git que ESTA PC ya tiene para `git_url` (la del almacen de
    Windows): viaja cifrada y la otra PC la guarda en el suyo. El valor nunca pasa por el agente ni
    por su transcript. Devuelve (code, respuesta)."""
    cuerpo = {"pc": pc, "nombre": f"git {git_url}", "destino": "git", "git_url": git_url, "desde": "git_local"}
    if usuario:
        cuerpo["usuario"] = usuario
    return pedir("POST", "/secrets", cuerpo, timeout=60)


def enviar_secreto(pc, nombre, valor, destino="memoria", git_url=None, usuario=None):
    """Manda un secreto a la PC `pc`, cifrado. destino "memoria": queda 10 min y se lee UNA vez con
    leer_secreto (desde cualquier PC de la LAN); "git": se guarda como credencial de git alla. Ojo:
    el valor que se pasa aca queda en el transcript de quien llama; para git preferi
    pasar_credencial_git. Devuelve (code, respuesta) — con "id" si es memoria."""
    cuerpo = {"pc": pc, "nombre": nombre, "destino": destino, "valor": valor}
    if git_url:
        cuerpo["git_url"] = git_url
    if usuario:
        cuerpo["usuario"] = usuario
    return pedir("POST", "/secrets", cuerpo, timeout=60)


def leer_secreto(secreto_id, pc=None):
    """Lee UNA vez un secreto de destino memoria (de esta PC, o de `pc`). Despues no existe mas."""
    return pedir("GET", f"/secrets/{secreto_id}" + (f"?pc={pc}" if pc else ""))


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


# codas trabajando a la vez contra un mismo servidor de modelos: con 5 en paralelo, Qwen en el DGX dejó a
# todas en «Waiting for model» (PENDIENTES, «Un solo modelo para todos los codas»)
CODAS_EN_PARALELO = 2


def _codas_corriendo(pc):
    return sum(
        1
        for s in sesiones()
        if s.get("agent") == "coda"
        and s.get("alive")
        and s.get("state") == "corriendo"
        and (s.get("pc") == pc or (pc is None and not s.get("pc")))
    )


def capacidad(pc, n, gb_por_sesion=0.7, reserva_gb=1.5, agent=None, en_paralelo=CODAS_EN_PARALELO):
    """¿Aguanta esa PC `n` sesiones más? Devuelve {ok, libre_gb, necesita_gb, entran}. La regla es la
    del server (`agentes_libres` en su salud, lienzo/health.py); `gb_por_sesion` y `reserva_gb` solo
    se usan con un peer viejo que todavía no publica ese campo.

    Con `agent="coda"` además cuenta el cupo del modelo, que la RAM no mide: entran a lo sumo
    `en_paralelo` codas corriendo a la vez en esa PC (`codas_corriendo` en la respuesta). Lo que no
    entra se escalona: se lanza cuando termine una."""
    r = _capacidad_ram(pc, n, gb_por_sesion, reserva_gb)
    if agent != "coda" or r["entran"] is None:
        return r
    corriendo = _codas_corriendo(pc)
    entran = min(r["entran"], max(0, en_paralelo - corriendo))
    r.update({"entran": entran, "ok": n <= entran, "codas_corriendo": corriendo})
    if not r["ok"] and entran < n:
        r["motivo"] = f"{corriendo} codas ya corren contra el modelo (tope {en_paralelo}): escalonar"
    return r


def _capacidad_ram(pc, n, gb_por_sesion, reserva_gb):
    for p in salud():
        if p.get("pc_id") == pc or (pc is None and p.get("local")):
            h = p.get("health") or {}
            libre, entran = h.get("mem_free_gb"), h.get("agentes_libres")
            if libre is None:
                # sin dato (peer recien caido, server viejo) no se dice que hay lugar: es cuando conviene frenar
                sin = {"libre_gb": None, "necesita_gb": round(n * gb_por_sesion, 1), "entran": None}
                return {"ok": False, **sin, "motivo": "sin dato de memoria"}
            if entran is None:  # peer viejo: la cuenta de antes
                entran = max(0, int((libre - reserva_gb) // gb_por_sesion)) if libre > reserva_gb else 0
            return {"ok": n <= entran, "libre_gb": libre, "necesita_gb": round(n * gb_por_sesion, 1), "entran": entran}
    return {"ok": False, "libre_gb": None, "necesita_gb": round(n * gb_por_sesion, 1), "entran": None}


def lanzar_y_titular(
    pc, cwd, titulo, agent="claude", espera=60, model=None, cablear_al_lanzar=True, proyecto=None, encargo=None
):
    """Lanza y devuelve LA tarjeta nueva (ya titulada), no solo el 200 de `lanzar`. Distingue la
    nueva de las que ya había en esa carpeta comparando ids antes y después. None si no apareció.

    **Nunca queda sin cablear**: con `YO` fijado, la tarjeta nueva sale con una regla `on_stop` hacia
    la coordinadora, para que el aviso de que terminó (o de que se colgó) llegue solo. La tarjeta nace
    como `pid-N` y al llegar su primer hook pasa a su id real: el lienzo le traslada la regla. Con
    `cablear_al_lanzar=False` se la deja sin regla (solo para una sesión de prueba descartable).

    Con `proyecto` y `encargo` (el id que devolvió `encargo(...)`), la tarjeta queda vinculada al
    encargo apenas aparece (`encargo_enviado`): v5 §7.2 pide que el lanzamiento admita la ronda."""

    def norm(c):
        # con barra o contrabarra, y con o sin barra final, es la misma carpeta (antes no coincidian y
        # la tarjeta nueva no se encontraba: devolvia None con la sesion abierta y sin regla)
        return (c or "").replace(chr(92), "/").rstrip("/").lower()

    def en_carpeta():
        return {
            x["session_id"]: x
            for x in sesiones()
            if x.get("agent") == agent and norm(x.get("cwd")) == norm(cwd) and (pc is None or x.get("pc") == pc)
        }

    if cablear_al_lanzar and not YO:
        print("lanzar_y_titular: c.YO esta vacio, la tarjeta nueva queda SIN regla de aviso", file=sys.stderr)
    antes = set(en_carpeta())
    code, res = lanzar(pc, cwd, titulo, agent, model)
    if code != 200:
        print(f"lanzar_y_titular: no se lanzo ({code}): {res}", file=sys.stderr)
        return None
    fin = time.time() + espera
    while time.time() < fin:
        time.sleep(3)
        nuevas = [x for sid, x in en_carpeta().items() if sid not in antes]
        if nuevas:
            nueva = nuevas[0]
            titular(nueva, titulo)
            if cablear_al_lanzar and YO:
                regla_informe(nueva, INFORME)
            if proyecto and encargo:
                try:
                    encargo_enviado(proyecto, encargo, nueva)
                except RuntimeError as e:  # la tarjeta ya existe: se informa, no se pierde
                    print(f"lanzar_y_titular: no se vinculo el encargo: {e}", file=sys.stderr)
            return nueva
    print(
        f"lanzar_y_titular: se lanzo pero la tarjeta no aparecio en {espera} s (queda abierta, sin titulo ni regla)",
        file=sys.stderr,
    )
    return None


def reiniciar(pc=None):
    """Reinicia el server de lienzo de esta PC (o de `pc`): sale y lienzo-server.cmd lo relanza en la
    misma ventana. Desde el 2026-10-04 el server ya no se reinicia solo al cambiar un .py (salvo
    `auto_reload: true` en config.json): despues de un git pull hay que llamar a esto. 409 si no corre
    bajo lienzo-server.cmd o si hay codigo que no compila."""
    return pedir("POST", "/restart", {"pc": pc} if pc else {}, timeout=30)


def titular(s, titulo):
    return pedir("PUT", f"/sessions/{s['session_id']}/title", {"title": titulo})[0]


def regla_informe(s, texto, max_fires=30):
    """Regla `on_stop` del frente hacia la coordinadora, para que el informe llegue solo.

    `repeat` es obligatorio: sin él dispara una vez y queda apagada, y un frente que cierra dos
    turnos avisa solo el primero.
    """
    if not YO:
        raise ValueError(
            "c.YO esta vacio: fija c.YO = <session_id de la coordinadora> antes de cablear (sin eso el server contesta 404 'sesion destino desconocida')"
        )
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
    if not YO:
        raise ValueError(
            "c.YO esta vacio: fija c.YO = <session_id de la coordinadora> antes de cablear (sin eso el server contesta 404 'sesion destino desconocida')"
        )
    r = pedir("GET", "/rules")[1]
    r = r if isinstance(r, list) else (r or {}).get("rules", []) or []
    ya = {x.get("from") for x in r if x.get("to") == YO and x.get("kind") == "on_stop"}
    out = {"creadas": [], "ya_estaban": [], "fallaron": []}
    pendientes = []
    for s in sesiones():
        sid = s["session_id"]
        if sid == YO or s.get("coordinator") or (pc and s.get("pc") != pc) or (solo_vivas and not s.get("alive")):
            continue
        if filtro and not filtro(s):
            continue
        if sid in ya:
            out["ya_estaban"].append(sid)
            continue
        pendientes.append((sid, texto or INFORME))

    def crear(par):
        sid, msg = par
        return sid, pedir(
            "POST",
            "/rules",
            {"kind": "on_stop", "from": sid, "to": YO, "text": msg, "repeat": True, "max_fires": max_fires},
        )

    # en paralelo: una regla de una tarjeta de otra PC lenta o caida esperaba su timeout antes de seguir
    # con las demas (PENDIENTES, «cablear consulta en serie»)
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=8) as pool:
        for sid, (code, res) in pool.map(crear, pendientes):
            if code == 200:
                out["creadas"].append(sid)
            else:
                out["fallaron"].append(
                    {
                        "sid": sid,
                        "code": code,
                        "error": (res if isinstance(res, str) else (res or {}).get("error", ""))[:140],
                    }
                )
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
    lo soporta o el id no es válido (solo `[A-Za-z0-9._/:@-]`). **En coda cambia el modelo por defecto
    de esa PC** (lo escribe en su `config.json`): avisarle al usuario antes de usarlo.
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


RESTAURAR_TIMEOUT_S = 330  # el reenvío a la otra PC (300 s) más el margen del server local


def restaurar(session_id=None, pc=None, todas=False, limit_by_memory=False):
    """POST /restaurar: relanza UNA sesión (`session_id`) o `todas` las de la PC `pc` (None = esta),
    de a una con ~2 s entre cada una. Devuelve (código, cuerpo) con `{restored, failed}`. `todas` se
    rechaza (409, con cuántas entran) si falta memoria en esa PC, salvo `limit_by_memory=True`, que
    relanza solo las que entran. Son varios lanzamientos en fila: espera más que los 300 s con
    que el server reenvía /restaurar a la PC dueña (federation.RESTORE_TIMEOUT_S). Con 120 s el
    skill veía un timeout aunque el relanzamiento siguiera andando del otro lado; no duplica
    sesiones (un segundo pedido da 409 mientras el primero corre), pero el llamador creía que
    había fallado.
    """
    if bool(session_id) == bool(todas):
        raise ValueError("pasá session_id, o todas=True (una de las dos)")
    cuerpo = {"all": True} if todas else {"session_id": session_id}
    if pc:
        cuerpo["pc"] = pc
    if limit_by_memory:
        cuerpo["limit_by_memory"] = True
    return pedir("POST", "/restaurar", cuerpo, timeout=RESTAURAR_TIMEOUT_S)


def copiar(pc, origen, destino, esperar=False, cada=5, **opciones):
    """POST /xfer: copia `origen` (archivo o carpeta de ESTA PC) a la carpeta `destino` de la PC `pc`,
    por el canal de peers (bloques firmados, retomable, verificado). Las dos rutas tienen que caer en
    `copy_roots` de su PC. `opciones`: hilos, bs_mib, mbps, disco_mbps, espejo. Devuelve el id; con
    `esperar=True`, la vista final (`avance`) cuando deja de copiar: `estado == "terminado"` es que
    todo llegó y se verificó del otro lado. Si el POST falla, levanta RuntimeError con el motivo."""
    code, res = pedir("POST", "/xfer", {"pc": pc, "origen": origen, "destino": destino, **opciones})
    if code != 202:
        raise RuntimeError(f"copiar: {code} {res}")
    if not esperar:
        return res["id"]
    while True:
        time.sleep(cada)
        v = avance(res["id"])
        if v.get("estado") not in ("listando", "copiando", "esperando"):
            return v


def avance(xid):
    """GET /xfer/<id>: estado (listando, copiando, terminado, con_errores, error, pausado,
    confirmar_espejo), pct, mbps, eta_s, archivos_hechos/total, salteados, errores, ultimos."""
    return pedir("GET", f"/xfer/{xid}")[1] or {}


def copias():
    """GET /xfer: todas las copias de esta PC, la más nueva primero."""
    r = pedir("GET", "/xfer")[1]
    return r if isinstance(r, list) else []


def pausar_copia(xid):
    """DELETE /xfer/<id>: pausa; lo que está en vuelo termina. `retomar_copia` sigue desde ahí."""
    return pedir("DELETE", f"/xfer/{xid}")


def retomar_copia(xid):
    return pedir("POST", f"/xfer/{xid}/retomar", {})


def confirmar_espejo(xid):
    """Con `espejo=True` la copia frena en `confirmar_espejo` mostrando `borraria`: esto la deja borrar."""
    return pedir("POST", f"/xfer/{xid}/confirmar", {})


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


# --- conocimiento por proyecto (docs/propuesta-memoria-2026-10-08/v5.md, etapa 1) -------------
#
# El lienzo guarda por proyecto (en una base por instancia, ~/.lienzo/conocimiento.sqlite), las rondas, los encargos tal
# como se mandaron, los informes tal como se entregaron (con hash y revisión) y lo que el server
# observa de las sesiones que trabajan un encargo. Etapa 1: inventario estructural; el bloque
# `conocimiento` del informe y los veredictos de la coordinadora vienen en las etapas 2 y 3.


def _conocimiento(metodo, ruta, cuerpo=None):
    code, res = pedir(metodo, "/conocimiento" + ruta, cuerpo)
    if code != 200:
        raise RuntimeError(f"conocimiento {metodo} {ruta}: {code} {res.get('error') if isinstance(res, dict) else res}")
    return res


def proyecto(pid, nombre=None, remotes=None, carpetas=None):
    """Registra el proyecto (o le suma remotes y carpetas si ya existe) y devuelve su ficha. `remotes`
    son claves como `github.com/arielelevy/teorema`; `carpetas`, `[{"pc": pc_id, "cwd": ruta}]`.
    Un alias que ya es de otro proyecto es 409: nada se fusiona por nombre."""
    return _conocimiento("POST", "/proyectos", {"id": pid, "nombre": nombre, "remotes": remotes, "carpetas": carpetas})


def proyecto_de(s):
    """El proyecto de una tarjeta por su repo_key o su carpeta en esa PC, o None si no está asignado."""
    q = urllib.parse.urlencode(
        {k: v for k, v in (("repo_key", s.get("repo_key")), ("cwd", s.get("cwd")), ("pc", s.get("pc"))) if v}
    )
    return _conocimiento("GET", f"/resolver?{q}").get(
        "proyecto"
    )  # un server caido o un 401 se ve, no es «sin proyecto»


def proyecto_carpeta(cwd, pc=None):
    """El proyecto de una carpeta, creado si falta (proyecto = carpeta: lo que pasa por el lienzo ya
    queda solo; esto sirve para conocer el id antes de la primera captura). `proyecto(...)` queda para
    ponerle nombre o sumarle remotes."""
    return _conocimiento("POST", "/carpeta", {"cwd": cwd, "pc": pc})["proyecto"]


def capturas(pid, session_id=None, clase=None, desde=None, limite=100):
    """Lo que el lienzo capturo solo en el proyecto: pedidos, respuestas finales, envíos y disparos de
    reglas, de lo más nuevo a lo más viejo. `clase`: pedido|respuesta|envio|regla."""
    return _consulta_memoria(
        pid, "capturas", {"session_id": session_id, "clase": clase, "desde": desde, "limite": limite}
    )


def prosa(pid, consulta, limite=30):
    """BM25 sobre lo escrito (cuerpos de encargos e informes, capturas): «prosa, no declarado»."""
    return _consulta_memoria(pid, "prosa", {"q": consulta, "limite": limite})


def texto_roto(pid):
    """U+FFFD y mojibake en nodos, cuerpos, cambios y capturas del proyecto (solo mide)."""
    return _conocimiento("GET", f"/{pid}/texto/roto")


def reparar_texto(pid, aplicar=False):
    """Repara el mojibake de los nodos con un cambio auditado por nodo; sin `aplicar`, dice qué haría.
    Los nodos con U+FFFD vuelven en `irrecuperables`."""
    return _conocimiento("POST", f"/{pid}/texto/reparar", {"por": f"coordinadora:{YO}", "aplicar": bool(aplicar)})


def abrir_ronda(pid, objetivo):
    """Abre una ronda y devuelve su nodo (`id`). Se abre ANTES de repartir: cada encargo la cita."""
    return _conocimiento(
        "POST", f"/{pid}/rondas", {"objetivo": objetivo, "coordinadora": YO, "autor": f"coordinadora:{YO}"}
    )


def encargo(pid, ronda, letra, texto, archivos=None):
    """Registra el encargo (el texto entero queda en rondas/<ronda>/encargo-<letra>.md) y devuelve su
    nodo. Después de lanzar o mandar, `encargo_enviado(pid, e["id"], s)` lo vincula a la tarjeta."""
    return _conocimiento(
        "POST",
        f"/{pid}/encargos",
        {"ronda": ronda, "letra": letra, "texto": texto, "archivos": archivos or [], "autor": f"coordinadora:{YO}"},
    )


def encargo_enviado(pid, encargo_id, s):
    """La tarjeta `s` tomó el encargo: pasa a `enviado` y queda vinculada (ejecutado_por). Desde acá
    el server registra solo lo que observe de esa sesión: cierre, permisos denegados, muerte a medias."""
    return _conocimiento(
        "POST",
        f"/{pid}/encargos/{encargo_id}/enviado",
        {k: s.get(k) for k in ("session_id", "agent", "model", "pc", "cwd")},
    )


def entregar(pid, encargo_id, cuerpo, revision=1, autor=None):
    """La entrega explícita de un informe íntegro: queda con hash en rondas/<ronda>/informe-<letra>-r<N>.md
    y el encargo pasa a `entregado`. Idempotente por (encargo, revisión, hash); la misma revisión con
    otro contenido es 409. La coordinadora lo llama con el texto que leyó del frente (`informe(s)`).
    Si el informe termina con un bloque ```conocimiento``` (ver INSTRUCCION_CONOCIMIENTO), el resultado
    trae `datos.conocimiento`: `{estado: "incorporado", ids: {local: id}}` o
    `{estado: "pendiente_de_vincular", errores: [{donde, error}]}`; en ese caso se le piden al frente
    las correcciones y se entrega como revisión siguiente."""
    return _conocimiento(
        "POST",
        f"/{pid}/entregas",
        {"encargo": encargo_id, "revision": revision, "cuerpo": cuerpo, "autor": autor or f"coordinadora:{YO}"},
    )


def cerrar_ronda(pid, ronda, motivo="", veredictos=None, sin_resolver=None):
    return _conocimiento(
        "POST",
        f"/{pid}/rondas/{ronda}/cerrar",
        {"por": f"coordinadora:{YO}", "motivo": motivo, "veredictos": veredictos, "sin_resolver": sin_resolver},
    )


def veredicto(pid, items, revision=None, evidencia=None, motivo=""):
    return _conocimiento(
        "POST",
        f"/{pid}/veredictos",
        {
            "items": items,
            "por": f"coordinadora:{YO}",
            "revision": revision,
            "evidencia": evidencia,
            "motivo": motivo,
        },
    )


def pendientes_memoria(pid, ronda=None):
    q = urllib.parse.urlencode({"ronda": ronda}) if ronda else ""
    return _conocimiento("GET", f"/{pid}/pendientes?{q}")


def duplicados(pid, ronda=None):
    q = urllib.parse.urlencode({"ronda": ronda}) if ronda else ""
    return _conocimiento("GET", f"/{pid}/duplicados?{q}")


def tema(pid, texto, aliases=None):
    return _conocimiento("POST", f"/{pid}/temas", {"texto": texto, "aliases": aliases, "por": f"coordinadora:{YO}"})


def temas(pid):
    return _conocimiento("GET", f"/{pid}/temas")


def _consulta_memoria(pid, ruta, parametros):
    q = urllib.parse.urlencode({k: v for k, v in parametros.items() if v is not None}, doseq=True)
    return _conocimiento("GET", f"/{pid}/{ruta}?{q}")


def briefing(pid, archivos=None, temas=None, consultas=None, desde_cierre=True, encargos=None, markdown=False):
    """Lo vigente, lo abierto, los avisos y lo cambiado desde el último cierre. `encargos` (ids) suma los
    archivos que declaró cada encargo; `markdown=True` agrega `markdown`, el texto para pegar."""
    return _consulta_memoria(
        pid,
        "briefing",
        {
            "archivos": archivos,
            "temas": temas,
            "q": consultas,
            "desde_cierre": int(desde_cierre),
            "encargos": encargos,
            "markdown": 1 if markdown else None,
        },
    )


def por_que(pid, alternativa):
    """¿Por qué se descartó esta alternativa? Decisiones que la descartan (con motivo), sus fundamentos
    y las que la eligen."""
    return _conocimiento("GET", f"/{pid}/alternativas/{alternativa}/por_que")


def reincorporar(pid, informe):
    """Vuelve a validar el bloque pendiente de un informe (lo que faltaba ya existe)."""
    return _conocimiento("POST", f"/{pid}/informes/{informe}/reincorporar", {"por": f"coordinadora:{YO}"})


def evidencia(pid, nombre, clase, contenido, texto=None):
    """Entrega un artefacto (bytes o texto) como evidencia del proyecto: queda en evidencia/ con hash."""
    import base64

    cuerpo = {"nombre": nombre, "clase": clase, "texto": texto, "autor": f"coordinadora:{YO}"}
    if isinstance(contenido, bytes):
        cuerpo["contenido_base64"] = base64.b64encode(contenido).decode("ascii")
    else:
        cuerpo["contenido_texto"] = contenido
    return _conocimiento("POST", f"/{pid}/evidencia", cuerpo)


def replicar(pc=None):
    """Trae ya de la PC `pc` (o de todas las vivas) lo nuevo de la memoria; normalmente corre sola."""
    return _conocimiento("POST", "/replicar", {"pc": pc})


def estado_replica(pid):
    """Cursores por PC, choques (nodos cambiados en dos PCs a la vez) y duplicados sugeridos."""
    return _conocimiento("GET", f"/{pid}/replica")


def respaldar(pid):
    """Respaldo de la base (API de backup de SQLite) y sus artefactos en ~/.lienzo/respaldos/."""
    return _conocimiento("POST", f"/{pid}/respaldo", {})


def preguntar(pid, consultas, archivos=None, temas=None, tipo=None, saltos=1, offset=0, limite=100, prosa=False):
    """joins -> BM25 -> grafo. Con `prosa=True` suma `prosa`: lo escrito en encargos, informes y capturas
    que coincide, marcado «prosa, no declarado» (no son nodos: no tienen estado ni veredicto)."""
    return _consulta_memoria(
        pid,
        "preguntar",
        {
            "q": consultas,
            "archivos": archivos,
            "temas": temas,
            "tipo": tipo,
            "saltos": saltos,
            "offset": offset,
            "limite": limite,
            "prosa": 1 if prosa else None,
        },
    )


def vista(pid, tema):
    return _consulta_memoria(pid, "vista", {"tema": tema})


def preparar_encargo(pid, texto, archivos=None, temas=None, consultas=None):
    """Texto para un frente con el briefing actual y la plantilla de conocimiento."""
    contexto = briefing(pid, archivos=archivos, temas=temas, consultas=consultas, markdown=True)
    return "\n\n".join((texto, contexto["markdown"], INSTRUCCION_CONOCIMIENTO))


def parecidos(pid, incidente, limite=20):
    return _consulta_memoria(pid, f"incidentes/{incidente}/parecidos", {"limite": limite})


def recurrencia(pid, incidente):
    return _conocimiento("GET", f"/{pid}/incidentes/{incidente}/recurrencia")


def cuestionar(pid, regla=None):
    ruta = f"reglas/{regla}/cuestionar" if regla else "reglas/cuestionar"
    return _conocimiento("POST", f"/{pid}/{ruta}", {})


def reglas_cuestionadas(pid):
    return _conocimiento("GET", f"/{pid}/reglas/cuestionadas")


def avisos(pid, nodo=None):
    return _conocimiento("GET", f"/{pid}/nodos/{nodo}/aviso" if nodo else f"/{pid}/avisos")


def dependencias(pid, nodo):
    return _conocimiento("GET", f"/{pid}/nodos/{nodo}/dependencias")


def lecciones(agente, modelo=None, proyectos=None):
    q = urllib.parse.urlencode(
        {
            k: v
            for k, v in {
                "agente": agente,
                "modelo": modelo,
                "proyectos": ",".join(proyectos) if proyectos else None,
            }.items()
            if v is not None
        }
    )
    return _conocimiento("GET", f"/lecciones?{q}")


def conocimiento(pid, consulta=None, tipo=None, saltos=1, estado=None, ronda=None):
    """Sin `consulta`: el resumen del proyecto (nodos por tipo y estado, rondas). Con `consulta`:
    búsqueda BM25 (sintaxis FTS5: `halving OR mitad`, `sustitu*`) más los vecinos a `saltos` por el
    grafo. Con `tipo`/`estado`/`ronda` y sin consulta: la lista de nodos."""
    if consulta:
        q = urllib.parse.urlencode(
            {k: v for k, v in (("q", consulta), ("tipo", tipo), ("saltos", saltos)) if v not in (None, "")}
        )
        return _conocimiento("GET", f"/{pid}/buscar?{q}")
    if tipo or estado or ronda:
        q = urllib.parse.urlencode({k: v for k, v in (("tipo", tipo), ("estado", estado), ("ronda", ronda)) if v})
        return _conocimiento("GET", f"/{pid}/nodos?{q}")
    return _conocimiento("GET", f"/{pid}")


INSTRUCCION_CONOCIMIENTO = """\
Terminá el informe con un bloque de conocimiento para el lienzo (JSON dentro de ```conocimiento ... ```).
Declarás lo que aprendiste del proyecto: hallazgos, decisiones con sus alternativas, preguntas, mediciones,
incidentes, reglas, temas y evidencia. Si no hay nada que declarar, no pongas el bloque.

```conocimiento
{
  "version": 1,
  "nodos": [
    {"id": "h1", "tipo": "hallazgo", "texto": "<una afirmacion>", "datos": {"donde": "ruta:linea o dominio:concepto", "gravedad": "baja|media|alta|critica"}},
    {"id": "a1", "tipo": "alternativa", "texto": "<un camino considerado>", "datos": {}},
    {"id": "d1", "tipo": "decision", "texto": "<lo elegido>", "datos": {"motivo": "<por que>"}},
    {"id": "p1", "tipo": "pregunta", "texto": "<lo que falta responder>", "datos": {"para_quien": "coordinadora|ariel"}},
    {"id": "m1", "tipo": "medicion", "texto": "<que se midio>", "datos": {"metrica": "", "valor": 0, "unidad": "", "condicion": "<commit, PC, datos>"}},
    {"id": "t1", "tipo": "tema", "texto": "<modulo, archivo o concepto>", "datos": {}}
  ],
  "vinculos": [
    {"de": "d1", "relacion": "motivada_por", "a": "h1"},
    {"de": "d1", "relacion": "descarta", "a": "a1", "motivo": "<por que no>"},
    {"de": "h1", "relacion": "sobre", "a": "t1"}
  ]
}
```

Reglas: cada nodo lleva id local unico, tipo, texto y datos. Una decision exige motivo y al menos un vinculo
elige o descarta; una regla exige ambito (proyecto|agente) y derivada_de; un incidente, herramienta y agente;
una evidencia, clase y referencia. Relaciones que podes declarar: motivada_por, elige, descarta, derivada_de,
aplica_a, sobre, apoya. Un extremo es un id local o `nodo:<id>` de algo que ya esta en el proyecto (te lo doy
en el encargo). Si algo no valida, el bloque entero queda afuera y te pido la correccion.
"""
