"""Login propio del lienzo (DISENO.es.md §7.6.2): passphrase de seis palabras (EFF, ~77 bits)
guardada como hash scrypt, TOTP de seis digitos (Microsoft Authenticator), cookie de sesion
de 32 bytes con vencimiento a 7 dias, y freno de cinco intentos por 15 minutos. Solo stdlib.

Archivos:
  ~/.lienzo/auth.json          {"salt", "hash", "totp_secret", "created", "last_totp_counter"}
  ~/.lienzo/sessions-web.json  {"<token>": {"created", "expires", "ip", "ua"}}
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import struct
import threading
import time

HOME = os.environ.get("USERPROFILE") or os.path.expanduser("~")
LIENZO = os.path.join(HOME, ".lienzo")
AUTH_FILE = os.path.join(LIENZO, "auth.json")
WEB_SESSIONS = os.path.join(LIENZO, "sessions-web.json")
WORDLIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eff_large_wordlist.txt")

COOKIE = "lienzo"
SESSION_DAYS = 7
MAX_FAILS = 5
BLOCK_S = 15 * 60
SCRYPT = dict(n=2 ** 14, r=8, p=1, dklen=32)

_lock = threading.RLock()
_fails: dict[str, list[float]] = {}      # ip -> timestamps de fallos; "*" es global
_blocked_until: dict[str, float] = {}


def _atomic(path: str, obj) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, path)


def _load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def now() -> dt.datetime:
    return dt.datetime.now().astimezone()


# --- passphrase ------------------------------------------------------------------

def words() -> list[str]:
    out = []
    with open(WORDLIST, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) == 2:
                out.append(parts[1])
    if len(out) < 7000:
        raise RuntimeError("lista de palabras incompleta")
    return out


def new_passphrase(n: int = 6) -> str:
    ws = words()
    return " ".join(secrets.choice(ws) for _ in range(n))


def _hash(passphrase: str, salt: bytes) -> bytes:
    norm = " ".join(passphrase.lower().split())
    return hashlib.scrypt(norm.encode("utf-8"), salt=salt, **SCRYPT)


# --- TOTP (RFC 6238, SHA1, 30 s, 6 digitos) ------------------------------------------

def totp(secret_b32: str, t: float | None = None, step: int = 30, digits: int = 6) -> str:
    key = base64.b32decode(secret_b32.upper() + "=" * (-len(secret_b32) % 8), casefold=True)
    counter = int((time.time() if t is None else t) // step)
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    code = (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def totp_counter(t: float | None = None, step: int = 30) -> int:
    return int((time.time() if t is None else t) // step)


def otpauth_uri(secret_b32: str, account: str = "lienzo", issuer: str = "Lienzo") -> str:
    return f"otpauth://totp/{issuer}:{account}?secret={secret_b32}&issuer={issuer}&algorithm=SHA1&digits=6&period=30"


# --- alta y verificacion -----------------------------------------------------------------

def configured() -> bool:
    return os.path.exists(AUTH_FILE)


def setup(account: str = "lienzo", mode: str = "code") -> dict:
    """Crea auth.json. mode="code": solo TOTP (decision del autor 2026-09-05, por usabilidad en
    el celular; el freno de intentos y la URL aleatoria del tunel acompañan). mode="full":
    ademas passphrase de seis palabras, devuelta en claro una sola vez."""
    with _lock:
        if configured():
            raise RuntimeError("ya hay acceso configurado; borrar ~/.lienzo/auth.json para rehacerlo")
        secret = base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")
        data = {"mode": mode, "totp_secret": secret, "created": now().isoformat(timespec="seconds"),
                "last_totp_counter": 0}
        passphrase = None
        if mode == "full":
            passphrase = new_passphrase()
            salt = secrets.token_bytes(16)
            data.update({"salt": salt.hex(), "hash": _hash(passphrase, salt).hex()})
        os.makedirs(LIENZO, exist_ok=True)
        _atomic(AUTH_FILE, data)
        return {"mode": mode, "passphrase": passphrase, "totp_secret": secret, "otpauth": otpauth_uri(secret, account)}


def current_otpauth(account: str = "lienzo") -> dict | None:
    """Secreto TOTP ya configurado, para volver a mostrar el QR (solo desde la PC)."""
    a = _load(AUTH_FILE)
    if not a.get("totp_secret"):
        return None
    return {"totp_secret": a["totp_secret"], "otpauth": otpauth_uri(a["totp_secret"], account)}


def mode() -> str:
    return _load(AUTH_FILE).get("mode") or "code" if configured() else "code"


def _blocked(ip: str) -> float:
    """Segundos que faltan de bloqueo (0 si no esta bloqueado)."""
    t = time.time()
    return max(0.0, max(_blocked_until.get(ip, 0), _blocked_until.get("*", 0)) - t)


def _register_fail(ip: str) -> None:
    t = time.time()
    for key in (ip, "*"):
        lst = [x for x in _fails.get(key, []) if t - x < BLOCK_S]
        lst.append(t)
        _fails[key] = lst
        if len(lst) >= MAX_FAILS:
            _blocked_until[key] = t + BLOCK_S
            _fails[key] = []


def login(passphrase: str, code: str, ip: str, ua: str = "") -> tuple[bool, str, str | None]:
    """(ok, motivo, token). Un solo mensaje de error hacia afuera; el motivo real va al log."""
    with _lock:
        if not configured():
            return False, "acceso remoto no configurado", None
        wait = _blocked(ip)
        if wait > 0:
            return False, f"bloqueado {int(wait // 60) + 1} min por intentos fallidos", None
        a = _load(AUTH_FILE)
        if (a.get("mode") or "code") == "full" and a.get("hash"):
            ok_pass = hmac.compare_digest(_hash(passphrase or "", bytes.fromhex(a["salt"])), bytes.fromhex(a["hash"]))
        else:
            ok_pass = True  # modo "code": solo el TOTP
        code = (code or "").strip().replace(" ", "")
        ok_code = False
        used_counter = None
        for delta in (-1, 0, 1):
            t = time.time() + delta * 30
            if hmac.compare_digest(totp(a["totp_secret"], t), code):
                ok_code = True
                used_counter = totp_counter(t)
        if ok_code and used_counter is not None and used_counter <= int(a.get("last_totp_counter") or 0):
            ok_code = False  # codigo ya usado: no se acepta dos veces
        if not (ok_pass and ok_code):
            _register_fail(ip)
            motivo = "passphrase incorrecta" if not ok_pass else "codigo TOTP incorrecto o repetido"
            return False, motivo, None
        a["last_totp_counter"] = used_counter
        _atomic(AUTH_FILE, a)
        token = secrets.token_hex(32)
        sessions = _load(WEB_SESSIONS)
        exp = now() + dt.timedelta(days=SESSION_DAYS)
        sessions[hashlib.sha256(token.encode()).hexdigest()] = {
            "created": now().isoformat(timespec="seconds"), "expires": exp.isoformat(timespec="seconds"),
            "ip": ip, "ua": ua[:200],
        }
        _prune(sessions)
        _atomic(WEB_SESSIONS, sessions)
        return True, "ok", token


def _prune(sessions: dict) -> None:
    t = now()
    for k in list(sessions):
        try:
            if dt.datetime.fromisoformat(sessions[k]["expires"]) < t:
                del sessions[k]
        except (KeyError, ValueError):
            del sessions[k]


# sessions-web.json se relee solo cuando cambia en disco (login, logout, purga): por el tunel cada
# request trae la cookie y antes se abria y parseaba el archivo en cada uno
_web_cache: dict = {"mtime": None, "data": {}}


def _web_sessions() -> dict:
    try:
        mtime = os.path.getmtime(WEB_SESSIONS)
    except OSError:
        mtime = None
    if mtime != _web_cache["mtime"]:
        _web_cache["data"] = _load(WEB_SESSIONS) if mtime is not None else {}
        _web_cache["mtime"] = mtime
    return _web_cache["data"]


def check(token: str | None) -> bool:
    if not token:
        return False
    with _lock:
        sessions = _web_sessions()
        entry = sessions.get(hashlib.sha256(token.encode()).hexdigest())
        if not entry:
            return False
        try:
            return dt.datetime.fromisoformat(entry["expires"]) > now()
        except (KeyError, ValueError):
            return False


def logout(token: str | None) -> None:
    if not token:
        return
    with _lock:
        sessions = _load(WEB_SESSIONS)
        sessions.pop(hashlib.sha256(token.encode()).hexdigest(), None)
        _atomic(WEB_SESSIONS, sessions)


def cookie_header(token: str, secure: bool = True) -> str:
    flags = f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_DAYS * 86400}"
    return flags + ("; Secure" if secure else "")


def parse_cookie(header: str | None) -> str | None:
    for part in (header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE and v:
            return v
    return None


if __name__ == "__main__":
    # prueba rapida: python auth.py  -> imprime una passphrase y un codigo TOTP de un secreto nuevo
    s = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
    print("passphrase:", new_passphrase())
    print("totp ahora:", totp(s), "uri:", otpauth_uri(s))
