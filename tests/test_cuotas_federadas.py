import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lienzo"))
from cuotas_federadas import estado


def test_lee_remoto_solo_si_falta_local_sin_sumar_cuentas():
    local = {"kiro": {"ok": False}, "claude": {"ok": True, "spend": {"used": 3}}}
    peers = [{"pc_id": "otra", "name": "Notebook", "alive": True}]
    calls = []
    def forward(pc, method, path, **kwargs):
        calls.append((pc, method, path))
        return 200, {"kiro": {"ok": True, "credits": {"used": 10}}, "claude": {"ok": True, "spend": {"used": 9}}}
    out = estado(local, peers, forward, True)
    assert out["kiro"]["source_pc"] == "otra"
    assert out["kiro"]["credits"]["used"] == 10
    assert out["claude"]["spend"]["used"] == 3
    assert calls == [("otra", "GET", "/cuotas?refrescar=1")]


def test_peer_caido_no_se_consulta_y_error_no_inventa_cuota():
    peers = [{"pc_id": "caida", "alive": False}, {"pc_id": "vieja", "alive": True}]
    def forward(pc, *args, **kwargs):
        assert pc == "vieja"
        return 404, {"error": "ruta desconocida"}
    out = estado({"kiro": {"ok": False}}, peers, forward)
    assert not out["kiro"]["ok"]
    assert out["remote_errors"][0]["pc"] == "vieja"
