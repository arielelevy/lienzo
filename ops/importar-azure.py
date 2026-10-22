"""Importación local explícita de la key de Azure OpenAI del investigador; la corre una persona.

Lee key1 de `arielfoundry` con `az` (siempre con --subscription, nunca --tenant) y la guarda con DPAPI en
`~/.lienzo/private/azure-openai.dpapi`. La key nunca se imprime ni se pasa en argv.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lienzo"))
import jev_credentials

SUBSCRIPTION = "f056467d-cfb4-4c52-b115-21123ef7f888"
ACCOUNT, GROUP = "arielfoundry", "ariel_ia_rg"

if __name__ == "__main__":
    az = shutil.which("az")
    if not az:
        sys.exit("No se encontró az; no se guardó nada")
    result = subprocess.run(
        [
            az,
            "cognitiveservices",
            "account",
            "keys",
            "list",
            "--name",
            ACCOUNT,
            "--resource-group",
            GROUP,
            "--subscription",
            SUBSCRIPTION,
            "--query",
            "key1",
            "-o",
            "tsv",
        ],
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
        check=False,
    )
    if result.returncode:
        sys.exit("az no devolvió la key (¿sesión de az para la suscripción?); no se guardó nada")
    jev_credentials.store(result.stdout.decode("utf-8").strip(), "azure-openai")
    print(json.dumps({"ok": True, "credential": "azure-openai protegida para el usuario de Lienzo"}))
