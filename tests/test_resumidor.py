"""Resumidor del nivel 3 (2026-10-29): días cerrados de capturas -> un informe por día con sus temas, cursor
propio, tope diario aparte del investigador y salida hacia el bot. La IA no se llama: un adaptador falso
lanza un Python real que devuelve una respuesta fija."""

import datetime as dt
import json
import sys

import conocimiento as k
import optimization_queue
import optimization_scheduler as s
import pytest
import registro_niveles as registro
import resumidor as rz

P = "resumen-test"
TARJETA = {"session_id": "ses-uno-123", "agent": "claude", "pc": "pcA"}
CHILD = r"""
import json, sys
work = sys.argv[1]
json.dump(json.load(open(work + "/fake.json", encoding="utf-8")), open(work + "/result.json", "w", encoding="utf-8"))
"""


def _fecha(dias_atras: int, hora: int = 12) -> str:
    local = dt.datetime.combine(dt.date.today() - dt.timedelta(days=dias_atras), dt.time(hora)).astimezone()
    return local.astimezone(dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _dia(dias_atras: int) -> str:
    return (dt.date.today() - dt.timedelta(days=dias_atras)).isoformat()


def _captura(monkeypatch, clase, texto, fecha, tarjeta=TARJETA):
    monkeypatch.setattr(k, "ahora", lambda: fecha)
    k.capturar(P, clase, texto, tarjeta)
    monkeypatch.undo()


@pytest.fixture(autouse=True)
def proyecto(monkeypatch):
    monkeypatch.setattr(k.state, "log", lambda msg: None)
    k._sesion_proyecto.clear()
    k._sesion_sin_proyecto.clear()
    k.registrar_proyecto(P, "Resumen")
    yield
    k._sesion_proyecto.clear()
    k._sesion_sin_proyecto.clear()


@pytest.fixture
def capturas(monkeypatch):
    with pytest.MonkeyPatch.context() as mp:
        _captura(mp, "pedido", "arreglá el login de la app", _fecha(2, 10))
        _captura(
            mp, "respuesta", "Listo: el login valida el token sk-ant-abcdefghijklmnopqrstuvwxyz0123", _fecha(2, 11)
        )
        _captura(mp, "envio", "esto no es pedido ni respuesta", _fecha(2, 11))
        _captura(mp, "pedido", "sumá exportar a CSV", _fecha(1, 9), {**TARJETA, "session_id": "ses-dos"})
        _captura(mp, "pedido", "hoy todavía no cerró", _fecha(0, 0))


def _respuesta(data, temas=("Login",)):
    return {
        "case_id": data["case_id"],
        "dias": [
            {
                "dia": d["dia"],
                "que_se_hizo": [f"trabajo del {d['dia']}"],
                "temas": list(temas),
                "en_que_quedo": "terminado",
            }
            for d in data["dias"]
        ],
        "limitaciones": "",
    }


def test_estado_solo_dias_cerrados(capturas):
    e = rz.estado(P)
    assert e["pendientes"] == [_dia(2), _dia(1)]
    assert e["capturas"] == 3  # el envío no cuenta y lo de hoy espera


def test_paquete_alias_redaccion_y_lectura(capturas):
    data = rz.packet(rz.case(P))
    assert [d["dia"] for d in data["dias"]] == [_dia(2), _dia(1)]
    textos = json.dumps(data["dias"], ensure_ascii=False)
    assert "sk-ant-abcdefghijklmnopqrstuvwxyz0123" not in textos
    assert "ses-uno-123" not in textos and {e["sesion"] for d in data["dias"] for e in d["eventos"]} == {"s1", "s2"}
    assert data["lectura"]["hasta_dia"] == _dia(1)
    assert data["lectura"]["hasta"] == rz._inicio_utc(_dia(0))
    assert "CASO:" in rz.prompt(data, "", False)


def test_validar_exige_los_dias_del_paquete(capturas):
    data = rz.packet(rz.case(P))
    assert rz.validate(_respuesta(data), data, None)
    otra = _respuesta(data)
    otra["dias"] = otra["dias"][:1]
    with pytest.raises(ValueError, match="días"):
        rz.validate(otra, data, None)
    with pytest.raises(ValueError):
        rz.validate({**_respuesta(data), "case_id": "otro"}, data, None)


def test_registro_informes_temas_y_cursor(capturas):
    case = rz.case(P)
    data = rz.packet(case)
    saved = rz.record(P, case, _respuesta(data, ("Login", "login ")), {}, data["lectura"])
    assert len(saved["informes"]) == 2
    with k._abrir(P) as con:
        temas = con.execute("SELECT texto FROM nodo WHERE proyecto=? AND tipo='tema'", (P,)).fetchall()
        assert [t[0] for t in temas] == ["Login"]  # mismo tema normalizado
        estados = {r[0] for r in con.execute("SELECT estado FROM nodo WHERE tipo='informe' AND proyecto=?", (P,))}
        assert estados == {"recibido"}
    assert rz.estado(P)["pendientes"] == []
    assert rz.resguardo_capturas()[P] == rz._inicio_utc(_dia(0))
    again = rz.record(P, case, _respuesta(data), {}, data["lectura"])  # idempotente por día
    assert again["informes"] == saved["informes"]


def test_el_bot_ve_los_resumenes(capturas):
    case = rz.case(P)
    data = rz.packet(case)
    rz.record(P, case, _respuesta(data), {}, data["lectura"])
    d = registro.externo_detalle(P)
    assert [r["dia"] for r in d["que_se_hizo"]] == [_dia(1), _dia(2)]
    assert d["que_se_hizo"][0] == {
        "tipo": "resumen",
        "dia": _dia(1),
        "que_se_hizo": [f"trabajo del {_dia(1)}"],
        "en_que_quedo": "terminado",
        "temas": ["Login"],
        "revisado": False,
    }
    assert registro.externo_buscar(P, "trabajo")["resultados"][0]["tipo"] == "resumen"
    [p] = [x for x in registro.externo_indice()["proyectos"] if x["proyecto"] == P]
    assert p["cantidades"]["resumen"] == 2


def test_dia_enorme_se_muestrea():
    eventos = [{"clase": "pedido", "texto": "p" * 100}] * 10 + [{"clase": "respuesta", "texto": "r" * 1000}] * 200
    quedan, recortado = rz._recortar(eventos)
    assert recortado and rz._tamano(quedan) <= rz.DIA_MAX
    assert sum(e["clase"] == "pedido" for e in quedan) == 10


def test_resumen_y_creencias_no_gastan_el_tope_del_investigador():
    q = optimization_queue.Queue()
    now = 1000.0
    q.jobs = [
        {"kind": "research", "case": {"kind": "resumen"}, "runs": [now, now], "run_adapters": ["claude", "claude"]},
        {"kind": "research", "case": {"kind": "creencias"}, "runs": [now], "run_adapters": ["claude"]},
    ]
    assert q.research_runs_since(0) == 0  # las dos familias tienen tope propio
    assert q.research_runs_since(0, "claude") == 0
    assert q.research_runs_since(0, familia="resumen") == 2
    assert q.research_runs_since(0, familia="creencias") == 1


# ------------------------------------------------------------------ de punta a punta con el scheduler


class FakeAdapter:
    name = "claude"
    agent = "claude"
    quota_every = None

    def limits(self, auth, project):
        return {
            "name": self.name,
            "available": True,
            "sends_to_external_service": True,
            "sandbox": "read-only-tools",
            "cancellable": True,
            "timeout": True,
            "consumption_bound": {"unit": "usd", "maximum": "0", "verified": True, "basis": "falso"},
            "blocked_by": [],
        }

    def command(self, work, root, seconds):
        data = json.loads((work / "prompt.md").read_text(encoding="utf-8").split("CASO:\n", 1)[1])
        assert json.loads((work / "schema.json").read_text(encoding="utf-8")) == rz.SCHEMA
        (work / "fake.json").write_text(json.dumps(_respuesta(data)), encoding="utf-8")
        return [sys.executable, "-c", CHILD, str(work)], ""

    def midrun_reason(self):
        return None

    @staticmethod
    def usage(stdout):
        return None


def _busy():
    return {
        "idle_seconds": 5,
        "ui_idle_seconds": 5,
        "cpu_pct": 10,
        "mem_free_gb": 6,
        "pending": False,
        "agents_busy": True,
    }


def test_scheduler_resume_en_segundo_plano(capturas, monkeypatch):
    monkeypatch.setattr(s.activity, "cancellation_reason", lambda _: None)
    monkeypatch.setattr(s.health, "_memoria", lambda: (8.0, 16.0))
    monkeypatch.setattr(s.creencias_research, "estado", lambda pid: {"pendientes": {}})
    scheduler = s.Scheduler()
    scheduler.research_adapter = lambda project: FakeAdapter()
    for _ in range(4):
        scheduler.tick(_busy())
    jobs = [j for j in scheduler.queue.view()["jobs"] if j["case"].get("kind") == "resumen"]
    assert [j["state"] for j in jobs] == ["observed"], scheduler.reason
    assert len(jobs[0]["results"]) == 2
    assert rz.estado(P)["pendientes"] == []


def test_scheduler_respeta_el_tope_propio(capturas, monkeypatch):
    monkeypatch.setattr(s.activity, "cancellation_reason", lambda _: None)
    monkeypatch.setattr(s.health, "_memoria", lambda: (8.0, 16.0))
    monkeypatch.setattr(s.creencias_research, "estado", lambda pid: {"pendientes": {}})
    scheduler = s.Scheduler()
    scheduler.research_adapter = lambda project: FakeAdapter()
    real = scheduler.queue.research_runs_since
    monkeypatch.setattr(
        scheduler.queue,
        "research_runs_since",
        lambda since, adapter=None, familia=None: (
            rz.TOPE_DIA if familia == "resumen" else real(since, adapter, familia=familia)
        ),
    )
    for _ in range(4):
        scheduler.tick(_busy())
    assert not [j for j in scheduler.queue.view()["jobs"] if j["case"].get("kind") == "resumen"]
