"""Motor real AA: protocolo 4, archivos como datos y contratos anteriores."""

import hashlib
import subprocess
import time

import prolog_learning as learning
import prolog_programa as programa
import prolog_servicio as servicio
import pytest


def comprobar_terminado(pid):
    if not learning.WSL:
        return
    for _ in range(20):
        result = subprocess.run(
            ["wsl.exe", "-d", "Ubuntu", "--", "kill", "-0", str(pid)], stdin=subprocess.DEVNULL, capture_output=True
        )
        if result.returncode != 0:
            return
        time.sleep(0.05)
    pytest.fail(f"SWI {pid} sigue vivo después del cierre")


@pytest.mark.skipif(not learning.motor_disponible(), reason="Sin SWI-Prolog que responda")
def test_motor_real_carga_pl_y_reusa_proceso(tmp_path):
    command = learning.command()
    command[command.index("-s") + 1] = command[command.index("-s") + 1].replace("main.pl", "servicio.pl")
    command[command.index("-g") + 1] = "servicio_main"
    data = {
        "clase": "creencia_operativa",
        "regla_logica": {
            "version": 1,
            "vocabulario": 1,
            "clausula": "impedir(C, investigador, ram) :- memoria_libre_gb(C, M), M < 3.",
        },
    }
    text = programa.renderizar(
        "aa", [{"id": "b", "proyecto": "aa", "texto": "Límite de RAM", "estado": "vigente", "datos": data}]
    )
    path = tmp_path / "aa.pl"
    path.write_text(text, encoding="utf-8", newline="\n")
    engine_path = path.as_posix()
    if learning.WSL:
        engine_path = "/mnt/" + path.drive[0].lower() + engine_path[len(path.drive) :]
    request = {
        "contract": 3,
        "domain": "logic",
        "facts": [
            {"pred": "creencia_habilitada", "args": ["b"], "source": "veredicto"},
            {"pred": "memoria_libre_gb", "args": ["pc", 1], "source": "medicion"},
        ],
        "rules": [],
        "queries": [{"pred": "impedir", "args": ["?C", "?A", "?M"]}],
        "explain": True,
    }
    svc = servicio.Servicio(command, plazo=30)
    try:
        msg = {
            "contract": 4,
            "op": "query",
            "archivos": [{"path": engine_path, "hash": hashlib.sha256(path.read_bytes()).hexdigest()}],
            "payload": request,
        }
        one = svc.pedir(msg)
        two = svc.pedir(msg)
        assert one["pid"] == two["pid"]
        answer = one["resultado"]["answers"][0]
        assert answer["results"][0]["bindings"] == {"C": "pc", "A": "investigador", "M": "ram"}
        assert answer["results"][0]["proof"]["rule"] == "creencia_b"
        assert two["cargas"] == one["cargas"]  # no releer sin cambio de generación
        msg["archivos"][0]["hash"] = "0" * 64
        with pytest.raises(servicio.ErrorServicio, match="hash"):
            svc.pedir(msg)
    finally:
        svc.cerrar()
    comprobar_terminado(one["pid"])


@pytest.mark.skipif(not learning.motor_disponible(), reason="Sin SWI-Prolog que responda")
def test_servidor_no_acepta_directivas_en_archivo(tmp_path):
    command = learning.command()
    command[command.index("-s") + 1] = command[command.index("-s") + 1].replace("main.pl", "servicio.pl")
    command[command.index("-g") + 1] = "servicio_main"
    sentinel = tmp_path / "efecto-no-autorizado.txt"
    path = tmp_path / "directiva.pl"

    def engine_path(p):
        text = p.as_posix()
        return "/mnt/" + p.drive[0].lower() + text[len(p.drive) :] if learning.WSL else text

    path.write_text(
        f':- setup_call_cleanup(open("{engine_path(sentinel)}",write,S),write(S,peligro),close(S)).\n', encoding="utf-8"
    )
    svc = servicio.Servicio(command, plazo=20)
    try:
        with pytest.raises(servicio.ErrorServicio, match="no permitido"):
            svc.pedir(
                {
                    "contract": 4,
                    "op": "query",
                    "archivos": [{"path": engine_path(path), "hash": hashlib.sha256(path.read_bytes()).hexdigest()}],
                    "payload": {"contract": 3, "domain": "logic", "facts": [], "rules": [], "queries": []},
                }
            )
        assert not sentinel.exists()
    finally:
        svc.cerrar()
