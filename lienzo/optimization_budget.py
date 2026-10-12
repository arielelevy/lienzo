"""Ledger operacional de una sola ronda/autoridad, sin replicar saldos entre PCs."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path

import identity
import state

POLICY = Path(__file__).resolve().parents[1] / "docs/specs/evaluador-harness/budget-policy.json"


def money(value) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("costo inválido")  # noqa: TRY004 - validación monetaria uniforme
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("costo inválido") from None
    if not result.is_finite() or result < 0:
        raise ValueError("costo inválido")
    return result


class Budget:
    def __init__(self, policy=None, pc=None):
        self.policy = json.loads(POLICY.read_text(encoding="utf-8")) if policy is None else policy
        peer_path = Path(state.LIENZO) / "peer.json"
        peer = json.loads(peer_path.read_text(encoding="utf-8")) if pc is None and peer_path.exists() else None
        if peer is not None and not isinstance(peer, dict):
            raise ValueError("identidad inválida; GET no la repara")
        self.pc = (peer or {}).get("pc_id", "unknown") if pc is None else pc
        self.limit = money(self.policy["limit_usd"])
        self.path = Path(state.LIENZO) / "optimization-budget.sqlite"

    @contextmanager
    def transaction(self):
        if self.pc != self.policy["owner_pc"]:
            raise ValueError("presupuesto administrado por otra PC; no hay saldo local para gastar")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path, timeout=.25)
        try:
            con.execute("BEGIN IMMEDIATE")
            con.execute("CREATE TABLE IF NOT EXISTS ledger (id TEXT PRIMARY KEY, round TEXT NOT NULL, status TEXT NOT NULL, reserved TEXT NOT NULL, cost TEXT, reference TEXT NOT NULL)")
            con.execute("CREATE TABLE IF NOT EXISTS authority (round TEXT PRIMARY KEY, owner TEXT NOT NULL, maximum TEXT NOT NULL)")
            con.execute("INSERT OR IGNORE INTO authority VALUES (?,?,?)", (self.policy["round"], self.pc, str(self.limit)))
            owner, old_limit = con.execute("SELECT owner,maximum FROM authority WHERE round=?", (self.policy["round"],)).fetchone()
            if owner != self.pc:
                raise ValueError("autoridad de ledger incompatible; no crear saldo alternativo")
            effective = min(money(old_limit), self.limit)
            con.execute("UPDATE authority SET maximum=? WHERE round=?", (str(effective), self.policy["round"]))
            for prior in self.policy["prior"]:
                amount = None if prior["cost_usd"] is None else str(money(prior["cost_usd"]))
                con.execute("INSERT OR IGNORE INTO ledger VALUES (?,?,?,?,?,?)", (prior["id"], self.policy["round"], "unknown" if amount is None else "settled", "0", amount, prior["source"]))
            yield con
            con.commit()
        finally:
            con.close()

    def _summary(self, con):
        authority = con.execute("SELECT owner,maximum FROM authority WHERE round=?", (self.policy["round"],)).fetchone()
        if authority is None or authority[0] != self.pc:
            raise ValueError("autoridad del ledger ausente o incompatible")
        limit = min(self.limit, money(authority[1]))
        rows = con.execute("SELECT status,reserved,cost FROM ledger WHERE round=?", (self.policy["round"],)).fetchall()
        for status, reserved, cost in rows:
            if status not in ("unknown", "held", "settled", "breach") or ((cost is None) != (status in ("unknown", "held"))):
                raise ValueError("ledger inconsistente; no se libera saldo")
            money(reserved)
            if cost is not None:
                money(cost)
        spent = sum((money(r[2]) for r in rows if r[2] is not None), Decimal(0))
        reserved = sum((money(r[1]) for r in rows if r[0] == "held"), Decimal(0))
        unknown = sum(r[0] == "unknown" for r in rows)
        breach = any(r[0] == "breach" for r in rows)
        remaining = max(Decimal(0), limit - spent - reserved)
        return {"limit_usd": str(limit), "spent_usd": str(spent), "reserved_usd": str(reserved),
                "available_usd": "0" if unknown else str(remaining), "unknown_charges": unknown,
                "owner_pc": self.policy["owner_pc"], "round": self.policy["round"],
                "blocked": bool(unknown or breach or any(r[0] == "held" for r in rows) or spent + reserved > limit)}

    def status(self):
        if self.pc != self.policy["owner_pc"]:
            return {"blocked": True, "owner_pc": self.policy["owner_pc"], "available_usd": "0", "reason": "autoridad en otra PC"}
        if not self.path.exists():
            return {"blocked": True, "initialized": False, "limit_usd": str(self.limit), "available_usd": "0", "reason": "presupuesto pendiente de activación"}
        con = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=.25)
        try:
            return self._summary(con)
        finally:
            con.close()

    def activate(self):
        if self.pc == "unknown":
            self.pc = identity.pc_id()
        if self.pc != self.policy["owner_pc"]:
            return self.status()
        with self.transaction() as con:
            return self._summary(con)

    def reserve(self, maximum, reference: str):
        amount = money(maximum)
        with self.transaction() as con:
            summary = self._summary(con)
            if summary["blocked"] or amount > money(summary["available_usd"]):
                raise ValueError("presupuesto bloqueado: cargos previos sin conciliar o saldo insuficiente")
            rid = str(uuid.uuid4())
            con.execute("INSERT INTO ledger VALUES (?,?,?,?,?,?)", (rid, self.policy["round"], "held", str(amount), None, reference))
            return rid

    def settle(self, reservation: str, actual):
        cost = money(actual)
        with self.transaction() as con:
            row = con.execute("SELECT status,cost,reserved FROM ledger WHERE id=? AND round=?", (reservation, self.policy["round"])).fetchone()
            if row is None:
                raise ValueError("reserva desconocida")
            if row[0] in ("settled", "breach"):
                if money(row[1]) != cost:
                    raise ValueError("conciliación incompatible con costo registrado")
                return
            if row[0] != "held":
                raise ValueError("cargo histórico desconocido requiere evidencia de conciliación")
            status = "breach" if cost > money(row[2]) else "settled"
            con.execute("UPDATE ledger SET status=?,cost=? WHERE id=?", (status, str(cost), reservation))
