"""Hijo del adaptador `azure-openai`: UNA llamada a la Responses API, sin herramientas ni lectura de repo.

Corre con `python -I` y sólo usa la biblioteca estándar. Todo lo que necesita llega por stdin (nunca por argv
ni archivos): {key, base_url, deployment, max_output_tokens, timeout, prompt, schema}. Escribe
`<work>/result.json` con la respuesta y una línea `{"usage": {...}}` por stdout. Un error se informa con el
código HTTP y el `error.code`, nunca con el cuerpo, la key ni los headers.

Red: sólo https a `*.cognitiveservices.azure.com` u `*.openai.azure.com`, sin proxy y sin redirecciones.
`local_test` (sólo en el stdin de una prueba) habilita http a 127.0.0.1 para el doble del servidor.
"""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HOSTS = (".cognitiveservices.azure.com", ".openai.azure.com")
MAX_BODY = 2_000_000
# Palabras de JSON Schema que el modo estricto puede no aceptar; la validación local las sigue exigiendo.
LOOSE = ("maxLength", "minItems", "maxItems")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def allowed(url: str, local_test: bool) -> bool:
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    if local_test and parts.scheme == "http" and host == "127.0.0.1":
        return True
    return parts.scheme == "https" and any(host.endswith(h) and len(host) > len(h) for h in HOSTS)


def loose(schema):
    if isinstance(schema, dict):
        return {k: loose(v) for k, v in schema.items() if k not in LOOSE}
    if isinstance(schema, list):
        return [loose(v) for v in schema]
    return schema


def output_text(body: dict) -> str:
    parts = []
    for item in body.get("output") or []:
        if isinstance(item, dict) and item.get("type") == "message":
            for content in item.get("content") or []:
                if isinstance(content, dict) and content.get("type") == "output_text":
                    parts.append(content.get("text") or "")
    return "".join(parts)


def fail(message: str) -> None:
    sys.stderr.write(message + "\n")
    sys.exit(2)


def not_sent(message: str) -> None:
    """Falla antes de abrir la conexión: nada llegó a Azure, el uso cero es conocido."""
    sys.stdout.write(json.dumps({"usage": {"input_tokens": 0, "output_tokens": 0, "sin_envio": 1}}) + "\n")
    sys.stdout.flush()
    fail(message)


def main() -> None:
    work = Path(sys.argv[1])
    try:
        job = json.loads(sys.stdin.read())
        url = str(job.get("base_url", "")).rstrip("/") + "/responses"
        body = {
            "model": job["deployment"],
            "input": job["prompt"],
            "max_output_tokens": int(job["max_output_tokens"]),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "investigacion",
                    "strict": True,
                    "schema": loose(job["schema"]),
                }
            },
        }
        headers = {"Content-Type": "application/json", "api-key": str(job["key"])}
    except ValueError, KeyError, TypeError, AttributeError:
        not_sent("entrada inválida")
    if not allowed(url, job.get("local_test") is True):
        not_sent("host no permitido: sólo https a Azure OpenAI")
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=float(job.get("timeout", 300))) as response:
            raw = response.read(MAX_BODY + 1)
    except urllib.error.HTTPError as error:
        code = None
        try:
            code = (json.loads(error.read(65536)).get("error") or {}).get("code")
        except ValueError, AttributeError, OSError:
            pass
        fail(f"Azure respondió HTTP {error.code}" + (f" ({str(code)[:60]})" if code else ""))
    except (urllib.error.URLError, OSError) as error:
        fail(f"sin respuesta de Azure: {type(error).__name__}")
    if len(raw) > MAX_BODY:
        fail("respuesta de Azure demasiado grande")
    try:
        data = json.loads(raw)
    except ValueError:
        fail("respuesta de Azure ilegible")
    if not isinstance(data, dict):
        fail("respuesta de Azure no es un objeto")
    usage = data.get("usage")
    if isinstance(usage, dict):
        tokens = {k: usage[k] for k in ("input_tokens", "output_tokens") if type(usage.get(k)) is int}
        sys.stdout.write(json.dumps({"usage": tokens}) + "\n")
        sys.stdout.flush()
    if data.get("status") not in (None, "completed"):
        fail(f"respuesta incompleta: {str(data.get('status'))[:40]}")
    text = output_text(data)
    try:
        result = json.loads(text)
    except ValueError:
        fail("la respuesta no es JSON")
    (work / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
