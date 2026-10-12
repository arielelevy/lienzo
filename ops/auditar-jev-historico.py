"""Lectura de metadatos de facturación; nunca imprime claves ni cuerpos de error."""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lienzo"))
import jev
import jev_credentials


def main():
    key = jev_credentials.load()
    urls = [
        "https://openrouter.ai/api/v1/generation?id=gen-dec-1791817912-L2TPZcw7ifWYEqwFFw1G",
        "https://openrouter.ai/api/v1/activity?date=2026-10-12",
    ]
    for url in urls:
        result = {"endpoint": url.split("?")[0], "paid_calls": 0}
        request = urllib.request.Request(url, headers={"Authorization": "Bearer " + key})
        try:
            with jev._open(request, timeout=12) as response:
                raw = response.read(128001)
            if len(raw) > 128000:
                raise ValueError("respuesta demasiado grande")
            data = json.loads(raw).get("data")
            if isinstance(data, dict):
                result["data"] = {k: data.get(k) for k in (
                    "id", "model", "created_at", "total_cost", "tokens_prompt",
                    "tokens_completion", "provider_name", "request_id",
                )}
            else:
                result["aggregate_available"] = isinstance(data, list)
        except urllib.error.HTTPError as error:
            result["http"] = error.code
        except (OSError, ValueError) as error:
            result["error_type"] = type(error).__name__
        print(json.dumps(result))


if __name__ == "__main__":
    main()
