"""Ledger del investigador pago: reserva previa, liquidación, cargo desconocido y tope mensual."""

import datetime as dt
import threading
from decimal import Decimal

import optimization_research_ledger as ledger
import pytest

BUDGET = Decimal(5)


def test_reserve_settle_and_unknown_keep_the_month_honest():
    first = ledger.reserve("azure-openai", "p", "c1", Decimal("1.2"), BUDGET)
    assert ledger.status("azure-openai", BUDGET)["spent_usd"] == "1.2"  # abierta cuenta entera
    ledger.settle(first, Decimal("0.3"), {"input_tokens": 1, "output_tokens": 2})
    second = ledger.reserve("azure-openai", "p", "c2", Decimal("1.0"), BUDGET)
    closed = ledger.settle(second, None, None)
    assert closed["state"] == "desconocido"
    status = ledger.status("azure-openai", BUDGET)
    assert status["spent_usd"] == "1.3" and status["available_usd"] == "3.7" and status["open_reservations"] == 0
    with pytest.raises(ValueError, match="ya cerrada"):
        ledger.settle(second, Decimal(0), None)


def test_hard_cut_at_the_monthly_budget_and_per_adapter():
    ledger.reserve("azure-openai", "p", "c", Decimal("4.5"), BUDGET)
    with pytest.raises(ValueError, match="^tope mensual"):
        ledger.reserve("azure-openai", "p", "c", Decimal("0.6"), BUDGET)
    ledger.reserve("azure-openai", "p", "c", Decimal("0.5"), BUDGET)  # justo el tope entra
    assert ledger.status("azure-openai", BUDGET)["available_usd"] == "0"
    assert ledger.status("otro", BUDGET)["spent_usd"] == "0"
    with pytest.raises(ValueError, match="mayor que cero"):
        ledger.reserve("azure-openai", "p", "c", Decimal(0), BUDGET)


def test_new_month_starts_from_zero():
    before = dt.datetime(2026, 10, 31, 23, 0, tzinfo=dt.UTC)
    ledger.reserve("azure-openai", "p", "c", Decimal(5), BUDGET, now=before)
    after = dt.datetime(2026, 11, 1, 0, 1, tzinfo=dt.UTC)
    assert ledger.status("azure-openai", BUDGET, now=after)["available_usd"] == "5"
    assert ledger.status("azure-openai", BUDGET, now=before)["available_usd"] == "0"


def test_concurrent_reservations_never_pass_the_budget():
    taken, refused = [], []

    def worker():
        try:
            taken.append(ledger.reserve("azure-openai", "p", "c", Decimal(1), BUDGET))
        except ValueError:
            refused.append(1)

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(taken) == 5 and len(refused) == 7
    assert ledger.status("azure-openai", BUDGET)["spent_usd"] == "5"


def test_unreadable_ledger_blocks():
    ledger.path().parent.mkdir(parents=True, exist_ok=True)
    ledger.path().write_bytes(b"esto no es sqlite" * 100)
    with pytest.raises(ValueError, match="ilegible"):
        ledger.status("azure-openai", BUDGET)
    with pytest.raises(ValueError, match="ilegible"):
        ledger.reserve("azure-openai", "p", "c", Decimal(1), BUDGET)
