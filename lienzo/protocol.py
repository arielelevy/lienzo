"""Capacidades del servidor publicadas en la salud autenticada de cada PC."""

import state

VERSION = 1
CAPABILITIES = (
    "rules.create",
    "rules.retarget",
    "sessions.actions",
    "snapshot",
    "restore",
    "secrets",
    "xfer",
    "run.named",
    "browser.remote",
)


def info() -> dict:
    cfg = state.load_config()
    roots = cfg.get("launch_roots")
    return {
        "protocol_version": VERSION,
        "capabilities": list(CAPABILITIES),
        "launch_roots": [r for r in roots if isinstance(r, str)] if isinstance(roots, list) else [],
    }
