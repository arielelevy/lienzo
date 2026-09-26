"""Plan multi-PC, encargo B (F0): `pc` y `repo_key` en cada sesion, link y regla; `transcript_bytes`
y `model` (leidos de la cola de la transcripcion); `set_coordinator` y la busqueda de la
coordinadora comparando `repo_key` en vez de `repo`; la herencia de pid por /clear conserva los
dos. Ver docs/ronda1/encargo-B.md.

`lienzo/identity.py` ya existe (frente A, en paralelo): se usa el real, no un stub, pero
`peer.json` y el cache de remotes quedan aislados en tmp (nunca tocan el ~/.lienzo real, que puede
estar en uso por otra sesion del lienzo)."""

import datetime as dt
import json
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
PID = 40001


@pytest.fixture
def aislado(tmp_path, monkeypatch):
    """Registro en tmp y peer.json/cache de identity en tmp: sin esto `identity.pc_id()` crearia o
    leeria `~/.lienzo/peer.json` de verdad, que en esta ronda esta prohibido tocar."""
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


def make_repo(root, name: str, remote: str | None) -> str:
    """Carpeta con un `.git/config` a mano (sin invocar `git`): alcanza para `identity.repo_key`."""
    d = root / name
    git = d / ".git"
    git.mkdir(parents=True)
    if remote:
        (git / "config").write_text(f'[remote "origin"]\n\turl = {remote}\n', encoding="utf-8")
    return str(d)


def write_jsonl(path, rows) -> str:
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    return str(path)


def ev(name: str, sid: str = SID, **k) -> dict:
    return {"hook_event_name": name, "session_id": sid, "agent": "claude", **k}


# --- 1. sesion nueva (hook y barrido): pc y repo_key ------------------------------------------


def test_evento_de_hook_trae_pc_y_repo_key(aislado):
    cwd = make_repo(aislado, "proj", "git@github.com:foo/bar.git")
    ses.apply_event(ev("SessionStart", cwd=cwd, host_ts=st.now()))
    s = st.sessions[SID]
    assert s["pc"] == identity.pc_id()
    assert s["repo_key"] == identity.repo_key(cwd) == "github.com/foo/bar"


def test_barrido_trae_pc_y_repo_key(aislado, monkeypatch):
    cwd = make_repo(aislado, "proj2", "git@github.com:foo/baz.git")
    monkeypatch.setattr(ses, "guess_transcript", lambda agent, cwd_, started: (None, None))
    monkeypatch.setattr(ses.procs, "cwd_of", lambda pid: cwd)
    p = {"pid": PID, "agent": "claude", "exe": "claude.exe", "created": st.now(), "in_vscode": False, "orphan": False}
    ses.adopt_process(p)
    s = st.sessions[f"pid-{PID}"]
    assert s["pc"] == identity.pc_id()
    assert s["repo_key"] == identity.repo_key(cwd) == "github.com/foo/baz"


def test_tarjeta_vieja_sin_pc_ni_repo_key_los_recibe_al_cargar(aislado):
    cwd = make_repo(aislado, "proj3", "git@github.com:foo/qux.git")
    old = ses.new_session(SID, "claude", "hook")
    old["cwd"] = cwd
    del old["pc"], old["repo_key"]  # forma de una version anterior a este cambio
    with open(os.path.join(st.SESSIONS, f"{SID}.json"), "w", encoding="utf-8") as f:
        json.dump(old, f)
    ses.load_sessions()
    s = st.sessions[SID]
    assert s["pc"] == identity.pc_id()
    assert s["repo_key"] == identity.repo_key(cwd) == "github.com/foo/qux"


# --- 2. transcript_bytes y model, leidos al refrescar la transcripcion ------------------------

CLAUDE_ROWS = [
    {"type": "user", "timestamp": "2026-09-26T10:00:00.000Z", "message": {"role": "user", "content": "hola"}},
    {
        "type": "assistant",
        "timestamp": "2026-09-26T10:00:01.000Z",
        "message": {
            "role": "assistant",
            "model": "claude-sonnet-5",
            "content": [{"type": "text", "text": "primera"}],
        },
    },
    {"type": "system", "subtype": "turn_duration", "timestamp": "2026-09-26T10:00:02.000Z"},
    {"type": "user", "timestamp": "2026-09-26T10:00:03.000Z", "message": {"role": "user", "content": "de nuevo"}},
    {
        "type": "assistant",
        "timestamp": "2026-09-26T10:00:04.000Z",
        "message": {
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": "segunda"}],
        },
    },
    {"type": "system", "subtype": "turn_duration", "timestamp": "2026-09-26T10:00:05.000Z"},
]


def test_transcript_bytes_y_model_al_refrescar(aislado):
    path = write_jsonl(aislado / "t.jsonl", CLAUDE_ROWS)
    s = ses.new_session(SID, "claude", "hook")
    s["transcript_path"] = path
    st.sessions[SID] = s
    assert ses.refresh_from_transcript(s) is True
    assert s["transcript_bytes"] == os.path.getsize(path)
    assert s["model"] == "claude-opus-5-5", "el modelo de la ULTIMA respuesta, no la primera"


def test_sin_transcripcion_transcript_bytes_y_model_quedan_none(aislado):
    s = ses.new_session(SID, "claude", "hook")
    assert s["transcript_bytes"] is None
    assert s["model"] is None


def test_model_of_codex_toma_el_ultimo_turn_context(aislado):
    rows = [
        {"type": "turn_context", "timestamp": "t0", "payload": {"model": "gpt-5-codex", "cwd": "d:/x"}},
        {"type": "event_msg", "timestamp": "t1", "payload": {"type": "task_started", "turn_id": "1"}},
        {"type": "turn_context", "timestamp": "t2", "payload": {"model": "gpt-5.1-codex-max", "cwd": "d:/x"}},
    ]
    path = write_jsonl(aislado / "r.jsonl", rows)
    assert ses.model_of("codex", path) == "gpt-5.1-codex-max"


def test_model_of_coda_no_esta_expuesto_en_la_base_queda_none(aislado):
    # CODA no guarda el modelo en su base (coda.py no expone nada que sirva): se deja en None,
    # tal como permite el encargo, en vez de inventar un acceso a su sqlite desde aca
    assert ses.model_of("coda", str(aislado / "lo-que-sea.sqlite")) is None


# --- 3. links, reglas y pendientes nuevos llevan pc -------------------------------------------


def test_add_link_lleva_pc(aislado, monkeypatch):
    monkeypatch.setattr(st.links, "path", str(aislado / "links.json"))
    monkeypatch.setattr(st.links, "items", [])
    ses.add_link(SID, OTHER, "hola", kind="user")
    assert st.links.items[-1]["pc"] == identity.pc_id()


def test_schedule_continue_lleva_pc(aislado, monkeypatch):
    monkeypatch.setattr(st.rules, "path", str(aislado / "rules.json"))
    monkeypatch.setattr(st.rules, "items", [])
    s = ses.new_session(SID, "claude", "hook")
    rl.schedule_continue(s, dt.datetime.now().astimezone() + dt.timedelta(minutes=5), "prueba")
    assert st.rules.items[-1]["pc"] == identity.pc_id()


def test_pendiente_con_pc_no_se_lo_saca_public_pending(aislado):
    # el pc de un pendiente lo escribe hook.py (frente A) al crear el archivo; aca solo se verifica
    # que sessions.py no se lo pise ni se lo saque, igual que ya hace con el resto de las claves
    st.pending.clear()
    st.pending["r1"] = {"request_id": "r1", "session_id": SID, "nonce": "secreto", "pc": identity.pc_id()}
    pub = ses.public_pending()
    assert pub[0]["pc"] == identity.pc_id()
    assert "nonce" not in pub[0]


# --- 4. set_coordinator: repo_key, no repo ----------------------------------------------------


def sess(sid: str, cwd: str) -> dict:
    s = ses.new_session(sid, "claude", "hook")
    s["cwd"] = cwd
    ses.apply_repo(s, cwd)
    st.sessions[sid] = s
    return s


def test_coordinadora_sigue_el_remote_no_el_nombre_de_carpeta(aislado):
    # A y B: mismo remote, carpetas distintas (el mismo repo clonado en dos lugares) -> comparten
    # coordinadora. C: mismo NOMBRE de carpeta que A ("carpeta1") pero remote distinto -> no.
    cwd_a = make_repo(aislado, "carpeta1", "git@github.com:foo/bar.git")
    cwd_b = make_repo(aislado / "otra-ruta", "carpeta2", "git@github.com:foo/bar.git")
    cwd_c = make_repo(aislado / "otra-ruta", "carpeta1", "git@github.com:foo/distinto.git")
    A, B, C = sess(SID, cwd_a), sess(OTHER, cwd_b), sess(THIRD, cwd_c)
    assert A["repo"] == C["repo"] == "carpeta1" and A["repo_key"] != C["repo_key"]
    assert A["repo_key"] == B["repo_key"]

    ses.set_coordinator(A, True)
    ses.set_coordinator(C, True)
    changed = ses.set_coordinator(B, True)
    assert {x["session_id"] for x in changed} == {SID, OTHER}, "prendio B y por repo_key apago a A"
    assert A["coordinator"] is False and B["coordinator"] is True
    assert C["coordinator"] is True, "otro repo_key (aunque el nombre de carpeta coincida): no se toca"


def test_stopped_recipients_avisa_a_la_coordinadora_del_mismo_repo_key(aislado):
    cwd_a = make_repo(aislado, "x", "git@github.com:foo/bar.git")
    cwd_b = make_repo(aislado / "otra-ruta", "y", "git@github.com:foo/bar.git")
    origen, coord = sess(SID, cwd_a), sess(OTHER, cwd_b)
    coord["coordinator"] = True
    recipients = ses.stopped_recipients(origen)
    assert [r["session_id"] for r in recipients] == [OTHER]


# --- 5. la herencia de pid por /clear conserva pc y repo_key ----------------------------------


def test_continue_session_conserva_pc_y_repo_key(aislado, monkeypatch):
    monkeypatch.setattr(st.rules, "path", str(aislado / "rules.json"))
    monkeypatch.setattr(st.rules, "items", [])
    monkeypatch.setattr(st.links, "path", str(aislado / "links.json"))
    monkeypatch.setattr(st.links, "items", [])
    cwd = make_repo(aislado, "heredado", "git@github.com:foo/heredado.git")
    old = sess(SID, cwd)
    old["pid"] = PID
    new = ses.new_session(OTHER, "claude", "hook")  # Codex antes del primer turno: todavia sin cwd
    st.sessions[OTHER] = new

    ses.continue_session(old, new)

    assert new["pc"] == identity.pc_id()
    assert new["cwd"] == cwd
    assert new["repo_key"] == identity.repo_key(cwd) == "github.com/foo/heredado"
    assert SID not in st.sessions
