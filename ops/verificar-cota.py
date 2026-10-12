"""GET de límites, sin cargos ni cambios en la clave compartida; salida sin secretos."""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lienzo"))
import jev
import jev_credentials

request = urllib.request.Request("https://openrouter.ai/api/v1/key", headers={"Authorization": "Bearer " + jev_credentials.load()})
with jev._open(request, timeout=12) as response:
    raw = response.read(128001)
if len(raw) > 128000:
    raise ValueError("respuesta de límites demasiado grande")
data = json.loads(raw)["data"]
print(json.dumps({"source": "GET /api/v1/key", "paid_calls": 0,
                  "limit_usd": data.get("limit"), "remaining_usd": data.get("limit_remaining"),
                  "reset": data.get("limit_reset"), "request_maximum_verified": False,
                  "note": "Límite de clave compartida no es cota por petición ni concilia HTTP400 histórico"}))
