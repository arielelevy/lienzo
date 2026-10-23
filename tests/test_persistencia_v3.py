"""T8: disco lleno simulado, sin procesos, envíos reales, navegador ni WSL."""

import copy
import json
from pathlib import Path

import pytest
import restore
import rondas
import state


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    Path(state.LIENZO).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(rondas, "_datos", {"avisos": {}, "turnos": {}, "politicas": {}})
    monkeypatch.setattr(rondas, "_sesion", lambda sid: (sid, {"alive": True}))
    monkeypatch.setattr(rondas, "_memoria_ok", lambda resource: (True, ""))
    monkeypatch.setattr(state, "log", lambda text: None)
    notifications, events = [], []
    monkeypatch.setattr(rondas, "_avisar", lambda *args: notifications.append(args))
    monkeypatch.setattr(state, "broadcast", events.append)
    return notifications, events


def fail_write(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("disco lleno sintetico V3")

    monkeypatch.setattr(state, "atomic_write", fail)


@pytest.mark.parametrize("action", ["conceder", "renovar", "encolar", "liberar", "salir_cola", "politica"])
def test_turno_no_responde_exito_ni_muta_si_falla_guardado(isolated, monkeypatch, action):
    if action != "conceder":
        assert rondas.pedir_turno("v3", {"session_id": "a"})[0] == 200
    if action in ("liberar", "salir_cola"):
        assert rondas.pedir_turno("v3", {"session_id": "b"})[0] == 202
    before, disk = copy.deepcopy(rondas._datos), Path(rondas._path()).read_bytes() if action != "conceder" else None
    notifications, events = isolated
    events.clear()
    fail_write(monkeypatch)
    if action in ("liberar", "salir_cola"):
        code, result = rondas.liberar_turno("v3", "a" if action == "liberar" else "b")
    elif action == "politica":
        code, result = rondas.fijar_politica("v3", {"mem_min_gb": 3})
    else:
        code, result = rondas.pedir_turno("v3", {"session_id": "b" if action == "encolar" else "a", "ttl_min": 40})
    assert code == 503 and "guardar" in result["error"]
    assert rondas._datos == before and notifications == [] and events == []
    assert (Path(rondas._path()).read_bytes() if disk is not None else None) == disk


def test_liberacion_y_pase_se_guardan_una_sola_vez(isolated, monkeypatch):
    rondas.pedir_turno("v3", {"session_id": "a"})
    rondas.pedir_turno("v3", {"session_id": "b"})
    atomic = state.atomic_write
    writes = []

    def write(path, text):
        writes.append(json.loads(text))
        if len(writes) > 1:
            raise OSError("segundo guardado sintetico V3")
        atomic(path, text)

    monkeypatch.setattr(state, "atomic_write", write)
    code, result = rondas.liberar_turno("v3", "a")
    assert code == 200 and result["dueno"]["session_id"] == "b"
    assert len(writes) == 1
    assert json.loads(Path(rondas._path()).read_text())["turnos"]["v3"]["dueno"]["session_id"] == "b"
    assert len(isolated[0]) == 1


@pytest.mark.parametrize("expiry", [False, True])
def test_pase_automatico_fallido_no_concede_ni_avisa(isolated, monkeypatch, expiry):
    rondas.pedir_turno("v3", {"session_id": "a"})
    rondas.pedir_turno("v3", {"session_id": "b"})
    turno = rondas._datos["turnos"]["v3"]
    if expiry:
        turno["dueno"]["vence"] = "2020-01-01T00:00:00+00:00"
    else:
        turno["dueno"] = None
    rondas._guardar()
    before = copy.deepcopy(rondas._datos)
    isolated[1].clear()
    fail_write(monkeypatch)
    rondas.revisar()
    assert rondas._datos == before
    assert isolated == ([], [])


@pytest.fixture
def restorable(tmp_path, monkeypatch):
    folder = tmp_path / "cwd"
    folder.mkdir()
    monkeypatch.setattr(restore.identity, "pc_id", lambda: "v3")
    return {
        "session_id": "00000000-0000-4000-8000-000000000003",
        "agent": "claude",
        "cwd": str(folder),
        "alive": True,
        "hooked": True,
    }


@pytest.mark.parametrize("action", ["remember", "live", "forget"])
def test_restore_no_afirma_guardado_si_falla_disco(restorable, monkeypatch, action):
    if action == "forget":
        assert restore.remember(restorable)
        restore._last_live[restorable["session_id"]] = 42.0
    original = Path(restore.path()).read_bytes() if action == "forget" else None
    before = dict(restore._last_live)
    fail_write(monkeypatch)
    with pytest.raises(OSError, match="disco lleno sintetico V3"):
        if action == "forget":
            restore.forget(restorable["session_id"])
        elif action == "live":
            restore.remember_live([restorable])
        else:
            restore.remember(restorable)
    assert restore._last_live == before
    assert (Path(restore.path()).read_bytes() if original is not None else None) == original


def test_restore_reintenta_inmediatamente_tras_guardado_fallido(restorable, monkeypatch):
    with monkeypatch.context() as patch:
        fail_write(patch)
        with pytest.raises(OSError):
            restore.remember_live([restorable])
    assert restore.live_due(restorable["session_id"])
    assert restore.remember_live([restorable]) == 1
    assert restore.restorables()[0]["session_id"] == restorable["session_id"]


@pytest.mark.parametrize("action", ["crear", "ack", "cerrar", "vencer"])
def test_avisos_comparten_guardado_estricto_sin_publicar_fallos(isolated, monkeypatch, action):
    if action != "crear":
        rondas._datos["avisos"]["av-v3"] = {
            "id": "av-v3",
            "estado": "abierto",
            "creado": "2026-10-22",
            "vence": "2020-01-01T00:00:00+00:00",
            "de": "coord",
            "texto": "prueba",
            "destinos": {"a": {"estado": "confirmado" if action == "cerrar" else "enviando"}},
        }
        rondas._guardar()
    before = copy.deepcopy(rondas._datos)
    monkeypatch.setattr(rondas.ses, "en_hilo", lambda *a: pytest.fail("no enviar avisos sin persistir"))
    fail_write(monkeypatch)
    if action == "crear":
        assert rondas.crear_aviso({"texto": "prueba", "a": ["a"]})[0] == 503
    elif action == "ack":
        assert rondas.ack("av-v3", "a")[0] == 503
    else:
        with pytest.raises(OSError):
            (rondas._cerrar_si_completo("av-v3") if action == "cerrar" else rondas._revisar_avisos())
    assert rondas._datos == before and isolated == ([], [])
