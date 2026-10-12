from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import optimization_budget as b
import optimization_cost as c
import pytest


def policy(prior=None):
    return {"round": "test", "owner_pc": "owner", "limit_usd": "5", "prior": [] if prior is None else prior}


def test_prior_unknown_blocks_and_is_not_zero():
    budget = b.Budget(policy([{"id": "known", "cost_usd": ".00002268", "source": "verified"}, {"id": "unknown", "cost_usd": None, "source": "HTTP400"}]), "owner")
    budget.activate()
    status = budget.status()
    assert status["spent_usd"] == "0.00002268" and status["available_usd"] == "0"
    assert status["unknown_charges"] == 1
    with pytest.raises(ValueError):
        budget.reserve(".001", "jev")
    assert budget.status() == status


def test_reservation_survives_restart_and_never_refunds_on_timeout():
    budget = b.Budget(policy(), "owner")
    reservation = budget.reserve("3", "test")
    restored = b.Budget(policy(), "owner")
    assert restored.status()["reserved_usd"] == "3"
    with pytest.raises(ValueError):
        restored.reserve("3", "test")
    restored.settle(reservation, ".1")
    restored.settle(reservation, ".1")
    assert restored.status()["spent_usd"] == "0.1"
    assert restored.status()["reserved_usd"] == "0"


def test_concurrent_reservations_share_five_total():
    def reserve(_):
        try:
            return b.Budget(policy(), "owner").reserve("3", "test")
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        reservations = list(pool.map(reserve, range(2)))
    assert sum(r is not None for r in reservations) == 1
    assert b.Budget(policy(), "owner").status()["reserved_usd"] == "3"


def test_other_pc_has_no_independent_five_dollars():
    budget = b.Budget(policy(), "other")
    assert budget.status()["available_usd"] == "0"
    with pytest.raises(ValueError):
        budget.reserve(".001", "jev")


@pytest.mark.parametrize("value", [None, True, "NaN", "Infinity", "-1", float("nan")])
def test_invalid_money_cannot_release_reservations(value):
    with pytest.raises(ValueError):
        b.money(value)


def test_actual_over_reservation_is_counted_and_blocks_future():
    budget = b.Budget(policy(), "owner")
    reservation = budget.reserve("1", "test")
    budget.settle(reservation, "6")
    assert budget.status()["blocked"] and Decimal(budget.status()["spent_usd"]) == 6


def test_estimates_are_not_maximums():
    assert c.maximum("local-rtk-contract") == "0"
    for adapter in ("jev", "codex", "claude"):
        with pytest.raises(ValueError):
            c.maximum(adapter)


def test_lowered_limit_preserves_existing_reservations():
    original = policy()
    b.Budget(original, "owner").reserve("1.5", "test")
    lowered = {**original, "limit_usd": "2"}
    b.Budget(lowered, "owner").activate()
    assert b.Budget(lowered, "owner").status()["available_usd"] == "0.5"
    with pytest.raises(ValueError):
        b.Budget(lowered, "owner").reserve(".6", "test")
    assert b.Budget(original, "owner").status()["limit_usd"] == "2"


def test_breach_below_total_still_blocks_provider():
    budget = b.Budget(policy(), "owner")
    rid = budget.reserve(".1", "test")
    budget.settle(rid, ".2")
    assert budget.status()["blocked"]


def test_jev_guard_rejects_unknown_history_before_credentials(monkeypatch):
    import jev
    budget = b.Budget(policy([{"id": "unknown", "cost_usd": None, "source": "HTTP400"}]), "owner")
    budget.activate()
    monkeypatch.setattr(jev.optimization_budget, "Budget", lambda: budget)
    monkeypatch.setattr(jev.jev_credentials, "load", lambda: pytest.fail("must not access credential"))
    with pytest.raises(ValueError, match="costos previos"):
        jev.decide({"counts": {}})


def test_jev_without_maximum_cannot_reserve_or_contact_provider(monkeypatch):
    import jev
    budget = b.Budget(policy(), "owner")
    budget.activate()
    monkeypatch.setattr(jev.optimization_budget, "Budget", lambda: budget)
    monkeypatch.setattr(jev.jev_credentials, "load", lambda: pytest.fail("must not access credential"))
    with pytest.raises(ValueError, match="máximo comprobable"):
        jev.decide({"counts": {}})
    assert budget.status()["reserved_usd"] == "0"


def test_jev_timeout_retains_real_reservation(monkeypatch):
    import jev
    budget = b.Budget(policy(), "owner")
    budget.activate()
    monkeypatch.setattr(jev.optimization_budget, "Budget", lambda: budget)
    monkeypatch.setattr(jev.optimization_cost, "maximum", lambda _: ".001")
    monkeypatch.setattr(jev.jev_credentials, "load", lambda: "synthetic")
    def timeout(*a, **k):
        raise TimeoutError()
    monkeypatch.setattr(jev, "_open", timeout)
    with pytest.raises(ValueError, match="no respondio"):
        jev.decide({"counts": {}})
    assert budget.status()["reserved_usd"] == "0.001"
    assert budget.status()["blocked"]


def test_semantically_invalid_response_still_accounts_confirmed_cost(monkeypatch):
    import io
    import json

    import jev
    budget = b.Budget(policy(), "owner")
    budget.activate()
    monkeypatch.setattr(jev.optimization_budget, "Budget", lambda: budget)
    monkeypatch.setattr(jev.optimization_cost, "maximum", lambda _: ".001")
    monkeypatch.setattr(jev.jev_credentials, "load", lambda: "synthetic")
    monkeypatch.setattr(jev, "_open", lambda *a, **k: io.BytesIO(json.dumps({"usage": {"cost": .00005}}).encode()))
    with pytest.raises(ValueError, match="incompletas"):
        jev.decide({"counts": {}})
    assert budget.status()["spent_usd"] == "0.00005"
    assert budget.status()["reserved_usd"] == "0"


def test_status_is_readonly_before_and_after_explicit_activation():
    budget = b.Budget(policy(), "owner")
    assert budget.status()["initialized"] is False
    assert not budget.path.exists()
    budget.activate()
    before = (budget.path.read_bytes(), budget.path.stat().st_mtime_ns)
    budget.status()
    assert (budget.path.read_bytes(), budget.path.stat().st_mtime_ns) == before
