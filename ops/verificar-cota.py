"""GET de límites, sin cargos ni cambios en la clave compartida; salida sin secretos."""

import hashlib
import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lienzo"))
import jev
import jev_credentials

key = jev_credentials.load()
request = urllib.request.Request("https://openrouter.ai/api/v1/key", headers={"Authorization": "Bearer " + key})
with jev._open(request, timeout=12) as response:
    raw = response.read(128001)
if len(raw) > 128000:
    raise ValueError("respuesta de límites demasiado grande")
data = json.loads(raw)["data"]
print(
    json.dumps(
        {
            "source": "GET /api/v1/key",
            "paid_calls": 0,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "key_sha256": hashlib.sha256(key.encode()).hexdigest(),
            "credential_modified_at": datetime.fromtimestamp(jev_credentials.path().stat().st_mtime, UTC).isoformat(),
            "usage_usd": data.get("usage"),
            "byok_usage_usd": data.get("byok_usage"),
            "limit_usd": data.get("limit"),
            "remaining_usd": data.get("limit_remaining"),
            "reset": data.get("limit_reset"),
            "request_maximum_verified": False,
            "note": "Límite de clave compartida no es cota por petición ni concilia HTTP400 histórico",
        }
    )
)
