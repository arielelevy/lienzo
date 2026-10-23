"""AA lote 2: transporte persistente real con servidor JSONL de prueba y SWI opcional."""

import os
import subprocess
import sys
import threading
import time

import pytest


def servicio():
    import prolog_servicio

    return prolog_servicio


def test_dos_consultas_reusan_pid_y_cierre_recoge_proceso(tmp_path):
    script = tmp_path / "echo.py"
    script.write_text(
        "import sys,json,os\nfor s in sys.stdin:\n d=json.loads(s); print(json.dumps({'request_id':d['request_id'],'pid':os.getpid(),'ok':True}),flush=True)\n",
        encoding="utf-8",
    )
    svc = servicio().Servicio([sys.executable, str(script)], plazo=2)
    try:
        a, b = svc.pedir({"op": "ping"}), svc.pedir({"op": "ping"})
        assert a["pid"] == b["pid"]
        proc = svc.proceso
    finally:
        svc.cerrar()
    assert proc.poll() is not None


def test_timeout_mata_proceso_y_no_devuelve_exito(tmp_path):
    script = tmp_path / "lento.py"
    script.write_text("import sys,time\nfor s in sys.stdin: time.sleep(60)\n", encoding="utf-8")
    svc = servicio().Servicio([sys.executable, str(script)], plazo=0.1)
    with pytest.raises(servicio().ErrorServicio, match="plazo"):
        svc.pedir({"op": "ping"})
    assert svc.proceso is None


def test_request_id_incorrecto_es_error_de_protocolo(tmp_path):
    script = tmp_path / "malo.py"
    script.write_text(
        "import sys,json\nfor s in sys.stdin: print(json.dumps({'request_id':'otro','ok':True}),flush=True)\n",
        encoding="utf-8",
    )
    svc = servicio().Servicio([sys.executable, str(script)], plazo=2)
    try:
        with pytest.raises(servicio().ErrorServicio, match="request_id"):
            svc.pedir({"op": "ping"})
    finally:
        svc.cerrar()


def test_cancelacion_no_envia_consulta(tmp_path):
    svc = servicio().Servicio([sys.executable, "-c", "raise Exception('no iniciar')"])
    with pytest.raises(servicio().ErrorServicio, match="cancelada"):
        svc.pedir({"op": "ping"}, cancelar=lambda: True)
    assert svc.proceso is None


def test_deadline_cubre_write_con_hijo_que_no_lee(tmp_path):
    script = tmp_path / "no_lee.py"
    script.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    svc = servicio().Servicio([sys.executable, str(script)], plazo=0.15)
    errors = []

    def request():
        try:
            svc.pedir({"op": "ping", "grande": "x" * 1_000_000})
        except servicio().ErrorServicio as exc:
            errors.append(str(exc))

    thread = threading.Thread(target=request, daemon=True)
    start = time.monotonic()
    thread.start()
    try:
        thread.join(1)
        assert not thread.is_alive(), "stdin.write bloqueó fuera del deadline"
        assert errors and "plazo" in errors[0]
        assert time.monotonic() - start < 1
    finally:
        if svc.proceso is not None:
            svc.proceso.kill()
        thread.join(3)
        svc.cerrar()


def test_expira_proceso_inactivo_sin_esperar_otra_consulta(tmp_path):
    script = tmp_path / "echo_idle.py"
    script.write_text(
        "import sys,json,os\nfor s in sys.stdin:\n d=json.loads(s); print(json.dumps({'request_id':d['request_id'],'ok':True}),flush=True)\n",
        encoding="utf-8",
    )
    svc = servicio().Servicio([sys.executable, str(script)])
    try:
        svc.pedir({"op": "ping"})
        proc = svc.proceso
        svc._ultimo = time.monotonic() - 121
        svc.expirar()
        assert svc.proceso is None and proc.poll() is not None
    finally:
        svc.cerrar()


@pytest.mark.skipif(os.name != "nt", reason="liveness local de Windows")
def test_timeout_recoge_tambien_el_hijo_del_servidor_simulado(tmp_path):
    import procinfo

    script = tmp_path / "padre_con_hijo.py"
    script.write_text(
        "import sys,json,subprocess,time\n"
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
        "d=json.loads(sys.stdin.readline()); print(json.dumps({'request_id':d['request_id'],'ok':True,'hijo':p.pid}),flush=True)\n"
        "sys.stdin.readline(); time.sleep(60)\n",
        encoding="utf-8",
    )
    svc = servicio().Servicio([sys.executable, str(script)], plazo=2)
    child = None
    try:
        child = svc.pedir({"op": "ping"})["hijo"]
        assert procinfo.alive(child)
        svc.plazo = 0.1
        with pytest.raises(servicio().ErrorServicio, match="plazo"):
            svc.pedir({"op": "ping"})
        assert not procinfo.alive(child), "quedó un descendiente del servidor después del timeout"
    finally:
        svc.cerrar()
        if child and procinfo.alive(child):
            subprocess.run(
                ["taskkill", "/PID", str(child), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
