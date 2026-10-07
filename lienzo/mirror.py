"""Espejo en memoria de las sesiones, pendientes, links y reglas de cada peer (plan-multi-pc-
2026-09-26.md, §3.3), y enrutado de comandos hacia la PC dueña de una sesion (§3.4). Un `Mirror`
por proceso: un `SSEClient` por peer conectado contra `/peer/events`, snapshot completo al
(re)conectar, y salud pedida cada `HEALTH_EVERY_S`. No persiste nada: si el server se reinicia, el
espejo se arma de nuevo desde cero apenas se reconecta a cada peer.

`MIRROR` es el singleton que usan server.py (rutas /peers, /sessions, /pending, enrutado) y, en la
ronda 3, sessions.py/rules.py/launch.py (owner_of, forward, sessions(), rules())."""

from __future__ import annotations

import statistics
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable

import federation
import red

HEALTH_EVERY_S = 15.0
# sin snapshot, evento SSE (incluido el ping cada 15 s) ni salud en este tiempo: el peer se
# considera caido. Bastante mas que HEALTH_EVERY_S para no marcarlo caido por un solo pedido lento.
PEER_TIMEOUT_S = 45.0


def iso(ts: float) -> str:
    import datetime as dt

    return dt.datetime.fromtimestamp(ts).astimezone().isoformat(timespec="milliseconds")


LATENCIAS_N = 50  # reenvios recientes con que se calcula la latencia tipica de un peer
LENTO_MS = 2000  # un GET que tarda mas que esto se loguea aunque haya salido bien


class _PeerMirror:
    """Estado espejado de un solo peer, mas lo necesario para hablarle (conexion firmada)."""

    def __init__(self, pc_id: str, info: dict, conn: federation.PeerConn):
        self.pc_id = pc_id
        self.info = info  # {name, color, host, port}
        self.conn = conn
        self.sessions: dict[str, dict] = {}
        self.pending: dict[str, dict] = {}
        self.links: list[dict] = []
        self.rules: list[dict] = []
        self.health: dict | None = None
        self.health_error: str | None = None  # el ultimo fallo avisado al pedir su salud
        self.diagnostico: str | None = None  # por que no llega, para el tablero (red.diagnosticar)
        self.latencias_ms: deque[float] = deque(maxlen=LATENCIAS_N)  # de los reenvios que llegaron
        self.last_seen: float = 0.0
        self.client: federation.SSEClient | None = None
        self.synced = False  # ya llego su snapshot completo en esta conexion
        self.event_generation = 0
        self.last_snapshot = time.monotonic()
        self.vivo_avisado: bool | None = None  # el ultimo estado vivo/caida que se dejo en el log
        self.evento_raro: str | None = None  # el ultimo tipo de evento no-objeto avisado


def _tag(items, pc_id: str) -> list[dict]:
    """Copia cada item con `pc` completado si no lo traia (compatibilidad con lo que se guardo
    antes de que este campo existiera; lo normal es que ya venga puesto)."""
    return [{**x, "pc": x.get("pc") or pc_id} for x in items]


class Mirror:
    """Un espejo por proceso. `transport` es inyectable (test doble sin red); `on_change` se llama
    cada vez que cambia algo espejado, para que server.py pueda avisar por SSE si hace falta."""

    def __init__(self, transport: federation.Transport | None = None, on_change: Callable[[], None] | None = None):
        self.transport = transport or federation.HTTPTransport()
        self.on_change = on_change or (lambda: None)
        self.on_snapshot: Callable[[str, set[str]], None] = lambda pc, ids: None
        self.log: Callable[[str], None] = lambda msg: None  # server.py lo cambia por su log
        self.diagnosticar: Callable[[str, BaseException], str | None] = red.diagnosticar  # inyectable
        self._lock = threading.RLock()
        self._peers: dict[str, _PeerMirror] = {}
        self._health_thread: threading.Thread | None = None
        self._health_loop_error: str | None = None  # el ultimo motivo avisado por _health_loop
        self._stop = threading.Event()

    # --- alta y baja de peers -------------------------------------------------------------

    def connect(self, pc_id: str, info: dict, host: str, port: int, key: bytes, self_pc_id: str) -> None:
        """Arranca (o reemplaza) el espejo de un peer: cliente SSE contra `/peer/events`, que pide
        el snapshot completo en cada (re)conexion (incluida la primera)."""
        self.disconnect(pc_id)
        conn = federation.PeerConn(host=host, port=port, key=key, self_pc_id=self_pc_id)
        pm = _PeerMirror(pc_id, dict(info), conn)
        with self._lock:
            self._peers[pc_id] = pm

        def on_event(ev: dict) -> None:
            self._apply_event(pm, ev)

        def on_reconnect() -> None:
            with self._lock:
                pm.last_seen = time.time()

        pm.client = self.transport.subscribe(conn, "/peer/events", on_event, on_reconnect)
        self._ensure_health_thread()

    def disconnect(self, pc_id: str) -> None:
        with self._lock:
            pm = self._peers.pop(pc_id, None)
        if pm is None:
            return  # no habia nada conectado: no es un cambio (evita un on_change de mas al reconectar)
        if pm.client is not None:
            pm.client.stop()
        self.on_change()

    def all_synced(self) -> bool:
        """True si hay peers conectados y TODOS ya mandaron su snapshot: recien ahi se sabe que una
        tarjeta ajena que no aparece es una tarjeta que ya no existe, y no una que todavia no llego."""
        with self._lock:
            return bool(self._peers) and all(pm.synced for pm in self._peers.values())

    def peer_ids(self) -> list[str]:
        with self._lock:
            return list(self._peers.keys())

    def stop(self) -> None:
        """Corta todo: los clientes SSE y el hilo de salud. Para tests y para un apagado limpio."""
        self._stop.set()
        with self._lock:
            pares = list(self._peers.values())
            self._peers.clear()
        for pm in pares:
            if pm.client is not None:
                pm.client.stop()
        if isinstance(self.transport, federation.HTTPTransport):
            self.transport.close()

    # --- eventos y snapshot ----------------------------------------------------------------

    def _get(self, pc_id: str) -> _PeerMirror | None:
        with self._lock:
            return self._peers.get(pc_id)

    def conn_of(self, pc_id: str) -> federation.PeerConn | None:
        """Donde esta y con que clave se le firma a ese peer: lo que usa xfer.py para su propia
        conexion (bloques binarios, keep-alive), sin pasar por el JSON de `forward`."""
        pm = self._get(pc_id)
        return pm.conn if pm is not None else None

    def supports(self, pc_id: str, capability: str) -> bool | None:
        """None si el peer todavia no publico contrato; False si explicita que no lo soporta."""
        with self._lock:
            pm = self._peers.get(pc_id)
            caps = (pm.health or {}).get("capabilities") if pm else None
            return capability in caps if isinstance(caps, list) else None

    def _apply_event(self, pm: _PeerMirror, ev: dict, *, expected_generation: int | None = None) -> None:
        """Un evento del SSE del peer (el mismo formato que /events: snapshot, session, removed,
        pending, links, rules, ping). pending/links/rules viajan como lista completa cada vez, no
        como delta: se reemplazan enteros, igual que hace el propio front con /events local."""
        if not isinstance(ev, dict):
            # un `data:` que no es un objeto JSON (federation._leer_eventos_sse lo entrega como
            # texto): antes `ev.get` reventaba el hilo SSE y el espejo de esa PC quedaba congelado
            if pm.evento_raro != type(ev).__name__:
                pm.evento_raro = type(ev).__name__
                self.log(f"evento SSE de {pm.info.get('name') or pm.pc_id} que no es un objeto, ignorado: {ev!r:.120}")
            return
        t = ev.get("type")
        if t == "ping":
            with self._lock:
                pm.last_seen = time.time()
            return
        with self._lock:
            if expected_generation is not None and (
                self._peers.get(pm.pc_id) is not pm or pm.event_generation != expected_generation
            ):
                return
            pm.last_seen = time.time()
            pm.event_generation += 1
            if t == "snapshot":
                pm.synced = True
                pm.last_snapshot = time.monotonic()
                pm.sessions = {s["session_id"]: s for s in ev.get("sessions", []) if s.get("session_id")}
                pm.pending = {p["request_id"]: p for p in ev.get("pending", []) if p.get("request_id")}
                pm.links = list(ev.get("links", []))
                pm.rules = list(ev.get("rules", []))
            elif t == "session":
                s = ev.get("session") or {}
                if s.get("session_id"):
                    pm.sessions[s["session_id"]] = s
            elif t == "removed":
                pm.sessions.pop(ev.get("session_id"), None)
            elif t == "pending":
                pm.pending = {p["request_id"]: p for p in ev.get("pending", []) if p.get("request_id")}
            elif t == "links":
                pm.links = list(ev.get("links", []))
            elif t == "rules":
                pm.rules = list(ev.get("rules", []))
            else:
                return  # tipo desconocido: no hay nada que aplicar, pero last_seen ya se toco
            snapshot_ids = set(pm.sessions) if t == "snapshot" else None
        self.on_change()
        if t == "snapshot":
            self.on_snapshot(pm.pc_id, snapshot_ids)

    # --- salud, cada HEALTH_EVERY_S ---------------------------------------------------------

    def _ensure_health_thread(self) -> None:
        if self._health_thread is not None and self._health_thread.is_alive():
            return
        self._stop.clear()
        self._health_thread = threading.Thread(target=self._health_loop, daemon=True)
        self._health_thread.start()

    def _health_loop(self) -> None:
        # espera antes de pedir la primera vez: recien conectado no hay salud todavia (peers_status
        # la muestra None hasta el primer HEALTH_EVERY_S), y asi un test que conecta un peer no
        # corre en carrera contra este hilo pidiendo salud de entrada.
        # nunca deja morir el hilo: antes una excepcion que no fuera OSError (un JSON roto, un
        # error en on_change) lo terminaba y la salud de todas las PCs quedaba congelada en la
        # ultima foto (revision 2026-10-04, B3). Se avisa solo cuando cambia el motivo.
        while not self._stop.wait(HEALTH_EVERY_S):
            for pc_id in self.peer_ids():
                try:
                    self._poll_health(pc_id)
                except Exception as e:
                    motivo = f"{type(e).__name__}: {e}"
                    if motivo != self._health_loop_error:
                        self._health_loop_error = motivo
                        self.log(f"salud de {pc_id}: falla ({motivo})\n{traceback.format_exc()}")
            try:
                self.revisar_vivos()
            except Exception:
                self.log(f"revisar pares vivos: falla\n{traceback.format_exc()}")

    def revisar_vivos(self) -> None:
        """Deja en el log cada par que pasa a caido (con cuanto hace que no se sabe nada y el
        diagnostico de red, si lo hay) y cada uno que vuelve. Antes la caida solo se veia en el
        tablero (`alive` calculado al pedir /peers) y en el log quedaba, a lo sumo, el error de
        un pedido suelto: un par que dejaba de contestar no era un hecho registrado."""
        ahora = time.time()
        cambios = []
        with self._lock:
            for pm in self._peers.values():
                vivo = bool(pm.last_seen) and (ahora - pm.last_seen) < PEER_TIMEOUT_S
                if vivo == pm.vivo_avisado or (vivo and pm.vivo_avisado is None):
                    pm.vivo_avisado = vivo
                    continue
                pm.vivo_avisado = vivo
                cambios.append((pm.info.get("name") or pm.pc_id, vivo, pm.last_seen, pm.diagnostico))
        for nombre, vivo, visto, diagnostico in cambios:
            if vivo:
                self.log(f"par {nombre}: de vuelta")
            else:
                hace = f"sin noticias hace {ahora - visto:.0f} s" if visto else "no contestó desde que se conectó"
                self.log(f"par {nombre}: caída ({hace}" + (f"; {diagnostico}" if diagnostico else "") + ")")
        if cambios:
            self.on_change()

    def reconectar_todos(self) -> None:
        """Corta el SSE de cada par para que reconecte ya: despues de un cambio de red el socket
        viejo puede quedar colgado de una interfaz que no existe hasta que venza su timeout de
        lectura. El snapshot llega entero de nuevo al reconectar."""
        with self._lock:
            clientes = [pm.client for pm in self._peers.values() if pm.client is not None]
        for c in clientes:
            c.reconnect()

    def _poll_health(self, pc_id: str) -> None:
        pm = self._get(pc_id)
        if pm is None:
            return
        nombre = pm.info.get("name") or pc_id
        try:
            # `request` y no `get`: hace falta el codigo. Con `get`, un 401 (clave distinta, reloj
            # corrido) devolvia su cuerpo de error como si fuera la salud, y la PC se veia VIVA
            # aunque no aceptara ni un pedido (segunda revision 2026-10-04)
            code, h = self.transport.request(pm.conn, "GET", "/peer/health")
            if code != 200:
                raise federation.PeerError(f"{code} {(h or {}).get('error') if isinstance(h, dict) else h}")
            if not isinstance(h, dict):
                raise federation.PeerError(f"la salud no es un objeto: {h!r:.80}")
        except OSError as e:
            # se avisa al empezar a fallar o al cambiar el motivo, no cada 15 s mientras siga igual
            error = f"{type(e).__name__}: {e}"
            diagnostico = self.diagnosticar(pm.conn.host, e)
            with self._lock:
                cambio = diagnostico != pm.diagnostico
                pm.diagnostico = diagnostico
            if error != pm.health_error:
                pm.health_error = error
                self.log(f"→ {nombre} GET /health: {error}" + (f" ({diagnostico})" if diagnostico else ""))
            if cambio:
                self.on_change()
            return
        if pm.health_error is not None:
            pm.health_error = None
            self.log(f"→ {nombre} GET /health: responde de nuevo")
        pm.diagnostico = None
        with self._lock:
            pm.health = h
            pm.last_seen = time.time()
        self.on_change()

        if time.monotonic() - pm.last_snapshot >= 60:
            self._poll_snapshot(pm)

    def _poll_snapshot(self, pm: _PeerMirror) -> None:
        """Reconcilia aun si se perdio un evento; no pisa eventos posteriores a la consulta."""
        with self._lock:
            generation = pm.event_generation
        try:
            code, snapshot = self.transport.request(pm.conn, "GET", "/peer/snapshot")
        except OSError as exc:
            self.log(f"snapshot de {pm.pc_id}: {type(exc).__name__}")
            return
        if code != 200 or not isinstance(snapshot, dict) or not isinstance(snapshot.get("sessions"), list):
            self.log(f"snapshot de {pm.pc_id}: respuesta invalida ({code})")
            return
        self._apply_event(pm, {**snapshot, "type": "snapshot"}, expected_generation=generation)

    # --- lo que consume server.py (y, ronda 3, sessions.py/rules.py) ------------------------

    def owner_of(self, sid: str) -> str | None:
        """`pc_id` de la PC dueña de `sid`, o `None` si es local (o si no se conoce: el llamador
        la trata como local y su propia busqueda da 404, que es lo que corresponde)."""
        with self._lock:
            for pc_id, pm in self._peers.items():
                if sid in pm.sessions:
                    return pc_id
        return None

    def rule_owner(self, rule_id: str) -> str | None:
        """`pc_id` de la PC que tiene la regla `rule_id` (la que viene en el espejo), o `None`."""
        with self._lock:
            for pc_id, pm in self._peers.items():
                if any(r.get("id") == rule_id for r in pm.rules):
                    return pc_id
        return None

    def sessions(self) -> list[dict]:
        with self._lock:
            return [dict(s) for pm in self._peers.values() for s in pm.sessions.values()]

    def pending(self) -> list[dict]:
        with self._lock:
            return [x for pm in self._peers.values() for x in _tag(pm.pending.values(), pm.pc_id)]

    def links(self) -> list[dict]:
        with self._lock:
            return [x for pm in self._peers.values() for x in _tag(pm.links, pm.pc_id)]

    def rules(self) -> list[dict]:
        with self._lock:
            return [x for pm in self._peers.values() for x in _tag(pm.rules, pm.pc_id)]

    def peers_status(self) -> list[dict]:
        """Una fila por peer conectado, sin la propia PC (server.py la antepone): `alive` sale de
        cuanto hace que se supo algo de el (evento SSE, reconexion o salud), no de si el socket
        SSE esta abierto en este instante."""
        ahora = time.time()
        out = []
        with self._lock:
            for pc_id, pm in self._peers.items():
                vivo = bool(pm.last_seen) and (ahora - pm.last_seen) < PEER_TIMEOUT_S
                out.append(
                    {
                        "pc_id": pc_id,
                        "name": pm.info.get("name") or pc_id,
                        "color": pm.info.get("color") or "#888888",
                        "alive": vivo,
                        "last_seen": iso(pm.last_seen) if pm.last_seen else None,
                        "local": False,
                        "health": pm.health if vivo else None,
                        "diagnostico": None if vivo else pm.diagnostico,
                        # mediana de los ultimos reenvios: una PC que se vuelve lenta se ve aca
                        "latencia_ms": round(statistics.median(pm.latencias_ms)) if pm.latencias_ms else None,
                    }
                )
        return out

    def forward(self, pc_id: str, method: str, path: str, body: dict | None = None, *, timeout: float | None = None) -> tuple[int, dict]:
        """Reenvia un comando a la PC dueña (`path` sin el prefijo `/peer`, que se agrega aca) y
        devuelve su respuesta tal cual: codigo y cuerpo. Peer caido, o desconocido: 503, para que
        el front lo muestre igual que "no hay consola donde escribir". El 503 lleva `no_llego` solo
        cuando el pedido seguro no salio de aca (peer desconocido, conexion rechazada): ese se puede
        reintentar; uno sin la marca pudo haberse ejecutado del otro lado (timeout, corte a mitad)."""
        pm = self._get(pc_id)
        if pm is None:
            return 503, {"error": f"sin conexión con {pc_id}", "no_llego": True}
        nombre = pm.info.get("name") or pc_id
        code, res = 0, {}
        t0 = time.monotonic()
        for intento in (1, 2):
            try:
                options = {"timeout": timeout} if timeout is not None else {}
                code, res = self.transport.request(pm.conn, method, f"/peer{path}", body, **options)
                break
            except ConnectionRefusedError:
                # el pedido no llego a ningun lado: reintentar una vez no puede duplicar nada
                if intento == 2:
                    self.log(f"→ {nombre} {method} {path}: conexion rechazada")
                    return 503, {"error": f"sin conexión con {nombre}", "no_llego": True}
                time.sleep(0.5)
            except OSError as e:
                # timeout o corte a mitad: puede haberse ejecutado, asi que NO se reintenta
                self.log(f"→ {nombre} {method} {path}: {type(e).__name__}: {e}")
                # con el motivo: un 503 pelado no decia si fue un timeout, un corte o la PC reiniciandose
                return 503, {"error": f"sin conexión con {nombre} ({type(e).__name__}: {e})"}
        if code == 404 and (res or {}).get("code") == "unknown_session":
            return self._tarjeta_fantasma(pm, path, nombre)
        ms = (time.monotonic() - t0) * 1000
        with self._lock:
            pm.latencias_ms.append(ms)
        if code >= 400:
            self.log(f"→ {nombre} {method} {path}: {code} {(res or {}).get('error')}")
        elif path != "/browser" and (method != "GET" or ms > LENTO_MS):
            # las acciones (enviar, aprobar, lanzar) quedan en el log con su latencia; las lecturas
            # (pantalla cada pocos segundos) solo si fueron lentas, para no llenarlo
            self.log(f"→ {nombre} {method} {path}: {code} ({ms:.0f} ms)")
        return code, res

    def _tarjeta_fantasma(self, pm: _PeerMirror, path: str, nombre: str) -> tuple[int, dict]:
        """El peer dice que esa tarjeta no existe y aca seguia en el espejo: se la saca del tablero
        y se pide un snapshot nuevo (cortando el stream, que reconecta y lo manda entero). Sin
        esto, cada envio a la tarjeta fantasma rebotaba para siempre."""
        partes = path.strip("/").split("/")
        sid = partes[1] if len(partes) >= 2 and partes[0] == "sessions" else None
        if sid:
            with self._lock:
                pm.sessions.pop(sid, None)
            self.log(f"tarjeta {sid[:8]} ya no existe en {nombre}: la saco del tablero y pido el estado de nuevo")
            self.on_change()
        if pm.client is not None:
            pm.client.reconnect()
        return 404, {"error": f"esa tarjeta ya no existe en {nombre} (se quitó del tablero)", "gone": True}


MIRROR = Mirror()
