"""Plan multi-PC, ronda 2, encargo B (F3): el arreglo de fondo de repo_key/repo en set_coordinator
y stopped_recipients, el enrutado por mirror.forward de send_to_session (y lo que usan fire_rule y
los avisos de stopped), el bucle A<->B global (loop_conflict, pura) y la coordinadora federada con
scope "pc". mirror.py (frente C) todavia no existe en este arbol: se stubea con un mirror falso
inyectado en sessions.mirror via monkeypatch, con la forma exacta que pacta el encargo comun
(owner_of, forward, rules, sessions). Ver docs/ronda2/encargo-B.md."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ruff: noqa: I001
# el orden importa: `from lienzo import server` agrega lienzo/ al sys.path (ver test_server.py)
from lienzo import server  # noqa: F401
import identity
import rules as rl
import sessions as ses
import state as st

SID = "10000000-0000-4000-8000-000000000001"
OTHER = "20000000-0000-4000-8000-000000000002"
THIRD = "30000000-0000-4000-8000-000000000003"


@pytest.fixture
def aislado(tmp_path, monkeypatch):
    """Registro en tmp y peer.json/cache de identity en tmp, igual que test_pc_fields.py: sin esto
    identity.pc_id() tocaria el ~/.lienzo real."""
    monkeypatch.setattr(st, "SESSIONS", str(tmp_path / "sessions"))
    monkeypatch.setattr(st, "LIENZO", str(tmp_path))
    monkeypatch.setattr(st, "broadcast", lambda ev: None)
    monkeypatch.setattr(st, "log", lambda msg: None)
    monkeypatch.setattr(ses, "on_turn_end", lambda sid: None)
    os.makedirs(st.SESSIONS, exist_ok=True)
    st.sessions.clear()
    st.transcript_stat.clear()
    identity._repo_cache.clear()
    yield tmp_path
    st.sessions.clear()
    st.transcript_stat.clear()


class FakeMirror:
    """Doble de mirror.MIRROR (frente C): las cuatro operaciones que pacta el encargo comun, con
    lo que se manda y se devuelve a la vista para que el test lo verifique."""

    def __init__(self):
        self.owners: dict[str, str] = {}
        self.session_list: list[dict] = []
        self.rule_list: list[dict] = []
        self.forward_calls: list[tuple] = []
        self.forward_result: tuple[int, dict] = (200, {"ok": True})

    def owner_of(self, sid):
        return self.owners.get(sid)

    def forward(self, pc_id, method, path, body=None):
        self.forward_calls.append((pc_id, method, path, body))
        return self.forward_result

    def sessions(self):
        return self.session_list

    def rules(self):
        return self.rule_list


class FakeMirrorModule:
    def __init__(self, singleton):
        self.MIRROR = singleton


@pytest.fixture
def mirror_fake(monkeypatch):
    fake = FakeMirror()
    monkeypatch.setattr(ses, "mirror", FakeMirrorModule(fake))
    yield fake


def make_repo(root, name: str, remote: str | None) -> str:
    d = root / name
    git = d / ".git"
    git.mkdir(parents=True)
    if remote:
        (git / "config").write_text(f'[remote "origin"]\n\turl = {remote}\n', encoding="utf-8")
    return str(d)


def sess(sid: str, cwd: str) -> dict:
    s = ses.new_session(sid, "claude", "hook")
    s["cwd"] = cwd
    ses.apply_repo(s, cwd)
    st.sessions[sid] = s
    return s


def sin_mirror(monkeypatch) -> None:
    """Sin mirror.py enchufado (el caso de hoy, antes de que C lo escriba): todo se resuelve local,
    exactamente como antes de esta ronda."""
    monkeypatch.setattr(ses, "mirror", None)


# --- 1. el arreglo de fondo: repo_key or repo, nunca dos None matchean -------------------------


def test_repo_identity_usa_repo_como_respaldo_de_repo_key():
    assert ses._repo_identity({"repo_key": None, "repo": "carpeta1"}) == "carpeta1"


def test_repo_identity_prioriza_repo_key_sobre_repo():
    assert ses._repo_identity({"repo_key": "github.com/foo/bar", "repo": "carpeta1"}) == "github.com/foo/bar"


def test_repo_identity_none_si_no_hay_nada():
    assert ses._repo_identity({"repo_key": None, "repo": None}) is None
    assert ses._repo_identity({}) is None


def test_set_coordinator_no_confunde_repo_key_none_con_repo_distinto(aislado):
    # bug viejo: other.get("repo_key") == s.get("repo_key") con las dos en None las hacia "el
    # mismo repo" aunque `repo` (la carpeta) fuera distinto
    a = ses.new_session(SID, "claude", "hook")
    a["repo_key"], a["repo"] = None, "carpeta-a"
    st.sessions[SID] = a
    b = ses.new_session(OTHER, "claude", "hook")
    b["repo_key"], b["repo"] = None, "carpeta-b"
    st.sessions[OTHER] = b
    ses.set_coordinator(a, True)
    changed = ses.set_coordinator(b, True)
    assert a["coordinator"] is True, "repo_key None en las dos no las hace el mismo repo"
    assert changed == [b]


def test_stopped_recipients_no_confunde_repo_key_none_con_repo_distinto(aislado):
    a = ses.new_session(SID, "claude", "hook")
    a["repo_key"], a["repo"] = None, "carpeta-a"
    st.sessions[SID] = a
    b = ses.new_session(OTHER, "claude", "hook")
    b["repo_key"], b["repo"], b["coordinator"] = None, "carpeta-b", True
    st.sessions[OTHER] = b
    assert ses.stopped_recipients(a) == []


# --- 2. repo_coordinator: prioridad scope "pc" de la propia PC, si no la federada ---------------


def test_repo_coordinator_prioriza_scope_pc_de_su_pc():
    local = [
        {"session_id": "a", "pc": "pc-1", "coordinator": True, "coordinator_scope": "pc", "repo_key": "r"},
        {"session_id": "b", "pc": "pc-1", "coordinator": True, "coordinator_scope": None, "repo_key": "r"},
    ]
    assert ses.repo_coordinator("r", "pc-1", local, [])["session_id"] == "a"


def test_repo_coordinator_scope_pc_de_otra_pc_no_cuenta():
    local = [
        {"session_id": "a", "pc": "pc-2", "coordinator": True, "coordinator_scope": "pc", "repo_key": "r"},
        {"session_id": "b", "pc": "pc-1", "coordinator": True, "coordinator_scope": None, "repo_key": "r"},
    ]
    assert ses.repo_coordinator("r", "pc-1", local, [])["session_id"] == "b"


def test_repo_coordinator_cae_a_la_federada_remota():
    remote = [{"session_id": "c", "pc": "pc-2", "coordinator": True, "coordinator_scope": None, "repo_key": "r"}]
    assert ses.repo_coordinator("r", "pc-1", [], remote)["session_id"] == "c"


def test_repo_coordinator_sin_repo_no_matchea_nada():
    local = [{"session_id": "a", "pc": "pc-1", "coordinator": True, "coordinator_scope": None, "repo_key": None}]
    assert ses.repo_coordinator(None, "pc-1", local, []) is None


# --- 3. send_to_session enruta por mirror.forward cuando la sesion es de otra PC ----------------


def test_send_to_session_local_sin_mirror_no_cambia(aislado, monkeypatch):
    sin_mirror(monkeypatch)
    s = ses.new_session(SID, "claude", "hook")
    st.sessions[SID] = s
    code, out = ses.send_to_session(s, "hola", [])
    assert code == 409, "sigue el camino local: sin pid, send_blocked la frena"


def test_send_to_session_remoto_enruta_por_mirror(aislado, mirror_fake):
    mirror_fake.owners[SID] = "pc-remota"
    mirror_fake.forward_result = (200, {"ok": True, "chars": 4})
    s = {"session_id": SID, "pc": "pc-remota"}
    code, out = ses.send_to_session(s, "hola", ["adjunto.md"])
    assert (code, out) == (200, {"ok": True, "chars": 4})
    assert mirror_fake.forward_calls == [
        ("pc-remota", "POST", f"/sessions/{SID}/send", {"text": "hola", "attachments": ["adjunto.md"]})
    ]


def test_send_to_session_remoto_no_llama_send_blocked(aislado, mirror_fake, monkeypatch):
    # una tarjeta remota no tiene pid local: si send_blocked corriera, rechazaria por "sin pid"
    mirror_fake.owners[SID] = "pc-remota"
    llamado = []
    monkeypatch.setattr(ses, "send_blocked", lambda s: llamado.append(1) or (409, {"error": "no deberia pasar"}))
    code, _ = ses.send_to_session({"session_id": SID}, "hola", [])
    assert code == 200
    assert llamado == []


def test_send_to_session_peer_caido_da_503(aislado, mirror_fake):
    mirror_fake.owners[SID] = "pc-remota"
    mirror_fake.forward_result = (503, {"error": "peer caido"})
    code, out = ses.send_to_session({"session_id": SID}, "hola", [])
    assert code == 503 and out["error"] == "peer caido"


# --- 4. fire_rule enruta a un destino que solo existe en el espejo ------------------------------


def test_fire_rule_a_destino_remoto_no_borra_la_regla(aislado, mirror_fake, monkeypatch):
    monkeypatch.setattr(st.rules, "path", str(aislado / "rules.json"))
    monkeypatch.setattr(st.rules, "items", [])
    monkeypatch.setattr(st.links, "path", str(aislado / "links.json"))
    monkeypatch.setattr(st.links, "items", [])
    src = ses.new_session(SID, "claude", "hook")
    st.sessions[SID] = src
    mirror_fake.session_list = [{"session_id": OTHER, "pc": "pc-b", "state": "termino", "stopped_by": None}]
    mirror_fake.owners[OTHER] = "pc-b"
    mirror_fake.forward_result = (200, {"ok": True, "chars": 5})
    rule = {
        "id": "r1",
        "kind": "on_stop",
        "from": SID,
        "to": OTHER,
        "text": "listo",
        "enabled": True,
        "repeat": False,
        "max_fires": 1,
        "fired": 0,
    }
    st.rules.items.append(rule)
    rl.fire_rule(rule)
    assert mirror_fake.forward_calls, "deberia haber reenviado a la PC dueña"
    assert rule in st.rules.items, "la regla no se borra: el destino existe (remoto)"
    assert rule["last_result"] == "ok"


def test_fire_rule_destino_desconocido_en_todos_lados_borra_la_regla(aislado, mirror_fake, monkeypatch):
    monkeypatch.setattr(st.rules, "path", str(aislado / "rules.json"))
    monkeypatch.setattr(st.rules, "items", [])
    rule = {"id": "r1", "kind": "on_stop", "from": None, "to": OTHER, "text": "x", "enabled": True}
    st.rules.items.append(rule)
    rl.fire_rule(rule)
    assert rule not in st.rules.items


def test_fire_rule_destino_remoto_detenido_no_gasta_el_disparo(aislado, mirror_fake, monkeypatch):
    monkeypatch.setattr(st.rules, "path", str(aislado / "rules.json"))
    monkeypatch.setattr(st.rules, "items", [])
    mirror_fake.session_list = [{"session_id": OTHER, "pc": "pc-b", "state": "termino", "stopped_by": "user"}]
    rule = {"id": "r1", "kind": "on_stop", "from": None, "to": OTHER, "text": "x", "enabled": True, "fired": 0}
    st.rules.items.append(rule)
    rl.fire_rule(rule)
    assert rule["fired"] == 0
    assert not mirror_fake.forward_calls, "destino detenido: no se le manda nada"
    assert rule["enabled"] is True, "sigue vigente: reintenta en el proximo Stop"


# --- 5. stopped_recipients ve la coordinadora y las reglas de otra PC ---------------------------


def test_stopped_recipients_incluye_coordinadora_remota(aislado, mirror_fake):
    cwd = make_repo(aislado, "x", "git@github.com:foo/bar.git")
    origen = sess(SID, cwd)
    remota = {
        "session_id": OTHER,
        "pc": "pc-b",
        "coordinator": True,
        "coordinator_scope": None,
        "repo_key": identity.repo_key(cwd),
        "repo": "x",
    }
    mirror_fake.session_list = [remota]
    recipients = ses.stopped_recipients(origen)
    assert [r["session_id"] for r in recipients] == [OTHER]


def test_stopped_recipients_incluye_sesion_remota_con_regla_vigente(aislado, mirror_fake):
    cwd = make_repo(aislado, "x", "git@github.com:foo/bar.git")
    origen = sess(SID, cwd)
    remota = {"session_id": OTHER, "pc": "pc-b", "coordinator": False, "coordinator_scope": None}
    mirror_fake.session_list = [remota]
    mirror_fake.rule_list = [{"id": "r1", "kind": "on_stop", "from": OTHER, "to": SID, "enabled": True, "pc": "pc-b"}]
    recipients = ses.stopped_recipients(origen)
    assert [r["session_id"] for r in recipients] == [OTHER]


# --- 6. coordinadora federada: apaga la remota, salvo scope "pc" --------------------------------


def test_set_coordinator_federada_apaga_la_remota_del_mismo_repo(aislado, mirror_fake):
    cwd = make_repo(aislado, "x", "git@github.com:foo/bar.git")
    s = sess(SID, cwd)
    remota = {
        "session_id": OTHER,
        "pc": "pc-b",
        "coordinator": True,
        "coordinator_scope": None,
        "repo_key": identity.repo_key(cwd),
    }
    mirror_fake.session_list = [remota]
    ses.set_coordinator(s, True)
    assert mirror_fake.forward_calls == [("pc-b", "PUT", f"/sessions/{OTHER}/coordinator", {"on": False})]


def test_set_coordinator_scope_pc_no_apaga_la_federada_remota(aislado, mirror_fake):
    cwd = make_repo(aislado, "x", "git@github.com:foo/bar.git")
    s = sess(SID, cwd)
    remota = {
        "session_id": OTHER,
        "pc": "pc-b",
        "coordinator": True,
        "coordinator_scope": None,
        "repo_key": identity.repo_key(cwd),
    }
    mirror_fake.session_list = [remota]
    ses.set_coordinator(s, True, scope="pc")
    assert mirror_fake.forward_calls == []
    assert s["coordinator"] is True and s["coordinator_scope"] == "pc"


def test_set_coordinator_federada_no_apaga_una_remota_scope_pc(aislado, mirror_fake):
    cwd = make_repo(aislado, "x", "git@github.com:foo/bar.git")
    s = sess(SID, cwd)
    remota_pc = {
        "session_id": OTHER,
        "pc": "pc-b",
        "coordinator": True,
        "coordinator_scope": "pc",
        "repo_key": identity.repo_key(cwd),
    }
    mirror_fake.session_list = [remota_pc]
    ses.set_coordinator(s, True)
    assert mirror_fake.forward_calls == [], "la separada de otra PC convive con la nueva federada"


def test_set_coordinator_scope_pc_convive_con_la_federada_local(aislado):
    cwd_a = make_repo(aislado, "x", "git@github.com:foo/bar.git")
    cwd_b = make_repo(aislado / "otra", "y", "git@github.com:foo/bar.git")
    fed = sess(SID, cwd_a)
    otra = sess(OTHER, cwd_b)
    ses.set_coordinator(fed, True)
    changed = ses.set_coordinator(otra, True, scope="pc")
    assert fed["coordinator"] is True, "la federada no se toca"
    assert otra["coordinator"] is True and otra["coordinator_scope"] == "pc"
    assert changed == [otra]


def test_set_coordinator_scope_pc_apaga_solo_a_otra_scope_pc(aislado):
    cwd_a = make_repo(aislado, "x", "git@github.com:foo/bar.git")
    cwd_b = make_repo(aislado / "otra", "y", "git@github.com:foo/bar.git")
    cwd_c = make_repo(aislado / "otra2", "z", "git@github.com:foo/bar.git")
    fed = sess(SID, cwd_a)
    p1 = sess(OTHER, cwd_b)
    p2 = sess(THIRD, cwd_c)
    ses.set_coordinator(fed, True)
    ses.set_coordinator(p1, True, scope="pc")
    changed = ses.set_coordinator(p2, True, scope="pc")
    assert {x["session_id"] for x in changed} == {OTHER, THIRD}
    assert p1["coordinator"] is False
    assert p2["coordinator"] is True and p2["coordinator_scope"] == "pc"
    assert fed["coordinator"] is True, "sigue conviviendo"


# --- 7. loop_conflict: pura, mira lo local y lo espejado ----------------------------------------


def test_loop_conflict_ninguno():
    assert rl.loop_conflict({"from": "A", "to": "B"}, [], []) is None


def test_loop_conflict_local():
    inversa = {"id": "r1", "kind": "on_stop", "from": "B", "to": "A", "enabled": True}
    assert rl.loop_conflict({"from": "A", "to": "B"}, [inversa], []) == inversa


def test_loop_conflict_remoto():
    inversa = {"id": "r9", "kind": "on_stop", "from": "B", "to": "A", "enabled": True, "pc": "otra"}
    assert rl.loop_conflict({"from": "A", "to": "B"}, [], [inversa]) == inversa


def test_loop_conflict_ignora_deshabilitada():
    inversa = {"id": "r1", "kind": "on_stop", "from": "B", "to": "A", "enabled": False}
    assert rl.loop_conflict({"from": "A", "to": "B"}, [inversa], []) is None


def test_loop_conflict_ignora_otro_kind():
    at_rule = {"id": "r1", "kind": "at", "from": "B", "to": "A", "enabled": True}
    assert rl.loop_conflict({"from": "A", "to": "B"}, [at_rule], []) is None


def test_loop_conflict_no_confunde_el_mismo_sentido():
    misma = {"id": "r1", "kind": "on_stop", "from": "A", "to": "B", "enabled": True}
    assert rl.loop_conflict({"from": "A", "to": "B"}, [misma], []) is None
