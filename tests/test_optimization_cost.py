import optimization_cost as cost
import pytest

BOUND = {"unit": "usd", "maximum": "0", "verified": True, "basis": "suscripción sin créditos, leída en vivo"}


def limits(**over):
    return {"consumption_bound": dict(BOUND), "cancellable": True, "timeout": True, **over}


def test_cli_maximum_requires_verified_zero_with_basis():
    assert cost.cli_maximum(limits()) == "0"


@pytest.mark.parametrize(
    "value",
    [
        limits(consumption_bound=None),
        limits(consumption_bound={**BOUND, "verified": False}),
        limits(consumption_bound={**BOUND, "maximum": "0.5"}),
        limits(consumption_bound={**BOUND, "unit": "tokens"}),
        limits(consumption_bound={**BOUND, "basis": ""}),
        limits(cancellable=False),
        limits(timeout=False),
        None,
    ],
)
def test_cli_maximum_blocks_anything_unproven(value):
    with pytest.raises(ValueError, match="CLI bloqueada"):
        cost.cli_maximum(value)


def test_generic_cli_and_status_stay_blocked():
    with pytest.raises(ValueError, match="CLI bloqueada"):
        cost.maximum("codex")
    assert cost.status()["cli"]["enabled"] is False
    assert cost.maximum("local-rtk-contract") == "0"
