"""Lecturas de cuotas en PCs emparejadas; las credenciales quedan en su PC."""

from concurrent.futures import ThreadPoolExecutor


def estado(local, peers, forward, refrescar=False):
    """Conserva la lectura local válida; busca una remota si falta. Nunca suma cuentas."""
    vivos = [p for p in peers if p.get("alive") and not p.get("local")]
    path = "/cuotas" + ("?refrescar=1" if refrescar else "")
    with ThreadPoolExecutor(max_workers=max(1, len(vivos))) as pool:
        jobs = [(p, pool.submit(forward, p["pc_id"], "GET", path, timeout=20)) for p in vivos]
        remotas, errores = [], []
        for peer, job in jobs:
            try:
                code, data = job.result()
            except (OSError, ValueError) as error:
                code, data = 503, {"error": type(error).__name__}
            if code != 200 or not isinstance(data, dict):
                errores.append({"pc": peer["pc_id"], "error": "lectura de cuotas remota no disponible"})
                continue
            remotas.append((peer, data))
    result = dict(local)
    for agent in ("claude", "claude_smartbi", "codex", "kiro"):
        if local.get(agent, {}).get("ok"):
            continue
        for peer, data in remotas:
            reading = data.get(agent)
            if isinstance(reading, dict) and reading.get("ok") is True:
                result[agent] = {
                    **reading,
                    "source_pc": peer["pc_id"],
                    "source_name": peer.get("name") or peer["pc_id"],
                }
                break
    return {**result, "remote_errors": errores}
