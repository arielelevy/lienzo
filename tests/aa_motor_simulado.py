"""Doble de contrato 3 para focales AA durante pausas: no inicia procesos.

Sólo interpreta el subconjunto de reglas de estos fixtures. No certifica al motor real.
Las pruebas obtenidas también atraviesan el verificador de producción.
"""

import prolog_contraste as pc


def _var(x):
    return isinstance(x, str) and x.startswith("?")


def _instantiate(lit, env):
    return {"pred": lit["pred"], "args": [env.get(x, x) for x in lit["args"]]}


def _join(lit, values, env):
    out = dict(env)
    for arg, value in zip(lit["args"], values, strict=True):
        if _var(arg):
            if arg in out and out[arg] != value:
                return None
            out[arg] = value
        elif arg != value:
            return None
    return out


def _body(items, model, env=None, proof=None):
    env, proof = env or {}, proof or []
    if not items:
        yield env, proof
        return
    item, rest = items[0], items[1:]
    if "cmp" in item:
        if pc._compara(item["cmp"], *(env.get(x, x) for x in item["args"])):
            yield from _body(rest, model, env, proof)
    elif item.get("not"):
        inst = _instantiate(item, env)
        inst.pop("not", None)
        if (inst["pred"], tuple(inst["args"])) not in model:
            yield from _body(rest, model, env, [*proof, {"not": inst}])
    else:
        for (pred, values), why in list(model.items()):
            if pred == item["pred"] and len(values) == len(item["args"]):
                joined = _join(item, values, env)
                if joined is not None:
                    yield from _body(rest, model, joined, [*proof, why])


def consultar(payload, *, archivos=None, cancelar=lambda: False):
    assert not archivos, "el doble no carga .pl ni inicia WSL"
    model = {
        (f["pred"], tuple(f["args"])): {
            "by": "given",
            "fact": {"pred": f["pred"], "args": f["args"]},
            "sources": [f["source"]] if f.get("source") else [],
        }
        for f in payload["facts"]
    }
    rules = payload["rules"]
    strata = {r["head"]["pred"]: 0 for r in rules}
    for _ in range(len(rules) + 1):
        changed = False
        for r in rules:
            head = r["head"]["pred"]
            level = max(
                (strata.get(i["pred"], 0) + int(i.get("not", False)) for i in r["body"] if "pred" in i), default=0
            )
            if level > strata[head]:
                strata[head], changed = level, True
        if not changed:
            break
    else:
        raise AssertionError("reglas no estratificadas en el fixture")
    for level in sorted(set(strata.values())):
        for _ in range(100):
            changed = False
            for r in rules:
                if strata[r["head"]["pred"]] != level:
                    continue
                for env, premises in _body(r["body"], model):
                    lit = _instantiate(r["head"], env)
                    key = (lit["pred"], tuple(lit["args"]))
                    if key not in model:
                        model[key] = {"by": "rule", "rule": r["id"], "fact": lit, "premises": premises}
                        changed = True
            if not changed:
                break
        else:
            raise AssertionError("fixture excedió el límite de cierre")
    answers = []
    for q in payload["queries"]:
        rows = []
        for (pred, values), proof in model.items():
            if pred != q["pred"]:
                continue
            env = _join(q, values, {})
            if env is not None:
                rows.append({"bindings": {k[1:]: v for k, v in env.items()}, "proof": proof, "sources": []})
        answers.append({"pred": q["pred"], "count": len(rows), "results": rows, "truncated": False})
    return {
        "contract": 3,
        "domain": "logic",
        "consistent": True,
        "answers": answers,
        "program_hash": "sha256:fixture-AA",
        "engine": {"name": "doble-AA", "version": "1"},
    }
