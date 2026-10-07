"""Secretos entre PCs (un token de git, una clave): cifrados en el camino, de un solo uso y nunca
en un log, un adjunto ni una respuesta.

Por que: hasta aca un token solo podia viajar como mensaje, y quedaba en claro en
~/.lienzo/adjuntos/ de la PC duena y en el transcript de las dos sesiones (medido el 2026-10-03,
cuando la otra PC perdio sus credenciales de git y el push de la sesion 4 no salio).

Cifrado: el canal entre PCs firma (HMAC) pero no cifra, asi que el valor viaja cifrado con la clave
del emparejamiento. Solo stdlib: keystream HMAC-SHA256(k_cifrado, nonce || contador) y despues
encrypt-then-MAC con HMAC-SHA256(k_mac, nonce || cifrado). Las dos subclaves salen de la del par,
con etiquetas distintas: la clave de firma nunca se usa directo para cifrar.

Destinos en la PC que lo recibe:
- "git": `git credential approve` (el valor va por stdin), que lo guarda en el almacen de credenciales
  de Windows por el Git Credential Manager. No queda nada en lienzo.
- "memoria": queda en memoria hasta TTL_S y se lee UNA vez (GET /secrets/<id>, solo desde esa PC).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
import urllib.parse
from collections.abc import Callable

try:
    from . import subproc
except ImportError:  # con lienzo/ en sys.path (server.py, las pruebas)
    import subproc

TTL_S = 600  # 10 minutos: lo que tarda una coda en usarlo; despues se borra solo
MAX_VALOR = 4096
NONCE_BYTES = 16
DESTINOS = ("git", "memoria")

# lo enchufa server.py (health.renovar_git): una credencial nueva se prueba enseguida y no a los 5 min
al_guardar_git: Callable[[], None] = lambda: None


def _subclave(clave: bytes, etiqueta: bytes) -> bytes:
    return hmac.new(clave, b"lienzo-secretos/" + etiqueta, hashlib.sha256).digest()


def _keystream(k: bytes, nonce: bytes, n: int) -> bytes:
    bloques = []
    for i in range((n + 31) // 32):
        bloques.append(hmac.new(k, nonce + i.to_bytes(8, "big"), hashlib.sha256).digest())
    return b"".join(bloques)[:n]


def cifrar(clave: bytes, texto: str) -> dict:
    """{"nonce", "ct", "tag"} en hex. El nonce es nuevo en cada llamada."""
    datos = texto.encode("utf-8")
    nonce = secrets.token_bytes(NONCE_BYTES)
    ct = bytes(a ^ b for a, b in zip(datos, _keystream(_subclave(clave, b"cifrado"), nonce, len(datos)), strict=True))
    tag = hmac.new(_subclave(clave, b"mac"), nonce + ct, hashlib.sha256).hexdigest()
    return {"nonce": nonce.hex(), "ct": ct.hex(), "tag": tag}


def descifrar(clave: bytes, cifrado: dict) -> str:
    """El texto, o ValueError si algo no cierra (clave distinta, datos tocados, formato roto). La
    MAC se verifica ANTES de descifrar y en tiempo constante."""
    try:
        nonce, ct, tag = bytes.fromhex(cifrado["nonce"]), bytes.fromhex(cifrado["ct"]), str(cifrado["tag"])
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError("secreto con formato invalido") from e
    esperado = hmac.new(_subclave(clave, b"mac"), nonce + ct, hashlib.sha256).hexdigest()
    if len(nonce) != NONCE_BYTES or not tag.isascii() or not hmac.compare_digest(esperado, tag):
        raise ValueError("secreto alterado o cifrado con otra clave")
    datos = bytes(a ^ b for a, b in zip(ct, _keystream(_subclave(clave, b"cifrado"), nonce, len(ct)), strict=True))
    return datos.decode("utf-8")


class Boveda:
    """Secretos en memoria, de un solo uso y con vencimiento. Nunca se escriben a disco."""

    def __init__(self, ttl_s: float = TTL_S, reloj=time.monotonic) -> None:
        self.ttl_s = ttl_s
        self._reloj = reloj
        self._items: dict[str, tuple[str, str, float]] = {}  # id -> (nombre, valor, vence)
        self._lock = threading.Lock()

    def guardar(self, nombre: str, valor: str) -> str:
        sid = secrets.token_urlsafe(12)
        with self._lock:
            self._purgar()
            self._items[sid] = (nombre, valor, self._reloj() + self.ttl_s)
        return sid

    def tomar(self, sid: str) -> tuple[str, str] | None:
        """(nombre, valor) y lo borra; None si no existe, ya se leyo o vencio."""
        with self._lock:
            self._purgar()
            item = self._items.pop(sid, None)
        return (item[0], item[1]) if item else None

    def pendientes(self) -> list[dict]:
        """Lo que hay guardado, SIN valores: id, nombre y segundos que le quedan."""
        with self._lock:
            self._purgar()
            ahora = self._reloj()
            return [{"id": k, "nombre": v[0], "vence_en_s": round(v[2] - ahora)} for k, v in self._items.items()]

    def _purgar(self) -> None:
        ahora = self._reloj()
        for k in [k for k, v in self._items.items() if v[2] <= ahora]:
            del self._items[k]


BOVEDA = Boveda()


def validar(d: dict) -> str | None:
    """Motivo del rechazo de un pedido de secreto, o None si esta bien. No mira el valor mas que
    para su tamano: nunca se devuelve ni se loguea."""
    if d.get("destino") not in DESTINOS:
        return f"destino debe ser uno de {DESTINOS}"
    nombre = d.get("nombre")
    if not isinstance(nombre, str) or not nombre.strip() or len(nombre) > 100:
        return "nombre: texto de 1 a 100 caracteres"
    if d.get("destino") == "git":
        url = d.get("git_url")
        if not isinstance(url, str) or _CONTROL & set(url) or _host_git(url) is None:
            return "git_url: una url https (p. ej. https://git.ejemplo.com)"
        if not isinstance(d.get("usuario"), str) or not d["usuario"].strip():
            return "usuario: hace falta para git"
        if _CONTROL & set(d["usuario"]):
            return "usuario: sin saltos de linea ni caracteres nulos"
        if isinstance(d.get("valor"), str) and _CONTROL & set(d["valor"]):
            return "valor: sin saltos de linea ni caracteres nulos"
    return None


# `git credential` lee lineas clave=valor: un salto de linea en el usuario o en el valor agregaba
# claves propias (otro host, otro protocolo) y un \0 corta la entrada (revision 2026-10-04, 0.6).
_CONTROL = frozenset("\r\n\0")


def _host_git(url: str) -> str | None:
    """hostname[:puerto] de una url https, o None. No `netloc`: ese trae `usuario:clave@` si la url
    los tiene, y terminaba en la linea host= de git credential."""
    partes = urllib.parse.urlsplit(url)
    try:
        puerto = partes.port
    except ValueError:
        return None
    if partes.scheme != "https" or not partes.hostname:
        return None
    return partes.hostname + (f":{puerto}" if puerto else "")


def aplicar_git(git_url: str, usuario: str, valor: str) -> tuple[bool, str]:
    """Guarda la credencial con `git credential approve`: el helper de git (en Windows, el Git
    Credential Manager) la deja en el almacen de credenciales del sistema. El valor va por stdin:
    no aparece en la linea de comandos ni en la salida. Nunca abre una ventana de login."""
    host = _host_git(git_url)
    if host is None or _CONTROL & set(usuario + valor):
        return False, "url, usuario o valor invalidos para git credential"
    entrada = f"protocol=https\nhost={host}\nusername={usuario}\npassword={valor}\n\n"
    # subproc.correr y no subprocess.run: con la salida en una tuberia, un Git Credential Manager
    # que queda vivo como nieto de git la retiene y el pedido se cuelga aunque venza el timeout
    # (el mismo cuelgue que ya se vio en health._ls_remote; revision 2026-10-04, 0.5)
    rc, _out, err = subproc.correr(["git", "credential", "approve"], entrada=entrada, timeout=20, sin_prompts=True)
    if rc != 0:
        # el error de git no deberia traer el valor, pero por las dudas se lo tapa
        return False, (err or "git credential approve fallo").replace(valor, "***").strip()[:300]
    return True, f"credencial guardada para {usuario}@{host}"


def leer_git_local(git_url: str) -> tuple[str, str] | None:
    """(usuario, valor) de la credencial que ESTA PC ya tiene guardada para ese host (`git credential
    fill`), o None. Asi un agente pasa la credencial a otra PC sin verla nunca: el valor va del
    almacen de Windows al cifrado sin pasar por su transcript. Nunca abre una ventana de login."""
    host = _host_git(git_url)
    if host is None:
        return None
    # primero con la ruta del repo y despues solo con el host: el GCM con proveedor OAuth generico a
    # veces solo encuentra la credencial con `path` y, sin ella, quiere abrir una ventana de login
    # (medido el 2026-10-04: «Cannot prompt because user interactivity has been disabled» y 404 en
    # pasar_credencial_git, con la misma credencial andando para ls-remote)
    ruta = urllib.parse.urlsplit(git_url).path.lstrip("/")
    for extra in ([f"path={ruta}\n"] if ruta else []) + [""]:
        rc, out, _err = subproc.correr(
            ["git", "credential", "fill"],
            entrada=f"protocol=https\nhost={host}\n{extra}\n",
            timeout=20,
            sin_prompts=True,
        )
        campos = dict(linea.split("=", 1) for linea in out.splitlines() if "=" in linea)
        if rc == 0 and campos.get("password"):
            return campos.get("username") or "", campos["password"]
    return None


def recibir(d: dict, valor: str) -> tuple[int, dict]:
    """Aplica un secreto ya descifrado en ESTA PC segun su destino. La respuesta nunca trae el valor."""
    if len(valor) > MAX_VALOR or not valor:
        return 400, {"error": f"el valor tiene que tener entre 1 y {MAX_VALOR} caracteres"}
    if d["destino"] == "git":
        if _CONTROL & set(valor):
            return 400, {"error": "valor: sin saltos de linea ni caracteres nulos"}
        ok, msg = aplicar_git(d["git_url"], d["usuario"], valor)
        if ok:
            try:
                al_guardar_git()
            except Exception as e:  # probar de nuevo es un extra: la credencial ya quedo guardada
                msg += f" (no se pudo volver a probar git ahora: {type(e).__name__})"
        return (200 if ok else 502), ({"ok": True, "detalle": msg} if ok else {"ok": False, "error": msg})
    sid = BOVEDA.guardar(d["nombre"], valor)
    return 200, {"ok": True, "id": sid, "vence_en_s": TTL_S}
