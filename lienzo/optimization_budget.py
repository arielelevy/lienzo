"""Ledger operacional de una sola ronda/autoridad, sin replicar saldos entre PCs."""

from __future__ import annotations

import json
import sqlite3
import time
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
        con = sqlite3.connect(self.path, timeout=0.25)
        try:
            con.execute("BEGIN IMMEDIATE")
            con.execute(
                "CREATE TABLE IF NOT EXISTS ledger (id TEXT PRIMARY KEY, round TEXT NOT NULL, status TEXT NOT NULL, reserved TEXT NOT NULL, cost TEXT, reference TEXT NOT NULL)"
            )
            con.execute(
                "CREATE TABLE IF NOT EXISTS authority (round TEXT PRIMARY KEY, owner TEXT NOT NULL, maximum TEXT NOT NULL)"
            )
            con.execute(
                "CREATE TABLE IF NOT EXISTS pilot (round TEXT PRIMARY KEY, started REAL NOT NULL, deadline REAL NOT NULL, maximum_calls INTEGER NOT NULL, cooldown REAL NOT NULL, attempts INTEGER NOT NULL, last_attempt REAL)"
            )
            con.execute(
                "CREATE TABLE IF NOT EXISTS pilot_samples (round TEXT NOT NULL, reference TEXT NOT NULL, reservation TEXT NOT NULL, PRIMARY KEY(round,reference))"
            )
            con.execute("CREATE TABLE IF NOT EXISTS dispatch (id TEXT PRIMARY KEY, previous_attempt REAL)")
            con.execute(
                "INSERT OR IGNORE INTO authority VALUES (?,?,?)", (self.policy["round"], self.pc, str(self.limit))
            )
            owner, old_limit = con.execute(
                "SELECT owner,maximum FROM authority WHERE round=?", (self.policy["round"],)
            ).fetchone()
            if owner != self.pc:
                raise ValueError("autoridad de ledger incompatible; no crear saldo alternativo")
            effective = min(money(old_limit), self.limit)
            con.execute("UPDATE authority SET maximum=? WHERE round=?", (str(effective), self.policy["round"]))
            for prior in self.policy["prior"]:
                amount = None if prior["cost_usd"] is None else str(money(prior["cost_usd"]))
                con.execute(
                    "INSERT OR IGNORE INTO ledger VALUES (?,?,?,?,?,?)",
                    (
                        prior["id"],
                        self.policy["round"],
                        "unknown" if amount is None else "settled",
                        "0",
                        amount,
                        prior["source"],
                    ),
                )
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
            if status not in (
                "unknown",
                "bounded_unknown",
                "staged",
                "cancelled_unsent",
                "held",
                "settled",
                "breach",
            ) or ((cost is None) != (status in ("unknown", "bounded_unknown", "staged", "cancelled_unsent", "held"))):
                raise ValueError("ledger inconsistente; no se libera saldo")
            money(reserved)
            if status == "bounded_unknown" and money(reserved) <= 0:
                raise ValueError("cota histórica inválida; no se libera saldo")
            if cost is not None:
                money(cost)
        spent = sum((money(r[2]) for r in rows if r[2] is not None), Decimal(0))
        reserved = sum((money(r[1]) for r in rows if r[0] in ("staged", "held", "bounded_unknown")), Decimal(0))
        unknown = sum(r[0] in ("unknown", "bounded_unknown") for r in rows)
        unbounded = sum(r[0] == "unknown" for r in rows)
        breach = any(r[0] == "breach" for r in rows)
        remaining = max(Decimal(0), limit - spent - reserved)
        pilot = None
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pilot'").fetchone():
            row = con.execute(
                "SELECT started,deadline,maximum_calls,cooldown,attempts,last_attempt FROM pilot WHERE round=?",
                (self.policy["round"],),
            ).fetchone()
            if row:
                pilot = dict(
                    zip(
                        ("started_at", "deadline", "maximum_calls", "cooldown_seconds", "attempts", "last_attempt"),
                        row,
                        strict=True,
                    )
                )
                pilot["within_window"] = row[0] <= time.time() < row[1]
        return {
            "limit_usd": str(limit),
            "spent_usd": str(spent),
            "reserved_usd": str(reserved),
            "available_usd": "0" if unbounded else str(remaining),
            "unknown_charges": unknown,
            "unbounded_charges": unbounded,
            "owner_pc": self.policy["owner_pc"],
            "round": self.policy["round"],
            "pilot": pilot,
            "blocked": bool(
                unbounded or breach or any(r[0] in ("staged", "held") for r in rows) or spent + reserved > limit
            ),
        }

    def bound_historical(self, charge: str, maximum, reference: str):
        """Acción explícita respaldada por evidencia; no inventa costo ni devuelve saldo.

        Solo una reserva histórica incierta puede acotarse. La cota nunca baja
        con una consulta posterior, ni por reiniciar o cargar una política vieja.
        """
        amount = money(maximum)
        if amount <= 0 or not isinstance(reference, str) or not reference.strip():
            raise ValueError("cota histórica requiere máximo positivo y evidencia")
        with self.transaction() as con:
            row = con.execute(
                "SELECT status,reserved,cost FROM ledger WHERE id=? AND round=?", (charge, self.policy["round"])
            ).fetchone()
            if row is None or row[0] not in ("unknown", "bounded_unknown") or row[2] is not None:
                raise ValueError("cargo histórico no acotable")
            if amount < money(row[1]):
                raise ValueError("no reducir reserva histórica sin conciliación")
            con.execute(
                "UPDATE ledger SET status='bounded_unknown',reserved=?,reference=? WHERE id=? AND round=?",
                (str(amount), reference, charge, self.policy["round"]),
            )
            return self._summary(con)

    def status(self):
        if self.pc != self.policy["owner_pc"]:
            return {
                "blocked": True,
                "owner_pc": self.policy["owner_pc"],
                "available_usd": "0",
                "reason": "autoridad en otra PC",
            }
        if not self.path.exists():
            return {
                "blocked": True,
                "initialized": False,
                "limit_usd": str(self.limit),
                "available_usd": "0",
                "reason": "presupuesto pendiente de activación",
            }
        con = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.25)
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

    def reserve(self, maximum, reference: str, *, staged=False):
        amount = money(maximum)
        with self.transaction() as con:
            summary = self._summary(con)
            if summary["blocked"] or amount > money(summary["available_usd"]):
                raise ValueError("presupuesto bloqueado: cargos previos sin conciliar o saldo insuficiente")
            now = time.time()
            pilot = con.execute(
                "SELECT started,deadline,maximum_calls,cooldown,attempts,last_attempt FROM pilot WHERE round=?",
                (self.policy["round"],),
            ).fetchone()
            if pilot is not None:
                start, deadline, cap, cooldown, attempts, last = pilot
                if not start <= now < deadline or attempts >= cap or (last is not None and now - last < cooldown):
                    raise ValueError("piloto bloqueado por ventana48h, tope o cooldown")
                if con.execute(
                    "SELECT 1 FROM pilot_samples WHERE round=? AND reference=?", (self.policy["round"], reference)
                ).fetchone():
                    raise ValueError("muestra de piloto ya reservada; sin reintento")
            rid = str(uuid.uuid4())
            con.execute(
                "INSERT INTO ledger VALUES (?,?,?,?,?,?)",
                (rid, self.policy["round"], "staged" if staged else "held", str(amount), None, reference),
            )
            if staged:
                con.execute("INSERT INTO dispatch VALUES (?,?)", (rid, pilot[5] if pilot is not None else None))
            if pilot is not None:
                con.execute("INSERT INTO pilot_samples VALUES (?,?,?)", (self.policy["round"], reference, rid))
                con.execute(
                    "UPDATE pilot SET attempts=attempts+1,last_attempt=? WHERE round=?", (now, self.policy["round"])
                )
            return rid

    def start_pilot(self):
        """Activación explícita e idempotente; reinicio no renueva plazo/saldo."""
        now = time.time()
        with self.transaction() as con:
            con.execute(
                "INSERT OR IGNORE INTO pilot VALUES (?,?,?,?,?,?,?)",
                (self.policy["round"], now, now + 48 * 3600, 24, 3600, 0, None),
            )
            return con.execute(
                "SELECT started,deadline,maximum_calls,cooldown,attempts FROM pilot WHERE round=?",
                (self.policy["round"],),
            ).fetchone()

    def pilot_eligible(self, reference: str) -> bool:
        status = self.status()
        pilot = status.get("pilot")
        if status["blocked"] or not pilot or not pilot["within_window"] or pilot["attempts"] >= pilot["maximum_calls"]:
            return False
        last = pilot["last_attempt"]
        if last is not None and time.time() - last < pilot["cooldown_seconds"]:
            return False
        con = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.25)
        try:
            return not con.execute(
                "SELECT 1 FROM pilot_samples WHERE round=? AND reference=?", (self.policy["round"], reference)
            ).fetchone()
        finally:
            con.close()

    def check_send(self, reservation: str):
        """Revalidar justo antes de red; un rechazo conserva la reserva."""
        with self.transaction() as con:
            row = con.execute(
                "SELECT status FROM ledger WHERE id=? AND round=?", (reservation, self.policy["round"])
            ).fetchone()
            if row not in (("held",), ("staged",)):
                raise ValueError("reserva de envío no vigente")
            if con.execute(
                "SELECT 1 FROM ledger WHERE round=? AND status IN ('unknown','breach')", (self.policy["round"],)
            ).fetchone():
                raise ValueError("histórico o cota invalida envío")
            summary = self._summary(con)
            if money(summary["spent_usd"]) + money(summary["reserved_usd"]) > money(summary["limit_usd"]):
                raise ValueError("presupuesto reducido invalida envío")
            pilot = con.execute("SELECT started,deadline FROM pilot WHERE round=?", (self.policy["round"],)).fetchone()
            if pilot is None or not pilot[0] <= time.time() < pilot[1]:
                raise ValueError("envío fuera de piloto48h")

    def cancel_unsent(self, reservation: str):
        """Solo el flujo que aún no marcó envío puede cancelar; incierto no se libera."""
        with self.transaction() as con:
            row = con.execute(
                "SELECT status FROM ledger WHERE id=? AND round=?", (reservation, self.policy["round"])
            ).fetchone()
            previous = con.execute("SELECT previous_attempt FROM dispatch WHERE id=?", (reservation,)).fetchone()
            if row != ("staged",) or previous is None:
                raise ValueError("sin prueba de reserva no enviada; saldo retenido")
            registered = con.execute(
                "SELECT 1 FROM pilot_samples WHERE round=? AND reservation=?", (self.policy["round"], reservation)
            ).fetchone()
            con.execute(
                "UPDATE ledger SET status='cancelled_unsent',reserved='0' WHERE id=? AND round=?",
                (reservation, self.policy["round"]),
            )
            if registered:
                con.execute(
                    "DELETE FROM pilot_samples WHERE round=? AND reservation=?", (self.policy["round"], reservation)
                )
                con.execute(
                    "UPDATE pilot SET attempts=attempts-1,last_attempt=? WHERE round=?",
                    (previous[0], self.policy["round"]),
                )

    def mark_sent(self, reservation: str):
        """Persistir antes de POST; desde aquí incluso duda/reinicio retienen saldo."""
        self.check_send(reservation)
        with self.transaction() as con:
            pilot = con.execute("SELECT started,deadline FROM pilot WHERE round=?", (self.policy["round"],)).fetchone()
            if pilot is None or not pilot[0] <= time.time() < pilot[1]:
                raise ValueError("envío fuera de piloto48h")
            cursor = con.execute(
                "UPDATE ledger SET status='held' WHERE id=? AND round=? AND status='staged'",
                (reservation, self.policy["round"]),
            )
            if cursor.rowcount != 1:
                raise ValueError("reserva no enviada ausente")

    def settle(self, reservation: str, actual):
        cost = money(actual)
        with self.transaction() as con:
            row = con.execute(
                "SELECT status,cost,reserved FROM ledger WHERE id=? AND round=?", (reservation, self.policy["round"])
            ).fetchone()
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
