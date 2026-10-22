"""Ledger del investigador pago (Azure): reserva antes de enviar, liquida con el uso informado.

Separado del de Jev (`optimization_budget`). Cada ejecución reserva su máximo comprobable antes de lanzar,
bajo `BEGIN IMMEDIATE`: dos reservas simultáneas no pueden pasar juntas el tope del mes. Con uso informado
se liquida al costo real; sin uso (corte, cancelación, error), la reserva queda entera como cargo
desconocido. Nunca se imputa cero. Un ledger ilegible bloquea: sin ledger no hay envío.

El mes es el calendario UTC (`AAAA-MM`), el mismo con el que factura Azure.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import time
import uuid
from decimal import Decimal
from pathlib import Path

import state

STATES = ("reservado", "liquidado", "desconocido")


class BudgetExceeded(ValueError):
    """La reserva no entra en el tope del mes: es del entorno, se pospone."""


class Unreadable(ValueError):
    """El ledger no se puede leer ni escribir: sin ledger no hay envío."""


def _unreadable(error: Exception) -> Unreadable:
    return Unreadable(f"ledger del investigador ilegible: {type(error).__name__}")


def path() -> Path:
    return Path(state.LIENZO) / "research-ledger.sqlite"


def month(now: dt.datetime | None = None) -> str:
    return (now or dt.datetime.now(dt.UTC)).strftime("%Y-%m")


def _connect() -> sqlite3.Connection:
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(target, timeout=10, isolation_level=None)
    con.execute(
        "CREATE TABLE IF NOT EXISTS cargo (id TEXT PRIMARY KEY, adaptador TEXT NOT NULL, proyecto TEXT NOT NULL, "
        "caso TEXT NOT NULL, mes TEXT NOT NULL, reservado_usd TEXT NOT NULL, real_usd TEXT, "
        "estado TEXT NOT NULL, uso TEXT, creado REAL NOT NULL, cerrado REAL)"
    )
    return con


def _spent(con, adapter: str, period: str) -> Decimal:
    """Lo comprometido del mes: real si se liquidó, la reserva entera si no (abierta o desconocida)."""
    total = Decimal(0)
    for reserved, real, status in con.execute(
        "SELECT reservado_usd, real_usd, estado FROM cargo WHERE adaptador=? AND mes=?", (adapter, period)
    ):
        if status not in STATES:
            raise Unreadable("ledger del investigador ilegible: estado desconocido")
        total += Decimal(real if status == "liquidado" else reserved)
    return total


def status(adapter: str, budget: Decimal, now=None) -> dict:
    """Lo gastado y lo disponible del mes. Levanta Unreadable si el ledger no se puede leer."""
    period = month(now)
    try:
        con = _connect()
        try:
            spent = _spent(con, adapter, period)
            open_count = con.execute(
                "SELECT COUNT(*) FROM cargo WHERE adaptador=? AND mes=? AND estado='reservado'", (adapter, period)
            ).fetchone()[0]
        finally:
            con.close()
    except (sqlite3.Error, ArithmeticError) as error:
        raise _unreadable(error) from error
    return {
        "month": period,
        "budget_usd": str(budget),
        "spent_usd": str(spent),
        "available_usd": str(max(Decimal(0), budget - spent)),
        "open_reservations": open_count,
    }


def reserve(adapter: str, project: str, case: str, amount: Decimal, budget: Decimal, now=None) -> str:
    """Reserva `amount` si entra en el tope del mes. Devuelve el id; levanta BudgetExceeded si no entra."""
    if amount <= 0:
        raise ValueError("una reserva tiene que ser mayor que cero")
    period = month(now)
    try:
        con = _connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            try:
                spent = _spent(con, adapter, period)
                if spent + amount > budget:
                    raise BudgetExceeded(
                        f"tope mensual: comprometido USD {spent} + máximo USD {amount} supera USD {budget}"
                    )
                cid = str(uuid.uuid4())
                con.execute(
                    "INSERT INTO cargo (id, adaptador, proyecto, caso, mes, reservado_usd, estado, creado) "
                    "VALUES (?,?,?,?,?,?,'reservado',?)",
                    (cid, adapter, project, case, period, str(amount), time.time()),
                )
                con.execute("COMMIT")
                return cid
            except BaseException:
                con.execute("ROLLBACK")
                raise
        finally:
            con.close()
    except (sqlite3.Error, ArithmeticError) as error:
        raise _unreadable(error) from error


def settle(cid: str, cost: Decimal | None, usage: dict | None) -> dict:
    """Cierra una reserva: con costo real la liquida al real (aunque supere lo reservado, se registra el
    real); sin costo queda `desconocido` y cuenta la reserva entera. Si no se puede escribir, la reserva
    sigue abierta y cuenta entera (Unreadable)."""
    try:
        con = _connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT reservado_usd, estado FROM cargo WHERE id=?", (cid,)).fetchone()
            if row is None or row[1] != "reservado":
                con.execute("ROLLBACK")
                raise ValueError("reserva inexistente o ya cerrada")
            status_ = "desconocido" if cost is None else "liquidado"
            con.execute(
                "UPDATE cargo SET estado=?, real_usd=?, uso=?, cerrado=? WHERE id=?",
                (status_, None if cost is None else str(cost), json.dumps(usage) if usage else None, time.time(), cid),
            )
            con.execute("COMMIT")
        finally:
            con.close()
    except sqlite3.Error as error:
        raise _unreadable(error) from error
    return {"id": cid, "state": status_, "reserved_usd": row[0], "real_usd": None if cost is None else str(cost)}
